"""TEI: перевод текста в набор чисел (шаг 2 и kb-index), модель bge-m3."""

import httpx

EMBEDDING_DIM = 1024  # столько чисел выдаёт bge-m3 на один текст


class EmbeddingServiceError(RuntimeError):
    """TEI не ответил или ответил не тем, что ожидалось."""


class TeiEmbedder:
    def __init__(self, base_url: str, timeout_s: float, http_client: httpx.AsyncClient | None = None):
        self._client = http_client or httpx.AsyncClient(base_url=base_url, timeout=timeout_s)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Возвращает по одному набору из 1024 чисел на каждый текст, в том же порядке."""
        if not texts:
            raise ValueError("embed: список текстов пуст")
        if any(not t.strip() for t in texts):
            raise ValueError("embed: в списке есть пустой текст")

        try:
            response = await self._client.post("/embed", json={"inputs": texts})
        except httpx.HTTPError as exc:
            raise EmbeddingServiceError(f"TEI недоступен: {exc!r}") from exc

        if response.status_code != 200:
            raise EmbeddingServiceError(
                f"TEI вернул HTTP {response.status_code}: {response.text[:500]}"
            )

        vectors = response.json()
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise EmbeddingServiceError(
                f"TEI вернул {len(vectors) if isinstance(vectors, list) else type(vectors).__name__} "
                f"наборов чисел на {len(texts)} текстов"
            )
        for i, vector in enumerate(vectors):
            if len(vector) != EMBEDDING_DIM:
                raise EmbeddingServiceError(
                    f"Текст №{i}: ожидалось {EMBEDDING_DIM} чисел, пришло {len(vector)}. "
                    "Проверьте, что TEI запущен с моделью BAAI/bge-m3"
                )
        return vectors

    async def aclose(self) -> None:
        await self._client.aclose()


def similarity(a: list[float], b: list[float]) -> float:
    """Близость смысла двух текстов: 1 — одинаковый смысл, около 0 — не связаны.
    TEI по умолчанию нормирует наборы чисел, поэтому достаточно скалярного произведения."""
    if len(a) != len(b):
        raise ValueError(f"Разная длина наборов: {len(a)} и {len(b)}")
    return sum(x * y for x, y in zip(a, b))
