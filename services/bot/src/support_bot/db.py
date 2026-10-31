"""Запись вопросов клиентов в PostgreSQL. Worker забирает их оттуда."""

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
