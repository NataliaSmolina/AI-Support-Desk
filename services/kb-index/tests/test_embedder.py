from unittest.mock import AsyncMock, patch

import httpx
import pytest
from kb_index.embedder import embed_texts

FAKE_EMBEDDINGS = [[0.1] * 384, [0.2] * 384]


def make_mock_response(json_data, status_code=200):
    """Создаёт мок HTTP-ответа."""
    response = httpx.Response(
        status_code=status_code,
        json=json_data,
        request=httpx.Request("POST", "http://test/embed"),
    )
    return response


@pytest.mark.asyncio
async def test_embed_empty_list_returns_empty():
    """Пустой список текстов не должен делать HTTP-запрос."""
    result = await embed_texts([])
    assert result == []


@pytest.mark.asyncio
async def test_embed_returns_embeddings():
    """Успешный ответ TEI возвращает список векторов."""
    mock_response = make_mock_response(FAKE_EMBEDDINGS)

    with patch("kb_index.embedder.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_client

        result = await embed_texts(["text1", "text2"])

    assert result == FAKE_EMBEDDINGS
    assert len(result) == 2
    assert len(result[0]) == 384


@pytest.mark.asyncio
async def test_embed_sends_correct_payload():
    """Проверяем, что запрос к TEI содержит правильные поля."""
    mock_response = make_mock_response([[0.1] * 384])

    with patch("kb_index.embedder.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_client

        await embed_texts(["hello"])

        # Проверяем, что post был вызван с правильными аргументами
        call_args = mock_client.post.call_args
        assert call_args.args[0].endswith("/embed")
        payload = call_args.kwargs["json"]
        assert payload["inputs"] == ["hello"]
        assert payload["truncate"] is True


@pytest.mark.asyncio
async def test_embed_raises_on_http_error():
    """При ошибке TEI (500) должно выбрасываться исключение."""
    mock_response = httpx.Response(
        status_code=500,
        request=httpx.Request("POST", "http://test/embed"),
    )

    with patch("kb_index.embedder.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_client

        with pytest.raises(httpx.HTTPStatusError):
            await embed_texts(["text"])


@pytest.mark.asyncio
async def test_embed_single_text():
    """Один текст возвращает один вектор."""
    mock_response = make_mock_response([[0.5] * 384])

    with patch("kb_index.embedder.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_client

        result = await embed_texts(["single"])

    assert len(result) == 1
    assert len(result[0]) == 384