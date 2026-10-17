"""Сообщения и кнопки в группе операторов."""

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from support_bot import texts
from support_bot.keyboards import DraftAction

# Хендлеры этого файла работают только в группах
GROUP_CHAT = F.chat.type.in_({"group", "supergroup"})

router = Router()
router.message.filter(GROUP_CHAT)


@router.message(Command("chat_id"))
async def chat_id(message: Message) -> None:
    """Подсказывает номера группы и темы, чтобы вписать их в .env."""
    await message.answer(texts.chat_ids(message.chat.id, message.message_thread_id))


# DraftAction.filter(...) ловит только кнопки карточки, и только с action="send".
# Распакованные данные кнопки aiogram передаст в аргумент callback_data.
@router.callback_query(DraftAction.filter(F.action == "send"))
async def send_draft(callback: CallbackQuery, callback_data: DraftAction, bot: Bot) -> None:
    card = callback.message
    # Telegram не дает менять сообщения старше 48 часов – тогда вместо Message приходит заглушка
    if not isinstance(card, Message):
        await callback.answer(texts.CARD_TOO_OLD, show_alert=True)
        return

    # Пока черновик всегда один. Позже здесь будет «взять черновик заявки из базы»
    try:
        await bot.send_message(chat_id=callback_data.chat_id, text=texts.FAKE_DRAFT)
    except TelegramForbiddenError:
        await callback.answer(texts.CLIENT_BLOCKED, show_alert=True)
        return

    # edit_text без reply_markup убирает кнопки – второй раз отправить нельзя
    await card.edit_text(texts.card_sent(card.text, callback.from_user.full_name))
    # Ответ на нажатие обязателен, иначе у оператора крутятся «часики»
    await callback.answer()


@router.callback_query(DraftAction.filter(F.action == "edit"))
async def edit_draft(callback: CallbackQuery) -> None:
    # Заглушка до следующего этапа
    await callback.answer(texts.EDIT_NOT_READY, show_alert=True)
