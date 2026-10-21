"""Проверка генерации ответов через Qwen3:8B в Docker."""

import asyncio
import json
import time
from pathlib import Path

from ai_clients.config import AISettings
from ai_clients.generator import LlmAnswerGenerator

TEST_CASES = json.loads(
    Path("evals/data/generation_cases.json").read_text(encoding="utf-8")
)


async def main():
    settings = AISettings()

    generator = LlmAnswerGenerator(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout_s=settings.request_timeout_s,
    )

    try:
        for index, case in enumerate(TEST_CASES, start=1):
            print(f"\n{'=' * 60}", flush=True)
            print(f"Тест {index}: {case['name']}", flush=True)
            print(f"Вопрос: {case['question']}", flush=True)

            start = time.perf_counter()

            try:
                result = await generator.generate(
                    question=case["question"],
                    documents=case["documents"],
                )

                elapsed = time.perf_counter() - start

                print(f"\nОтвет: {result.answer}", flush=True)
                print(f"Источники: {result.source_ids}", flush=True)
                print(f"Эскалация: {result.needs_escalation}", flush=True)
                print(f"Время: {elapsed:.1f} с", flush=True)

            except Exception as exc:
                print(f"\nОшибка: {type(exc).__name__}: {exc}", flush=True)

    finally:
        await generator.aclose()


if __name__ == "__main__":
    asyncio.run(main())