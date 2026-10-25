"""Integration-тесты пайплайна kb-index.

Проверяют контракт TEI, полную индексацию, пропуск неизменённых документов,
инкрементальное обновление, удаление исчезнувших файлов и атомарность записи.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import asyncpg
import pytest
from ai_clients.config import AISettings
from ai_clients.tei import TeiEmbedder

if TYPE_CHECKING:
    from kb_index.config import Settings
    from kb_index.pipeline import Pipeline

pytestmark = pytest.mark.integration


class _CountingEmbedder:
    def __init__(self, inner):
        self.inner = inner
        self.calls = 0
        self.texts = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        self.texts += len(texts)
        return await self.inner.embed(texts)


class _CountingLoader:
    def __init__(self, inner):
        self.inner = inner
        self.calls = 0
        self.documents = []

    def source(self) -> str:
        return self.inner.source()

    def load(self):
        self.calls += 1
        self.documents = self.inner.load()
        return self.documents


@dataclass
class _PipelineEnv:
    settings: Settings
    pool: asyncpg.Pool
    pipeline: Pipeline
    counter: _CountingEmbedder
    loader: _CountingLoader
    refunds: Path
    shipping: Path

    def reset_counters(self) -> None:
        self.counter.calls = 0
        self.counter.texts = 0
        self.loader.calls = 0
        self.loader.documents = []


@pytest.fixture(scope="session")
def _ensure_containers(containers):
    """Просто убеждаемся, что контейнеры подняты до любого теста в модуле."""
    return containers


def _write_kb(directory: Path) -> tuple[Path, Path]:
    refunds = directory / "refunds.md"
    refunds.write_text(
        "# Refunds\n"
        "Money is returned within 3 business days.\n"
        "\n"
        "## How to request\n"
        "Write to support@example.com.\n",
        encoding="utf-8",
    )
    shipping = directory / "shipping.md"
    shipping.write_text(
        "# Shipping\n"
        "We ship worldwide via DHL and CDEK.\n",
        encoding="utf-8",
    )
    return refunds, shipping


@pytest.fixture
async def pipeline_env(tmp_kb_dir: Path, _ensure_containers) -> _PipelineEnv:
    from kb_index.chunker import MarkdownHeaderChunker
    from kb_index.config import Settings
    from kb_index.database import DBLoader
    from kb_index.embedder import TeiEmbedderAdapter
    from kb_index.loader import LocalDirectoryLoader
    from kb_index.pipeline import Pipeline

    refunds, shipping = _write_kb(tmp_kb_dir)
    settings = Settings()
    ai_settings = AISettings()
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)
    tei = TeiEmbedder(
        base_url=ai_settings.tei_embed_url,
        timeout_s=ai_settings.request_timeout_s,
    )
    counter = _CountingEmbedder(TeiEmbedderAdapter(tei))
    loader = _CountingLoader(LocalDirectoryLoader(settings.kb_dir))

    try:
        async with pool.acquire() as conn:
            await conn.execute("TRUNCATE public.kb_documents, public.kb_chunks")

        pipeline = Pipeline(
            loader=loader,
            chunker=MarkdownHeaderChunker(),
            embedder=counter,
            db_loader=DBLoader(pool, embedding_dimension=settings.embedding_dimension),
            embed_batch_size=settings.embed_batch_size,
        )
        yield _PipelineEnv(
            settings=settings,
            pool=pool,
            pipeline=pipeline,
            counter=counter,
            loader=loader,
            refunds=refunds,
            shipping=shipping,
        )
    finally:
        await tei.aclose()
        await pool.close()


@pytest.mark.asyncio
async def test_full_pipeline_end_to_end(pipeline_env: _PipelineEnv):
    await pipeline_env.pipeline.run()


@pytest.mark.asyncio
async def test_pipeline_indexes_all_chunks(pipeline_env: _PipelineEnv):
    env = pipeline_env

    await env.pipeline.run()

    assert env.loader.calls == 1
    assert len(env.loader.documents) == 2
    assert env.counter.texts == 3

    async with env.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT source_file, headers, text, "
            "       vector_dims(embedding) AS embedding_dim "
            "FROM public.kb_chunks ORDER BY source_file, text"
        )
        assert len(rows) == 3
        assert {row["source_file"] for row in rows} == {
            str(env.refunds),
            str(env.shipping),
        }

        for row in rows:
            assert row["embedding_dim"] == env.settings.embedding_dimension

        refunds_chunks = [
            row for row in rows if row["source_file"] == str(env.refunds)
        ]
        assert len(refunds_chunks) == 2
        headers = {tuple(json.loads(row["headers"])) for row in refunds_chunks}
        assert headers == {("Refunds",), ("Refunds", "How to request")}

        document_count = await conn.fetchval(
            "SELECT COUNT(*) FROM public.kb_documents"
        )
        assert document_count == 2


@pytest.mark.asyncio
async def test_pipeline_skips_unchanged_documents(pipeline_env: _PipelineEnv):
    env = pipeline_env
    await env.pipeline.run()

    env.reset_counters()
    await env.pipeline.run()

    assert env.loader.calls == 1
    assert len(env.loader.documents) == 2
    assert env.counter.calls == 0
    assert env.counter.texts == 0

    async with env.pool.acquire() as conn:
        chunk_count = await conn.fetchval("SELECT COUNT(*) FROM public.kb_chunks")
        document_count = await conn.fetchval(
            "SELECT COUNT(*) FROM public.kb_documents"
        )
    assert chunk_count == 3
    assert document_count == 2


@pytest.mark.asyncio
async def test_pipeline_embeds_only_changed_chunks(pipeline_env: _PipelineEnv):
    env = pipeline_env
    await env.pipeline.run()

    env.refunds.write_text(
        "# Refunds\n"
        "Money is returned within 5 business days.\n"
        "\n"
        "## How to request\n"
        "Write to support@example.com.\n",
        encoding="utf-8",
    )

    env.reset_counters()
    await env.pipeline.run()

    assert env.loader.calls == 1
    assert env.counter.texts == 1

    async with env.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT text FROM public.kb_chunks WHERE source_file = $1",
            str(env.refunds),
        )
        chunk_count = await conn.fetchval("SELECT COUNT(*) FROM public.kb_chunks")
    texts = {row["text"] for row in rows}
    assert "Money is returned within 5 business days." in texts
    assert "Money is returned within 3 business days." not in texts
    assert chunk_count == 3


@pytest.mark.asyncio
async def test_pipeline_prunes_deleted_documents(pipeline_env: _PipelineEnv):
    env = pipeline_env
    await env.pipeline.run()

    env.shipping.unlink()
    env.reset_counters()
    await env.pipeline.run()

    assert env.loader.calls == 1
    assert [doc.source_file for doc in env.loader.documents] == [str(env.refunds)]
    assert env.counter.calls == 0
    assert env.counter.texts == 0

    async with env.pool.acquire() as conn:
        sources = {
            row["source_file"]
            for row in await conn.fetch("SELECT source_file FROM public.kb_chunks")
        }
        chunk_count = await conn.fetchval("SELECT COUNT(*) FROM public.kb_chunks")
        documents = await conn.fetch("SELECT source_file FROM public.kb_documents")

    assert sources == {str(env.refunds)}
    assert chunk_count == 2
    assert [row["source_file"] for row in documents] == [str(env.refunds)]


@pytest.mark.asyncio
async def test_embedder_contract_directly(_ensure_containers):
    """Прямая проверка контракта TEI /embed без полного пайплайна."""
    from kb_index.config import Settings
    from kb_index.embedder import TeiEmbedderAdapter

    settings = Settings()
    ai_settings = AISettings()

    tei = TeiEmbedder(
        base_url=ai_settings.tei_embed_url,
        timeout_s=ai_settings.request_timeout_s,
    )
    embedder = TeiEmbedderAdapter(tei)
    try:
        texts = ["Hello world", "Привет, мир", "日本語"]
        embeddings = await embedder.embed(texts)
    finally:
        await tei.aclose()

    assert len(embeddings) == len(texts), "TEI returned wrong number of embeddings"
    for i, vec in enumerate(embeddings):
        assert len(vec) == settings.embedding_dimension, (
            f"Embedding #{i} has dim {len(vec)}, expected {settings.embedding_dimension}. "
        )
        assert any(v != 0.0 for v in vec), f"Embedding #{i} is all zeros"
        assert all(v == v for v in vec), f"Embedding #{i} contains NaN"  # noqa: PLR0124


@pytest.mark.asyncio
async def test_sync_document_rolls_back_on_write_error(tmp_path, _ensure_containers):
    """Ошибка записи не должна оставлять частично обновлённый документ."""
    from kb_index.config import Settings
    from kb_index.database import DBLoader
    from kb_index.models import Chunk

    settings = Settings()
    source_file = str(tmp_path / "rollback.md")
    good = Chunk(text="good text", headers=("A",), source_file=source_file)
    bad = Chunk(text="bad\x00text", headers=("A",), source_file=source_file)
    embeddings = [[0.0] * settings.embedding_dimension for _ in range(2)]

    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=2)
    try:
        db = DBLoader(pool, embedding_dimension=settings.embedding_dimension)

        with pytest.raises(asyncpg.exceptions.CharacterNotInRepertoireError):
            await db.sync_document(
                source_file=source_file,
                doc_hash="rollback-doc",
                index_version="test",
                valid_hashes=[good.content_hash, bad.content_hash],
                chunks_to_upsert=[good, bad],
                embeddings=embeddings,
            )

        async with pool.acquire() as conn:
            document_count = await conn.fetchval(
                "SELECT COUNT(*) FROM public.kb_documents WHERE source_file = $1",
                source_file,
            )
            chunk_count = await conn.fetchval(
                "SELECT COUNT(*) FROM public.kb_chunks WHERE source_file = $1",
                source_file,
            )
        assert document_count == 0, "Failed sync left a document row behind"
        assert chunk_count == 0, "Failed sync left chunk rows behind"
    finally:
        await pool.close()
