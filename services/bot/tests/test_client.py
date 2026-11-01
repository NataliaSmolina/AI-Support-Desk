from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import psycopg
from aiogram import F

from support_bot import db, texts
from support_bot.handlers.client import PRIVATE_CHAT, help_command, not_text, question, start, status_command


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


async def test_question_db_error_tells_client(monkeypatch):
    # Подменяем запись в базу: она падает, как при недоступном сервере
    monkeypatch.setattr(db, "save_question", AsyncMock(side_effect=psycopg.OperationalError))
    message = AsyncMock()
    message.text = "Где мой заказ?"
    settings = SimpleNamespace(operator_chat_id=None)

    await question(message, AsyncMock(), settings, pool=object(), event_update=SimpleNamespace(update_id=1))

    # Клиенту только сообщение об ошибке, без «Вопрос получен»
    message.answer.assert_awaited_once_with(texts.SAVE_FAILED)


async def test_status_without_db():
    message = AsyncMock()

    await status_command(message, pool=None)

    message.answer.assert_awaited_once_with(texts.STATUS_UNAVAILABLE)


def test_status_list_shows_number_time_and_status():
    # 10:31 по UTC – это 13:31 по Москве
    created_at = datetime(2026, 10, 31, 10, 31, tzinfo=UTC)

    result = texts.status_list([(15, "processing", created_at)]).as_kwargs()

    assert "Обращение #15\n31.10.26, 13:31\nСтатус: В обработке" in result["text"]
    # Номер выделен жирным
    assert result["entities"][0].type == "bold"


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
