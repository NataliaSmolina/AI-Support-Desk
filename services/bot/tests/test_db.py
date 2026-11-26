"""Тесты на настоящей базе. Запуск: uv run pytest -m integration services/bot

Все записи делаются в транзакции, которая в конце откатывается, – в общей базе ничего не остается.
"""

from contextlib import asynccontextmanager

import psycopg
import pytest
from pydantic import ValidationError

from support_bot import db
from support_bot.config import BotSettings

# Обычный uv run pytest эти тесты пропускает – нужна база
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

    # connect_timeout – если база недоступна (например, выключен Tailscale), ошибка через 5 секунд, а не зависание
    async with await psycopg.AsyncConnection.connect(url.get_secret_value(), connect_timeout=5) as conn:
        # force_rollback – в конце все отменяется, даже если тест прошел
        async with conn.transaction(force_rollback=True):
            yield RollbackPool(conn)


async def test_question_creates_new_ticket_with_message(pool):
    # Вопрос создает тикет со статусом new и сообщение клиента, привязанное к этому тикету
    ticket_id = await db.save_question(pool, UPDATE_ID, 111, "Где мой заказ?")

    cur = await pool.conn.execute(
        "SELECT t.status, t.chat_id, m.author, m.text "
        "FROM tickets t JOIN messages m ON m.ticket_id = t.id WHERE t.id = %s",
        (ticket_id,),
    )
    assert await cur.fetchone() == ("new", 111, "client", "Где мой заказ?")


async def test_client_sees_own_ticket_first(pool):
    # В списке клиента только что созданное обращение идет первым со статусом new
    ticket_id = await db.save_question(pool, UPDATE_ID, 111, "Где мой заказ?")

    tickets = await db.client_tickets(pool, 111)

    first_id, status, _created_at = tickets[0]
    assert (first_id, status) == (ticket_id, "new")


async def test_repeated_update_is_skipped(pool):
    # Первый update_id дает номер тикета. Повтор того же события возвращает None
    first = await db.save_question(pool, UPDATE_ID, 111, "Где мой заказ?")
    second = await db.save_question(pool, UPDATE_ID, 111, "Где мой заказ?")

    assert first is not None
    assert second is None


async def test_client_chat_id_comes_from_ticket(pool):
    # По номеру тикета находим чат клиента, а для неизвестного номера получаем None
    ticket_id = await db.save_question(pool, UPDATE_ID, 111, "Где мой заказ?")

    assert await db.client_chat_id(pool, ticket_id) == 111
    assert await db.client_chat_id(pool, -1) is None


async def test_operator_reply_is_saved_in_ticket_history(pool):
    # История одного тикета содержит вопрос с автором client и ответ с автором operator
    question = "Где мой заказ?"
    reply = "Заказ '123' в пути."
    ticket_id = await db.save_question(pool, UPDATE_ID, 111, question)

    await db.save_operator_reply(pool, ticket_id, reply)

    cur = await pool.conn.execute(
        "SELECT author, text FROM messages WHERE ticket_id = %s ORDER BY id",
        (ticket_id,),
    )
    assert await cur.fetchall() == [("client", question), ("operator", reply)]


async def test_ticket_details_returns_recent_messages(pool):
    # Получаем данные тикета и пять последних сообщений по порядку, каждое до 300 символов
    ticket_id = await db.save_question(pool, UPDATE_ID, 111, "Первый вопрос")
    for number in range(6):
        await db.save_operator_reply(pool, ticket_id, f"Ответ {number} " + "x" * 400)

    ticket, messages = await db.ticket_details(pool, ticket_id)

    assert ticket["id"] == ticket_id
    assert ticket["status"] == "new"
    assert ticket["category"] is None
    assert len(messages) == 5
    assert messages[0]["text"].startswith("Ответ 1")
    assert messages[-1]["text"].startswith("Ответ 5")
    assert all(len(message["text"]) <= 300 for message in messages)
    # Для неизвестного номера история и данные тикета отсутствуют
    assert await db.ticket_details(pool, -1) is None
