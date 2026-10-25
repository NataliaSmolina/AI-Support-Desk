BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE public.kb_documents (
    source_file   TEXT PRIMARY KEY,
    doc_hash      TEXT NOT NULL,
    index_version TEXT NOT NULL,
    indexed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE public.kb_chunks (
    source_file  TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    headers      JSONB NOT NULL,
    text         TEXT NOT NULL,
    embedding    vector NOT NULL,
    PRIMARY KEY (source_file, content_hash),
    CONSTRAINT fk_kb_chunks_document
        FOREIGN KEY (source_file)
        REFERENCES public.kb_documents(source_file)
        ON DELETE CASCADE
);

COMMIT;
