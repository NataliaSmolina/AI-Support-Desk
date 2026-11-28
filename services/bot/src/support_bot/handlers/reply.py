"""Один ручной ответ оператора в личном чате с ботом."""

import logging
import re
from dataclasses import dataclass

import psycopg
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, ForceReply, Message
from psycopg_pool import AsyncConnectionPool

from support_bot import db, texts
from support_bot.config import BotSettings
from support_bot.keyboards import REPLY_CALLBACK_PREFIX, REPLY_START_PREFIX

router = Router()
router.message.filter(F.chat.type == "private")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReplyCard:
    ticket_id: int
    chat_id: int
    message_id: int
    text: str


# Один переход из группы в личку на оператора. После /start карточка хранится в FSM.
pending_cards: dict[tuple[int, int], ReplyCard] = {}


@router.callback_query(F.data.startswith(REPLY_CALLBACK_PREFIX))
async def open_reply(callback: CallbackQuery, bot: Bot, settings: BotSettings) -> None:
    if callback.from_user.id not in settings.operator_ids:
        await callback.answer(texts.NOT_OPERATOR, show_alert=True)
        return
    card = callback.message
    number = (callback.data or "").removeprefix(REPLY_CALLBACK_PREFIX)
    if (
        not isinstance(card, Message)
        or card.chat.id != settings.operator_chat_id
        or not card.text
        or not re.fullmatch(r"[1-9][0-9]{0,18}", number)
        or not card.text.startswith(f"Обращение #{number}\n")
    ):
        await callback.answer(texts.REPLY_LINK_INVALID, show_alert=True)
        return
    username = (await bot.me()).username
    if not username:
        await callback.answer(texts.REPLY_LINK_INVALID, show_alert=True)
        return
    pending_cards[bot.id, callback.from_user.id] = ReplyCard(
        int(number), card.chat.id, card.message_id, card.text,
    )
    await callback.answer(url=f"https://t.me/{username}?start={REPLY_START_PREFIX}{number}")


class OperatorReply(StatesGroup):
    waiting_for_text = State()


def is_operator(message: Message, settings: BotSettings) -> bool:
    return message.from_user is not None and message.from_user.id in settings.operator_ids


@router.message(CommandStart(deep_link=True, magic=F.args.startswith(REPLY_START_PREFIX)))
async def start_reply(
    message: Message, command: CommandObject, state: FSMContext, settings: BotSettings, bot: Bot,
    pool: AsyncConnectionPool | None = None,
) -> None:
    if not is_operator(message, settings):
        await message.answer(texts.NOT_OPERATOR)
        return
    number = (command.args or "").removeprefix(REPLY_START_PREFIX)
    if not re.fullmatch(r"[0-9]{1,19}", number) or not 0 < int(number) <= 9_223_372_036_854_775_807:
        await message.answer(texts.REPLY_LINK_INVALID)
        return
    if await state.get_state() is not None:
        await message.answer(texts.REPLY_ALREADY_OPEN)
        return

    ticket_id = int(number)
    key = (bot.id, message.from_user.id)
    card = pending_cards.get(key)
    if card is None or card.ticket_id != ticket_id:
        await message.answer(texts.REPLY_OPEN_FROM_CARD)
        return
    if pool is None:
        await message.answer(texts.TICKET_UNAVAILABLE)
        return
    operator_id = message.from_user.id
    try:
        # Закрепляем тикет, когда оператор открывает ввод в личке
        ticket = await db.claim_operator_ticket(pool, ticket_id, operator_id)
    except psycopg.Error:
        logger.exception("Не удалось взять обращение %s", ticket_id)
        await message.answer(texts.TICKET_UNAVAILABLE)
        return
    if ticket is None:
        await message.answer(texts.TICKET_NOT_FOUND)
        return
    if not ticket.can_reply(operator_id):
        await message.answer(
            texts.REPLY_TICKET_TAKEN if ticket.status == "operator_processing" else texts.REPLY_TICKET_INACTIVE,
        )
        return

    prompt = await message.answer(
        f"{texts.REPLY_PROMPT_PREFIX}{ticket_id}. Для отмены отправьте /cancel.",
        reply_markup=ForceReply(input_field_placeholder="Ответ клиенту"),
    )
    # Пока Telegram отправлял подсказку, оператор мог нажать на другую карточку
    if pending_cards.get(key) is card:
        pending_cards.pop(key)
    # Запоминаем раунд, чтобы подсказка подходила только к этому этапу переписки
    await state.set_data({
        "ticket_id": ticket_id, "reply_round": ticket.reply_round, "prompt_id": prompt.message_id, "card": card,
    })
    await state.set_state(OperatorReply.waiting_for_text)


@router.message(Command("cancel"))
async def cancel_reply(message: Message, state: FSMContext, settings: BotSettings) -> None:
    if not is_operator(message, settings):
        await message.answer(texts.NOT_OPERATOR)
        return
    pending_cards.pop((state.key.bot_id, message.from_user.id), None)
    if await state.get_state() != OperatorReply.waiting_for_text.state:
        await message.answer(texts.REPLY_NOT_OPEN)
        return
    await state.clear()
    await message.answer(texts.REPLY_CANCELLED)


def is_reply_to_prompt(message: Message, bot: Bot) -> bool:
    original = message.reply_to_message
    return (
        original is not None
        and original.from_user is not None
        and original.from_user.id == bot.id
        and (original.text or "").startswith(texts.REPLY_PROMPT_PREFIX)
    )


@router.message(is_reply_to_prompt)
async def send_reply(
    message: Message, bot: Bot, state: FSMContext, settings: BotSettings,
    pool: AsyncConnectionPool | None = None,
) -> None:
    if not is_operator(message, settings):
        await message.answer(texts.NOT_OPERATOR)
        return
    if await state.get_state() != OperatorReply.waiting_for_text.state:
        await message.answer(texts.REPLY_NOT_OPEN)
        return
    selection = await state.get_data()
    original = message.reply_to_message
    if original is None or original.message_id != selection["prompt_id"]:
        await message.answer(texts.REPLY_USE_PROMPT)
        return
    if not message.text or not message.text.strip() or message.text.startswith("/"):
        await message.answer(texts.REPLY_TEXT_REQUIRED)
        return
    if pool is None:
        await message.answer(texts.TICKET_UNAVAILABLE)
        return
    ticket_id = selection["ticket_id"]
    reply_round = selection["reply_round"]
    operator_id = message.from_user.id
    reply_text = message.text
    try:
        ticket = await db.operator_ticket(pool, ticket_id)
    except psycopg.Error:
        logger.exception("Не удалось получить чат обращения %s", ticket_id)
        await message.answer(texts.TICKET_UNAVAILABLE)
        return
    if ticket is None:
        await state.clear()
        await message.answer(texts.TICKET_NOT_FOUND)
        return
    # Пока оператор писал текст, назначение, статус или раунд могли измениться
    if not ticket.can_reply(operator_id) or ticket.reply_round != reply_round:
        await state.clear()
        await message.answer(texts.REPLY_TICKET_INACTIVE)
        return

    try:
        await bot.send_message(chat_id=ticket.chat_id, text=reply_text)
    except TelegramForbiddenError:
        logger.warning("Telegram запретил отправку по обращению %s", ticket_id)
        await message.answer(texts.CLIENT_BLOCKED)
        return
    except TelegramAPIError:
        logger.exception("Telegram не подтвердил отправку по обращению %s", ticket_id)
        await state.clear()
        await message.answer(texts.REPLY_SEND_UNCONFIRMED)
        return

    await state.clear()
    try:
        # Записываем ручной ответ в историю после подтверждения Telegram
        saved = await db.confirm_operator_reply(pool, ticket_id, reply_round, operator_id, reply_text)
    except psycopg.Error:
        logger.exception("Ответ отправлен, но не сохранен для обращения %s", ticket_id)
        saved = False
    else:
        if not saved:
            logger.warning("База не подтвердила ответ оператора по обращению %s, раунд %s", ticket_id, reply_round)

    card = selection["card"]
    operator_name = message.from_user.full_name
    status = f"Обработал: {operator_name}"
    warning = None if saved else texts.REPLY_SAVE_FAILED
    if warning:
        status += "\nОтвет отправлен, история не сохранена."
    try:
        await bot.edit_message_text(
            chat_id=card.chat_id,
            message_id=card.message_id,
            text=f"{card.text}\n\n{status}",
        )
    except TelegramAPIError:
        logger.exception("Не удалось обновить карточку обращения %s", ticket_id)
        warning = f"{warning}\n{texts.CARD_UPDATE_FAILED}" if warning else texts.CARD_UPDATE_FAILED
    await message.answer(warning or f"Ответ на обращение #{ticket_id} отправлен.")


@router.message(OperatorReply.waiting_for_text, ~F.text.startswith("/"))
async def remind_to_reply(message: Message) -> None:
    await message.answer(texts.REPLY_USE_PROMPT)
