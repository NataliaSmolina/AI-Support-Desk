
BEGIN;

CREATE TABLE public.messages (
    id BIGSERIAL PRIMARY KEY,
    ticket_id BIGINT NOT NULL REFERENCES public.tickets(id),
    author VARCHAR(20) NOT NULL
        CHECK (author IN ('client', 'bot', 'operator')),
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_messages_ticket_id
    ON public.messages(ticket_id);

CREATE TABLE public.tg_updates (
    update_id BIGINT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;
