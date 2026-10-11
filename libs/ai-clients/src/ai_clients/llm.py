"""Классификация обращений через общую LLM-клиентскую библиотеку."""
import json
from enum import StrEnum

import httpx
from pydantic import BaseModel, ValidationError

from .ollama import LLMClient, LLMRequestError


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
    def __init__(self, base_url: str, model: str, timeout_s: float,
                 http_client: httpx.AsyncClient | None = None, *,
                 provider: str | None = None, llm_client: LLMClient | None = None):
        self._owns_client = llm_client is None
        self._client = llm_client or LLMClient(base_url, model, timeout_s, http_client, provider)

    async def classify(self, question: str) -> Classification:
        if not question.strip():
            raise ValueError("classify: пустой вопрос")
        try:
            content = await self._client.chat(
                [{"role": "system", "content": SYSTEM_PROMPT},
                 {"role": "user", "content": f"Вопрос клиента: {question}"}],
                schema=Classification.model_json_schema(), schema_name="classification",
                max_tokens=100,
            )
        except LLMRequestError as exc:
            raise ClassificationError(str(exc)) from exc
        try:
            return Classification.model_validate_json(_strip_think(content))
        except ValidationError as exc:
            raise ClassificationError(f"Ответ модели не по формату: {content[:500]!r}\n{exc}") from exc

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _strip_think(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("<think>"):
        end = stripped.find("</think>")
        if end != -1 and not stripped[len("<think>"):end].strip():
            return stripped[end + len("</think>"):].strip()
    return stripped


def classification_schema_json() -> str:
    return json.dumps(Classification.model_json_schema(), ensure_ascii=False, indent=2)
