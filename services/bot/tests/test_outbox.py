import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import psycopg
import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter, TelegramServerError
from aiogram.methods import SendMessage
from pydantic import SecretStr

from support_bot import main as bot_main, outbox


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


async def test_run_recovers_stale_tasks_and_continues_after_db_error(bot, settings, monkeypatch):
    # На старте проверяем зависшие отправки, после ошибки БД возвращаемся к обработке
    pool = object()
    stop = asyncio.Event()
    recover = AsyncMock(return_value=0)
    handled = AsyncMock(side_effect=[psycopg.OperationalError("database unavailable"), True])
    monkeypatch.setattr(outbox, "mark_stale_unknown", recover)
    monkeypatch.setattr(outbox, "POLL_INTERVAL_S", 0.001)

    async def process(*args):
        if await handled(*args):
            stop.set()
        return True

    monkeypatch.setattr(outbox, "process_next", process)

    await asyncio.wait_for(outbox.run(bot, pool, settings, stop), timeout=1)

    recover.assert_awaited_once_with(pool, outbox.STALE_SEND_AFTER_S)
    assert handled.await_count == 2


async def test_main_waits_for_outbox_before_closing_connections(bot, monkeypatch):
    # Запуск поднимает очередь рядом с Telegram, остановка дожидается ее перед закрытием соединений
    settings = SimpleNamespace(database_url=SecretStr("stub"), bot_token=SecretStr("stub"))
    pool = SimpleNamespace(close=AsyncMock())
    session = AsyncMock()
    session.__aenter__.return_value = bot
    dispatcher = Mock(start_polling=AsyncMock())
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def poll(*args, **kwargs):
        await started.wait()

    async def run_queue(bot, pool, settings, stop):
        started.set()
        await stop.wait()
        session.__aexit__.assert_not_awaited()
        pool.close.assert_not_awaited()
        stopped.set()

    dispatcher.start_polling.side_effect = poll
    monkeypatch.setattr(bot_main, "BotSettings", lambda: settings)
    monkeypatch.setattr(bot_main.db, "open_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr(bot_main, "Bot", Mock(return_value=session))
    monkeypatch.setattr(bot_main, "Dispatcher", Mock(return_value=dispatcher))
    monkeypatch.setattr(outbox, "run", run_queue)

    await asyncio.wait_for(bot_main.main(), timeout=1)

    assert stopped.is_set()
    dispatcher.start_polling.assert_awaited_once_with(bot, close_bot_session=False)
    session.__aexit__.assert_awaited_once()
    pool.close.assert_awaited_once()
