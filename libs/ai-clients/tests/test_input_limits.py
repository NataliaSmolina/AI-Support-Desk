import json

import httpx
import pytest
from pydantic import ValidationError

from ai_clients.config import ModelInputLimits
from ai_clients.generator import GENERATION_PROMPT, GenerationError, LlmAnswerGenerator
from ai_clients.llm import SYSTEM_PROMPT, LlmClassifier
from ai_clients.ollama import LLMClient, LLMRequestError
from ai_clients.tei import EMBEDDING_DIM, EmbeddingServiceError, TeiEmbedder
from ai_clients.tokenization import InputTooLongError, ModelTokenizer, TokenizationError


@pytest.fixture
def counter(local_tokenizer_path):
    return ModelTokenizer(local_tokenizer_path, "local")


def limits(**overrides):
    return ModelInputLimits(_env_file=None, **overrides)


def messages(question, documents):
    chunks = [f"[Источник {d['id']}]\n{d['text']}" for d in documents]
    return [
        {"role": "system", "content": GENERATION_PROMPT},
        {"role": "user", "content": f"Вопрос: {question}\n\nДокументы:\n" + "\n\n".join(chunks)},
    ]


def response(ids):
    return httpx.Response(200, json={"message": {"content": json.dumps({
        "answer": "Ответ по источнику", "source_ids": ids, "needs_escalation": False,
    })}})


async def test_tei_boundary_counts_special_tokens_and_disables_server_truncation(counter):
    text = "Длинноесловонарусском языке"
    size = counter.count_text(text)
    assert size == 4  # Two words and CLS/SEP, not characters or bytes.
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=[[0.1] * EMBEDDING_DIM])
    async with httpx.AsyncClient(base_url="http://tei.test", transport=httpx.MockTransport(handler)) as http:
        embedder = TeiEmbedder("http://tei.test", 1, http, limits=limits(tei_max_input_tokens=size))
        await embedder.embed([text])
        assert seen == [{"inputs": [text], "truncate": False}]
        with pytest.raises(InputTooLongError) as exc:
            await embedder.embed([text + " ещё"])
        assert exc.value.tokens == size + 1
        assert exc.value.limit == size
        assert len(seen) == 1


async def test_tei_checks_whole_batch_before_embedding(counter):
    async with httpx.AsyncClient(base_url="http://tei.test", transport=httpx.MockTransport(
        lambda _: pytest.fail("Oversized batch must not reach /embed"),
    )) as http:
        embedder = TeiEmbedder("http://tei.test", 1, http, limits=limits(tei_max_input_tokens=3))
        with pytest.raises(InputTooLongError, match="текст №2"):
            await embedder.embed(["допустимо", "слишком большой"])


@pytest.mark.parametrize("provider", ["ollama", "openai"])
async def test_classifier_checks_full_prompt_output_reserve_and_schema(counter, provider):
    question = "Один"
    chat = [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Вопрос клиента: {question}"}]
    from ai_clients.llm import Classification
    schema = Classification.model_json_schema()
    size = counter.count_messages(chat, schema=schema if provider == "openai" else None)
    assert size > counter.count_text(question)
    seen = []
    result = dict(category="other", priority="low", sentiment="calm", wants_human=False)
    def handler(request):
        payload = json.loads(request.content)
        seen.append(payload)
        if provider == "ollama":
            assert payload["options"]["num_ctx"] == size + 100 + 17
            return httpx.Response(200, json={"message": {"content": json.dumps(result)}})
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": json.dumps(result)}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = LLMClient("http://llm.test/v1", "test", 1, http, provider=provider,
                           limits=limits(llm_context_tokens=size + 100 + 17, llm_context_reserve_tokens=17))
        classifier = LlmClassifier("http://llm.test/v1", "test", 1, llm_client=client)
        try:
            assert (await classifier.classify(question)).category == "other"
            with pytest.raises(InputTooLongError) as exc:
                await classifier.classify(question + " ещё")
            assert exc.value.tokens == size + 1
            assert exc.value.limit == size
            assert len(seen) == 1
        finally:
            await client.aclose()


async def test_generator_keeps_whole_documents_and_original_ids_at_boundary(counter):
    question = "Вопрос"
    first = {"id": "original-hash-1", "text": "Первый факт."}
    second = {"id": "original-hash-2", "text": "Второй факт."}
    size = counter.count_messages(messages(question, [first]))
    seen = []
    def handler(request):
        payload = json.loads(request.content)
        seen.append(payload)
        assert payload["messages"] == messages(question, [first])
        assert payload["options"]["num_predict"] == 350
        return response([first["id"]])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = LLMClient("http://llm.test", "test", 1, http,
                           limits=limits(llm_context_tokens=size + 350 + 11, llm_context_reserve_tokens=11))
        generator = LlmAnswerGenerator("http://llm.test", "test", 1, llm_client=client)
        result = await generator.generate(question, [first, second])
        assert result.source_ids == [first["id"]]
        assert len(seen) == 1


async def test_generator_skips_large_document_and_tries_later_candidates(counter):
    small = {"id": "small", "text": "Короткий факт"}
    size = counter.count_messages(messages("Вопрос", [small]))
    def handler(request):
        assert json.loads(request.content)["messages"] == messages("Вопрос", [small])
        return response(["small"])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = LLMClient("http://llm.test", "test", 1, http,
                           limits=limits(llm_context_tokens=size + 350, llm_context_reserve_tokens=0))
        result = await LlmAnswerGenerator("http://llm.test", "test", 1, llm_client=client).generate(
            "Вопрос", [{"id": "large", "text": "длинный " * 10_000}, small],
        )
        assert result.source_ids == ["small"]


async def test_generator_rejects_sources_from_excluded_document(counter):
    small = {"id": "selected", "text": "Факт"}
    size = counter.count_messages(messages("Вопрос", [small]))
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response(["excluded"]))) as http:
        client = LLMClient("http://llm.test", "test", 1, http,
                           limits=limits(llm_context_tokens=size + 350, llm_context_reserve_tokens=0))
        generator = LlmAnswerGenerator("http://llm.test", "test", 1, llm_client=client)
        with pytest.raises(GenerationError, match="источник"):
            await generator.generate("Вопрос", [small, {"id": "excluded", "text": "длинный " * 10_000}])


async def test_generator_question_overflow_and_no_fitting_documents_do_not_call_llm(counter):
    doc = {"id": "real", "text": "огромный " * 10_000}
    size = counter.count_messages(messages("Вопрос", []))
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail("Must not call LLM"))) as http:
        client = LLMClient("http://llm.test", "test", 1, http,
                           limits=limits(llm_context_tokens=size + 350, llm_context_reserve_tokens=0))
        generator = LlmAnswerGenerator("http://llm.test", "test", 1, llm_client=client)
        with pytest.raises(InputTooLongError, match="ни один документ"):
            await generator.generate("Вопрос", [doc])
        with pytest.raises(InputTooLongError, match="LLM: вход"):
            await generator.generate("Вопрос ещё", [doc])


async def test_invalid_document_is_not_silently_dropped_by_packing(counter):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail("Must not call LLM"))) as http:
        client = LLMClient("http://llm.test", "test", 1, http)
        generator = LlmAnswerGenerator("http://llm.test", "test", 1, llm_client=client)
        with pytest.raises(ValueError, match="уникальные"):
            await generator.generate("Вопрос", [{"id": "x", "text": "Факт"}, {"id": "x", "text": "Ещё факт"}])


def test_missing_tokenizer_does_not_fallback_to_character_estimation(tmp_path):
    with pytest.raises(TokenizationError, match="--download"):
        ModelTokenizer(str(tmp_path / "missing"), "local").count_text("Приватный текст")


def test_chat_count_includes_role_markers_and_schema(counter):
    chat = [{"role": "system", "content": "Правила"}, {"role": "user", "content": "Вопрос"}]
    plain = counter.count_messages(chat)
    assert plain > sum(counter.count_text(m["content"]) for m in chat)
    assert counter.count_messages(chat, schema={"type": "object"}) > plain


def test_invalid_limits_rejected():
    with pytest.raises(ValidationError):
        limits(tei_max_input_tokens=0)
    with pytest.raises(ValidationError):
        limits(llm_context_tokens=100, llm_context_reserve_tokens=100)


async def test_all_fitting_documents_preserve_order_and_full_text():
    docs = [{"id": "hash-1", "text": "Первый полный фрагмент."},
            {"id": "hash-2", "text": "Второй полный фрагмент."}]
    def handler(request):
        assert json.loads(request.content)["messages"] == messages("Вопрос", docs)
        return response([d["id"] for d in docs])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = LLMClient("http://llm.test", "test", 1, http)
        result = await LlmAnswerGenerator("http://llm.test", "test", 1, llm_client=client).generate("Вопрос", docs)
        assert result.source_ids == ["hash-1", "hash-2"]


@pytest.mark.parametrize("kind", ["tei", "llm"])
async def test_unavailable_tokenizer_is_service_error_without_inference(kind):
    class Unavailable:
        def count_text(self, *args, **kwargs):
            raise TokenizationError("Токенизатор не загружен; выполните --download")
        count_messages = count_text
    async with httpx.AsyncClient(base_url="http://model.test", transport=httpx.MockTransport(
        lambda _: pytest.fail("No inference without token counts"),
    )) as http:
        if kind == "tei":
            with pytest.raises(EmbeddingServiceError, match="--download"):
                await TeiEmbedder("http://model.test", 1, http, token_counter=Unavailable()).embed(["Текст"])
        else:
            with pytest.raises(LLMRequestError, match="--download"):
                await LLMClient("http://model.test", "test", 1, http, token_counter=Unavailable()).chat(
                    [{"role": "user", "content": "Вопрос"}],
                )


async def test_shared_tokenizer_counts_concurrent_requests_consistently(counter):
    import asyncio
    texts = ["Русский текст " * (i + 1) for i in range(16)]
    expected = [counter.count_text(t) for t in texts]
    actual = await asyncio.gather(*(asyncio.to_thread(counter.count_text, t) for t in texts))
    assert actual == expected


def test_cached_hub_tokenizer_is_opened_as_local_directory_without_network(monkeypatch, local_tokenizer_path):
    import huggingface_hub
    import requests
    calls = []
    def cached_snapshot(source, **kwargs):
        calls.append((source, kwargs))
        assert kwargs['local_files_only'] is True
        assert 'tokenizer.json' in kwargs['allow_patterns']
        assert all('safetensors' not in pattern for pattern in kwargs['allow_patterns'])
        return local_tokenizer_path
    monkeypatch.setattr(huggingface_hub, 'snapshot_download', cached_snapshot)
    monkeypatch.setattr(requests.sessions.Session, 'request', lambda *a, **kw: pytest.fail('Offline lookup accessed network'))
    counter = ModelTokenizer('organisation/cached-tokenizer', 'pinned-revision')
    assert counter.count_text('Пример') == 3
    assert calls[0][0] == 'organisation/cached-tokenizer'
