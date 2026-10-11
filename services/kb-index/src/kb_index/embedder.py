import logging

import httpx

from .config import settings

logger = logging.getLogger(__name__)

async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Отправляет тексты в TEI и возвращает списки эмбеддингов."""
    if not texts:
        return []
    
    logger.info(f"Embedding {len(texts)} chunks via TEI at {settings.tei_url}...")
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{settings.tei_url}/embed",
            json={"inputs": texts, "truncate": True},
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
        return response.json()