BEGIN;

ALTER TABLE public.tickets
    ADD COLUMN locked_by       VARCHAR(100),
    ADD COLUMN next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ADD COLUMN last_error      TEXT,
    ADD COLUMN sentiment       VARCHAR(20),
    ADD COLUMN wants_human     BOOLEAN;

-- Очередь: только новые тикеты, у которых подошло время
CREATE INDEX idx_tickets_queue ON public.tickets (next_attempt_at, id) WHERE status = 'new';
-- Поиск зависших
CREATE INDEX idx_tickets_stale ON public.tickets (locked_at) WHERE status = 'processing';

COMMIT;
