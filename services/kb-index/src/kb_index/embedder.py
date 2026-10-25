import logging
from typing import Protocol

from ai_clients.tei import TeiEmbedder

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Возвращает по одному вектору на каждый текст."""


class TeiEmbedderAdapter:
    """Адаптер клиента TEI под порт Embedder."""

    def __init__(self, tei: TeiEmbedder):
        self._tei = tei

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Отправляет тексты в TEI. Пустой список возвращает [] без HTTP-запроса."""
        if not texts:
            return []

        logger.info(f"Embedding {len(texts)} chunks via TEI...")
        return await self._tei.embed(texts)

    async def aclose(self) -> None:
        await self._tei.aclose()
