"""Кнопки под сообщениями бота."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from support_bot import texts

REPLY_START_PREFIX = "reply_"
REPLY_CALLBACK_PREFIX = "reply:"


def reply_keyboard(ticket_id: int) -> InlineKeyboardMarkup:
    """Передает боту номер обращения и сообщение с карточкой."""
    button = InlineKeyboardButton(
        text=texts.BUTTON_REPLY, callback_data=f"{REPLY_CALLBACK_PREFIX}{ticket_id}",
    )
    return InlineKeyboardMarkup(inline_keyboard=[[button]])
