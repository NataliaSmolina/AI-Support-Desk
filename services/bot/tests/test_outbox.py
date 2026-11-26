from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import psycopg
import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter, TelegramServerError
from aiogram.methods import SendMessage

from support_bot import outbox


@pytest.fixture
def task():
    return outbox.OutboxTask(
        id=1, ticket_id=15, reply_round=1, attempts=1, action="send_client_reply",
        chat_id=123, current_round=1, ticket_status="ready", decision="auto",
        decision_reason=None, answer="Ваш заказ уже в пути.", question="Где мой заказ?",
    )


@pytest.fixture
def store(monkeypatch, task):
    claim = AsyncMock(return_value=task)
    finish = AsyncMock()
    confirm = AsyncMock(return_value=True)
    monkeypatch.setattr(outbox, "claim_next", claim)
    monkeypatch.setattr(outbox, "_finish", finish)
    monkeypatch.setattr(outbox, "_confirm_auto_reply", confirm)
    return SimpleNamespace(pool=object(), claim=claim, finish=finish, confirm=confirm)


@pytest.fixture
def bot():
    bot = AsyncMock(spec=Bot)
    bot.send_message.return_value = SimpleNamespace(chat=SimpleNamespace(id=123), message_id=42)
    return bot


@pytest.fixture
def settings():
    return SimpleNamespace(operator_chat_id=-100222, operator_thread_id=5)


async def test_empty_queue_does_not_call_telegram(bot, store, settings):
    # Если PostgreSQL не вернул задачу, обработчик возвращает False без отправки и записи результата
    store.claim.return_value = None

    assert not await outbox.process_next(bot, store.pool, settings)

    bot.send_message.assert_not_awaited()
    store.finish.assert_not_awaited()
    store.confirm.assert_not_awaited()


async def test_auto_reply_is_confirmed_with_telegram_receipt(bot, store, settings, task):
    # Готовый текст отправляется в чат клиента, а в БД передается ответ Telegram с ID сообщения
    assert await outbox.process_next(bot, store.pool, settings)

    bot.send_message.assert_awaited_once_with(chat_id=123, text=task.answer)
    store.confirm.assert_awaited_once_with(store.pool, task, bot.send_message.return_value)
    store.finish.assert_not_awaited()


@pytest.mark.parametrize("status", [
    # Новое обращение ждет назначения оператора – карточку нужно отправить
    "waiting_operator",
    # Обращение уже в работе у оператора – карточку с уточнением тоже нужно отправить
    "operator_processing",
])
async def test_operator_card_uses_configured_topic_and_latest_question(bot, store, settings, task, status):
    # Проверяем чат и тему, причину передачи, последнее сообщение и номер тикета на кнопке
    task = replace(task, action="notify_operator", ticket_status=status, decision="escalate",
                   decision_reason="Не найдены источники", question="Последнее уточнение")
    store.claim.return_value = task
    receipt = bot.send_message.return_value
    receipt.chat.id = settings.operator_chat_id

    assert await outbox.process_next(bot, store.pool, settings)

    bot.send_message.assert_awaited_once()
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == settings.operator_chat_id
    assert kwargs["message_thread_id"] == settings.operator_thread_id
    assert "Не найдены источники" in kwargs["text"]
    assert "Последнее уточнение" in kwargs["text"]
    assert kwargs["reply_markup"].inline_keyboard[0][0].callback_data == "reply:15"
    store.finish.assert_awaited_once_with(store.pool, task, "sent", receipt=receipt)
    store.confirm.assert_not_awaited()


@pytest.mark.parametrize(("error_type", "status"), [
    # При обрыве сети неизвестно, принял ли Telegram сообщение
    (TelegramNetworkError, "unknown"),
    # После серверной ошибки результат отправки тоже неизвестен
    (TelegramServerError, "unknown"),
    # Telegram явно запретил отправку, поэтому попытка завершилась отказом
    (TelegramForbiddenError, "failed"),
])
async def test_telegram_error_does_not_confirm_delivery(bot, store, settings, task, error_type, status):
    # Сохраняем статус и тип ошибки, подтверждение доставки не вызываем
    bot.send_message.side_effect = error_type(SendMessage(chat_id=123, text="test"), "ошибка")

    assert await outbox.process_next(bot, store.pool, settings)

    store.finish.assert_awaited_once_with(store.pool, task, status, error=error_type.__name__)
    store.confirm.assert_not_awaited()


async def test_telegram_rate_limit_reschedules_task(bot, store, settings, task):
    # Если Telegram просит подождать 30 секунд, задача возвращается в pending с этой задержкой
    bot.send_message.side_effect = TelegramRetryAfter(
        SendMessage(chat_id=123, text="test"), "повторите позже", 30,
    )

    assert await outbox.process_next(bot, store.pool, settings)

    store.finish.assert_awaited_once_with(store.pool, task, "pending", error="TelegramRetryAfter", retry_after=30)
    store.confirm.assert_not_awaited()


@pytest.mark.parametrize(("changes", "operator_chat_id", "reason"), [
    # У задачи старый раунд. Она не должна ответить за текущее обращение
    ({"current_round": 2}, -100222, "устаревший раунд обращения"),
    # Автоответ состоит из пробелов. Отправлять клиенту нечего
    ({"answer": " "}, -100222, "автоответ для этого обращения недоступен"),
    # Тикет закрыт. Готовый текст уже нельзя отправлять автоматически
    ({"ticket_status": "closed"}, -100222, "автоответ для этого обращения недоступен"),
    # Для карточки оператора отсутствует чат назначения
    ({"action": "notify_operator", "ticket_status": "waiting_operator"}, None, "не настроен чат операторов"),
    # Закрытое обращение нельзя заново передавать оператору этой задачей
    ({"action": "notify_operator", "ticket_status": "closed"}, -100222, "уведомление для этого обращения недоступно"),
    # Бот не умеет выполнять это действие из очереди
    ({"action": "unexpected"}, -100222, "неизвестное действие очереди"),
])
async def test_invalid_task_is_rejected_before_sending(bot, store, settings, task, changes, operator_chat_id, reason):
    # Каждый вариант должен дать failed с конкретной причиной и без запроса к Telegram
    task = replace(task, **changes)
    store.claim.return_value = task
    settings.operator_chat_id = operator_chat_id

    assert await outbox.process_next(bot, store.pool, settings)

    bot.send_message.assert_not_awaited()
    store.confirm.assert_not_awaited()
    store.finish.assert_awaited_once_with(store.pool, task, "failed", error=reason)


async def test_refused_confirmation_keeps_receipt_for_review(bot, store, settings, task):
    # Telegram вернул ID, но база отказалась подтвердить автоответ – сохраняем unknown вместе с ID
    store.confirm.return_value = False

    assert await outbox.process_next(bot, store.pool, settings)

    bot.send_message.assert_awaited_once()
    store.finish.assert_awaited_once_with(
        store.pool, task, "unknown", error="база не подтвердила автоответ", receipt=bot.send_message.return_value,
    )


async def test_db_failure_after_send_does_not_resend(bot, store, settings):
    # Если БД недоступна после отправки, пробрасываем ошибку и отправляем сообщение только один раз
    store.confirm.side_effect = psycopg.OperationalError("database unavailable")

    with pytest.raises(psycopg.OperationalError):
        await outbox.process_next(bot, store.pool, settings)

    bot.send_message.assert_awaited_once()
    store.finish.assert_not_awaited()
