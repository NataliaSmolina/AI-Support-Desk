from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import psycopg
import pytest
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


@pytest.mark.parametrize("text", [
    "Где мой заказ?",  # Обычный вопрос должен уйти в обработку Worker
    "Позови оператора",  # Просьба об операторе тоже сохраняется для решения Worker
])
async def test_question_saves_text_and_only_confirms_receipt(monkeypatch, text):
    # После записи бот присылает только номер тикета, даже если клиент попросил оператора
    save = AsyncMock(return_value=15)
    monkeypatch.setattr(db, "save_question", save)
    message = AsyncMock()
    message.text = text
    message.caption = None
    message.chat.id = 111
    pool = object()

    await question(message, pool=pool, event_update=SimpleNamespace(update_id=1))

    save.assert_awaited_once_with(pool, 1, 111, text)
    message.answer.assert_awaited_once_with(texts.accepted(15))


async def test_question_keeps_caption_and_warns_about_attachment(monkeypatch):
    # Подпись сохраняется как вопрос, клиент видит номер и предупреждение о вложении
    save = AsyncMock(return_value=15)
    monkeypatch.setattr(db, "save_question", save)
    message = AsyncMock(text=None, caption="Где возврат?")
    message.chat.id = 111
    pool = object()

    await question(message, pool=pool, event_update=SimpleNamespace(update_id=1))

    save.assert_awaited_once_with(pool, 1, 111, "Где возврат?")
    assert message.answer.await_args_list == [call(texts.accepted(15)), call(texts.ATTACHMENT_IGNORED)]


async def test_question_without_db_is_not_accepted():
    # Без подключения к базе клиент получает сообщение об ошибке приема
    message = AsyncMock()
    message.text = "Где мой заказ?"
    message.caption = None
    await question(message)

    message.answer.assert_awaited_once_with(texts.SAVE_FAILED)


async def test_question_without_update_is_not_accepted(monkeypatch):
    # Без события Telegram бот сообщает об ошибке и не вызывает сохранение
    save = AsyncMock()
    monkeypatch.setattr(db, "save_question", save)
    message = AsyncMock()
    message.text = "Где мой заказ?"
    message.caption = None
    await question(message, pool=object())

    message.answer.assert_awaited_once_with(texts.SAVE_FAILED)
    save.assert_not_awaited()


async def test_question_db_error_tells_client(monkeypatch):
    # Ошибка записи в базу приводит к сообщению SAVE_FAILED
    monkeypatch.setattr(db, "save_question", AsyncMock(side_effect=psycopg.OperationalError))
    message = AsyncMock()
    message.text = "Где мой заказ?"
    await question(message, pool=object(), event_update=SimpleNamespace(update_id=1))

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


@pytest.mark.parametrize(("status", "label"), [
    ("ready", "Ответ готовится к отправке"),  # Worker подготовил ответ
    ("waiting_operator", "Ожидает оператора"),  # Нужен ручной ответ
    ("operator_processing", "В работе у оператора"),  # Обращение уже взяли
    ("waiting_client", "Ожидаем ответа клиента"),  # Ответ уже отправлен
    ("closed", "Закрыто"),  # Обращение завершено
])
def test_status_list_translates_lifecycle_statuses(status, label):
    # /status показывает клиенту понятную подпись для каждого нового этапа
    created_at = datetime(2026, 10, 31, 10, 31, tzinfo=UTC)

    text, _ = texts.status_list([(15, status, created_at)]).render()

    assert f"Статус: {label}" in text


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
