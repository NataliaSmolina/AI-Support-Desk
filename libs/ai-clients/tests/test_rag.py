from unittest.mock import AsyncMock

import pytest

from ai_clients.generator import GeneratedAnswer, GenerationError
from ai_clients.rag import RagAnswerer, RagError
from ai_clients.retrieval import RetrievedChunk, RetrievalError
from ai_clients.tei import EmbeddingServiceError


@pytest.fixture
def parts():
    embedder = AsyncMock()
    embedder.embed.return_value = [[1.0, 0.0, 0.0]]
    search = AsyncMock()
    search.search.return_value = [
        RetrievedChunk("a", "Возврат занимает 10 дней.", "refunds.md", ("Возврат",), 0.1),
        RetrievedChunk("b", "Возврат на карту.", "method.md", (), 0.2),
    ]
    generator = AsyncMock()
    generator.generate.return_value = GeneratedAnswer(
        answer="Возврат на карту за 10 дней.", source_ids=["a", "b"], needs_escalation=False,
    )
    return embedder, search, generator


async def test_question_goes_through_embedding_search_and_generation(parts):
    embedder, search, generator = parts
    result = await RagAnswerer(*parts).answer_question("Когда возврат?")
    embedder.embed.assert_awaited_once_with(["Когда возврат?"])
    search.search.assert_awaited_once_with([1.0, 0.0, 0.0])
    generator.generate.assert_awaited_once_with("Когда возврат?", [
        {"id": "a", "text": "Возврат занимает 10 дней."},
        {"id": "b", "text": "Возврат на карту."},
    ])
    assert result.source_ids == ["a", "b"]
    assert result.reason is None
    assert result.retrieved_chunks[0].source_file == "refunds.md"
    assert result.timings.total_s >= result.timings.search_s >= 0
    assert result.model_dump(mode="json")["retrieved_chunks"][0]["headers"] == ["Возврат"]


async def test_empty_search_escalates_without_calling_llm(parts):
    parts[1].search.return_value = []
    result = await RagAnswerer(*parts).answer_question("Вопрос")
    assert result.answer is None and result.needs_escalation
    assert result.reason == "no_documents"
    assert result.timings.generation_s == 0
    parts[2].generate.assert_not_awaited()


async def test_insufficient_information_is_not_technical_failure(parts):
    parts[2].generate.return_value = GeneratedAnswer(answer=None, source_ids=[], needs_escalation=True)
    result = await RagAnswerer(*parts).answer_question("Вопрос")
    assert result.reason == "insufficient_information"
    assert len(result.retrieved_chunks) == 2


@pytest.mark.parametrize(("index", "method", "error", "stage"), [
    (0, "embed", EmbeddingServiceError("private"), "embedding"),
    (1, "search", RetrievalError("private"), "search"),
    (2, "generate", GenerationError("private"), "generation"),
])
async def test_failures_are_not_converted_to_no_documents(parts, index, method, error, stage):
    getattr(parts[index], method).side_effect = error
    with pytest.raises(RagError) as caught:
        await RagAnswerer(*parts).answer_question("Вопрос")
    assert caught.value.stage == stage
    assert "private" not in str(caught.value)
    assert caught.value.timings["total_s"] >= 0
    if index == 2:
        assert [c.id for c in caught.value.retrieved_chunks] == ["a", "b"]
    if index < 2:
        parts[2].generate.assert_not_awaited()


async def test_blank_question_does_not_call_services(parts):
    with pytest.raises(ValueError):
        await RagAnswerer(*parts).answer_question("  ")
    parts[0].embed.assert_not_awaited()


async def test_cancel_propagates_to_worker(parts):
    import asyncio
    parts[0].embed.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await RagAnswerer(*parts).answer_question("Вопрос")


async def test_embedder_must_return_one_vector(parts):
    parts[0].embed.return_value = []
    with pytest.raises(RagError) as caught:
        await RagAnswerer(*parts).answer_question("Вопрос")
    assert caught.value.stage == "embedding"
    parts[1].search.assert_not_awaited()
