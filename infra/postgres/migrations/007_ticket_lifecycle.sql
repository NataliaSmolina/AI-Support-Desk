BEGIN;

ALTER TABLE public.tickets
    ADD COLUMN IF NOT EXISTS reply_round INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS operator_id BIGINT,
    ADD COLUMN IF NOT EXISTS close_after TIMESTAMPTZ;

ALTER TABLE public.bot_outbox
    ADD COLUMN IF NOT EXISTS reply_round INTEGER NOT NULL DEFAULT 1,
    DROP CONSTRAINT IF EXISTS bot_outbox_ticket_id_action_key;

-- Один и тот же тикет может получить ещё один ответ после уточнения клиента
CREATE UNIQUE INDEX IF NOT EXISTS idx_bot_outbox_ticket_round_action
    ON public.bot_outbox (ticket_id, reply_round, action);

CREATE INDEX IF NOT EXISTS idx_tickets_close_after
    ON public.tickets (close_after, id)
    WHERE status = 'waiting_client';

UPDATE public.tickets SET status = 'closed'
WHERE closed_at IS NOT NULL AND status IN ('classified', 'failed');

-- Старые черновики остаются у оператора, чтобы не отправить их задним числом
WITH moved AS (
    UPDATE public.tickets
    SET status = 'waiting_operator', decision = 'escalate',
        decision_reason = CASE WHEN decision = 'draft'
            THEN 'черновик подготовлен до включения автоответов'
            ELSE COALESCE(decision_reason, 'не удалось обработать обращение') END
    WHERE closed_at IS NULL AND status IN ('classified', 'failed')
    RETURNING id, reply_round
)
INSERT INTO public.bot_outbox (ticket_id, reply_round, action)
SELECT id, reply_round, 'notify_operator' FROM moved
ON CONFLICT (ticket_id, reply_round, action) DO NOTHING;

-- Вызывается после того, как Telegram вернул id отправленного автоответа
CREATE OR REPLACE FUNCTION public.confirm_auto_reply(
    p_outbox_id BIGINT, p_chat_id BIGINT, p_message_id BIGINT
) RETURNS BOOLEAN LANGUAGE plpgsql AS $$
DECLARE
    v_ticket public.tickets%ROWTYPE;
    v_sent_at TIMESTAMPTZ;
BEGIN
    SELECT t.* INTO v_ticket
    FROM public.tickets t JOIN public.bot_outbox o ON o.ticket_id = t.id
    WHERE o.id = p_outbox_id
    FOR UPDATE OF t;

    IF NOT FOUND OR v_ticket.status <> 'ready' OR v_ticket.decision IS DISTINCT FROM 'auto'
        OR v_ticket.chat_id IS DISTINCT FROM p_chat_id OR p_message_id IS NULL THEN
        RETURN FALSE;
    END IF;

    v_sent_at := clock_timestamp();
    UPDATE public.bot_outbox
    SET status = 'sent', sent_at = v_sent_at, locked_at = NULL, last_error = NULL,
        telegram_chat_id = p_chat_id, telegram_message_id = p_message_id
    WHERE id = p_outbox_id AND reply_round = v_ticket.reply_round
        AND action = 'send_client_reply' AND status IN ('sending', 'unknown');
    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    INSERT INTO public.messages (ticket_id, author, text, created_at)
    VALUES (v_ticket.id, 'bot', v_ticket.answer, v_sent_at);
    UPDATE public.tickets
    SET status = 'waiting_client', close_after = v_sent_at + interval '1 hour'
    WHERE id = v_ticket.id;
    RETURN TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION public.claim_operator_ticket(p_ticket_id BIGINT, p_operator_id BIGINT)
RETURNS BOOLEAN LANGUAGE plpgsql AS $$
BEGIN
    UPDATE public.tickets
    SET status = 'operator_processing', operator_id = p_operator_id
    WHERE id = p_ticket_id AND status = 'waiting_operator' AND p_operator_id IS NOT NULL;
    RETURN FOUND;
END;
$$;

-- Бот вызывает после успешной отправки ручного ответа
CREATE OR REPLACE FUNCTION public.confirm_operator_reply(
    p_ticket_id BIGINT, p_reply_round INTEGER, p_operator_id BIGINT, p_text TEXT
) RETURNS BOOLEAN LANGUAGE plpgsql AS $$
DECLARE
    v_sent_at TIMESTAMPTZ := clock_timestamp();
BEGIN
    IF p_text IS NULL OR btrim(p_text) = '' THEN
        RETURN FALSE;
    END IF;

    UPDATE public.tickets
    SET status = 'waiting_client', close_after = v_sent_at + interval '12 hours'
    WHERE id = p_ticket_id AND reply_round = p_reply_round
        AND status = 'operator_processing' AND operator_id = p_operator_id;
    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    INSERT INTO public.messages (ticket_id, author, text, created_at)
    VALUES (p_ticket_id, 'operator', p_text, v_sent_at);
    RETURN TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION public.add_ticket_followup(
    p_ticket_id BIGINT, p_update_id BIGINT, p_chat_id BIGINT, p_text TEXT
) RETURNS TEXT LANGUAGE plpgsql AS $$
DECLARE
    v_ticket public.tickets%ROWTYPE;
    v_now TIMESTAMPTZ;
BEGIN
    SELECT * INTO v_ticket FROM public.tickets
    WHERE id = p_ticket_id AND chat_id = p_chat_id FOR UPDATE;
    IF NOT FOUND OR p_text IS NULL OR btrim(p_text) = '' THEN
        RETURN 'unavailable';
    END IF;

    IF EXISTS (SELECT 1 FROM public.tg_updates WHERE update_id = p_update_id) THEN
        RETURN 'duplicate';
    END IF;

    v_now := clock_timestamp();
    IF v_ticket.status <> 'waiting_client' OR v_ticket.close_after IS NULL
        OR v_ticket.close_after <= v_now THEN
        RETURN 'unavailable';
    END IF;

    INSERT INTO public.tg_updates (update_id) VALUES (p_update_id) ON CONFLICT DO NOTHING;
    IF NOT FOUND THEN
        RETURN 'duplicate';
    END IF;

    INSERT INTO public.messages (ticket_id, author, text, created_at)
    VALUES (p_ticket_id, 'client', p_text, v_now);

    UPDATE public.tickets
    SET status = CASE WHEN v_ticket.decision = 'auto' THEN 'new' ELSE 'operator_processing' END,
        close_after = NULL, attempts = 0, next_attempt_at = v_now, reply_round = reply_round + 1
    WHERE id = p_ticket_id;

    IF v_ticket.decision <> 'auto' THEN
        INSERT INTO public.bot_outbox (ticket_id, reply_round, action)
        VALUES (p_ticket_id, v_ticket.reply_round + 1, 'notify_operator')
        ON CONFLICT (ticket_id, reply_round, action) DO NOTHING;
    END IF;

    RETURN 'accepted';
END;
$$;

COMMIT;
