import json
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass

import asyncpg

from .models import Chunk

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DocumentState:
    doc_hash: str
    index_version: str


@dataclass(frozen=True)
class SyncResult:
    upserted: int
    deleted: int


class DBLoader:
    """Запись и обслуживание чанков в PostgreSQL (pgvector)."""

    def __init__(self, pool: asyncpg.Pool, embedding_dimension: int):
        self.pool = pool
        self.embedding_dimension = embedding_dimension

    async def get_document_state(self, source_file: str) -> DocumentState | None:
        """Возвращает сохранённое состояние документа или None."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT doc_hash, index_version "
                "FROM public.kb_documents WHERE source_file = $1",
                source_file,
            )
        if row is None:
            return None
        return DocumentState(
            doc_hash=row["doc_hash"],
            index_version=row["index_version"],
        )

    async def get_existing_hashes(self, source_file: str) -> set[str]:
        """Возвращает хэши чанков, которые уже есть в БД для данного файла."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT content_hash FROM public.kb_chunks WHERE source_file = $1",
                source_file,
            )
        return {row["content_hash"] for row in rows}

    async def sync_document(
        self,
        *,
        source_file: str,
        doc_hash: str,
        index_version: str,
        valid_hashes: Sequence[str],
        chunks_to_upsert: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
    ) -> SyncResult:
        """Атомарно обновляет состояние документа, чанки и удаляет orphan'ы."""
        self._validate(
            source_file=source_file,
            doc_hash=doc_hash,
            index_version=index_version,
            valid_hashes=valid_hashes,
            chunks=chunks_to_upsert,
            embeddings=embeddings,
        )

        records = [
            (
                chunk.source_file,
                chunk.content_hash,
                json.dumps(list(chunk.headers), ensure_ascii=False),
                chunk.text,
                self._vector_literal(embedding),
            )
            for chunk, embedding in zip(chunks_to_upsert, embeddings)
        ]

        upsert_query = """
            INSERT INTO public.kb_chunks (source_file, content_hash, headers, text, embedding)
            VALUES ($1, $2, $3::jsonb, $4, $5::vector)
            ON CONFLICT (source_file, content_hash) DO UPDATE SET
                headers = EXCLUDED.headers,
                text = EXCLUDED.text,
                embedding = EXCLUDED.embedding;
        """

        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                    INSERT INTO public.kb_documents
                        (source_file, doc_hash, index_version, indexed_at)
                    VALUES ($1, $2, $3, NOW())
                    ON CONFLICT (source_file) DO UPDATE SET
                        doc_hash = EXCLUDED.doc_hash,
                        index_version = EXCLUDED.index_version,
                        indexed_at = NOW();
                    """,
                source_file,
                doc_hash,
                index_version,
            )

            if records:
                await conn.executemany(upsert_query, records)

            if valid_hashes:
                result = await conn.execute(
                    """
                        DELETE FROM public.kb_chunks
                        WHERE source_file = $1
                          AND NOT (content_hash = ANY($2::text[]));
                        """,
                    source_file,
                    list(valid_hashes),
                )
            else:
                result = await conn.execute(
                    "DELETE FROM public.kb_chunks WHERE source_file = $1",
                    source_file,
                )

        deleted = self._deleted_count(result)
        logger.info(
            f"Synced {source_file}: upserted={len(records)}, deleted={deleted}."
        )
        return SyncResult(upserted=len(records), deleted=deleted)

    async def prune_missing_sources(self, active_sources: Sequence[str]) -> int:
        """Удаляет документы и их чанки, которых больше нет в источнике."""
        sources = list(dict.fromkeys(active_sources))
        if not sources:
            logger.warning("No active sources; skipping orphan cleanup.")
            return 0

        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM public.kb_documents "
                "WHERE NOT (source_file = ANY($1::text[]))",
                sources,
            )

        deleted = self._deleted_count(result)
        if deleted:
            logger.info(f"Pruned {deleted} documents missing from the source.")
        return deleted

    def _validate(
        self,
        *,
        source_file: str,
        doc_hash: str,
        index_version: str,
        valid_hashes: Sequence[str],
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        if not source_file or not doc_hash or not index_version:
            raise ValueError("source_file, doc_hash and index_version must be non-empty")

        if len(chunks) != len(embeddings):
            raise ValueError(
                f"Chunk/embedding count mismatch: {len(chunks)} chunks, "
                f"{len(embeddings)} embeddings"
            )

        valid = set(valid_hashes)
        chunk_hashes: set[str] = set()

        for chunk in chunks:
            if chunk.source_file != source_file:
                raise ValueError(
                    f"Chunk source_file {chunk.source_file!r} does not match {source_file!r}"
                )
            if chunk.content_hash not in valid:
                raise ValueError(
                    f"Chunk hash {chunk.content_hash!r} is not in valid_hashes"
                )
            if chunk.content_hash in chunk_hashes:
                raise ValueError(f"Duplicate chunk hash: {chunk.content_hash!r}")
            chunk_hashes.add(chunk.content_hash)

        for index, vector in enumerate(embeddings):
            if len(vector) != self.embedding_dimension:
                raise ValueError(
                    f"Embedding #{index} has dimension {len(vector)}, "
                    f"expected {self.embedding_dimension}"
                )
            for value in vector:
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                ):
                    raise ValueError(
                        f"Embedding #{index} contains a non-finite or non-numeric value"
                    )

    @staticmethod
    def _vector_literal(embedding: Sequence[float]) -> str:
        return "[" + ",".join(map(str, embedding)) + "]"

    @staticmethod
    def _deleted_count(result: str | None) -> int:
        return int(result.split()[-1]) if result else 0
