from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram import F

from support_bot import texts
from support_bot.handlers.client import PRIVATE_CHAT, help_command, not_text, question, start


async def test_start_answers_with_greeting():
    # Вместо настоящего сообщения из Telegram — заглушка
    message = AsyncMock()

    await start(message)

    message.answer.assert_awaited_once_with(texts.START)


async def test_start_logs_user_id(caplog):
    # caplog — встроенная в pytest «ловушка» для логов
    caplog.set_level("INFO")
    message = AsyncMock()
    message.from_user.id = 123456

    await start(message)

    assert "id=123456" in caplog.text


async def test_help_answers_with_help():
    message = AsyncMock()

    await help_command(message)

    message.answer.assert_awaited_once_with(texts.HELP)


async def test_question_answers_accepted():
    message = AsyncMock()
    bot = AsyncMock()
    # Группа операторов не задана
    settings = SimpleNamespace(operator_chat_id=None, operator_thread_id=None)

    await question(message, bot, settings)

    message.answer.assert_awaited_once_with(texts.ACCEPTED)
    bot.send_message.assert_not_awaited()


async def test_question_sends_card_to_operators():
    message = AsyncMock()
    message.text = "Где мой заказ?"
    message.chat.id = 111
    bot = AsyncMock()
    settings = SimpleNamespace(operator_chat_id=-100222, operator_thread_id=5)

    await question(message, bot, settings)

    # Достаём аргументы, с которыми бот отправил карточку
    sent = bot.send_message.await_args.kwargs
    assert sent["chat_id"] == -100222
    assert sent["message_thread_id"] == 5
    assert "Где мой заказ?" in sent["text"]
    assert sent["reply_markup"] is not None


async def test_not_text_asks_for_text():
    message = AsyncMock()

    await not_text(message)

    message.answer.assert_awaited_once_with(texts.ONLY_TEXT)


def test_not_text_filter():
    # Тот же фильтр, что в хендлере not_text
    no_text = ~F.text

    photo = SimpleNamespace(text=None)
    question = SimpleNamespace(text="Где мой заказ?")

    assert no_text.resolve(photo) is True
    assert no_text.resolve(question) is False


def test_client_handlers_only_in_private_chat():
    private = SimpleNamespace(chat=SimpleNamespace(type="private"))
    group = SimpleNamespace(chat=SimpleNamespace(type="group"))

    assert PRIVATE_CHAT.resolve(private) is True
    assert PRIVATE_CHAT.resolve(group) is False
