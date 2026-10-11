from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram import F

from support_bot import texts
from support_bot.handlers.client import help_command, not_text, start


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
