"""Проверка логики embed без запущенного TEI: ответы TEI подменяются."""

import json

import httpx
import pytest

from ai_clients.tei import EMBEDDING_DIM, EmbeddingServiceError, TeiEmbedder, similarity


def make_embedder(handler) -> TeiEmbedder:
    client = httpx.AsyncClient(base_url="http://tei.test", transport=httpx.MockTransport(handler))
    return TeiEmbedder("http://tei.test", 5, http_client=client)


async def test_returns_vector_per_text_in_order():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/embed"
        texts = json.loads(request.content)["inputs"]
        assert texts == ["первый", "второй"]
        return httpx.Response(200, json=[[float(i)] * EMBEDDING_DIM for i, _ in enumerate(texts)])

    vectors = await make_embedder(handler).embed(["первый", "второй"])
    assert len(vectors) == 2
    assert vectors[0][0] == 0.0 and vectors[1][0] == 1.0
    assert all(len(v) == EMBEDDING_DIM for v in vectors)


async def test_aclose_does_not_close_injected_http_client():
    embedder = make_embedder(lambda _: httpx.Response(200, json=[[0.0] * EMBEDDING_DIM]))
    client = embedder._client

    await embedder.aclose()

    assert not client.is_closed
    await client.aclose()


async def test_aclose_closes_owned_http_client():
    embedder = TeiEmbedder("http://tei.test", 5)
    client = embedder._client

    await embedder.aclose()

    assert client.is_closed


async def test_http_error_is_raised_not_swallowed():
    embedder = make_embedder(lambda r: httpx.Response(500, text="model not loaded"))
    with pytest.raises(EmbeddingServiceError, match="HTTP 500"):
        await embedder.embed(["текст"])


async def test_count_mismatch_is_error():
    embedder = make_embedder(lambda r: httpx.Response(200, json=[[0.1] * EMBEDDING_DIM]))
    with pytest.raises(EmbeddingServiceError, match="на 2 текстов"):
        await embedder.embed(["один", "два"])


async def test_invalid_json_is_error():
    embedder = make_embedder(lambda r: httpx.Response(200, content=b"not json"))
    with pytest.raises(EmbeddingServiceError, match="некорректный JSON"):
        await embedder.embed(["текст"])


async def test_non_list_vector_is_error():
    embedder = make_embedder(lambda r: httpx.Response(200, json=[None]))
    with pytest.raises(EmbeddingServiceError, match="ожидался список чисел"):
        await embedder.embed(["текст"])


@pytest.mark.parametrize("value", ["bad", True, float("inf"), float("nan")])
async def test_non_numeric_or_non_finite_vector_value_is_error(value):
    body = json.dumps([[value] + [0.0] * (EMBEDDING_DIM - 1)], allow_nan=True)
    embedder = make_embedder(lambda r: httpx.Response(200, content=body))
    with pytest.raises(EmbeddingServiceError, match="нечисловое или не конечное"):
        await embedder.embed(["текст"])


async def test_integer_values_are_returned_as_floats():
    embedder = make_embedder(lambda r: httpx.Response(200, json=[[1] * EMBEDDING_DIM]))
    vectors = await embedder.embed(["текст"])
    assert vectors[0][0] == 1.0
    assert isinstance(vectors[0][0], float)


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
