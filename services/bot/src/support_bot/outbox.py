"""Отправка ответов и карточек из очереди Worker в Telegram."""

import logging
from dataclasses import dataclass
from typing import Literal

import psycopg
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError, TelegramRetryAfter, TelegramServerError
from aiogram.types import Message
from psycopg.rows import class_row
from psycopg_pool import AsyncConnectionPool

from support_bot import texts
from support_bot.config import BotSettings
from support_bot.keyboards import reply_keyboard

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutboxTask:
    id: int
    ticket_id: int
    reply_round: int
    attempts: int
    action: str
    chat_id: int
    current_round: int
    ticket_status: str
    decision: str | None
    decision_reason: str | None
    answer: str | None
    question: str | None


async def claim_next(pool: AsyncConnectionPool) -> OutboxTask | None:
    """Забирает одну готовую задачу и фиксирует попытку до запроса к Telegram."""
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=class_row(OutboxTask)) as cur:
            await cur.execute("""
                WITH picked AS (
                    SELECT id FROM public.bot_outbox
                    WHERE status = 'pending' AND next_attempt_at <= statement_timestamp()
                    ORDER BY next_attempt_at, id
                    LIMIT 1 FOR UPDATE SKIP LOCKED
                ), claimed AS (
                    UPDATE public.bot_outbox AS o
                    SET status = 'sending', attempts = o.attempts + 1, locked_at = clock_timestamp()
                    FROM picked WHERE o.id = picked.id
                    RETURNING o.id, o.ticket_id, o.reply_round, o.attempts, o.action
                )
                SELECT c.*, t.chat_id, t.reply_round AS current_round, t.status AS ticket_status,
                       t.decision, t.decision_reason, t.answer,
                       (SELECT m.text FROM public.messages AS m
                        WHERE m.ticket_id = t.id AND m.author = 'client'
                        ORDER BY m.id DESC LIMIT 1) AS question
                FROM claimed AS c JOIN public.tickets AS t ON t.id = c.ticket_id
                """)
            return await cur.fetchone()


async def mark_stale_unknown(pool: AsyncConnectionPool, timeout_s: float) -> int:
    """Помечает зависшие отправки для проверки перед повтором."""
    async with pool.connection() as conn:
        cur = await conn.execute(
            "UPDATE public.bot_outbox SET status = 'unknown', locked_at = NULL, "
            "last_error = 'отправка прервалась' WHERE status = 'sending' "
            "AND locked_at <= statement_timestamp() - make_interval(secs => %s)",
            (timeout_s,),
        )
        return cur.rowcount


async def _finish(
    pool: AsyncConnectionPool,
    task: OutboxTask,
    status: Literal['pending', 'sent', 'unknown', 'failed'],
    *,
    error: str | None = None,
    retry_after: int | None = None,
    receipt: Message | None = None,
) -> None:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "UPDATE public.bot_outbox SET status = %s, locked_at = NULL, last_error = %s, "
            "next_attempt_at = COALESCE(clock_timestamp() + make_interval(secs => %s), next_attempt_at), "
            "telegram_chat_id = %s, telegram_message_id = %s, "
            "sent_at = CASE WHEN %s = 'sent' THEN clock_timestamp() END "
            "WHERE id = %s AND attempts = %s AND status IN ('sending', 'unknown')",
            (status, error, retry_after, receipt.chat.id if receipt else None,
             receipt.message_id if receipt else None, status, task.id, task.attempts),
        )
        if cur.rowcount == 0:
            logger.warning("Не записан результат %s задачи %s, попытка %s", status, task.id, task.attempts)


async def _confirm_auto_reply(pool: AsyncConnectionPool, task: OutboxTask, receipt: Message) -> bool:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT public.confirm_auto_reply(id, %s, %s) FROM public.bot_outbox "
            "WHERE id = %s AND attempts = %s",
            (receipt.chat.id, receipt.message_id, task.id, task.attempts),
        )
        row = await cur.fetchone()
        return row is not None and row[0]


def _delivery_error(task: OutboxTask, settings: BotSettings) -> str | None:
    if task.reply_round != task.current_round:
        return "устаревший раунд обращения"
    if task.action == 'send_client_reply':
        if task.ticket_status != 'ready' or task.decision != 'auto' or not (task.answer or '').strip():
            return "автоответ для этого обращения недоступен"
    elif task.action == 'notify_operator':
        if task.ticket_status not in {'waiting_operator', 'operator_processing'} or not task.question:
            return "уведомление для этого обращения недоступно"
        if settings.operator_chat_id is None:
            return "не настроен чат операторов"
    else:
        return "неизвестное действие очереди"
    return None


async def process_next(bot: Bot, pool: AsyncConnectionPool, settings: BotSettings) -> bool:
    """Выполняет одну задачу. False означает, что готовых задач нет."""
    task = await claim_next(pool)
    if task is None:
        return False

    error = _delivery_error(task, settings)
    if error:
        await _finish(pool, task, 'failed', error=error)
        logger.warning("Задача %s не отправлена: %s", task.id, error)
        return True

    try:
        if task.action == 'send_client_reply':
            receipt = await bot.send_message(chat_id=task.chat_id, text=task.answer)
        else:
            receipt = await bot.send_message(
                chat_id=settings.operator_chat_id,
                message_thread_id=settings.operator_thread_id,
                text=texts.card(task.question, task.ticket_id, reason=task.decision_reason),
                reply_markup=reply_keyboard(task.ticket_id),
            )
    except TelegramRetryAfter as exc:
        await _finish(pool, task, 'pending', error=type(exc).__name__, retry_after=exc.retry_after)
        logger.info("Задача %s отложена на %s с", task.id, exc.retry_after)
    except (TelegramNetworkError, TelegramServerError) as exc:
        await _finish(pool, task, 'unknown', error=type(exc).__name__)
        logger.warning("Нет подтверждения Telegram для задачи %s", task.id)
    except TelegramAPIError as exc:
        await _finish(pool, task, 'failed', error=type(exc).__name__)
        logger.warning("Telegram отклонил задачу %s: %s", task.id, type(exc).__name__)
    else:
        try:
            if task.action == 'notify_operator':
                await _finish(pool, task, 'sent', receipt=receipt)
            elif not await _confirm_auto_reply(pool, task, receipt):
                await _finish(pool, task, 'unknown', error="база не подтвердила автоответ", receipt=receipt)
                logger.warning("База не приняла подтверждение автоответа для задачи %s", task.id)
        except psycopg.Error:
            logger.exception("Не удалось записать доставку задачи %s, сообщение %s", task.id, receipt.message_id)
            raise
    return True
