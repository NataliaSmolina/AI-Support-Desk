"""Проверка шага 1 на настоящей модели.

Прогоняет вопросы из evals/data/classify_questions.json, сравнивает ответ модели
с ожидаемым и пишет таблицу в docs/experiments/02-classify-results.md.

Запуск (из корня проекта): uv run python evals/check_classify.py
"""

import asyncio
import json
import platform
import sys
import time
from datetime import datetime
from pathlib import Path

from ai_clients.llm import ClassificationError, LlmClassifier
from ai_clients.config import AISettings

QUESTIONS = Path("evals/data/classify_questions.json")
RESULTS = Path("docs/experiments/02-classify-results.md")
FIELDS = ("category", "priority", "sentiment", "wants_human")


async def main() -> int:
    settings = AISettings()
    cases = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    classifier = LlmClassifier(settings.llm_base_url, settings.llm_model, settings.request_timeout_s)

    rows, times, errors = [], [], 0
    correct = {f: 0 for f in FIELDS}
    try:
        await classifier.classify("прогрев")  # первый запрос медленнее: модель загружается в память
        for case in cases:
            started = time.perf_counter()
            try:
                got = (await classifier.classify(case["question"])).model_dump(mode="json")
            except ClassificationError as exc:
                errors += 1
                rows.append(f"| {case['question']} | ОШИБКА: {str(exc).splitlines()[0][:120]} | — | — |")
                print(f"ОШИБКА на «{case['question']}»: {exc}", file=sys.stderr)
                continue
            elapsed = time.perf_counter() - started
            times.append(elapsed)

            expected = case["expected"]
            diffs = []
            for f in FIELDS:
                if got[f] == expected[f]:
                    correct[f] += 1
                else:
                    diffs.append(f"{f}: ждали {expected[f]}, получили {got[f]}")
            verdict = "верно" if not diffs else "; ".join(diffs)
            rows.append(f"| {case['question']} | {json.dumps(got, ensure_ascii=False)} | {verdict} | {elapsed:.1f} с |")
    finally:
        await classifier.aclose()

    total = len(cases)
    avg = sum(times) / len(times) if times else float("nan")
    lines = [
        "# Результаты проверки шага 1 (определение темы)",
        "",
        f"- Дата: {datetime.now():%Y-%m-%d %H:%M}",
        f"- Машина: {platform.machine()}, {platform.platform()}",
        f"- Модель: {settings.llm_model} ({settings.llm_base_url})",
        f"- Вопросов: {total}, ошибок формата или связи: {errors}",
        f"- Среднее время ответа: {avg:.1f} с",
        "",
        "| Поле | Верно |",
        "|---|---|",
        *[f"| {f} | {correct[f]} из {total} |" for f in FIELDS],
        "",
        "| Вопрос | Ответ модели | Сравнение с ожидаемым | Время |",
        "|---|---|---|---|",
        *rows,
        "",
    ]
    RESULTS.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"Записано в {RESULTS}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
