import json
from unittest.mock import AsyncMock

import asyncpg
import pytest

from ai_clients.retrieval import PgVectorSearch, RetrievalError


def row(distance=0.1, headers='["Возврат"]'):
    return dict(content_hash="hash", source_file="refunds.md", headers=headers,
                text="Возврат за 10 дней.", distance=distance)


async def test_vector_is_parameterized_and_metadata_is_preserved():
    pool = AsyncMock()
    pool.fetch.return_value = [row()]
    result = await PgVectorSearch(pool, embedding_dimension=3, top_k=2).search([1.0, 0.0, 0.0])
    sql, vector, limit = pool.fetch.call_args.args
    assert "<=>" in sql
    assert json.loads(vector) == [1.0, 0.0, 0.0]
    assert limit == 2
    assert result[0].headers == ("Возврат",)
    assert result[0].id == "hash"


async def test_optional_distance_filter():
    pool = AsyncMock()
    pool.fetch.return_value = [row(0.1), {**row(0.7), "content_hash": "far"}]
    chunks = await PgVectorSearch(pool, embedding_dimension=3, max_distance=0.3).search([1, 0, 0])
    assert [c.id for c in chunks] == ["hash"]


async def test_empty_database_returns_empty_list():
    pool = AsyncMock()
    pool.fetch.return_value = []
    assert await PgVectorSearch(pool, embedding_dimension=3).search([1, 0, 0]) == []


@pytest.mark.parametrize("vector", [[1, 0], [0, 0, 0], [True, 0, 0], [float("nan"), 0, 0],
                                  [float("inf"), 0, 0], ["x", 0, 0]])
async def test_bad_query_vectors_do_not_reach_database(vector):
    pool = AsyncMock()
    with pytest.raises(RetrievalError):
        await PgVectorSearch(pool, embedding_dimension=3).search(vector)
    pool.fetch.assert_not_awaited()


@pytest.mark.parametrize("error", [asyncpg.DataError("different dimensions"),
                                  asyncpg.UndefinedTableError("missing"),
                                  OSError("connection"), TimeoutError()])
async def test_database_failures_are_technical_errors(error):
    pool = AsyncMock()
    pool.fetch.side_effect = error
    with pytest.raises(RetrievalError, match="Не удалось выполнить поиск"):
        await PgVectorSearch(pool, embedding_dimension=3).search([1, 0, 0])


@pytest.mark.parametrize("record", [row(float("nan")), row(None), row(headers="bad json"),
                                   row(headers='{"bad":1}'), {**row(), "text": " "}])
async def test_corrupt_rows_are_not_treated_as_valid_context(record):
    pool = AsyncMock()
    pool.fetch.return_value = [record]
    with pytest.raises(RetrievalError):
        await PgVectorSearch(pool, embedding_dimension=3).search([1, 0, 0])


@pytest.mark.parametrize("kwargs", [{"top_k": 0}, {"embedding_dimension": 0},
                                    {"max_distance": -1}, {"max_distance": float("nan")},
                                    {"timeout_s": 0}])
def test_bad_settings(kwargs):
    with pytest.raises(ValueError):
        PgVectorSearch(AsyncMock(), **kwargs)
