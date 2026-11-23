"""TEI: перевод текста в набор чисел (шаг 2 и kb-index), модель bge-m3."""

import asyncio
import math

import httpx

from .config import ModelInputLimits
from .tokenization import InputTooLongError, ModelTokenizer, TokenCounter, TokenizationError

EMBEDDING_DIM = 1024  # столько чисел выдаёт bge-m3 на один текст


class EmbeddingServiceError(RuntimeError):
    """TEI не ответил или ответил не тем, что ожидалось."""


class TeiEmbedder:
    def __init__(self, base_url: str, timeout_s: float, http_client: httpx.AsyncClient | None = None,
                 *, limits: ModelInputLimits | None = None, token_counter: TokenCounter | None = None):
        self._limits = limits or ModelInputLimits()
        self._token_counter = token_counter or ModelTokenizer(
            self._limits.tei_tokenizer, self._limits.tei_tokenizer_revision,
            local_files_only=self._limits.tokenizer_local_files_only,
        )
        self._owns_client = http_client is None
        self._client = http_client if http_client is not None else httpx.AsyncClient(
            base_url=base_url, timeout=timeout_s
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Возвращает по одному набору из 1024 чисел на каждый текст, в том же порядке."""
        if not texts:
            raise ValueError("embed: список текстов пуст")
        if any(not t.strip() for t in texts):
            raise ValueError("embed: в списке есть пустой текст")

        # Весь batch проверяется до первого /embed. Спецтокены BGE входят в лимит.
        try:
            counts = await asyncio.to_thread(lambda: [self._token_counter.count_text(t) for t in texts])
        except TokenizationError as exc:
            raise EmbeddingServiceError(str(exc)) from exc
        for index, count in enumerate(counts, start=1):
            if count > self._limits.tei_max_input_tokens:
                raise InputTooLongError(
                    f"TEI: текст №{index} содержит {count} токенов при лимите "
                    f"{self._limits.tei_max_input_tokens}. Разделите текст на меньшие фрагменты.",
                    tokens=count, limit=self._limits.tei_max_input_tokens,
                )

        try:
            response = await self._client.post("/embed", json={"inputs": texts, "truncate": False})
        except httpx.HTTPError as exc:
            raise EmbeddingServiceError(f"TEI недоступен: {exc!r}") from exc

        if response.status_code != 200:
            raise EmbeddingServiceError(
                f"TEI вернул HTTP {response.status_code}: {response.text[:500]}"
            )

        try:
            vectors = response.json()
        except ValueError as exc:
            raise EmbeddingServiceError("TEI вернул некорректный JSON") from exc

        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise EmbeddingServiceError(
                f"TEI вернул {len(vectors) if isinstance(vectors, list) else type(vectors).__name__} "
                f"наборов чисел на {len(texts)} текстов"
            )
        for i, vector in enumerate(vectors):
            if not isinstance(vector, list):
                raise EmbeddingServiceError(f"Текст №{i}: ожидался список чисел, пришёл {type(vector).__name__}")
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in vector
            ):
                raise EmbeddingServiceError(f"Текст №{i}: вектор содержит нечисловое или не конечное значение")
        return [[float(value) for value in vector] for vector in vectors]

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def similarity(a: list[float], b: list[float]) -> float:
    """Близость смысла двух текстов: 1 — одинаковый смысл, около 0 — не связаны.
    TEI по умолчанию нормирует наборы чисел, поэтому достаточно скалярного произведения."""
    if len(a) != len(b):
        raise ValueError(f"Разная длина наборов: {len(a)} и {len(b)}")
    return sum(x * y for x, y in zip(a, b))
