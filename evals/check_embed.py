"""Проверка шага 2 на настоящем TEI.

Переводит три текста в числа и проверяет, что два текста про возврат денег
ближе друг к другу, чем текст про возврат и текст про доставку.
Результат пишет в docs/experiments/01-tei-embed-results.md.

Запуск (из корня проекта): uv run python evals/check_embed.py
"""

import asyncio
import platform
import sys
import time
from datetime import datetime
from pathlib import Path

from ai_clients.config import AISettings
from ai_clients.tei import EMBEDDING_DIM, TeiEmbedder, similarity

TEXTS = [
    "Когда вернутся деньги за отменённый заказ?",
    "Сколько дней идёт возврат средств на карту?",
    "Где сейчас мой заказ?",
]
RESULTS = Path("docs/experiments/01-tei-embed-results.md")


async def main() -> int:
    settings = AISettings()
    embedder = TeiEmbedder(settings.tei_embed_url, settings.request_timeout_s)
    try:
        await embedder.embed(["прогрев"])  # первый запрос медленнее: модель загружается в память

        started = time.perf_counter()
        vectors = await embedder.embed(TEXTS)
        batch_ms = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        await embedder.embed([TEXTS[0]])
        single_ms = (time.perf_counter() - started) * 1000
    finally:
        await embedder.aclose()

    refund_refund = similarity(vectors[0], vectors[1])
    refund_delivery = similarity(vectors[0], vectors[2])
    passed = refund_refund > refund_delivery

    lines = [
        "# Результаты проверки шага 2 (TEI, bge-m3)",
        "",
        f"- Дата: {datetime.now():%Y-%m-%d %H:%M}",
        f"- Машина: {platform.machine()}, {platform.platform()}",
        f"- Адрес TEI: {settings.tei_embed_url}",
        f"- Чисел на текст: {len(vectors[0])} (ожидалось {EMBEDDING_DIM})",
        f"- Время на 1 текст: {single_ms:.0f} мс",
        f"- Время на 3 текста одним запросом: {batch_ms:.0f} мс",
        "",
        "| Пара текстов | Близость |",
        "|---|---|",
        f"| «{TEXTS[0]}» — «{TEXTS[1]}» | {refund_refund:.3f} |",
        f"| «{TEXTS[0]}» — «{TEXTS[2]}» | {refund_delivery:.3f} |",
        "",
        f"**Итог:** {'тексты про возврат ближе друг к другу — ПРОВЕРКА ПРОЙДЕНА' if passed else 'ПРОВЕРКА НЕ ПРОЙДЕНА: текст про доставку оказался ближе'}",
        "",
    ]
    RESULTS.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"Записано в {RESULTS}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
