import logging

from ai_clients.tei import TeiEmbedder

logger = logging.getLogger(__name__)


class Embedder:
    """Клиент сервиса эмбеддингов TEI (Text Embeddings Inference)."""

    def __init__(self, tei: TeiEmbedder):
        self._tei = tei

    @property
    def embedding_dim(self) -> int:
        return self._tei._embedding_dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Отправляет тексты в TEI. Пустой список возвращает [] без HTTP-запроса."""
        if not texts:
            return []

        logger.info(f"Embedding {len(texts)} chunks via TEI...")
        return await self._tei.embed(texts)

    async def aclose(self) -> None:
        await self._tei.aclose()
