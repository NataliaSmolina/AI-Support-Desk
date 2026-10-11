"""Сообщения от клиентов."""

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from support_bot import texts

router = Router()
logger = logging.getLogger(__name__)


@router.message(CommandStart())
async def start(message: Message) -> None:
    logger.info("/start от пользователя id=%s", message.from_user.id)
    await message.answer(texts.START)


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(texts.HELP)


# ~F.text — «в сообщении нет текста»: фото, стикер, голосовое, файл.
# Хендлеры проверяются сверху вниз, поэтому этот стоит последним.
@router.message(~F.text)
async def not_text(message: Message) -> None:
    await message.answer(texts.ONLY_TEXT)
