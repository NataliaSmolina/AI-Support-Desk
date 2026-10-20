BEGIN;

ALTER TABLE public.tickets
    ADD COLUMN IF NOT EXISTS locked_by       VARCHAR(100),
    ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS last_error      TEXT,
    ADD COLUMN IF NOT EXISTS sentiment       VARCHAR(20),
    ADD COLUMN IF NOT EXISTS wants_human     BOOLEAN;

-- Очередь: только новые тикеты, у которых подошло время
CREATE INDEX IF NOT EXISTS idx_tickets_queue
    ON public.tickets (next_attempt_at, id)
    WHERE status = 'new';

-- Поиск зависших тикетов
CREATE INDEX IF NOT EXISTS idx_tickets_stale
    ON public.tickets (locked_at)
    WHERE status = 'processing';

COMMIT;