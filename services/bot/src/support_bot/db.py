"""Обращения и история сообщений в PostgreSQL."""

from datetime import datetime

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


async def client_chat_id(pool: AsyncConnectionPool, ticket_id: int) -> int | None:
    """Чат клиента по номеру тикета. None – тикет не найден."""
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT chat_id FROM tickets WHERE id = %s", (ticket_id,))
        row = await cur.fetchone()
        return row[0] if row is not None else None


async def save_operator_reply(pool: AsyncConnectionPool, ticket_id: int, text: str) -> None:
    """Сохраняет доставленный ответ в истории обращения."""
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO messages (ticket_id, author, text) VALUES (%s, 'operator', %s)",
            (ticket_id, text),
        )
