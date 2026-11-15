import asyncio
import os
from pathlib import Path

import psycopg
import pytest

from ai_clients.llm import (
    Category, Classification, ClassificationError, Priority, Sentiment,
)
from support_worker.config import Settings
from support_worker.main import backoff_s, handle_ticket
from support_worker.tickets import claim_ticket, recover_stuck

TEST_DSN = os.environ.get("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DSN, reason="TEST_DATABASE_URL не задан"),
]

MIGRATIONS = Path(__file__).resolve().parents[3] / "infra" / "postgres" / "migrations"
SETTINGS = Settings(dsn=TEST_DSN or "", max_attempts=3, lock_timeout_s=30,
                    heartbeat_s=1, backoff_base_s=5)
OK = Classification(category=Category.DELIVERY, priority=Priority.NORMAL,
                    sentiment=Sentiment.CALM, wants_human=False)


class FakeClassifier:
    def __init__(self, result=OK, error=None, hook=None):
        self.result, self.error, self.hook = result, error, hook

    async def classify(self, question: str):
        if self.hook:
            await self.hook()
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def conn():
    with psycopg.connect(TEST_DSN, autocommit=True) as ac:
        assert ac.info.dbname.endswith("_test"), "тесты очищают таблицы: нужна БД *_test"
        if ac.execute("SELECT to_regclass('public.tickets')").fetchone()[0] is None:
            for f in sorted(MIGRATIONS.glob("*.sql")):
                ac.execute(f.read_text(encoding="utf-8"))
    with psycopg.connect(TEST_DSN) as c:
        c.execute("TRUNCATE public.tickets RESTART IDENTITY CASCADE")
        c.commit()
        yield c


def add_ticket(conn, text="Где мой заказ?", **cols):
    names = ["chat_id", *cols]
    values = [1, *cols.values()]
    marks = ", ".join(["%s"] * len(values))
    tid = conn.execute(
        f"INSERT INTO public.tickets ({', '.join(names)}) VALUES ({marks}) RETURNING id", values
    ).fetchone()[0]
    if text is not None:
        conn.execute(
            "INSERT INTO public.messages (ticket_id, author, text) VALUES (%s, 'client', %s)",
            (tid, text),
        )
    conn.commit()
    return tid


def state(conn, tid=None):
    conn.commit()
    where, args = ("WHERE id = %s", (tid,)) if tid else ("", ())
    return conn.execute(
        "SELECT status, attempts, last_error, locked_by, category, decision "
        f"FROM public.tickets {where} ORDER BY id", args
    ).fetchone()


async def run_once(conn, classifier):
    ticket = claim_ticket(conn, "w1")
    return await handle_ticket(conn, ticket, "w1", SETTINGS, classifier)


def test_backoff_grows_and_is_capped():
    assert [backoff_s(n, SETTINGS) for n in (1, 2, 3)] == [5, 10, 20]
    assert backoff_s(20, SETTINGS) == SETTINGS.backoff_cap_s


def test_claim_returns_oldest_ticket_with_message_once(conn):
    add_ticket(conn, "первый")
    add_ticket(conn, "второй")
    first, second = claim_ticket(conn, "w1"), claim_ticket(conn, "w1")
    assert (first["message"], second["message"]) == ("первый", "второй")
    assert first["attempts"] == 1
    assert claim_ticket(conn, "w1") is None


def test_claim_skips_ticket_without_client_message_and_backoff(conn):
    add_ticket(conn, text=None)
    add_ticket(conn, next_attempt_at="2999-01-01")
    assert claim_ticket(conn, "w1") is None


async def test_success_saves_classification(conn):
    add_ticket(conn)
    assert await run_once(conn, FakeClassifier()) == "done"
    status, attempts, err, locked_by, category, _ = state(conn)
    assert (status, locked_by, category, err) == ("classified", None, "delivery", None)


async def test_transient_error_returns_ticket_to_queue_with_backoff(conn):
    add_ticket(conn)
    assert await run_once(conn, FakeClassifier(error=ClassificationError("таймаут"))) == "retry"
    status, attempts, err, locked_by, *_ = state(conn)
    assert (status, attempts, locked_by) == ("new", 1, None)
    assert "ClassificationError" in err
    assert claim_ticket(conn, "w2") is None  # задержка перед повтором ещё не прошла


async def test_ticket_fails_after_last_attempt(conn):
    add_ticket(conn, attempts=2)
    assert await run_once(conn, FakeClassifier(error=RuntimeError("снова"))) == "failed"
    status, _, _, _, _, decision = state(conn)
    assert (status, decision) == ("failed", "escalate")


async def test_permanent_error_fails_immediately(conn):
    add_ticket(conn)
    assert await run_once(conn, FakeClassifier(error=ValueError("пустой вопрос"))) == "failed"
    assert state(conn)[1] == 1


async def test_result_discarded_if_ticket_was_taken_over(conn):
    add_ticket(conn)

    async def steal():
        with psycopg.connect(TEST_DSN) as other:
            other.execute("UPDATE public.tickets SET locked_by = 'w2'")

    assert await run_once(conn, FakeClassifier(hook=steal)) == "lost"
    status, _, _, locked_by, category, _ = state(conn)
    assert (status, locked_by, category) == ("processing", "w2", None)


async def test_heartbeat_refreshes_lock_during_long_processing(conn):
    add_ticket(conn)
    seen = []

    async def slow():
        with psycopg.connect(TEST_DSN) as o:
            o.execute("UPDATE public.tickets SET locked_at = NOW() - interval '1 hour'")
        await asyncio.sleep(1.6)
        with psycopg.connect(TEST_DSN) as o:
            seen.append(o.execute(
                "SELECT NOW() - locked_at < interval '10 seconds' FROM public.tickets"
            ).fetchone()[0])

    assert await run_once(conn, FakeClassifier(hook=slow)) == "done"
    assert seen == [True]


def test_recover_requeues_stale_and_fails_exhausted(conn):
    retry = add_ticket(conn, status="processing", attempts=1, locked_by="dead")
    exhausted = add_ticket(conn, status="processing", attempts=3, locked_by="dead")
    alive = add_ticket(conn, status="processing", attempts=1, locked_by="live")
    conn.execute(
        "UPDATE public.tickets SET locked_at = NOW() - interval '10 minutes' WHERE id IN (%s, %s)",
        (retry, exhausted),
    )
    conn.execute("UPDATE public.tickets SET locked_at = NOW() WHERE id = %s", (alive,))
    conn.commit()

    assert recover_stuck(conn, max_attempts=3, lock_timeout_s=300) == ([retry], [exhausted])
    assert state(conn, retry)[0] == "new"
    assert state(conn, exhausted)[0] == "failed" and state(conn, exhausted)[5] == "escalate"
    assert state(conn, alive)[0] == "processing"