"""Вопрос → TEI → поиск → генератор. Очередь и доставка остаются вызывающему сервису."""

import time
from contextlib import AsyncExitStack, asynccontextmanager
from collections.abc import AsyncIterator
from typing import Literal, Protocol

import asyncpg
from pydantic import BaseModel

from .config import AISettings, RagSettings
from .generator import GeneratedAnswer, GenerationError, LlmAnswerGenerator
from .retrieval import PgVectorSearch, RetrievedChunk, RetrievalError
from .tei import EmbeddingServiceError, TeiEmbedder


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class Search(Protocol):
    async def search(self, vector: list[float]) -> list[RetrievedChunk]: ...


class Generator(Protocol):
    async def generate(self, question: str, documents: list[dict[str, str]]) -> GeneratedAnswer: ...


class RagError(RuntimeError):
    """Технический сбой на конкретном этапе. Повторы назначает вызывающий сервис."""

    def __init__(self, stage: Literal["embedding", "search", "generation"], message: str,
                 *, retrieved_chunks: list[RetrievedChunk] | None = None,
                 timings: dict[str, float] | None = None):
        self.stage = stage
        self.retrieved_chunks = retrieved_chunks or []
        self.timings = timings or {}
        super().__init__(message)


class RagTimings(BaseModel):
    embedding_s: float = 0
    search_s: float = 0
    generation_s: float = 0
    total_s: float = 0


class RagResult(BaseModel):
    answer: str | None
    source_ids: list[str]
    needs_escalation: bool
    reason: Literal["no_documents", "insufficient_information"] | None
    retrieved_chunks: list[RetrievedChunk]
    timings: RagTimings


class RagAnswerer:
    """Все зависимости переданы извне и остаются во владении вызывающего кода."""

    def __init__(self, embedder: Embedder, search: Search, generator: Generator):
        self._embedder = embedder
        self._search = search
        self._generator = generator

    async def answer_question(self, question: str) -> RagResult:
        if not question.strip():
            raise ValueError("answer_question: пустой вопрос")
        total = time.perf_counter()
        timings = RagTimings()
        started = time.perf_counter()
        try:
            vectors = await self._embedder.embed([question])
            if len(vectors) != 1:
                raise EmbeddingServiceError("На вопрос должен быть получен ровно один вектор")
        except EmbeddingServiceError as exc:
            timings.embedding_s = time.perf_counter() - started
            timings.total_s = time.perf_counter() - total
            raise RagError("embedding", "TEI не вернул корректный эмбеддинг вопроса",
                           timings=timings.model_dump()) from exc
        timings.embedding_s = time.perf_counter() - started
        started = time.perf_counter()
        try:
            chunks = await self._search.search(vectors[0])
        except RetrievalError as exc:
            timings.search_s = time.perf_counter() - started
            timings.total_s = time.perf_counter() - total
            raise RagError("search", "Не удалось выполнить поиск по базе знаний",
                           timings=timings.model_dump()) from exc
        timings.search_s = time.perf_counter() - started
        if not chunks:
            timings.total_s = time.perf_counter() - total
            return RagResult(answer=None, source_ids=[], needs_escalation=True,
                             reason="no_documents", retrieved_chunks=[], timings=timings)
        started = time.perf_counter()
        try:
            generated = await self._generator.generate(
                question, [{"id": c.id, "text": c.text} for c in chunks],
            )
        except GenerationError as exc:
            timings.generation_s = time.perf_counter() - started
            timings.total_s = time.perf_counter() - total
            raise RagError("generation", "Не удалось получить корректный ответ LLM",
                           retrieved_chunks=chunks, timings=timings.model_dump()) from exc
        timings.generation_s = time.perf_counter() - started
        timings.total_s = time.perf_counter() - total
        return RagResult(
            **generated.model_dump(),
            reason="insufficient_information" if generated.needs_escalation else None,
            retrieved_chunks=chunks, timings=timings,
        )


@asynccontextmanager
async def open_rag(ai: AISettings, settings: RagSettings) -> AsyncIterator[RagAnswerer]:
    """Создаёт и гарантированно закрывает свои HTTP-клиенты и пул PostgreSQL."""
    async with AsyncExitStack() as stack:
        try:
            pool = await asyncpg.create_pool(
                settings.database_url.get_secret_value(), min_size=1, max_size=2,
                timeout=settings.rag_search_timeout_s,
            )
        except (asyncpg.PostgresError, OSError, TimeoutError, ValueError) as exc:
            raise RagError("search", "Не удалось подключиться к PostgreSQL для поиска") from exc
        stack.push_async_callback(pool.close)
        embedder = TeiEmbedder(ai.tei_embed_url, ai.request_timeout_s)
        stack.push_async_callback(embedder.aclose)
        generator = LlmAnswerGenerator(
            ai.llm_base_url, ai.llm_model, ai.request_timeout_s, provider=ai.llm_provider,
        )
        stack.push_async_callback(generator.aclose)
        search = PgVectorSearch(
            pool, embedding_dimension=settings.embedding_dimension,
            top_k=settings.rag_top_k, max_distance=settings.rag_max_distance,
            timeout_s=settings.rag_search_timeout_s,
        )
        yield RagAnswerer(embedder, search, generator)
