"""Сообщения и кнопки в группе операторов."""

import logging

import psycopg
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from psycopg_pool import AsyncConnectionPool

from support_bot import db, texts
from support_bot.config import BotSettings
from support_bot.keyboards import Action, DraftAction

# Хендлеры этого файла работают только в группах
GROUP_CHAT = F.chat.type.in_({"group", "supergroup"})

router = Router()
router.message.filter(GROUP_CHAT)
logger = logging.getLogger(__name__)


@router.message(Command("chat_id"))
async def chat_id(message: Message) -> None:
    """Подсказывает номера группы и темы, чтобы вписать их в .env."""
    await message.answer(texts.chat_ids(message.chat.id, message.message_thread_id))


def not_operator(callback: CallbackQuery, settings: BotSettings) -> bool:
    """Фильтр: нажал не оператор. settings aiogram подставит так же, как в хендлеры."""
    return callback.from_user.id not in settings.operator_ids


# Старые кнопки содержат chat_id, его нельзя принимать за ticket_id.
@router.callback_query(F.data.startswith("draft:"))
async def outdated_card(callback: CallbackQuery) -> None:
    await callback.answer(texts.CARD_OUTDATED, show_alert=True)


# Перед рабочими кнопками: хендлеры проверяются сверху вниз, поэтому нажатие не-оператора
# до «Отправить» и «Исправить» не доходит. Проверка написана один раз для всех кнопок.
@router.callback_query(DraftAction.filter(), not_operator)
async def deny_not_operator(callback: CallbackQuery, settings: BotSettings) -> None:
    # Видно в терминале, какой ID пришел, – сразу понятно, что вписать в OPERATOR_IDS
    logger.warning("Отказ: нажал id=%s, операторы=%s", callback.from_user.id, settings.operator_ids)
    await callback.answer(texts.NOT_OPERATOR, show_alert=True)


# DraftAction.filter(...) ловит только кнопки карточки, и только с действием SEND.
# Распакованные данные кнопки aiogram передаст в аргумент callback_data.
@router.callback_query(DraftAction.filter(F.action == Action.SEND))
async def send_draft(
    callback: CallbackQuery,
    callback_data: DraftAction,
    bot: Bot,
    pool: AsyncConnectionPool | None = None,
) -> None:
    card = callback.message
    # Telegram не дает менять сообщения старше 48 часов – тогда вместо Message приходит заглушка
    if not isinstance(card, Message):
        await callback.answer(texts.CARD_TOO_OLD, show_alert=True)
        return

    if pool is None:
        await callback.answer(texts.TICKET_UNAVAILABLE, show_alert=True)
        return
    try:
        client_id = await db.client_chat_id(pool, callback_data.ticket_id)
    except psycopg.Error:
        logger.exception("Не удалось получить чат тикета %s", callback_data.ticket_id)
        await callback.answer(texts.TICKET_UNAVAILABLE, show_alert=True)
        return
    if client_id is None:
        await callback.answer(texts.TICKET_NOT_FOUND, show_alert=True)
        return

    # Пока черновик всегда один. Позже здесь будет «взять черновик заявки из базы»
    reply_text = texts.FAKE_DRAFT
    try:
        await bot.send_message(chat_id=client_id, text=reply_text)
    except TelegramForbiddenError:
        await callback.answer(texts.CLIENT_BLOCKED, show_alert=True)
        return
    except TelegramAPIError:
        logger.exception("Telegram не подтвердил отправку по тикету %s", callback_data.ticket_id)
        await callback.answer(texts.REPLY_SEND_UNCONFIRMED, show_alert=True)
        return

    # Пишем историю после успешной отправки, чтобы не записать недоставленный ответ.
    warning = None
    try:
        await db.save_operator_reply(pool, callback_data.ticket_id, reply_text)
    except psycopg.Error:
        logger.exception("Ответ доставлен, но не сохранен для тикета %s", callback_data.ticket_id)
        warning = texts.REPLY_SAVE_FAILED

    sent_card = texts.card_sent(card.text, callback.from_user.full_name, history_saved=warning is None)
    # Убираем кнопки и при ошибке сохранения: клиент уже получил ответ.
    try:
        await card.edit_text(sent_card)
    except TelegramAPIError:
        logger.exception("Не удалось обновить карточку тикета %s после отправки", callback_data.ticket_id)
        warning = f"{warning}\n{texts.CARD_UPDATE_FAILED}" if warning else texts.CARD_UPDATE_FAILED

    # Ответ на нажатие обязателен, иначе у оператора крутятся «часики»
    if warning is not None:
        await callback.answer(warning, show_alert=True)
    else:
        await callback.answer()


@router.callback_query(DraftAction.filter(F.action == Action.EDIT))
async def edit_draft(callback: CallbackQuery) -> None:
    # Заглушка до следующего этапа
    await callback.answer(texts.EDIT_NOT_READY, show_alert=True)
