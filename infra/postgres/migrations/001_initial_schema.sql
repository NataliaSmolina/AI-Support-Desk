CREATE TABLE IF NOT EXISTS public.tickets (
    id BIGSERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'new',
    category VARCHAR(50),
    priority VARCHAR(20),
    confidence REAL,
    decision VARCHAR(20),
    locked_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);