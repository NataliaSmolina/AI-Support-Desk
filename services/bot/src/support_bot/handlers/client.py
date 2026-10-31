"""Сообщения от клиентов."""

import logging

import psycopg
from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, Update
from psycopg_pool import AsyncConnectionPool

from support_bot import db, texts
from support_bot.config import BotSettings
from support_bot.keyboards import draft_keyboard

# Все хендлеры этого файла работают только в личке с ботом, не в группах
PRIVATE_CHAT = F.chat.type == "private"

router = Router()
router.message.filter(PRIVATE_CHAT)
logger = logging.getLogger(__name__)


@router.message(CommandStart())
async def start(message: Message) -> None:
    logger.info("/start от пользователя id=%s", message.from_user.id)
    await message.answer(texts.START)


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(texts.HELP)


# F.text – обычный текст, F.caption – подпись к фото или файлу. «|» значит «или».
# Команды /start и /help тоже текст, но их ловят хендлеры выше: проверка идёт сверху вниз.
@router.message(F.text | F.caption)
async def question(
    message: Message,
    bot: Bot,
    settings: BotSettings,
    pool: AsyncConnectionPool | None = None,
    event_update: Update | None = None,
) -> None:
    # event_update – всё событие от Telegram, из него нужен номер update_id
    # У обычного сообщения text, у текста с фото caption
    text = message.text or message.caption

    # Сначала сохраняем, потом говорим «получен»
    if pool is not None and event_update is not None:
        try:
            ticket_id = await db.save_question(pool, event_update.update_id, message.chat.id, text)
        except psycopg.Error:
            logger.exception("Не удалось сохранить вопрос от chat_id=%s", message.chat.id)
            await message.answer(texts.SAVE_FAILED)
            return
        # Повтор соо
        if ticket_id is None:
            return
        logger.info("Тикет %s от chat_id=%s", ticket_id, message.chat.id)

    await message.answer(texts.ACCEPTED)
    if message.caption:
        await message.answer(texts.ATTACHMENT_IGNORED)

    if settings.operator_chat_id is None:
        return

    # Прототип: позже карточку будет отправлять не этот хендлер, а бот по готовому черновику из базы
    await bot.send_message(
        chat_id=settings.operator_chat_id,
        message_thread_id=settings.operator_thread_id,
        text=texts.card(text, texts.FAKE_DRAFT),
        reply_markup=draft_keyboard(message.chat.id),
    )


# Сюда доходит только то, где нет ни текста, ни подписи: стикер, голосовое, фото без подписи.
@router.message(~F.text)
async def not_text(message: Message) -> None:
    await message.answer(texts.ONLY_TEXT)
