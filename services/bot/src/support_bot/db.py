"""Обращения и история сообщений в PostgreSQL."""

from dataclasses import dataclass
from datetime import datetime

from psycopg import AsyncConnection
from psycopg.rows import class_row, dict_row
from psycopg_pool import AsyncConnectionPool


async def open_pool(database_url: str) -> AsyncConnectionPool:
    """Пул – несколько готовых соединений с базой, хендлеры берут их по очереди."""
    # open=False и отдельный open советует открывать в async по документации
    pool = AsyncConnectionPool(database_url, open=False, timeout=10)
    await pool.open()
    return pool


async def save_question(pool: AsyncConnectionPool, update_id: int, chat_id: int, text: str) -> int | None:
    """Создает тикет с вопросом клиента и возвращает его номер. None – это сообщение уже сохраняли."""
    # Все записи в одной транзакции, при ошибке не сохранится ничего
    async with pool.connection() as conn:
        # Проверка на двойную отправку
        cur = await conn.execute(
            "INSERT INTO tg_updates (update_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (update_id,),
        )
        if cur.rowcount == 0:
            return None

        # Статус 'new' база ставит сама – по нему worker находит новые тикеты
        cur = await conn.execute("INSERT INTO tickets (chat_id) VALUES (%s) RETURNING id", (chat_id,))
        (ticket_id,) = await cur.fetchone()

        await conn.execute(
            "INSERT INTO messages (ticket_id, author, text) VALUES (%s, 'client', %s)",
            (ticket_id, text),
        )
        return ticket_id


async def client_tickets(pool: AsyncConnectionPool, chat_id: int, limit: int = 5) -> list[tuple[int, str, datetime]]:
    """Последние обращения клиента: номер, статус и время создания, новые сверху."""
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, status, created_at FROM tickets WHERE chat_id = %s ORDER BY id DESC LIMIT %s",
            (chat_id, limit),
        )
        return await cur.fetchall()


@dataclass(frozen=True)
class OperatorTicket:
    chat_id: int
    reply_round: int
    status: str
    operator_id: int | None

    def can_reply(self, operator_id: int) -> bool:
        return self.status == "operator_processing" and self.operator_id == operator_id


async def _operator_ticket(conn: AsyncConnection, ticket_id: int) -> OperatorTicket | None:
    async with conn.cursor(row_factory=class_row(OperatorTicket)) as cur:
        await cur.execute(
            "SELECT chat_id, reply_round, status, operator_id FROM public.tickets WHERE id = %s",
            (ticket_id,),
        )
        return await cur.fetchone()


async def operator_ticket(pool: AsyncConnectionPool, ticket_id: int) -> OperatorTicket | None:
    """Возвращает адресата, раунд и назначение тикета перед отправкой ответа."""
    async with pool.connection() as conn:
        return await _operator_ticket(conn, ticket_id)


async def claim_operator_ticket(
    pool: AsyncConnectionPool, ticket_id: int, operator_id: int,
) -> OperatorTicket | None:
    """Пробует назначить оператора и возвращает фактическое состояние тикета."""
    async with pool.connection() as conn:
        # SQL назначает свободный тикет, а чтение показывает владельца и при повторном открытии
        await conn.execute("SELECT public.claim_operator_ticket(%s, %s)", (ticket_id, operator_id))
        return await _operator_ticket(conn, ticket_id)


async def ticket_details(pool: AsyncConnectionPool, ticket_id: int) -> tuple[dict, list[dict]] | None:
    """Обращение, результат Worker и пять последних сообщений для оператора."""
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT id, status, category, priority, sentiment, wants_human, "
                "decision, decision_reason, answer "
                "FROM public.tickets WHERE id = %s",
                (ticket_id,),
            )
            ticket = await cur.fetchone()
            if ticket is None:
                return None
            await cur.execute(
                "SELECT author, left(text, 300) AS text FROM public.messages "
                "WHERE ticket_id = %s ORDER BY id DESC LIMIT 5",
                (ticket_id,),
            )
            messages = await cur.fetchall()
            return ticket, list(reversed(messages))


async def confirm_operator_reply(
    pool: AsyncConnectionPool, ticket_id: int, reply_round: int, operator_id: int, text: str,
) -> bool:
    """Сохраняет отправленный ответ и переводит текущий раунд в ожидание клиента."""
    async with pool.connection() as conn:
        # PostgreSQL обновляет статус и записывает ответ в историю в одной транзакции
        cur = await conn.execute(
            "SELECT public.confirm_operator_reply(%s, %s, %s, %s)",
            (ticket_id, reply_round, operator_id, text),
        )
        (saved,) = await cur.fetchone()
        return saved
