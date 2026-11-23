import psycopg
from psycopg.rows import dict_row

_OWNED = "id = %(id)s AND locked_by = %(worker)s AND status = 'processing'"

_CLAIM_SQL = """
WITH picked AS (
    SELECT t.id
    FROM public.tickets AS t
    WHERE t.status = 'new'
      AND t.next_attempt_at <= statement_timestamp()
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
        ORDER BY m.id DESC LIMIT 1) AS message
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


def _enqueue(conn: psycopg.Connection, ticket_ids: list[int], action: str) -> None:
    if ticket_ids:
        conn.execute(
            "INSERT INTO public.bot_outbox (ticket_id, reply_round, action) "
            "SELECT id, reply_round, %s FROM public.tickets WHERE id = ANY(%s) "
            "ON CONFLICT (ticket_id, reply_round, action) DO NOTHING",
            (action, ticket_ids),
        )


def finish_processing(
    conn: psycopg.Connection,
    ticket_id: int,
    worker_id: str,
    *,
    category: str,
    priority: str,
    sentiment: str,
    wants_human: bool,
    decision: str,
    decision_reason: str,
    answer: str | None,
    source_ids: list[str],
) -> bool:
    """Сохраняет результат обработки и ставит задачу для бота."""
    auto = decision == "auto"
    if auto and (not answer or not answer.strip() or not source_ids):
        raise ValueError("для автоответа нужны текст и источники")
    cur = conn.execute(
        "UPDATE public.tickets SET "
        "status = %(status)s, "
        "category = %(category)s, "
        "priority = %(priority)s, "
        "sentiment = %(sentiment)s, "
        "wants_human = %(wants_human)s, "
        "decision = %(decision)s, "
        "decision_reason = %(decision_reason)s, "
        "answer = %(answer)s, "
        "source_ids = %(source_ids)s, "
        "close_after = NULL, locked_at = NULL, locked_by = NULL, last_error = NULL "
        f"WHERE {_OWNED}",
        {
            "id": ticket_id,
            "worker": worker_id,
            "status": "ready" if auto else "waiting_operator",
            "category": category,
            "priority": priority,
            "sentiment": sentiment,
            "wants_human": wants_human,
            "decision": decision,
            "decision_reason": decision_reason,
            "answer": answer,
            "source_ids": source_ids,
        },
    )
    saved = cur.rowcount == 1
    if saved:
        _enqueue(conn, [ticket_id], "send_client_reply" if auto else "notify_operator")
    conn.commit()
    return saved


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
        "UPDATE public.tickets SET status = 'waiting_operator', decision = 'escalate', "
        "decision_reason = 'не удалось обработать обращение', answer = NULL, source_ids = '{}', "
        f"last_error = %(error)s, locked_at = NULL, locked_by = NULL WHERE {_OWNED}",
        {"id": ticket_id, "worker": worker_id, "error": error},
    )
    saved = cur.rowcount == 1
    if saved:
        _enqueue(conn, [ticket_id], "notify_operator")
    conn.commit()
    return saved


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
        "UPDATE public.tickets SET status = 'waiting_operator', decision = 'escalate', "
        "decision_reason = 'не удалось обработать обращение', answer = NULL, source_ids = '{}', "
        "locked_at = NULL, locked_by = NULL, "
        "last_error = 'worker перестал отвечать, попытки исчерпаны' "
        f"WHERE {stale} AND attempts >= %(max)s RETURNING id",
        params,
    ).fetchall()
    failed_ids = [r[0] for r in failed]
    _enqueue(conn, failed_ids, "notify_operator")
    conn.commit()
    return [r[0] for r in requeued], failed_ids


def close_overdue(conn: psycopg.Connection) -> list[int]:
    """Закрывает обращения, по которым истёк срок ожидания клиента."""
    rows = conn.execute(
        "WITH due AS ("
        "SELECT id FROM public.tickets WHERE status = 'waiting_client' AND close_after <= NOW() "
        "ORDER BY close_after, id LIMIT 100 FOR UPDATE SKIP LOCKED"
        ") UPDATE public.tickets t SET status = 'closed', closed_at = NOW(), close_after = NULL "
        "FROM due WHERE t.id = due.id RETURNING t.id"
    ).fetchall()
    conn.commit()
    return [row[0] for row in rows]
