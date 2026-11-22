"""Сообщения и кнопки в группе операторов."""

import logging
import re

import psycopg
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message
from psycopg_pool import AsyncConnectionPool

from support_bot import db, texts
from support_bot.config import BotSettings

# Хендлеры этого файла работают только в группах
GROUP_CHAT = F.chat.type.in_({"group", "supergroup"})

router = Router()
router.message.filter(GROUP_CHAT)
logger = logging.getLogger(__name__)


@router.message(Command("chat_id"))
async def chat_id(message: Message) -> None:
    """Подсказывает номера группы и темы, чтобы вписать их в .env."""
    await message.answer(texts.chat_ids(message.chat.id, message.message_thread_id))


@router.message(Command("ticket"))
async def ticket_command(
    message: Message, command: CommandObject, settings: BotSettings, pool: AsyncConnectionPool | None = None,
) -> None:
    """Показывает сведения об обращении оператору в настроенной группе."""
    if (
        settings.operator_chat_id is None
        or message.chat.id != settings.operator_chat_id
        or message.from_user is None
        or message.from_user.id not in settings.operator_ids
    ):
        return
    args = command.args or ""
    if not re.fullmatch(r"[0-9]{1,19}", args) or not 0 < int(args) <= 9_223_372_036_854_775_807:
        await message.answer(texts.TICKET_USAGE)
        return
    if pool is None:
        await message.answer(texts.TICKET_UNAVAILABLE)
        return
    ticket_id = int(args)
    try:
        details = await db.ticket_details(pool, ticket_id)
    except psycopg.Error:
        logger.exception("Не удалось получить тикет %s", ticket_id)
        await message.answer(texts.TICKET_UNAVAILABLE)
        return
    if details is None:
        await message.answer(texts.TICKET_NOT_FOUND)
        return
    ticket, messages = details
    await message.answer(**texts.ticket_details(ticket, messages).as_kwargs())


# Уже отправленные карточки сохраняют старые callback-кнопки.
@router.callback_query(F.data.startswith(("draft:", "ticket_draft:")))
async def outdated_card(callback: CallbackQuery) -> None:
    await callback.answer(texts.CARD_OUTDATED, show_alert=True)
