"""Сообщения в группе операторов."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from support_bot import texts

# Хендлеры этого файла работают только в группах
GROUP_CHAT = F.chat.type.in_({"group", "supergroup"})

router = Router()
router.message.filter(GROUP_CHAT)


@router.message(Command("chat_id"))
async def chat_id(message: Message) -> None:
    """Подсказывает номера группы и темы, чтобы вписать их в .env."""
    await message.answer(texts.chat_ids(message.chat.id, message.message_thread_id))
