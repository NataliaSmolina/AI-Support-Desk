"""LLM: классификация обращений. Ollama локально через /api/chat, vLLM через OpenAI API."""

import json
from enum import StrEnum

import httpx
from openai import APIError, AsyncOpenAI
from pydantic import BaseModel, ValidationError


class Category(StrEnum):
    BILLING = "billing"
    DELIVERY = "delivery"
    ACCOUNT = "account"
    OTHER = "other"


class Priority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    CRITICAL = "critical"


class Sentiment(StrEnum):
    CALM = "calm"
    NEGATIVE = "negative"


class Classification(BaseModel):
    category: Category
    priority: Priority
    sentiment: Sentiment
    wants_human: bool


SYSTEM_PROMPT = """Ты классификатор обращений в службу поддержки интернет-магазина.
Определи для вопроса клиента:

category — тема:
  billing  — оплата, списания, возврат денег, чеки
  delivery — доставка, сроки, статус и местонахождение заказа
  account  — вход, пароль, регистрация, личные данные в профиле
  other    — всё, что не подходит под темы выше

priority — срочность:
  critical — деньги списаны ошибочно или дважды, угроза безопасности аккаунта, клиент пишет, что дело срочное
  normal   — обычный вопрос
  low      — общий вопрос без проблемы

sentiment — настроение:
  negative — клиент раздражён, жалуется, пишет капслоком, угрожает
  calm     — в остальных случаях

wants_human — true, если клиент прямо просит оператора или живого человека, иначе false.

Верни только JSON по заданной схеме, без пояснений."""


class ClassificationError(RuntimeError):
    """Модель не ответила или ответила не по формату."""


class LlmClassifier:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_s: float,
        http_client: httpx.AsyncClient | None = None,
    ):
        self._model = model
        # В текущем проекте порт 11500 зарезервирован для локальной Ollama.
        self._is_ollama = "11500" in base_url
        self._client: AsyncOpenAI | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._owns_http_client = False

        if self._is_ollama:
            self._owns_http_client = http_client is None
            self._http_client = http_client if http_client is not None else httpx.AsyncClient(timeout=timeout_s)
            self._ollama_url = base_url.rstrip("/").removesuffix("/v1")
        else:
            self._client = AsyncOpenAI(
                base_url=base_url,
                api_key="not-used",
                timeout=timeout_s,
                max_retries=0,
                http_client=http_client,
            )

    async def classify(self, question: str) -> Classification:
        if not question.strip():
            raise ValueError("classify: пустой вопрос")

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Вопрос клиента: {question}"},
        ]
        schema = Classification.model_json_schema()

        try:
            if self._is_ollama:
                assert self._http_client is not None
                response = await self._http_client.post(
                    f"{self._ollama_url}/api/chat",
                    json={
                        "model": self._model,
                        "messages": messages,
                        "stream": False,
                        "think": False,
                        "format": "json",
                        "options": {"temperature": 0, "num_predict": 100},
                    },
                )
                response.raise_for_status()
                data = response.json()
                content = data.get("message", {}).get("content")
            else:
                assert self._client is not None
                response = await self._client.chat.completions.create(
                    model=self._model,
                    temperature=0,
                    messages=messages,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "classification",
                            "schema": schema,
                            "strict": True,
                        },
                    },
                )
                if not response.choices:
                    raise ClassificationError("Модель вернула ответ без вариантов (choices пуст)")
                content = response.choices[0].message.content
        except (APIError, httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise ClassificationError(f"Ошибка обращения к LLM: {exc!r}") from exc

        if not content:
            raise ClassificationError("Модель вернула пустой ответ")

        try:
            return Classification.model_validate_json(_strip_think(content))
        except ValidationError as exc:
            raise ClassificationError(f"Ответ модели не по формату: {content[:500]!r}\n{exc}") from exc

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.close()
        if self._http_client is not None and self._owns_http_client:
            await self._http_client.aclose()


def _strip_think(content: str) -> str:
    """Убираем только пустой блок <think></think> перед JSON."""
    stripped = content.strip()
    if stripped.startswith("<think>"):
        end = stripped.find("</think>")
        if end != -1 and not stripped[len("<think>"):end].strip():
            return stripped[end + len("</think>"):].strip()
    return stripped


def classification_schema_json() -> str:
    """Схема ответа для документации."""
    return json.dumps(Classification.model_json_schema(), ensure_ascii=False, indent=2)
