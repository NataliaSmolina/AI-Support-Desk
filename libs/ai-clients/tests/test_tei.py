"""Проверка логики embed без запущенного TEI: ответы TEI подменяются."""

import httpx
import pytest

from ai_clients.tei import EMBEDDING_DIM, EmbeddingServiceError, TeiEmbedder, similarity


def make_embedder(handler) -> TeiEmbedder:
    client = httpx.AsyncClient(base_url="http://tei.test", transport=httpx.MockTransport(handler))
    return TeiEmbedder("http://tei.test", 5, http_client=client)


async def test_returns_vector_per_text_in_order():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/embed"
        texts = __import__("json").loads(request.content)["inputs"]
        return httpx.Response(200, json=[[float(i)] * EMBEDDING_DIM for i, _ in enumerate(texts)])

    vectors = await make_embedder(handler).embed(["первый", "второй"])
    assert len(vectors) == 2
    assert vectors[0][0] == 0.0 and vectors[1][0] == 1.0
    assert all(len(v) == EMBEDDING_DIM for v in vectors)


async def test_http_error_is_raised_not_swallowed():
    embedder = make_embedder(lambda r: httpx.Response(500, text="model not loaded"))
    with pytest.raises(EmbeddingServiceError, match="HTTP 500"):
        await embedder.embed(["текст"])


async def test_wrong_dimension_is_error():
    embedder = make_embedder(lambda r: httpx.Response(200, json=[[0.1] * 384]))
    with pytest.raises(EmbeddingServiceError, match="1024"):
        await embedder.embed(["текст"])


async def test_count_mismatch_is_error():
    embedder = make_embedder(lambda r: httpx.Response(200, json=[[0.1] * EMBEDDING_DIM]))
    with pytest.raises(EmbeddingServiceError, match="на 2 текстов"):
        await embedder.embed(["один", "два"])


async def test_connection_failure_is_error():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(EmbeddingServiceError, match="недоступен"):
        await make_embedder(handler).embed(["текст"])


async def test_empty_input_rejected():
    embedder = make_embedder(lambda r: httpx.Response(200, json=[]))
    with pytest.raises(ValueError):
        await embedder.embed([])
    with pytest.raises(ValueError):
        await embedder.embed(["  "])


def test_similarity():
    assert similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
    with pytest.raises(ValueError):
        similarity([1.0], [1.0, 2.0])
