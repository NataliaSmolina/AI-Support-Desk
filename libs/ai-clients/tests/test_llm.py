"""Проверка логики classify без запущенной модели: ответы сервера подменяются."""

import json

import httpx
import pytest

from ai_clients.llm import (
    Category,
    ClassificationError,
    LlmClassifier,
    Priority,
    Sentiment,
)


def completion(content: str | None) -> dict:
    return {
        "id": "test",
        "object": "chat.completion",
        "created": 0,
        "model": "test-model",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": content}}],
    }


def make_classifier(handler) -> LlmClassifier:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return LlmClassifier("http://llm.test/v1", "test-model", 5, http_client=client)


VALID = {"category": "billing", "priority": "critical", "sentiment": "negative", "wants_human": False}


async def test_valid_answer_parsed_and_request_has_schema():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=completion(json.dumps(VALID)))

    result = await make_classifier(handler).classify("Списали деньги дважды!")
    assert result.category is Category.BILLING
    assert result.priority is Priority.CRITICAL
    assert result.sentiment is Sentiment.NEGATIVE
    assert result.wants_human is False
    assert seen["response_format"]["type"] == "json_schema"
    assert seen["temperature"] == 0


async def test_empty_think_block_is_removed():
    content = "<think>\n\n</think>\n" + json.dumps(VALID)
    result = await make_classifier(lambda r: httpx.Response(200, json=completion(content))).classify("вопрос")
    assert result.category is Category.BILLING


async def test_non_empty_think_block_is_error():
    content = "<think>думаю...</think>" + json.dumps(VALID)
    with pytest.raises(ClassificationError, match="не по формату"):
        await make_classifier(lambda r: httpx.Response(200, json=completion(content))).classify("вопрос")


async def test_unknown_category_is_error():
    bad = {**VALID, "category": "refunds"}
    with pytest.raises(ClassificationError, match="не по формату"):
        await make_classifier(lambda r: httpx.Response(200, json=completion(json.dumps(bad)))).classify("вопрос")


async def test_empty_answer_is_error():
    with pytest.raises(ClassificationError, match="пустой"):
        await make_classifier(lambda r: httpx.Response(200, json=completion(""))).classify("вопрос")


async def test_server_error_is_raised():
    with pytest.raises(ClassificationError, match="ошибку"):
        await make_classifier(lambda r: httpx.Response(500, json={"error": "boom"})).classify("вопрос")


async def test_empty_question_rejected():
    with pytest.raises(ValueError):
        await make_classifier(lambda r: httpx.Response(200, json=completion("{}"))).classify("   ")
