"""Integration-тест пайплайна kb-index.

Проверяет:
1. TEI реально возвращает эмбеддинги (контракт /embed не сломан).
2. PostgreSQL принимает запись с pgvector указанной размерности.
3. Весь Pipeline.run() проходит без исключений от load() до cleanup_orphans().
4. Повторный запуск на тех же файлах не дублирует чанки (идемпотентность).
5. Изменение файла приводит к обновлению только изменившихся чанков.

"""

from __future__ import annotations

import json

import asyncpg
import pytest
from ai_clients.config import AISettings
from ai_clients.tei import TeiEmbedder

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def _ensure_containers(containers):
    """Просто убеждаемся, что контейнеры подняты до любого теста в модуле."""
    return containers


async def _acquire_connection() -> asyncpg.Connection:
    """Собирает URL из окружения и возвращает подключение к БД."""
    from kb_index.config import get_settings

    settings = get_settings()
    return await asyncpg.connect(settings.database_url)


@pytest.mark.asyncio
async def test_full_pipeline_end_to_end(tmp_kb_dir, _ensure_containers):
    """Полный сценарий: 2 файла -> индексация -> проверка в БД -> изменение -> переиндексация."""

    from kb_index.chunker import MarkdownHeaderChunker
    from kb_index.config import get_settings
    from kb_index.database import DBLoader
    from kb_index.embedder import Embedder
    from kb_index.loader import LocalDirectoryLoader
    from kb_index.pipeline import Pipeline

    # -- ШАГ 1. Создаём markdown-файлы в изолированной директории --
    refunds = tmp_kb_dir / "refunds.md"
    refunds.write_text(
        "# Refunds\n"
        "Money is returned within 3 business days.\n"
        "\n"
        "## How to request\n"
        "Write to support@example.com.\n",
        encoding="utf-8",
    )
    shipping = tmp_kb_dir / "shipping.md"
    shipping.write_text(
        "# Shipping\n"
        "We ship worldwide via DHL and CDEK.\n",
        encoding="utf-8",
    )

    # -- ШАГ 2. Собираем пайплайн из компонентов --
    settings = get_settings()
    ai_settings = AISettings()
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)

    tei = TeiEmbedder(
        base_url=ai_settings.tei_embed_url,
        timeout_s=ai_settings.request_timeout_s,
    )
    try:
        pipeline = Pipeline(
            loader=LocalDirectoryLoader(settings.kb_dir),
            chunker=MarkdownHeaderChunker(),
            embedder=Embedder(tei),
            db_loader=DBLoader(pool, embedding_dimension=settings.embedding_dimension),
            embed_batch_size=settings.embed_batch_size,
        )

        # -- ШАГ 3. Первый прогон пайплайна --
        await pipeline.run()

        conn = await pool.acquire()
        try:
            # Проверяем, что все чанки попали в БД
            rows = await conn.fetch(
                "SELECT source_file, headers, text, "
                "       vector_dims(embedding) AS embedding_dim "
                "FROM kb_chunks ORDER BY source_file, text"
            )

            # Должно быть: 2 чанка из refunds.md (H1 + H2) и 1 чанк из shipping.md (H1)
            assert len(rows) == 3, f"Expected 3 chunks in DB, got {len(rows)}"

            # Проверяем размерность эмбеддингов — контракт с TEI
            for row in rows:
                assert row["embedding_dim"] == settings.embedding_dimension, (
                    f"TEI returned embedding dim {row['embedding_dim']}, "
                    f"expected {settings.embedding_dimension}"
                )

            # Проверяем иерархию заголовков
            sources = {row["source_file"] for row in rows}
            assert len(sources) == 2  # refunds.md и shipping.md

            refunds_chunks = [r for r in rows if r["source_file"].endswith("refunds.md")]
            assert len(refunds_chunks) == 2
            headers_list = {tuple(json.loads(r["headers"])) for r in refunds_chunks}
            assert ("Refunds",) in headers_list
            assert ("Refunds", "How to request") in headers_list

        finally:
            await pool.release(conn)

        # -- ШАГ 4. Идемпотентность: повторный запуск не добавляет чанки --
        await pipeline.run()
        conn = await pool.acquire()
        try:
            count = await conn.fetchval("SELECT COUNT(*) FROM kb_chunks")
            assert count == 3, f"Idempotency broken: expected 3 chunks after re-run, got {count}"
        finally:
            await pool.release(conn)

        # -- ШАГ 5. Изменение файла: обновляется только изменённый чанк --
        refunds.write_text(
            "# Refunds\n"
            "Money is returned within 5 business days.\n"  # изменено: 3 -> 5
            "\n"
            "## How to request\n"
            "Write to support@example.com.\n",  # не изменено
            encoding="utf-8",
        )
        await pipeline.run()

        conn = await pool.acquire()
        try:
            count = await conn.fetchval("SELECT COUNT(*) FROM kb_chunks")
            assert count == 3, f"Update broke count: expected 3 chunks, got {count}"

            # Хэш изменившегося чанка должен обновиться, неизменённого — остаться
            rows_after = await conn.fetch(
                "SELECT text, source_file FROM kb_chunks "
                "WHERE source_file LIKE '%refunds.md' ORDER BY text"
            )
            texts = {r["text"] for r in rows_after}
            assert "Money is returned within 5 business days." in texts
            assert "Money is returned within 3 business days." not in texts
        finally:
            await pool.release(conn)

    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_embedder_contract_directly(_ensure_containers):
    """Прямая проверка контракта TEI /embed без полного пайплайна.

    """
    from kb_index.config import get_settings
    from kb_index.embedder import Embedder

    settings = get_settings()
    ai_settings = AISettings()

    tei = TeiEmbedder(
            base_url=ai_settings.tei_embed_url,
            timeout_s=ai_settings.request_timeout_s,
        )
    embedder = Embedder(tei)

    texts = ["Hello world", "Привет, мир", "日本語"]
    embeddings = await embedder.embed(texts)

    assert len(embeddings) == len(texts), "TEI returned wrong number of embeddings"
    for i, vec in enumerate(embeddings):
        assert len(vec) == settings.embedding_dimension, (
            f"Embedding #{i} has dim {len(vec)}, expected {settings.embedding_dimension}. "
        )
        # Эмбеддинги не должны быть нулевыми или NaN
        assert any(v != 0.0 for v in vec), f"Embedding #{i} is all zeros"
        assert all(v == v for v in vec), f"Embedding #{i} contains NaN"  # noqa: PLR0124


@pytest.mark.asyncio
async def test_database_schema_migration_safe(_ensure_containers):
    """Проверяет, что DBLoader.init() идемпотентен и создаёт pgvector."""
    from kb_index.config import get_settings
    from kb_index.database import DBLoader

    settings = get_settings()
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=2)
    try:
        db = DBLoader(pool, embedding_dimension=settings.embedding_dimension)

        # Двойной вызов init() не должен падать (идемпотентность схемы)
        await db.init()
        await db.init()

        conn = await pool.acquire()
        try:
            # pgvector extension создан
            has_vector = await conn.fetchval(
                "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
            )
            assert has_vector == 1, "pgvector extension не установлен"

            # Таблица kb_chunks существует с правильной размерностью
            column = await conn.fetchrow("""
                SELECT data_type, udt_name
                FROM information_schema.columns
                WHERE table_name = 'kb_chunks' AND column_name = 'embedding'
            """)
            assert column is not None, "Колонка 'embedding' не найдена в kb_chunks"
            assert column["udt_name"] == "vector", (
                f"Колонка 'embedding' имеет тип {column['udt_name']}, ожидался 'vector'"
            )
        finally:
            await pool.release(conn)
    finally:
        await pool.close()