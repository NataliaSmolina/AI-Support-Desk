"""Кнопки под сообщениями бота."""

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from support_bot import texts


class DraftAction(CallbackData, prefix="draft"):
    """Данные, зашитые в кнопку карточки.

    Telegram хранит их как строку, например 'draft:send:123456'.
    CallbackData сам превращает объект в строку (pack) и обратно (unpack).
    """

    action: str  # "send" или "edit"
    chat_id: int  # куда отправить ответ — личка клиента


def draft_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """Кнопки «Отправить» и «Исправить» под карточкой оператора."""
    send = InlineKeyboardButton(
        text=texts.BUTTON_SEND,
        callback_data=DraftAction(action="send", chat_id=chat_id).pack(),
    )
    edit = InlineKeyboardButton(
        text=texts.BUTTON_EDIT,
        callback_data=DraftAction(action="edit", chat_id=chat_id).pack(),
    )
    # Список списков: каждый внутренний список — один ряд кнопок
    return InlineKeyboardMarkup(inline_keyboard=[[send, edit]])
