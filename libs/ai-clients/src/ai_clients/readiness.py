"""Быстрая проверка API и наличия модели без загрузки весов и генерации."""
import asyncio
import sys

import httpx

from .config import AISettings


class LLMReadinessError(RuntimeError):
    """Сервер недоступен, ответ некорректен или модель не установлена."""


async def check_llm_ready(settings: AISettings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
    base = settings.llm_base_url.rstrip("/")
    ollama = settings.llm_provider == "ollama"
    url = f"{base.removesuffix('/v1')}/api/tags" if ollama else f"{base}/models"
    try:
        async with httpx.AsyncClient(timeout=settings.llm_health_timeout_s, transport=transport) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.TimeoutException:
        raise LLMReadinessError("Истёк таймаут проверки LLM; проверьте готовность сервера.") from None
    except httpx.HTTPStatusError as exc:
        raise LLMReadinessError(
            f"API LLM вернул HTTP {exc.response.status_code}; проверьте LLM_PROVIDER и LLM_BASE_URL."
        ) from None
    except httpx.RequestError:
        raise LLMReadinessError(
            "Не удалось подключиться к LLM; запустите сервер и проверьте LLM_BASE_URL."
        ) from None
    try:
        payload = response.json()
        rows = payload["models" if ollama else "data"]
        key = "name" if ollama else "id"
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) or not isinstance(row.get(key), str) for row in rows
        ):
            raise ValueError
        names = {row[key] for row in rows}
    except (ValueError, KeyError, TypeError):
        raise LLMReadinessError("Некорректный список моделей; проверьте LLM_PROVIDER и API сервера.") from None
    model = settings.llm_model
    # Ollama использует latest при отсутствии тега; имена других провайдеров точные.
    if ollama and ":" not in model.rsplit("/", 1)[-1]:
        model += ":latest"
    if model not in names:
        hint = " Загрузите её через ollama pull на выбранном сервере." if ollama else ""
        raise LLMReadinessError(f"Модель {settings.llm_model!r} отсутствует на сервере.{hint}")


async def main() -> int:
    settings = AISettings()
    try:
        await check_llm_ready(settings)
    except LLMReadinessError as exc:
        print(f"LLM не готов: {exc}", file=sys.stderr)
        return 1
    print(f"API доступен, модель {settings.llm_model!r} найдена (провайдер: {settings.llm_provider}).")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
