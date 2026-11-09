   ALTER TABLE public.tickets
       ADD COLUMN IF NOT EXISTS closed_by BIGINT,
       ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ;