"""SQL-интеграция на отдельной БД evals/compose.rag.yml; все изменения откатываются."""

import os

import asyncpg
import pytest
import pytest_asyncio

from ai_clients.retrieval import PgVectorSearch, RetrievalError

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def connection():
    dsn = os.getenv("RAG_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Задайте RAG_TEST_DATABASE_URL для выделенной БД rag_eval на порту 5436")
    conn = await asyncpg.connect(dsn, timeout=5)
    try:
        if await conn.fetchval("SELECT current_database()") != "rag_eval":
            pytest.fail("Интеграционные тесты разрешены только в отдельной БД rag_eval")
        tx = conn.transaction()
        await tx.start()
        try:
            await conn.execute("TRUNCATE public.kb_documents CASCADE")
            await conn.execute("""
                INSERT INTO public.kb_documents(source_file, doc_hash, index_version)
                VALUES ('near.md', 'd1', 'test'), ('middle.md', 'd2', 'test'), ('far.md', 'd3', 'test')
            """)
            await conn.execute("""
                INSERT INTO public.kb_chunks(source_file, content_hash, headers, text, embedding)
                VALUES ('near.md', 'a', '["Near"]', 'Near text', '[1,0,0]'),
                       ('middle.md', 'b', '[]', 'Middle text', '[0.8,0.6,0]'),
                       ('far.md', 'c', '[]', 'Far text', '[-1,0,0]')
            """)
            yield conn
        finally:
            await tx.rollback()
    finally:
        await conn.close()


async def test_exact_cosine_order_and_limit(connection):
    result = await PgVectorSearch(connection, embedding_dimension=3, top_k=2).search([1, 0, 0])
    assert [c.id for c in result] == ["a", "b"]
    assert result[0].distance == pytest.approx(0)
    assert result[1].distance == pytest.approx(0.2)
    assert result[0].headers == ("Near",)


async def test_distance_cutoff_and_no_results(connection):
    search = PgVectorSearch(connection, embedding_dimension=3, max_distance=0.1)
    assert [c.id for c in await search.search([1, 0, 0])] == ["a"]
    assert await search.search([0, 0, 1]) == []


async def test_mismatched_stored_dimension_is_failure_not_empty_search(connection):
    await connection.execute("UPDATE public.kb_chunks SET embedding = '[1,0]' WHERE content_hash = 'a'")
    with pytest.raises(RetrievalError):
        await PgVectorSearch(connection, embedding_dimension=3).search([1, 0, 0])


async def test_database_with_no_chunks(connection):
    await connection.execute("DELETE FROM public.kb_chunks")
    assert await PgVectorSearch(connection, embedding_dimension=3).search([1, 0, 0]) == []
