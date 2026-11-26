"""Проверки очереди на отдельной PostgreSQL (TEST_DATABASE_URL)."""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import psycopg
import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendMessage

from support_bot import outbox

pytestmark = pytest.mark.integration
MIGRATIONS = Path(__file__).resolve().parents[3] / "infra" / "postgres" / "migrations"


@pytest.fixture(scope="module")
def test_dsn():
    dsn = os.getenv("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TEST_DATABASE_URL не задан")
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as conn:
        if not conn.info.dbname.endswith("_test"):
            pytest.fail("Для проверок очереди нужна отдельная БД с именем *_test")
        for migration in sorted(MIGRATIONS.glob("*.sql")):
            conn.execute(migration.read_text(encoding="utf-8"))
    return dsn


@pytest.fixture
async def pool(test_dsn):
    async with await psycopg.AsyncConnection.connect(test_dsn, connect_timeout=5) as conn:
        async with conn.transaction(force_rollback=True):
            # У каждой проверки своя очередь. В конце исходное содержимое восстановится
            await conn.execute("TRUNCATE public.bot_outbox")

            @asynccontextmanager
            async def connection():
                yield conn

            yield SimpleNamespace(conn=conn, connection=connection)


@pytest.fixture
def bot():
    bot = AsyncMock(spec=Bot)
    bot.send_message.return_value = SimpleNamespace(chat=SimpleNamespace(id=123), message_id=42)
    return bot


@pytest.fixture
def settings():
    return SimpleNamespace(operator_chat_id=-100222, operator_thread_id=5)


async def seed_ticket(conn, *, action="send_client_reply"):
    auto_reply = action == "send_client_reply"
    cursor = await conn.execute(
        "INSERT INTO public.tickets (chat_id, status, decision, answer, decision_reason) "
        "VALUES (123, %s, %s, %s, %s) RETURNING id",
        ("ready", "auto", "Заказ в пути.", None) if auto_reply else
        ("waiting_operator", "escalate", None, "Не найдены источники"),
    )
    ticket_id, = await cursor.fetchone()
    await conn.execute(
        "INSERT INTO public.messages (ticket_id, author, text) VALUES (%s, 'client', 'Где мой заказ?')",
        (ticket_id,),
    )
    cursor = await conn.execute(
        "INSERT INTO public.bot_outbox (ticket_id, action) VALUES (%s, %s) RETURNING id",
        (ticket_id, action),
    )
    outbox_id, = await cursor.fetchone()
    return ticket_id, outbox_id


@pytest.mark.parametrize(("action", "recipient", "status", "history"), [
    # Автоответ записывается от имени бота, тикет переходит в waiting_client
    ("send_client_reply", 123, "waiting_client", [("client", "Где мой заказ?"), ("bot", "Заказ в пути.")]),
    # Карточка уходит в группу. В истории пока есть только вопрос, тикет ждет оператора
    ("notify_operator", -100222, "waiting_operator", [("client", "Где мой заказ?")]),
])
async def test_successful_delivery_saves_receipt_once(pool, bot, settings, action, recipient, status, history):
    # Обе задачи получают sent, ID чата и сообщения, время отправки и не забираются повторно
    ticket_id, outbox_id = await seed_ticket(pool.conn, action=action)
    bot.send_message.return_value.chat.id = recipient

    assert await outbox.process_next(bot, pool, settings)
    assert not await outbox.process_next(bot, pool, settings)

    bot.send_message.assert_awaited_once()
    cursor = await pool.conn.execute(
        "SELECT o.status, o.attempts, o.telegram_chat_id, o.telegram_message_id, "
        "o.sent_at IS NOT NULL, o.locked_at IS NULL, t.status, t.close_after IS NOT NULL "
        "FROM public.bot_outbox AS o JOIN public.tickets AS t ON t.id = o.ticket_id WHERE o.id = %s",
        (outbox_id,),
    )
    assert await cursor.fetchone() == ("sent", 1, recipient, 42, True, True, status, status == "waiting_client")
    cursor = await pool.conn.execute(
        "SELECT author, text FROM public.messages WHERE ticket_id = %s ORDER BY id", (ticket_id,),
    )
    assert await cursor.fetchall() == history


async def test_rate_limited_task_only_retries_when_due(pool, bot, settings):
    # До next_attempt_at задача ждет. Когда срок наступает, вторая попытка записывается как sent
    _, outbox_id = await seed_ticket(pool.conn)
    bot.send_message.side_effect = TelegramRetryAfter(SendMessage(chat_id=123, text="test"), "retry", 300)

    assert await outbox.process_next(bot, pool, settings)
    assert not await outbox.process_next(bot, pool, settings)
    cursor = await pool.conn.execute(
        "SELECT status, attempts, next_attempt_at > statement_timestamp(), locked_at IS NULL "
        "FROM public.bot_outbox WHERE id = %s", (outbox_id,),
    )
    assert await cursor.fetchone() == ("pending", 1, True, True)
    await pool.conn.execute(
        "UPDATE public.bot_outbox SET next_attempt_at = statement_timestamp() WHERE id = %s", (outbox_id,),
    )
    bot.send_message.side_effect = None

    assert await outbox.process_next(bot, pool, settings)
    cursor = await pool.conn.execute("SELECT status, attempts FROM public.bot_outbox WHERE id = %s", (outbox_id,))
    assert await cursor.fetchone() == ("sent", 2)


async def test_stale_claim_is_not_sent_again(pool, bot, settings):
    # Свежий захват еще действует. Просроченный переходит в unknown и не отправляется повторно
    _, outbox_id = await seed_ticket(pool.conn)

    task = await outbox.claim_next(pool)
    assert task is not None and task.id == outbox_id
    assert await outbox.claim_next(pool) is None
    assert await outbox.mark_stale_unknown(pool, timeout_s=60) == 0
    await pool.conn.execute(
        "UPDATE public.bot_outbox SET locked_at = statement_timestamp() - interval '2 minutes' WHERE id = %s",
        (outbox_id,),
    )

    assert await outbox.mark_stale_unknown(pool, timeout_s=60) == 1
    assert not await outbox.process_next(bot, pool, settings)
    bot.send_message.assert_not_awaited()
    cursor = await pool.conn.execute(
        "SELECT status, attempts, locked_at IS NULL, sent_at IS NULL FROM public.bot_outbox WHERE id = %s",
        (outbox_id,),
    )
    assert await cursor.fetchone() == ("unknown", 1, True, True)
