import asyncio
import os
from pathlib import Path

import psycopg
import pytest
from types import SimpleNamespace
from ai_clients.llm import (
    Category, Classification, ClassificationError, Priority, Sentiment,
)
from support_worker.config import Settings
from support_worker.main import backoff_s, handle_ticket
from support_worker.tickets import claim_ticket, close_overdue, finish_processing, recover_stuck

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

class FakeRag:
    def __init__(self, source_file="kb/faq/delivery.md"):
        self.source_file = source_file

    async def answer_question(self, question: str):
        return SimpleNamespace(
            answer="Ваш заказ уже отправлен.",
            source_ids=["delivery_policy.pdf"],
            needs_escalation=False,
            retrieved_chunks=[SimpleNamespace(source_file=self.source_file)],
        )

class FakeClassifier:
    def __init__(self, result=OK, error=None, hook=None):
        self.result, self.error, self.hook = result, error, hook

    async def classify(self, question: str):
        if self.hook:
            await self.hook()
        if self.error:
            raise self.error
        return self.result


@pytest.fixture(scope="session")
def migrated_db():
    with psycopg.connect(TEST_DSN, autocommit=True) as ac:
        assert ac.info.dbname.endswith("_test"), "тесты очищают таблицы: нужна БД *_test"
        for f in sorted(MIGRATIONS.glob("*.sql")):
            ac.execute(f.read_text(encoding="utf-8"))


@pytest.fixture
def conn(migrated_db):
    with psycopg.connect(TEST_DSN) as c:
        c.execute("TRUNCATE public.tickets, public.tg_updates RESTART IDENTITY CASCADE")
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
        "SELECT status, attempts, last_error, locked_by, category, decision, "
        "decision_reason, answer, source_ids "
        f"FROM public.tickets {where} ORDER BY id", args
    ).fetchone()


async def run_once(conn, classifier, rag=None):
    ticket = claim_ticket(conn, "w1")
    return await handle_ticket(
        conn, ticket, "w1", SETTINGS, classifier, rag if rag is not None else FakeRag()
    )


def outbox(conn):
    return conn.execute(
        "SELECT ticket_id, action, status FROM public.bot_outbox ORDER BY id"
    ).fetchall()


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
    tid = add_ticket(conn)

    assert await run_once(conn, FakeClassifier()) == "done"

    (
        status,
        attempts,
        err,
        locked_by,
        category,
        decision,
        decision_reason,
        answer,
        source_ids,
    ) = state(conn)

    assert status == "ready"
    assert locked_by is None
    assert category == "delivery"
    assert decision == "auto"
    assert decision_reason is not None
    assert answer == "Ваш заказ уже отправлен."
    assert source_ids == ["delivery_policy.pdf"]
    assert err is None
    assert outbox(conn) == [(tid, "send_client_reply", "pending")]


async def test_transient_error_returns_ticket_to_queue_with_backoff(conn):
    add_ticket(conn)
    assert await run_once(conn, FakeClassifier(error=ClassificationError("таймаут"))) == "retry"
    status, attempts, err, locked_by, *_ = state(conn)
    assert (status, attempts, locked_by) == ("new", 1, None)
    assert "ClassificationError" in err
    assert claim_ticket(conn, "w2") is None  # задержка перед повтором ещё не прошла
    assert outbox(conn) == []


async def test_request_for_human_is_saved_without_rag(conn):
    class UnavailableRag:
        async def answer_question(self, question: str):
            pytest.fail("RAG must not run when the client asks for an operator")

    tid = add_ticket(conn)
    classifier = FakeClassifier(result=OK.model_copy(update={"wants_human": True}))
    assert await run_once(conn, classifier, UnavailableRag()) == "done"
    status, attempts, error, _, _, decision, _, answer, sources = state(conn)
    assert (status, attempts, error, decision, answer, sources) == (
        "waiting_operator", 1, None, "escalate", None, [],
    )
    assert outbox(conn) == [(tid, "notify_operator", "pending")]


async def test_ticket_fails_after_last_attempt(conn):
    tid = add_ticket(conn, attempts=2)
    assert await run_once(conn, FakeClassifier(error=RuntimeError("снова"))) == "failed"

    result = state(conn)
    assert result[0] == "waiting_operator"
    assert result[5] == "escalate"
    assert outbox(conn) == [(tid, "notify_operator", "pending")]


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

    result = state(conn)
    assert result[0] == "processing"
    assert result[3] == "w2"
    assert result[4] is None
    assert outbox(conn) == []


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
    assert state(conn, exhausted)[0] == "waiting_operator" and state(conn, exhausted)[5] == "escalate"
    assert state(conn, alive)[0] == "processing"
    assert outbox(conn) == [(exhausted, "notify_operator", "pending")]


async def test_reprocessing_does_not_enqueue_duplicate_card(conn):
    tid = add_ticket(conn)
    assert await run_once(conn, FakeClassifier()) == "done"
    conn.execute("UPDATE public.bot_outbox SET status = 'sent' WHERE ticket_id = %s", (tid,))
    conn.execute("UPDATE public.tickets SET status = 'new' WHERE id = %s", (tid,))
    conn.commit()

    assert await run_once(conn, FakeClassifier()) == "done"
    assert outbox(conn) == [(tid, "send_client_reply", "sent")]


def test_outbox_error_rolls_back_ticket_result(conn):
    tid = add_ticket(conn)
    claim_ticket(conn, "w1")
    # Имитируем ошибку записи в очередь и проверяем, что результат тикета тоже откатился.
    conn.execute("ALTER TABLE public.bot_outbox ADD CHECK (action <> 'send_client_reply')")
    with pytest.raises(psycopg.errors.CheckViolation):
        finish_processing(
            conn, tid, "w1", category="delivery", priority="normal", sentiment="calm",
            wants_human=False, decision="auto", decision_reason="есть источники",
            answer="Ответ", source_ids=["delivery_policy.pdf"],
        )
    conn.rollback()

    assert state(conn, tid)[0] == "processing"
    assert state(conn, tid)[5] is None
    assert outbox(conn) == []


async def test_internal_context_goes_to_operator(conn):
    tid = add_ticket(conn)
    assert await run_once(conn, FakeClassifier(), FakeRag("kb/policies/internal/templates.md")) == "done"
    assert state(conn, tid)[0] == "waiting_operator"
    assert state(conn, tid)[7] is None
    assert outbox(conn) == [(tid, "notify_operator", "pending")]


def confirm_auto(conn, tid):
    outbox_id = conn.execute(
        "UPDATE public.bot_outbox SET status = 'sending' "
        "WHERE ticket_id = %s AND status = 'pending' RETURNING id", (tid,),
    ).fetchone()[0]
    assert conn.execute("SELECT public.confirm_auto_reply(%s, 1, 100)", (outbox_id,)).fetchone()[0]
    assert not conn.execute("SELECT public.confirm_auto_reply(%s, 1, 100)", (outbox_id,)).fetchone()[0]


def remaining_hours(conn, tid, author):
    return conn.execute(
        "SELECT EXTRACT(EPOCH FROM (t.close_after - m.created_at)) / 3600 "
        "FROM public.tickets t JOIN public.messages m ON m.ticket_id = t.id "
        "WHERE t.id = %s AND m.author = %s ORDER BY m.id DESC LIMIT 1", (tid, author),
    ).fetchone()[0]


async def test_auto_reply_waits_for_delivery_and_closes_after_one_hour(conn):
    tid = add_ticket(conn)
    assert await run_once(conn, FakeClassifier()) == "done"
    assert close_overdue(conn) == []
    confirm_auto(conn, tid)
    assert remaining_hours(conn, tid, "bot") == 1
    assert state(conn, tid)[0] == "waiting_client"
    assert close_overdue(conn) == []

    conn.execute("UPDATE public.tickets SET close_after = NOW() - interval '1 second' WHERE id = %s", (tid,))
    assert close_overdue(conn) == [tid]
    assert state(conn, tid)[0] == "closed"


async def test_llm_followup_can_escalate_same_ticket(conn):
    tid = add_ticket(conn)
    assert await run_once(conn, FakeClassifier()) == "done"
    confirm_auto(conn, tid)
    result = conn.execute("SELECT public.add_ticket_followup(%s, 11, 1, 'Позовите оператора')", (tid,))
    assert result.fetchone()[0] == "accepted"
    assert conn.execute(
        "SELECT public.add_ticket_followup(%s, 11, 1, 'Позовите оператора')", (tid,),
    ).fetchone()[0] == "duplicate"
    ticket = claim_ticket(conn, "w1")
    assert (ticket["id"], ticket["message"], ticket["attempts"]) == (tid, "Позовите оператора", 1)
    classifier = FakeClassifier(result=OK.model_copy(update={"wants_human": True}))
    assert await handle_ticket(conn, ticket, "w1", SETTINGS, classifier, FakeRag()) == "done"
    assert state(conn, tid)[0] == "waiting_operator"
    assert outbox(conn) == [(tid, "send_client_reply", "sent"), (tid, "notify_operator", "pending")]


def test_operator_followup_returns_to_assigned_operator(conn):
    tid = add_ticket(conn, status="waiting_operator", decision="escalate")
    assert conn.execute("SELECT public.claim_operator_ticket(%s, 7)", (tid,)).fetchone()[0]
    assert not conn.execute("SELECT public.claim_operator_ticket(%s, 8)", (tid,)).fetchone()[0]
    assert not conn.execute("SELECT public.confirm_operator_reply(%s, 1, 8, 'Ответ')", (tid,)).fetchone()[0]
    assert conn.execute("SELECT public.confirm_operator_reply(%s, 1, 7, 'Ответ')", (tid,)).fetchone()[0]
    assert remaining_hours(conn, tid, "operator") == 12

    assert conn.execute("SELECT public.add_ticket_followup(%s, 12, 1, 'Уточнение')", (tid,)).fetchone()[0] == "accepted"
    assert state(conn, tid)[0] == "operator_processing"
    assert close_overdue(conn) == []
    assert outbox(conn) == [(tid, "notify_operator", "pending")]
    assert not conn.execute("SELECT public.confirm_operator_reply(%s, 1, 7, 'Ответ')", (tid,)).fetchone()[0]
    assert conn.execute("SELECT public.confirm_operator_reply(%s, 2, 7, 'Новый ответ')", (tid,)).fetchone()[0]
    assert remaining_hours(conn, tid, "operator") == 12
    conn.execute("UPDATE public.tickets SET close_after = NOW() - interval '1 second' WHERE id = %s", (tid,))
    assert conn.execute("SELECT public.add_ticket_followup(%s, 13, 1, 'Поздний ответ')", (tid,)).fetchone()[0] == "unavailable"
    assert close_overdue(conn) == [tid]
