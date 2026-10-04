"""LLM: определение темы вопроса (шаг 1). Работает с любым OpenAI-совместимым сервером: Ollama локально, vLLM на сервере."""

import json
from enum import StrEnum

import httpx
from openai import APIError, AsyncOpenAI
from pydantic import BaseModel, ValidationError


class Category(StrEnum):
    BILLING = "billing"      # оплата и возвраты
    DELIVERY = "delivery"    # доставка
    ACCOUNT = "account"      # аккаунт и вход
    OTHER = "other"          # всё остальное


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
        # Ollama и vLLM не проверяют ключ, но SDK требует непустое значение.
        self._client = AsyncOpenAI(
            base_url=base_url, api_key="not-used", timeout=timeout_s, max_retries=0, http_client=http_client
        )
        self._model = model

    async def classify(self, question: str) -> Classification:
        if not question.strip():
            raise ValueError("classify: пустой вопрос")

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                temperature=0,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    # /no_think выключает режим рассуждений у Qwen3: для классификации он не нужен и только замедляет ответ.
                    {"role": "user", "content": f"Вопрос клиента: {question}\n/no_think"},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "classification",
                        "schema": Classification.model_json_schema(),
                        "strict": True,
                    },
                },
            )
        except APIError as exc:
            raise ClassificationError(f"Сервер модели вернул ошибку: {exc!r}") from exc
        except httpx.HTTPError as exc:
            raise ClassificationError(f"Сервер модели недоступен: {exc!r}") from exc

        if not response.choices:
            raise ClassificationError("Модель вернула ответ без вариантов (choices пуст)")
        content = response.choices[0].message.content
        if not content:
            raise ClassificationError("Модель вернула пустой ответ")

        try:
            return Classification.model_validate_json(_strip_think(content))
        except ValidationError as exc:
            raise ClassificationError(f"Ответ модели не по формату: {content[:500]!r}\n{exc}") from exc

    async def aclose(self) -> None:
        await self._client.close()


def _strip_think(content: str) -> str:
    """Qwen3 с /no_think иногда оставляет пустой блок <think></think> перед JSON — убираем только его.
    Если блок не пустой, значит режим рассуждений не выключился: текст не трогаем,
    и проверка формата явно упадёт с ошибкой."""
    stripped = content.strip()
    if stripped.startswith("<think>"):
        end = stripped.find("</think>")
        if end != -1 and not stripped[len("<think>"):end].strip():
            return stripped[end + len("</think>"):].strip()
    return stripped


def classification_schema_json() -> str:
    """Схема ответа — для документации и проверки глазами."""
    return json.dumps(Classification.model_json_schema(), ensure_ascii=False, indent=2)
