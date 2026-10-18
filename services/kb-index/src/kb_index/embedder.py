import logging

import httpx

from .config import get_settings

logger = logging.getLogger(__name__)


class Embedder:
    """Клиент сервиса эмбеддингов TEI (Text Embeddings Inference)."""

    def __init__(self, tei_embed_url: str | None = None, timeout: float = 60.0):
        self.tei_embed_url = tei_embed_url or get_settings().tei_embed_url
        self.timeout = timeout

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Отправляет тексты в TEI и возвращает списки эмбеддингов."""
        if not texts:
            return []

        logger.info(f"Embedding {len(texts)} chunks via TEI at {self.tei_embed_url}...")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.tei_embed_url}/embed",
                json={"inputs": texts, "truncate": True},
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            return response.json()
