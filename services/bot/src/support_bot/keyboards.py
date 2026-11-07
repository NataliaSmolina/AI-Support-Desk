"""Кнопки под сообщениями бота."""

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from support_bot import texts


class Action(StrEnum):
    """Что можно сделать с черновиком. Другие значения – ошибка, а не тихо неработающая кнопка."""

    SEND = "send"
    EDIT = "edit"


class DraftAction(CallbackData, prefix="ticket_draft"):
    """Данные, зашитые в кнопку карточки.

    Telegram хранит их как строку, например 'ticket_draft:send:15'.
    CallbackData сам превращает объект в строку (pack) и обратно (unpack).
    """

    action: Action
    ticket_id: int


def draft_keyboard(ticket_id: int) -> InlineKeyboardMarkup:
    """Кнопки «Отправить» и «Исправить» под карточкой оператора."""
    send = InlineKeyboardButton(
        text=texts.BUTTON_SEND,
        callback_data=DraftAction(action=Action.SEND, ticket_id=ticket_id).pack(),
    )
    edit = InlineKeyboardButton(
        text=texts.BUTTON_EDIT,
        callback_data=DraftAction(action=Action.EDIT, ticket_id=ticket_id).pack(),
    )
    # Список списков: каждый внутренний список — один ряд кнопок
    return InlineKeyboardMarkup(inline_keyboard=[[send, edit]])
