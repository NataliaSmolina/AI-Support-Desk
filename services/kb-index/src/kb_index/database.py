import json
import logging

import asyncpg

from .models import Chunk

logger = logging.getLogger(__name__)


class DBLoader:
    """Запись и обслуживание чанков в PostgreSQL (pgvector)."""

    def __init__(self, pool: asyncpg.Pool, embedding_dimension: int):
        self.pool = pool
        self.embedding_dimension = embedding_dimension

    async def init(self) -> None:
        """Создаёт таблицу и расширение pgvector, если их нет."""
        async with self.pool.acquire() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS kb_chunks (
                    content_hash TEXT PRIMARY KEY,
                    source_file TEXT NOT NULL,
                    headers JSONB NOT NULL,
                    text TEXT NOT NULL,
                    embedding vector({self.embedding_dimension})
                );
                CREATE INDEX IF NOT EXISTS idx_kb_chunks_source ON kb_chunks(source_file);
            """)
        logger.info(f"Database initialized. Table 'kb_chunks' ready (dim={self.embedding_dimension}).")

    async def get_existing_hashes(self, source_file: str) -> set[str]:
        """Возвращает хэши чанков, которые уже есть в БД для данного файла."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT content_hash FROM kb_chunks WHERE source_file = $1", source_file)
        return {row["content_hash"] for row in rows}

    async def upsert_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        """Записывает или обновляет чанки в БД."""
        if not chunks:
            return

        if len(chunks) != len(embeddings):
            raise ValueError(
                f"Chunk/embedding count mismatch: {len(chunks)} chunks, "
                f"{len(embeddings)} embeddings"
            )

        records = [
            (
                chunk.content_hash,
                chunk.source_file,
                json.dumps(chunk.headers, ensure_ascii=False),
                chunk.text,
                "[" + ",".join(map(str, embedding)) + "]",
            )
            for chunk, embedding in zip(chunks, embeddings)
        ]

        query = """
            INSERT INTO kb_chunks (content_hash, source_file, headers, text, embedding)
            VALUES ($1, $2, $3::jsonb, $4, $5::vector)
            ON CONFLICT (content_hash) DO UPDATE SET
                text = EXCLUDED.text,
                headers = EXCLUDED.headers,
                source_file = EXCLUDED.source_file,
                embedding = EXCLUDED.embedding;
        """
        async with self.pool.acquire() as conn:
            await conn.executemany(query, records)
        logger.info(f"Upserted {len(chunks)} chunks into PostgreSQL.")

    async def cleanup_orphans(self, source_file: str, valid_hashes: list[str]) -> None:
        """Удаляет из БД чанки, которых больше нет в обновлённом MD-файле."""
        async with self.pool.acquire() as conn:
            if not valid_hashes:
                result = await conn.execute("DELETE FROM kb_chunks WHERE source_file = $1", source_file)
            else:
                query = """
                    DELETE FROM kb_chunks
                    WHERE source_file = $1 AND NOT (content_hash = ANY($2::text[]))
                """
                result = await conn.execute(query, source_file, valid_hashes)

        deleted_count = int(result.split()[-1]) if result else 0
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} orphaned chunks for {source_file}.")
