"""Smoke-test the TEI embedding contract against a running server.

Run from the repository root: uv run python evals/check_tei_contract.py
The measured result is written to docs/experiments/03-tei-embedding-api-contract-live-results.md.
"""

import asyncio
import platform
import sys
import time
from datetime import datetime
from pathlib import Path

from ai_clients.config import AISettings
from ai_clients.tei import EMBEDDING_DIM, TeiEmbedder

TEXTS = [
    "Проверка эмбеддинга для вопроса о возврате заказа.",
    "Проверка эмбеддинга для вопроса о сроках доставки.",
]
RESULTS = Path("docs/experiments/03-tei-embedding-api-contract-live-results.md")


async def main() -> int:
    settings = AISettings()
    embedder = TeiEmbedder(settings.tei_embed_url, settings.request_timeout_s)
    try:
        started = time.perf_counter()
        vectors = await embedder.embed(TEXTS)
        batch_ms = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        single_vector = await embedder.embed([TEXTS[0]])
        single_ms = (time.perf_counter() - started) * 1000
    finally:
        await embedder.aclose()

    if len(vectors) != len(TEXTS):
        raise RuntimeError(f"TEI вернул {len(vectors)} векторов на {len(TEXTS)} текстов")
    if any(len(vector) != EMBEDDING_DIM for vector in vectors + single_vector):
        raise RuntimeError(f"Ожидались векторы размерности {EMBEDDING_DIM}")
    if any(not isinstance(value, float) for vector in vectors + single_vector for value in vector):
        raise RuntimeError("Клиент вернул значения векторов не типа float")

    lines = [
        "# Результаты эксперимента 3: контракт API эмбеддингов TEI",
        "",
        f"- Дата: {datetime.now():%Y-%m-%d %H:%M}",
        f"- Машина: {platform.machine()}, {platform.platform()}",
        f"- Адрес TEI: {settings.tei_embed_url}",
        "- Модель: BAAI/bge-m3 (согласно `infra/tei/compose.yml`)",
        f"- Текстов в пакетном запросе: {len(TEXTS)}",
        f"- Векторов получено: {len(vectors)}",
        f"- Размерность каждого вектора: {len(vectors[0])} (ожидалось {EMBEDDING_DIM})",
        f"- Время пакетного запроса: {batch_ms:.0f} мс",
        f"- Время запроса одного текста: {single_ms:.0f} мс",
        "",
        "| Проверка | Результат |",
        "|---|---|",
        "| Один вектор возвращён на каждый текст | ПРОЙДЕНА |",
        "| Размерность вектора соответствует модели | ПРОЙДЕНА |",
        "| Значения векторов представлены типом float | ПРОЙДЕНА |",
        "| Одиночный запрос также обработан | ПРОЙДЕНА |",
        "",
        "**Итог:** контракт TEI проверен на работающем сервере.",
        "",
        "Проверки некорректного JSON, структуры ответа, размерности и значений "
        "вектора выполняются отдельно в `libs/ai-clients/tests/test_tei.py` с MockTransport.",
        "",
    ]
    RESULTS.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"Записано в {RESULTS}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
