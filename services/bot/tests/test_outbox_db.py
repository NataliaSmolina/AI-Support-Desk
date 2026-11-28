"""Проверки очереди на отдельной PostgreSQL (TEST_DATABASE_URL)."""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import psycopg
import pytest
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramRetryAfter
from aiogram.filters import CommandObject
from aiogram.methods import SendMessage
from psycopg_pool import AsyncConnectionPool

from ai_clients.llm import Category, Classification, Priority, Sentiment
from support_bot import db, outbox, texts
from support_bot.handlers.client import question
from support_bot.handlers.reply import ReplyCard, pending_cards, send_reply, start_reply
from support_worker.config import Settings as WorkerSettings
from support_worker.main import handle_ticket
from support_worker.tickets import claim_ticket

pytestmark = pytest.mark.integration
MIGRATIONS = Path(__file__).resolve().parents[3] / "infra" / "postgres" / "migrations"


@pytest.fixture(scope="module")
def test_dsn():
    dsn = os.getenv("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TEST_DATABASE_URL не задан")
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as conn:
        if not conn.info.dbname.endswith("_test"):
            pytest.fail("Для проверок очереди нужна отдельная БД с именем *_test")
        for migration in sorted(MIGRATIONS.glob("*.sql")):
            conn.execute(migration.read_text(encoding="utf-8"))
    return dsn


@pytest.fixture
async def pool(test_dsn):
    async with await psycopg.AsyncConnection.connect(test_dsn, connect_timeout=5) as conn:
        async with conn.transaction(force_rollback=True):
            # У каждой проверки своя очередь. В конце исходное содержимое восстановится
            await conn.execute("TRUNCATE public.bot_outbox")

            @asynccontextmanager
            async def connection():
                yield conn

            yield SimpleNamespace(conn=conn, connection=connection)


@pytest.fixture
def bot():
    bot = AsyncMock(spec=Bot)
    bot.send_message.return_value = SimpleNamespace(chat=SimpleNamespace(id=123), message_id=42)
    return bot


@pytest.fixture
def settings():
    return SimpleNamespace(operator_chat_id=-100222, operator_thread_id=5)


async def seed_ticket(conn, *, action="send_client_reply"):
    auto_reply = action == "send_client_reply"
    cursor = await conn.execute(
        "INSERT INTO public.tickets (chat_id, status, decision, answer, decision_reason) "
        "VALUES (123, %s, %s, %s, %s) RETURNING id",
        ("ready", "auto", "Заказ в пути.", None) if auto_reply else
        ("waiting_operator", "escalate", None, "Не найдены источники"),
    )
    ticket_id, = await cursor.fetchone()
    await conn.execute(
        "INSERT INTO public.messages (ticket_id, author, text) VALUES (%s, 'client', 'Где мой заказ?')",
        (ticket_id,),
    )
    cursor = await conn.execute(
        "INSERT INTO public.bot_outbox (ticket_id, action) VALUES (%s, %s) RETURNING id",
        (ticket_id, action),
    )
    outbox_id, = await cursor.fetchone()
    return ticket_id, outbox_id


@pytest.mark.parametrize(("action", "recipient", "status", "history"), [
    # Автоответ записывается от имени бота, тикет переходит в waiting_client
    ("send_client_reply", 123, "waiting_client", [("client", "Где мой заказ?"), ("bot", "Заказ в пути.")]),
    # Карточка уходит в группу. В истории пока есть только вопрос, тикет ждет оператора
    ("notify_operator", -100222, "waiting_operator", [("client", "Где мой заказ?")]),
])
async def test_successful_delivery_saves_receipt_once(pool, bot, settings, action, recipient, status, history):
    # Обе задачи получают sent, ID чата и сообщения, время отправки и не забираются повторно
    ticket_id, outbox_id = await seed_ticket(pool.conn, action=action)
    bot.send_message.return_value.chat.id = recipient

    assert await outbox.process_next(bot, pool, settings)
    assert not await outbox.process_next(bot, pool, settings)

    bot.send_message.assert_awaited_once()
    cursor = await pool.conn.execute(
        "SELECT o.status, o.attempts, o.telegram_chat_id, o.telegram_message_id, "
        "o.sent_at IS NOT NULL, o.locked_at IS NULL, t.status, t.close_after IS NOT NULL "
        "FROM public.bot_outbox AS o JOIN public.tickets AS t ON t.id = o.ticket_id WHERE o.id = %s",
        (outbox_id,),
    )
    assert await cursor.fetchone() == ("sent", 1, recipient, 42, True, True, status, status == "waiting_client")
    cursor = await pool.conn.execute(
        "SELECT author, text FROM public.messages WHERE ticket_id = %s ORDER BY id", (ticket_id,),
    )
    assert await cursor.fetchall() == history


async def test_rate_limited_task_only_retries_when_due(pool, bot, settings):
    # До next_attempt_at задача ждет. Когда срок наступает, вторая попытка записывается как sent
    _, outbox_id = await seed_ticket(pool.conn)
    bot.send_message.side_effect = TelegramRetryAfter(SendMessage(chat_id=123, text="test"), "retry", 300)

    assert await outbox.process_next(bot, pool, settings)
    assert not await outbox.process_next(bot, pool, settings)
    cursor = await pool.conn.execute(
        "SELECT status, attempts, next_attempt_at > statement_timestamp(), locked_at IS NULL "
        "FROM public.bot_outbox WHERE id = %s", (outbox_id,),
    )
    assert await cursor.fetchone() == ("pending", 1, True, True)
    await pool.conn.execute(
        "UPDATE public.bot_outbox SET next_attempt_at = statement_timestamp() WHERE id = %s", (outbox_id,),
    )
    bot.send_message.side_effect = None

    assert await outbox.process_next(bot, pool, settings)
    cursor = await pool.conn.execute("SELECT status, attempts FROM public.bot_outbox WHERE id = %s", (outbox_id,))
    assert await cursor.fetchone() == ("sent", 2)


async def test_stale_claim_is_not_sent_again(pool, bot, settings):
    # Свежий захват еще действует. Просроченный переходит в unknown и не отправляется повторно
    _, outbox_id = await seed_ticket(pool.conn)

    task = await outbox.claim_next(pool)
    assert task is not None and task.id == outbox_id
    assert await outbox.claim_next(pool) is None
    assert await outbox.mark_stale_unknown(pool, timeout_s=60) == 0
    await pool.conn.execute(
        "UPDATE public.bot_outbox SET locked_at = statement_timestamp() - interval '2 minutes' WHERE id = %s",
        (outbox_id,),
    )

    assert await outbox.mark_stale_unknown(pool, timeout_s=60) == 1
    assert not await outbox.process_next(bot, pool, settings)
    bot.send_message.assert_not_awaited()
    cursor = await pool.conn.execute(
        "SELECT status, attempts, locked_at IS NULL, sent_at IS NULL FROM public.bot_outbox WHERE id = %s",
        (outbox_id,),
    )
    assert await cursor.fetchone() == ("unknown", 1, True, True)


@pytest.mark.parametrize(("question_text", "wants_human", "has_answer", "reason"), [
    # В базе есть ответ – Worker ставит автоответ в очередь
    ("Сколько дней дается на возврат товара?", False, True, None),
    # RAG не нашел ответа – Worker передает вопрос оператору
    ("Можно оплатить заказ криптовалютой?", False, False, "не найдены источники"),
    # Клиент просит человека – Worker ставит карточку в очередь без поиска по базе знаний
    ("Позови оператора", True, False, "клиент просит оператора"),
])
async def test_worker_result_is_delivered_for_new_telegram_question(
    test_dsn, bot, settings, monkeypatch, question_text, wants_human, has_answer, reason,
):
    # Проводим один тикет от приема вопроса до доставки и записи ответа в историю
    chat_id = uuid4().int >> 72
    update_id = chat_id
    operator_id = 802
    settings.operator_ids = [operator_id]
    bot.id = 321
    bot.send_message.side_effect = lambda **kwargs: SimpleNamespace(
        chat=SimpleNamespace(id=kwargs["chat_id"]), message_id=42,
    )
    client_message = AsyncMock(text=question_text, caption=None)
    client_message.chat.id = chat_id
    answer = "На возврат товара дается 14 календарных дней." if has_answer else None
    classifier = AsyncMock()
    classifier.classify.return_value = Classification(
        category=Category.OTHER, priority=Priority.NORMAL, sentiment=Sentiment.CALM, wants_human=wants_human,
    )
    rag = AsyncMock()
    rag.answer_question.return_value = SimpleNamespace(
        answer=answer, needs_escalation=not has_answer,
        source_ids=["returns-source"] if has_answer else [],
        retrieved_chunks=[SimpleNamespace(source_file="kb/faq/returns.md")] if has_answer else [],
    )

    async with AsyncConnectionPool(test_dsn, open=False, min_size=2, max_size=2, timeout=5) as flow_pool:
        async with flow_pool.connection() as guard:
            # Захват с SKIP LOCKED пропустит чужие записи тестовой базы
            await guard.execute("SELECT id FROM public.tickets WHERE status = 'new' FOR UPDATE")
            await guard.execute("SELECT id FROM public.bot_outbox WHERE status = 'pending' FOR UPDATE")
            try:
                await question(client_message, pool=flow_pool, event_update=SimpleNamespace(update_id=update_id))
                bot.send_message.assert_not_awaited()

                with psycopg.connect(test_dsn, connect_timeout=5) as worker_conn:
                    ticket = claim_ticket(worker_conn, "bot-flow-test")
                    assert ticket is not None and (ticket["chat_id"], ticket["message"]) == (chat_id, question_text)
                    result = await handle_ticket(
                        worker_conn, ticket, "bot-flow-test", WorkerSettings(dsn=test_dsn), classifier, rag,
                    )
                assert result == "done"
                ticket_id = ticket["id"]
                client_message.answer.assert_awaited_once_with(texts.accepted(ticket_id))
                classifier.classify.assert_awaited_once_with(question_text)
                if wants_human:
                    rag.answer_question.assert_not_awaited()
                else:
                    rag.answer_question.assert_awaited_once_with(question_text)

                assert await outbox.process_next(bot, flow_pool, settings)
                assert not await outbox.process_next(bot, flow_pool, settings)
                bot.send_message.assert_awaited_once()
                if has_answer:
                    bot.send_message.assert_awaited_once_with(chat_id=chat_id, text=answer)
                    action, recipient, author = "send_client_reply", chat_id, "bot"
                else:
                    sent = bot.send_message.await_args.kwargs
                    assert sent["chat_id"] == settings.operator_chat_id
                    assert sent["message_thread_id"] == settings.operator_thread_id
                    assert reason in sent["text"] and question_text in sent["text"]
                    assert sent["reply_markup"].inline_keyboard[0][0].callback_data == f"reply:{ticket_id}"
                    assert (await db.operator_ticket(flow_pool, ticket_id)).status == "waiting_operator"
                    action, recipient, author = "notify_operator", settings.operator_chat_id, "operator"

                    # Открываем ответ по отправленной карточке и отправляем текст оператором
                    card = ReplyCard(ticket_id, recipient, 42, sent["text"])
                    monkeypatch.setitem(pending_cards, (bot.id, operator_id), card)
                    operator_message = AsyncMock()
                    operator_message.from_user.id = operator_id
                    operator_message.from_user.full_name = "Иван Петров"
                    operator_message.answer.return_value.message_id = 80
                    dispatcher = Dispatcher()
                    state = dispatcher.fsm.get_context(bot=bot, chat_id=operator_id, user_id=operator_id)
                    await start_reply(
                        operator_message, CommandObject(args=f"reply_{ticket_id}"), state, settings, bot, flow_pool,
                    )
                    assert (await db.operator_ticket(flow_pool, ticket_id)).operator_id == operator_id
                    answer = "Проверю этот вопрос и помогу вам."
                    operator_message.text = answer
                    operator_message.reply_to_message.message_id = 80
                    await send_reply(operator_message, bot, state, settings, flow_pool)
                    bot.send_message.assert_awaited_with(chat_id=chat_id, text=answer)

                async with flow_pool.connection() as conn:
                    cur = await conn.execute(
                        "SELECT action, status, telegram_chat_id FROM public.bot_outbox WHERE ticket_id = %s",
                        (ticket_id,),
                    )
                    assert await cur.fetchall() == [(action, "sent", recipient)]
                details, history = await db.ticket_details(flow_pool, ticket_id)
                assert details["status"] == "waiting_client"
                assert [(message["author"], message["text"]) for message in history] == [
                    ("client", question_text), (author, answer),
                ]
            finally:
                # Убираем только данные обращения из этого прогона
                async with flow_pool.connection() as conn:
                    await conn.execute(
                        "DELETE FROM public.messages WHERE ticket_id IN "
                        "(SELECT id FROM public.tickets WHERE chat_id = %s)", (chat_id,),
                    )
                    await conn.execute("DELETE FROM public.tickets WHERE chat_id = %s", (chat_id,))
                    await conn.execute("DELETE FROM public.tg_updates WHERE update_id = %s", (update_id,))
