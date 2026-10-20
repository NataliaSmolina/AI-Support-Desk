import psycopg
from psycopg.rows import dict_row

_OWNED = "id = %(id)s AND locked_by = %(worker)s AND status = 'processing'"

_CLAIM_SQL = """
WITH picked AS (
    SELECT t.id
    FROM public.tickets AS t
    WHERE t.status = 'new'
      AND t.next_attempt_at <= NOW()
      AND EXISTS (
          SELECT 1 FROM public.messages AS m
          WHERE m.ticket_id = t.id AND m.author = 'client'
      )
    ORDER BY t.next_attempt_at, t.id
    FOR UPDATE OF t SKIP LOCKED
    LIMIT 1
), claimed AS (
    UPDATE public.tickets AS t
    SET status = 'processing', locked_at = NOW(), locked_by = %(worker)s,
        attempts = t.attempts + 1
    FROM picked
    WHERE t.id = picked.id
    RETURNING t.id, t.chat_id, t.attempts
)
SELECT c.id, c.chat_id, c.attempts,
       (SELECT m.text FROM public.messages AS m
        WHERE m.ticket_id = c.id AND m.author = 'client'
        ORDER BY m.created_at, m.id LIMIT 1) AS message
FROM claimed AS c
"""


def claim_ticket(conn: psycopg.Connection, worker_id: str) -> dict | None:
    """Забирает один тикет или возвращает None, если очередь пуста"""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_CLAIM_SQL, {"worker": worker_id})
        row = cur.fetchone()
    conn.commit()
    return row


def touch_ticket(conn: psycopg.Connection, ticket_id: int, worker_id: str) -> bool:
    """обновляет locked_at. False: тикет у нас уже отобрали, обработка завершается"""
    cur = conn.execute(
        f"UPDATE public.tickets SET locked_at = NOW() WHERE {_OWNED}",
        {"id": ticket_id, "worker": worker_id},
    )
    conn.commit()
    return cur.rowcount == 1


def finish_classification(
    conn: psycopg.Connection, ticket_id: int, worker_id: str, *,
    category: str, priority: str, sentiment: str, wants_human: bool,
) -> bool:
    """Сохраняет результат классификации. False: тикет уже не наш, результат отбрасывается"""
    cur = conn.execute(
        "UPDATE public.tickets SET status = 'classified', category = %(category)s, "
        "priority = %(priority)s, sentiment = %(sentiment)s, wants_human = %(wants_human)s, "
        f"locked_at = NULL, locked_by = NULL, last_error = NULL WHERE {_OWNED}",
        {"id": ticket_id, "worker": worker_id, "category": category, "priority": priority,
         "sentiment": sentiment, "wants_human": wants_human},
    )
    conn.commit()
    return cur.rowcount == 1


def release_for_retry(
    conn: psycopg.Connection, ticket_id: int, worker_id: str, error: str, delay_s: float,
    *, refund_attempt: bool = False,
) -> bool:
    """Временная ошибка: тикет возвращается в очередь и станет доступен через delay_s секунд.

    refund_attempt=True не засчитывает попытку
    """
    cur = conn.execute(
        "UPDATE public.tickets SET status = 'new', locked_at = NULL, locked_by = NULL, "
        "last_error = %(error)s, next_attempt_at = NOW() + make_interval(secs => %(delay)s), "
        f"attempts = GREATEST(attempts - %(refund)s, 0) WHERE {_OWNED}",
        {"id": ticket_id, "worker": worker_id, "error": error, "delay": delay_s,
         "refund": int(refund_attempt)},
    )
    conn.commit()
    return cur.rowcount == 1


def mark_failed(conn: psycopg.Connection, ticket_id: int, worker_id: str, error: str) -> bool:
    """Попытки исчерпаны или ошибка постоянная: тикет уходит оператору"""
    cur = conn.execute(
        "UPDATE public.tickets SET status = 'failed', decision = 'escalate', "
        f"last_error = %(error)s, locked_at = NULL, locked_by = NULL WHERE {_OWNED}",
        {"id": ticket_id, "worker": worker_id, "error": error},
    )
    conn.commit()
    return cur.rowcount == 1


def recover_stuck(
    conn: psycopg.Connection, max_attempts: int, lock_timeout_s: float
) -> tuple[list[int], list[int]]:
    """Возвращает id вернувшихся в очередь, id отправленных оператору

    Зависший тикет: статус `processing`, а locked_at старше lock_timeout_s. Живой worker
    обновляет locked_at, поэтому его тикет сюда не попадает.
    """
    params = {"timeout": lock_timeout_s, "max": max_attempts}
    stale = "status = 'processing' AND locked_at < NOW() - make_interval(secs => %(timeout)s)"
    requeued = conn.execute(
        "UPDATE public.tickets SET status = 'new', locked_at = NULL, locked_by = NULL, "
        "last_error = 'worker перестал отвечать, тикет возвращён в очередь', "
        f"next_attempt_at = NOW() WHERE {stale} AND attempts < %(max)s RETURNING id",
        params,
    ).fetchall()
    failed = conn.execute(
        "UPDATE public.tickets SET status = 'failed', decision = 'escalate', "
        "locked_at = NULL, locked_by = NULL, "
        "last_error = 'worker перестал отвечать, попытки исчерпаны' "
        f"WHERE {stale} AND attempts >= %(max)s RETURNING id",
        params,
    ).fetchall()
    conn.commit()
    return [r[0] for r in requeued], [r[0] for r in failed]