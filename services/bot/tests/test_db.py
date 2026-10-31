"""Тесты на настоящей базе. Запуск: uv run pytest -m integration services/bot

Все записи делаются в транзакции, которая в конце откатывается, – в общей базе ничего не остается.
"""

from contextlib import asynccontextmanager

import psycopg
import pytest
from pydantic import ValidationError

from support_bot import db
from support_bot.config import BotSettings

# Обычный uv run pytest эти тесты пропускает: нужна база
pytestmark = pytest.mark.integration

UPDATE_ID = 999_000_001


class RollbackPool:
    """Подмена пула: отдает одно и то же соединение, внутри которого открыта откатываемая транзакция."""

    def __init__(self, conn: psycopg.AsyncConnection):
        self.conn = conn

    @asynccontextmanager
    async def connection(self):
        yield self.conn


@pytest.fixture
async def pool():
    try:
        url = BotSettings().database_url
    except ValidationError:
        url = None
    if url is None:
        pytest.skip("DATABASE_URL не задан")

    async with await psycopg.AsyncConnection.connect(url.get_secret_value()) as conn:
        # force_rollback: в конце всё отменяется, даже если тест прошел
        async with conn.transaction(force_rollback=True):
            yield RollbackPool(conn)


async def test_question_creates_new_ticket_with_message(pool):
    ticket_id = await db.save_question(pool, UPDATE_ID, 111, "Где мой заказ?")

    cur = await pool.conn.execute(
        "SELECT t.status, t.chat_id, m.author, m.text "
        "FROM tickets t JOIN messages m ON m.ticket_id = t.id WHERE t.id = %s",
        (ticket_id,),
    )
    # Именно такой тикет ищет worker: статус new и сообщение от client
    assert await cur.fetchone() == ("new", 111, "client", "Где мой заказ?")


async def test_repeated_update_is_skipped(pool):
    first = await db.save_question(pool, UPDATE_ID, 111, "Где мой заказ?")
    second = await db.save_question(pool, UPDATE_ID, 111, "Где мой заказ?")

    assert first is not None
    assert second is None
