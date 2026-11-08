import json

import httpx
import pytest
from pydantic import ValidationError

from ai_clients.config import AISettings
from ai_clients.ollama import LLMClient
from ai_clients.readiness import LLMReadinessError, check_llm_ready


def settings(**overrides):
    return AISettings(_env_file=None, llm_provider="ollama", llm_model="qwen3:8b", **overrides)


@pytest.mark.parametrize("base", ["http://llm.test:11434", "http://llm.test:11500/v1/"])
async def test_ollama_on_any_port(base):
    def handler(request):
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "qwen3:8b"}]})
    await check_llm_ready(settings(llm_base_url=base), transport=httpx.MockTransport(handler))


async def test_openai_models_on_ollama_port():
    config = AISettings(_env_file=None, llm_provider="openai", llm_model="test",
                        llm_base_url="http://llm.test:11500/v1")
    def handler(request):
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "test"}]})
    await check_llm_ready(config, transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("payload", [{}, {"models": None}, {"models": [1]},
                                       {"models": [{"name": 5}]}, []])
async def test_invalid_model_list(payload):
    with pytest.raises(LLMReadinessError, match="Некорректный список"):
        await check_llm_ready(settings(), transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=payload)))


async def test_missing_model():
    with pytest.raises(LLMReadinessError, match="отсутствует.*ollama pull"):
        await check_llm_ready(settings(), transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"models": []})))


async def test_latest_alias():
    config = settings().model_copy(update={"llm_model": "qwen3"})
    await check_llm_ready(config, transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"models": [{"name": "qwen3:latest"}]})))


@pytest.mark.parametrize(("error", "message"), [
    (httpx.ConnectError, "Не удалось подключиться"),
    (httpx.ReadTimeout, "таймаут"),
])
async def test_connection_errors(error, message):
    def handler(request):
        raise error("internal details", request=request)
    with pytest.raises(LLMReadinessError, match=message):
        await check_llm_ready(settings(), transport=httpx.MockTransport(handler))


async def test_http_error():
    with pytest.raises(LLMReadinessError, match="HTTP 404"):
        await check_llm_ready(settings(), transport=httpx.MockTransport(
            lambda _: httpx.Response(404, text="private details")))


async def test_invalid_json():
    with pytest.raises(LLMReadinessError, match="Некорректный список"):
        await check_llm_ready(settings(), transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="not json")))


async def test_chat_provider_is_not_inferred_from_port():
    def handler(request):
        assert request.url.path == "/api/chat"
        assert json.loads(request.content)["model"] == "test"
        return httpx.Response(200, json={"message": {"content": "{}"}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = LLMClient("http://llm.test:1234/v1", "test", 5, http)
        try:
            assert await client.chat([]) == "{}"
        finally:
            await client.aclose()
        assert not http.is_closed


def test_invalid_provider_and_timeout():
    with pytest.raises(ValidationError):
        AISettings(_env_file=None, llm_provider="typo")
    with pytest.raises(ValidationError):
        settings(llm_health_timeout_s=0)


def test_provider_from_environment(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    assert AISettings(_env_file=None).llm_provider == "openai"
