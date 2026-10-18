from unittest.mock import AsyncMock, patch

import httpx
import pytest
from kb_index.embedder import Embedder

TEI_URL = "http://tei.test"
EMBEDDING_DIM = 1024


def make_fake_embeddings(count: int) -> list[list[float]]:
    return [[0.1] * EMBEDDING_DIM for _ in range(count)]


def make_mock_response(json_data, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=json_data,
        request=httpx.Request("POST", f"{TEI_URL}/embed"),
    )


def make_mock_client(response: httpx.Response) -> AsyncMock:
    mock_client = AsyncMock()
    mock_client.post.return_value = response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


@pytest.mark.asyncio
async def test_embed_empty_list_returns_empty():
    """Пустой список текстов не должен делать HTTP-запрос."""
    result = await Embedder(tei_embed_url=TEI_URL).embed([])
    assert result == []


@pytest.mark.asyncio
async def test_embed_returns_embeddings():
    """Успешный ответ TEI возвращает список векторов."""
    fake_embeddings = make_fake_embeddings(2)

    with patch("kb_index.embedder.httpx.AsyncClient") as MockClient:
        MockClient.return_value = make_mock_client(make_mock_response(fake_embeddings))
        result = await Embedder(tei_embed_url=TEI_URL).embed(["text1", "text2"])

    assert result == fake_embeddings
    assert len(result) == 2
    assert len(result[0]) == EMBEDDING_DIM


@pytest.mark.asyncio
async def test_embed_sends_correct_payload():
    """Проверяем, что запрос к TEI содержит правильные поля."""
    with patch("kb_index.embedder.httpx.AsyncClient") as MockClient:
        mock_client = make_mock_client(make_mock_response(make_fake_embeddings(1)))
        MockClient.return_value = mock_client

        await Embedder(tei_embed_url=TEI_URL).embed(["hello"])

        call_args = mock_client.post.call_args
        assert call_args.args[0] == f"{TEI_URL}/embed"
        payload = call_args.kwargs["json"]
        assert payload["inputs"] == ["hello"]
        assert payload["truncate"] is True


@pytest.mark.asyncio
async def test_embed_raises_on_http_error():
    """При ошибке TEI (500) должно выбрасываться исключение."""
    error_response = httpx.Response(
        status_code=500,
        request=httpx.Request("POST", f"{TEI_URL}/embed"),
    )

    with patch("kb_index.embedder.httpx.AsyncClient") as MockClient:
        MockClient.return_value = make_mock_client(error_response)

        with pytest.raises(httpx.HTTPStatusError):
            await Embedder(tei_embed_url=TEI_URL).embed(["text"])


@pytest.mark.asyncio
async def test_embed_single_text():
    """Один текст возвращает один вектор."""
    fake_embeddings = make_fake_embeddings(1)

    with patch("kb_index.embedder.httpx.AsyncClient") as MockClient:
        MockClient.return_value = make_mock_client(make_mock_response(fake_embeddings))
        result = await Embedder(tei_embed_url=TEI_URL).embed(["single"])

    assert len(result) == 1
    assert len(result[0]) == EMBEDDING_DIM
