BEGIN;

CREATE TABLE IF NOT EXISTS public.bot_outbox (
    id                BIGSERIAL PRIMARY KEY,
    ticket_id         BIGINT NOT NULL REFERENCES public.tickets(id) ON DELETE CASCADE,
    action            TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'sending', 'sent', 'unknown', 'failed')),
    attempts          INTEGER NOT NULL DEFAULT 0,
    next_attempt_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    locked_at         TIMESTAMPTZ,
    last_error        TEXT,
    telegram_chat_id  BIGINT,
    telegram_message_id BIGINT,
    sent_at           TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (ticket_id, action)
);

CREATE INDEX IF NOT EXISTS idx_bot_outbox_pending
    ON public.bot_outbox (next_attempt_at, id)
    WHERE status = 'pending';

COMMIT;
