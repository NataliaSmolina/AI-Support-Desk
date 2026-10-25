"""Генерация ответов без запуска Docker: подмена HTTP через MockTransport."""
import json

import httpx
import pytest

from ai_clients.generator import GenerationError, LlmAnswerGenerator


def generator(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return LlmAnswerGenerator("http://127.0.0.1:11500/v1", "test", 5, client)


async def test_generates_answer_from_documents():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": json.dumps({
            "answer": "Деньги вернут в течение 10 дней.", "source_ids": ["refund"],
            "needs_escalation": False})}})

    result = await generator(handler).generate("Когда вернут деньги?", [
        {"id": "refund", "text": "Возврат денег — в течение 10 дней."}])
    assert result.source_ids == ["refund"]
    assert seen["think"] is False
    assert seen["format"] == "json"
    assert "refund" in seen["messages"][1]["content"]


async def test_no_documents_requires_escalation():
    result = await generator(lambda _: pytest.fail("Запрос не должен выполняться")).generate("Вопрос", [])
    assert result.answer is None
    assert result.needs_escalation


async def test_unknown_source_rejected():
    def handler(_):
        return httpx.Response(200, json={"message": {"content": json.dumps({
            "answer": "Ответ", "source_ids": ["invented"], "needs_escalation": False})}})
    with pytest.raises(GenerationError, match="источник"):
        await generator(handler).generate("Вопрос", [{"id": "real", "text": "Текст"}])


@pytest.mark.parametrize(
    ("source_ids", "needs_escalation"),
    [([], False), (["real"], True)],
)
async def test_answer_with_text_requires_sources_without_escalation(source_ids, needs_escalation):
    def handler(_):
        return httpx.Response(200, json={"message": {"content": json.dumps({
            "answer": "Ответ", "source_ids": source_ids,
            "needs_escalation": needs_escalation})}})

    with pytest.raises(GenerationError, match="должен содержать источники"):
        await generator(handler).generate("Вопрос", [{"id": "real", "text": "Текст"}])


async def test_invalid_json_rejected():
    raw_answer = "oops: private question text"
    with pytest.raises(GenerationError, match="не по формату") as exc_info:
        await generator(lambda _: httpx.Response(200, json={"message": {"content": raw_answer}})).generate(
            "Вопрос", [{"id": "real", "text": "Текст"}])
    assert raw_answer not in str(exc_info.value)
