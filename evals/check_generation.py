"""Проверка генерации ответов через Qwen3:8B в Docker."""

import asyncio
import time

from ai_clients.config import AISettings
from ai_clients.generator import LlmAnswerGenerator


TEST_CASES = [
    {
        "name": "Ответ есть в документах",
        "question": "Когда мне вернут деньги за отменённый заказ?",
        "documents": [
            {
                "id": "refund-policy",
                "text": (
                    "После отмены заказа деньги возвращаются "
                    "в течение 10 рабочих дней на исходный способ оплаты."
                ),
            }
        ],
    },
    {
        "name": "Информации недостаточно",
        "question": "Можно ли оплатить заказ криптовалютой?",
        "documents": [
            {
                "id": "payment-policy",
                "text": (
                    "Магазин принимает банковские карты "
                    "Visa и Mastercard."
                ),
            }
        ],
    },
    {
        "name": "Несколько документов",
        "question": "Сколько стоит доставка в Казань и сколько она занимает?",
        "documents": [
            {
                "id": "delivery-price",
                "text": "Стоимость доставки в Казань составляет 350 рублей.",
            },
            {
                "id": "delivery-time",
                "text": "Срок доставки в Казань составляет 3–5 рабочих дней.",
            },
        ],
    },
]


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