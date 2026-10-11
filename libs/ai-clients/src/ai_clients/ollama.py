"""Общий транспорт для Ollama в Docker и OpenAI-совместимых серверов."""
from typing import Any

import httpx
from openai import APIError, AsyncOpenAI


class LLMRequestError(RuntimeError):
    """Не удалось получить ответ модели."""


class LLMClient:
    def __init__(self, base_url: str, model: str, timeout_s: float,
                 http_client: httpx.AsyncClient | None = None,
                 provider: str | None = None):
        self.model = model
        # Обратная совместимость с существующей настройкой проекта.
        self.provider = provider or ("ollama" if "11500" in base_url else "openai")
        if self.provider not in {"ollama", "openai"}:
            raise ValueError("provider должен быть 'ollama' или 'openai'")
        self._owns_http_client = self.provider == "ollama" and http_client is None
        self._http_client = None
        self._openai = None
        if self.provider == "ollama":
            self._http_client = http_client if http_client is not None else httpx.AsyncClient(timeout=timeout_s)
            self._base_url = base_url.rstrip("/").removesuffix("/v1")
        else:
            self._openai = AsyncOpenAI(base_url=base_url, api_key="not-used", timeout=timeout_s,
                                       max_retries=0, http_client=http_client)

    async def chat(self, messages: list[dict[str, str]], *, schema: dict[str, Any] | None = None,
                   schema_name: str = "response", max_tokens: int = 100) -> str:
        try:
            if self.provider == "ollama":
                assert self._http_client is not None
                response = await self._http_client.post(
                    f"{self._base_url}/api/chat",
                    json={"model": self.model, "messages": messages, "stream": False,
                          "think": False, "format": "json" if schema is not None else "json",
                          "options": {"temperature": 0, "num_predict": max_tokens}},
                )
                response.raise_for_status()
                content = response.json().get("message", {}).get("content")
            else:
                assert self._openai is not None
                kwargs: dict[str, Any] = {"model": self.model, "temperature": 0,
                                          "messages": messages, "max_tokens": max_tokens}
                if schema is not None:
                    kwargs["response_format"] = {"type": "json_schema", "json_schema": {
                        "name": schema_name, "schema": schema, "strict": True}}
                else:
                    kwargs["response_format"] = {"type": "json_object"}
                response = await self._openai.chat.completions.create(**kwargs)
                if not response.choices:
                    raise LLMRequestError("Модель вернула ответ без вариантов")
                content = response.choices[0].message.content
        except (APIError, httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise LLMRequestError(f"Сервер модели вернул ошибку: {exc!r}") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMRequestError("Модель вернула пустой ответ")
        return content

    async def aclose(self) -> None:
        if self._openai is not None:
            await self._openai.close()
        if self._owns_http_client and self._http_client is not None:
            await self._http_client.aclose()
