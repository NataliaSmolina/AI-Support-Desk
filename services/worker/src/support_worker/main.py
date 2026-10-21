import asyncio
import contextlib
import logging
import os
import socket
import time
import uuid

import psycopg

from ai_clients.config import AISettings
from ai_clients.llm import LlmClassifier

from .config import Settings
from .tickets import (
    claim_ticket, finish_classification, mark_failed, recover_stuck,
    release_for_retry, touch_ticket,
)

log = logging.getLogger("worker")

PERMANENT_ERRORS = (ValueError,)


def backoff_s(attempt: int, settings: Settings) -> float:
    """1-я попытка упала: 5 с, 2-я: 10 с, 3-я: 20 с ... (не больше backoff_cap_s)."""
    return min(settings.backoff_cap_s, settings.backoff_base_s * 2 ** (attempt - 1))


def _touch(dsn: str, ticket_id: int, worker_id: str) -> bool:
    with psycopg.connect(dsn) as conn:  # отдельное соединение: основное может быть занято
        return touch_ticket(conn, ticket_id, worker_id)


async def _beat(settings: Settings, ticket_id: int, worker_id: str, lost: asyncio.Event) -> None:
    """Пока тикет обрабатывается, раз в heartbeat_s обновляет locked_at.

    Долгий вызов LLM не должен выглядеть как зависание. Если тикет у нас отобрали,
    выставляется флаг `lost`, и результат обработки отбрасывается.
    """
    while True:
        await asyncio.sleep(settings.heartbeat_s)
        try:
            alive = await asyncio.to_thread(_touch, settings.dsn, ticket_id, worker_id)
        except psycopg.Error:
            log.exception("ticket_id=%s не удалось обновить heartbeat", ticket_id)
            continue
        if not alive:
            log.warning("ticket_id=%s у worker %s отобрали", ticket_id, worker_id)
            lost.set()
            return


async def handle_ticket(
    conn: psycopg.Connection, ticket: dict, worker_id: str, settings: Settings, classifier
) -> str:
    """Обрабатывает уже захваченный тикет. Возвращает: done | retry | failed | lost."""
    tid, attempt = ticket["id"], ticket["attempts"]
    lost = asyncio.Event()
    beat = asyncio.create_task(_beat(settings, tid, worker_id, lost))
    try:
        result = await classifier.classify(ticket["message"])
        if lost.is_set():
            log.warning("ticket_id=%s: тикет отобран, результат отброшен", tid)
            return "lost"
        saved = finish_classification(
            conn, tid, worker_id,
            category=result.category.value, priority=result.priority.value,
            sentiment=result.sentiment.value, wants_human=result.wants_human,
        )
        if not saved:
            log.warning("ticket_id=%s: тикет уже не наш, результат отброшен", tid)
            return "lost"
        log.info("ticket_id=%s: %s, %s", tid, result.category.value, result.priority.value)
        return "done"
    except asyncio.CancelledError:
        # Worker останавливают (Ctrl+C): возвращаем тикет сразу и не засчитываем попытку.
        conn.rollback()
        release_for_retry(conn, tid, worker_id, "worker остановлен", 0, refund_attempt=True)
        raise
    except PERMANENT_ERRORS as e:
        log.exception("ticket_id=%s: постоянная ошибка, тикет уходит оператору", tid)
        conn.rollback()
        mark_failed(conn, tid, worker_id, f"{type(e).__name__}: {e}")
        return "failed"
    except Exception as e:  # исключения не глушим: логируем с ticket_id и решаем, что дальше
        error = f"{type(e).__name__}: {e}"
        log.exception("ticket_id=%s: ошибка на попытке %s из %s", tid, attempt, settings.max_attempts)
        conn.rollback()
        if attempt >= settings.max_attempts:
            mark_failed(conn, tid, worker_id, error)
            log.error("ticket_id=%s: попытки исчерпаны, статус failed", tid)  # сюда позже алерт
            return "failed"
        release_for_retry(conn, tid, worker_id, error, backoff_s(attempt, settings))
        return "retry"
    finally:
        beat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await beat


async def run(settings: Settings) -> None:
    worker_id = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    ai = AISettings()
    classifier = LlmClassifier(
        base_url=ai.llm_base_url, model=ai.llm_model, timeout_s=ai.request_timeout_s,
    )
    log.info("worker %s запущен", worker_id)
    next_recover = 0.0
    try:
        with psycopg.connect(settings.dsn) as conn:
            while True:
                if time.monotonic() >= next_recover:
                    requeued, failed = recover_stuck(
                        conn, settings.max_attempts, settings.lock_timeout_s
                    )
                    if requeued:
                        log.warning("возвращены в очередь зависшие тикеты: %s", requeued)
                    if failed:
                        log.error("зависшие тикеты без попыток переданы оператору: %s", failed)
                    next_recover = time.monotonic() + settings.recover_s

                ticket = claim_ticket(conn, worker_id)
                if ticket is None:
                    await asyncio.sleep(settings.poll_s)
                    continue
                log.info("ticket_id=%s взят в обработку (попытка %s)", ticket["id"], ticket["attempts"])
                await handle_ticket(conn, ticket, worker_id, settings, classifier)
    finally:
        await classifier.aclose()
        log.info("worker %s остановлен", worker_id)


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(Settings.from_env()))


if __name__ == "__main__":
    main()