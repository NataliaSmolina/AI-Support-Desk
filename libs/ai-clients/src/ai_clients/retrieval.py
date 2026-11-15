"""Точный поиск чанков в существующей базе kb-index через pgvector."""

import json
import math
from dataclasses import dataclass
from typing import Sequence

import asyncpg

from .tei import EMBEDDING_DIM


class RetrievalError(RuntimeError):
    """Поиск не выполнен: это техническая ошибка, а не отсутствие информации."""


@dataclass(frozen=True)
class RetrievedChunk:
    id: str
    text: str
    source_file: str
    headers: tuple[str, ...]
    distance: float


# Без ANN-индекса: точное ранжирование по косинусному расстоянию.
# Вторичные ключи обеспечивают стабильный порядок при одинаковом расстоянии.
SEARCH_SQL = """
SELECT content_hash, source_file, headers, text,
       embedding <=> $1::vector AS distance
FROM public.kb_chunks
ORDER BY distance, source_file, content_hash
LIMIT $2
"""


class PgVectorSearch:
    """Использует переданный пул; его созданием и закрытием управляет вызывающий код."""

    def __init__(self, pool: asyncpg.Pool | asyncpg.Connection, *, embedding_dimension: int = EMBEDDING_DIM,
                 top_k: int = 5, max_distance: float | None = None,
                 timeout_s: float = 10):
        if embedding_dimension < 1 or top_k < 1:
            raise ValueError("Размерность и top_k должны быть положительными")
        if max_distance is not None and (
            not math.isfinite(max_distance) or not 0 <= max_distance <= 2
        ):
            raise ValueError("max_distance должен быть конечным числом от 0 до 2")
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("Таймаут поиска должен быть положительным конечным числом")
        self._pool = pool
        self._dimension = embedding_dimension
        self._top_k = top_k
        self._max_distance = max_distance
        self._timeout_s = timeout_s

    async def search(self, vector: Sequence[float]) -> list[RetrievedChunk]:
        if len(vector) != self._dimension:
            raise RetrievalError(f"Размерность вопроса: {len(vector)}, ожидалось {self._dimension}")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
               for v in vector):
            raise RetrievalError("Вектор вопроса содержит некорректные значения")
        if not any(v != 0 for v in vector):
            raise RetrievalError("Косинусное расстояние не определено для нулевого вектора")
        literal = json.dumps(list(vector), allow_nan=False)
        try:
            rows = await self._pool.fetch(SEARCH_SQL, literal, self._top_k, timeout=self._timeout_s)
        except (asyncpg.PostgresError, asyncpg.InterfaceError, OSError, TimeoutError) as exc:
            # Не включаем DSN, вопрос или содержимое документов в сообщение ошибки.
            raise RetrievalError(
                "Не удалось выполнить поиск в PostgreSQL; проверьте подключение, "
                "миграцию базы знаний и размерность сохранённых эмбеддингов"
            ) from exc
        chunks = []
        for row in rows:
            distance = row["distance"]
            if distance is None or not math.isfinite(distance):
                raise RetrievalError("База знаний содержит вектор с неопределённым расстоянием")
            if self._max_distance is not None and distance > self._max_distance:
                continue
            headers = row["headers"]
            if isinstance(headers, str):
                try:
                    headers = json.loads(headers)
                except ValueError:
                    raise RetrievalError("Некорректные заголовки чанка в базе знаний") from None
            if not isinstance(headers, list) or any(not isinstance(h, str) for h in headers):
                raise RetrievalError("Некорректные заголовки чанка в базе знаний")
            if not row["content_hash"] or not row["source_file"] or not row["text"].strip():
                raise RetrievalError("В базе знаний найден чанк с пустыми обязательными полями")
            chunks.append(RetrievedChunk(
                id=row["content_hash"], text=row["text"], source_file=row["source_file"],
                headers=tuple(headers), distance=float(distance),
            ))
        return chunks
