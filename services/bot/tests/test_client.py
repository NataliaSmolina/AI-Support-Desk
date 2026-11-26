from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import psycopg
from aiogram import F

from support_bot import db, texts
from support_bot.handlers.client import PRIVATE_CHAT, help_command, not_text, question, start, status_command


async def test_start_answers_with_greeting():
    # /start один раз отправляет клиенту текст приветствия
    message = AsyncMock()

    await start(message)

    message.answer.assert_awaited_once_with(texts.START)


async def test_start_logs_user_id(caplog):
    # После /start в журнале появляется Telegram ID клиента
    caplog.set_level("INFO")
    message = AsyncMock()
    message.from_user.id = 123456

    await start(message)

    assert "id=123456" in caplog.text


async def test_help_answers_with_help():
    # /help один раз отправляет инструкцию по работе с ботом
    message = AsyncMock()

    await help_command(message)

    message.answer.assert_awaited_once_with(texts.HELP)


async def test_question_sends_card_to_operators(monkeypatch):
    # Сохраненный вопрос приходит в настроенную тему с кнопкой ответа на тикет №15
    monkeypatch.setattr(db, "save_question", AsyncMock(return_value=15))
    message = AsyncMock()
    message.text = "Где мой заказ?"
    message.caption = None
    message.chat.id = 111
    bot = AsyncMock()
    settings = SimpleNamespace(operator_chat_id=-100222, operator_thread_id=5)

    await question(message, bot, settings, pool=object(), event_update=SimpleNamespace(update_id=1))

    # Достаем аргументы, с которыми бот отправил карточку
    sent = bot.send_message.await_args.kwargs
    assert sent["chat_id"] == -100222
    assert sent["message_thread_id"] == 5
    assert "Где мой заказ?" in sent["text"]
    assert sent["reply_markup"] is not None
    button = sent["reply_markup"].inline_keyboard[0][0]
    assert button.text == "Ответить"
    assert button.callback_data == "reply:15"


async def test_question_without_db_is_not_accepted():
    # Без подключения к базе клиент получает сообщение об ошибке, карточка не отправляется
    message = AsyncMock()
    message.text = "Где мой заказ?"
    message.caption = None
    bot = AsyncMock()
    settings = SimpleNamespace(operator_chat_id=-100222, operator_thread_id=5)

    await question(message, bot, settings)

    message.answer.assert_awaited_once_with(texts.SAVE_FAILED)
    bot.send_message.assert_not_awaited()


async def test_question_without_update_is_not_accepted(monkeypatch):
    # Без события Telegram бот сообщает об ошибке и не вызывает сохранение или отправку карточки
    save = AsyncMock()
    monkeypatch.setattr(db, "save_question", save)
    message = AsyncMock()
    message.text = "Где мой заказ?"
    message.caption = None
    bot = AsyncMock()
    settings = SimpleNamespace(operator_chat_id=-100222, operator_thread_id=5)

    await question(message, bot, settings, pool=object())

    message.answer.assert_awaited_once_with(texts.SAVE_FAILED)
    save.assert_not_awaited()
    bot.send_message.assert_not_awaited()


async def test_question_db_error_tells_client(monkeypatch):
    # Ошибка записи в базу приводит к сообщению SAVE_FAILED
    monkeypatch.setattr(db, "save_question", AsyncMock(side_effect=psycopg.OperationalError))
    message = AsyncMock()
    message.text = "Где мой заказ?"
    settings = SimpleNamespace(operator_chat_id=None)

    await question(message, AsyncMock(), settings, pool=object(), event_update=SimpleNamespace(update_id=1))

    message.answer.assert_awaited_once_with(texts.SAVE_FAILED)


async def test_status_without_db():
    # /status без базы сообщает, что список обращений недоступен
    message = AsyncMock()

    await status_command(message, pool=None)

    message.answer.assert_awaited_once_with(texts.STATUS_UNAVAILABLE)


def test_status_list_shows_number_time_and_status():
    # /status переводит время в московское, показывает понятный статус и выделяет номер жирным
    created_at = datetime(2026, 10, 31, 10, 31, tzinfo=UTC)

    result = texts.status_list([(15, "processing", created_at)]).as_kwargs()

    assert "Обращение #15\n31.10.26, 13:31\nСтатус: В обработке" in result["text"]
    assert result["entities"][0].type == "bold"


async def test_not_text_asks_for_text():
    # Обработчик сообщения без текста просит клиента описать вопрос словами
    message = AsyncMock()

    await not_text(message)

    message.answer.assert_awaited_once_with(texts.ONLY_TEXT)


def test_not_text_filter():
    # Фильтр ~F.text срабатывает для фото без текста и пропускает текстовый вопрос
    no_text = ~F.text

    photo = SimpleNamespace(text=None)
    question = SimpleNamespace(text="Где мой заказ?")

    assert no_text.resolve(photo) is True
    assert no_text.resolve(question) is False


def test_client_handlers_only_in_private_chat():
    # Фильтр клиентских обработчиков принимает личные сообщения и исключает групповые
    private = SimpleNamespace(chat=SimpleNamespace(type="private"))
    group = SimpleNamespace(chat=SimpleNamespace(type="group"))

    assert PRIVATE_CHAT.resolve(private) is True
    assert PRIVATE_CHAT.resolve(group) is False
