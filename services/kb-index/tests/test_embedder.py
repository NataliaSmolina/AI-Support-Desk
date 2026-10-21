from unittest.mock import AsyncMock

import pytest
from ai_clients.tei import TeiEmbedder
from kb_index.embedder import Embedder


@pytest.mark.asyncio
async def test_embed_empty_list_returns_empty_without_calling_tei():
    """Пустой список не должен делать HTTP-запрос к TEI."""
    mock_tei = AsyncMock(spec=TeiEmbedder)
    embedder = Embedder(mock_tei)

    result = await embedder.embed([])

    assert result == []
    mock_tei.embed.assert_not_awaited()


@pytest.mark.asyncio
async def test_embed_delegates_to_tei():
    """Непустой список делегируется TeiEmbedder и возвращается как есть."""
    fake_vectors = [[0.1] * 1024, [0.2] * 1024]
    mock_tei = AsyncMock(spec=TeiEmbedder)
    mock_tei.embed.return_value = fake_vectors
    embedder = Embedder(mock_tei)

    result = await embedder.embed(["text1", "text2"])

    assert result == fake_vectors
    mock_tei.embed.assert_awaited_once_with(["text1", "text2"])


@pytest.mark.asyncio
async def test_aclose_delegates_to_tei():
    """aclose пробрасывается на TeiEmbedder для корректного закрытия HTTP-клиента."""
    mock_tei = AsyncMock(spec=TeiEmbedder)
    embedder = Embedder(mock_tei)

    await embedder.aclose()

    mock_tei.aclose.assert_awaited_once()
