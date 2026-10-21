"""Evaluate classification and grounded generation against the configured LLM.

Run from the repository root:
    uv run python evals/check_llm_baseline.py

To evaluate an OpenAI-compatible server with the same cases:
    uv run python evals/check_llm_baseline.py --provider openai --output docs/experiments/04-llm-baseline-openai-results.md
"""

import argparse
import asyncio
import json
import platform
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from ai_clients.config import AISettings
from ai_clients.generator import GenerationError, LlmAnswerGenerator
from ai_clients.llm import ClassificationError, LlmClassifier

CLASSIFICATION_CASES = Path("evals/data/classify_questions.json")
GENERATION_CASES = Path("evals/data/generation_cases.json")
DEFAULT_RESULTS = Path("docs/experiments/04-llm-baseline-results.md")
CLASSIFICATION_FIELDS = ("category", "priority", "sentiment", "wants_human")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate LLM baseline quality and latency.")
    parser.add_argument(
        "--provider",
        choices=("ollama", "openai"),
        default="ollama",
        help="LLM API transport (default: ollama).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_RESULTS,
        help=f"Markdown report path (default: {DEFAULT_RESULTS}).",
    )
    return parser.parse_args()


def classification_mismatches(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    return [
        f"{field}: ожидалось {expected[field]!r}, получено {actual[field]!r}"
        for field in CLASSIFICATION_FIELDS
        if actual[field] != expected[field]
    ]


def generation_mismatches(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    failures = []
    answer_present = actual["answer"] is not None
    if answer_present != expected["answer_present"]:
        failures.append(f"наличие ответа: ожидалось {expected['answer_present']}, получено {answer_present}")
    if (
        set(actual["source_ids"]) != set(expected["source_ids"])
        or len(actual["source_ids"]) != len(set(actual["source_ids"]))
    ):
        failures.append(
            f"источники: ожидались {expected['source_ids']}, получены {actual['source_ids']}"
        )
    if actual["needs_escalation"] != expected["needs_escalation"]:
        failures.append(
            "эскалация: ожидалось "
            f"{expected['needs_escalation']}, получено {actual['needs_escalation']}"
        )
    return failures


def markdown_value(value: Any) -> str:
    return f"`{json.dumps(value, ensure_ascii=False)}`"


def markdown_elapsed(value: float | None) -> str:
    return f"{value:.1f} с" if value is not None else "—"


async def main() -> int:
    args = parse_args()
    settings = AISettings()
    classification_cases = json.loads(CLASSIFICATION_CASES.read_text(encoding="utf-8"))
    generation_cases = json.loads(GENERATION_CASES.read_text(encoding="utf-8"))
    server_version, server_version_error = await read_server_version(
        args.provider, settings.llm_base_url, settings.request_timeout_s
    )

    classifier = LlmClassifier(
        settings.llm_base_url,
        settings.llm_model,
        settings.request_timeout_s,
        provider=args.provider,
    )
    generator = LlmAnswerGenerator(
        settings.llm_base_url,
        settings.llm_model,
        settings.request_timeout_s,
        provider=args.provider,
    )

    classification_rows: list[dict[str, Any]] = []
    generation_rows: list[dict[str, Any]] = []
    warmup_errors: list[str] = []
    classification_times: list[float] = []
    generation_times: list[float] = []

    try:
        try:
            await classifier.classify("Прогрев классификатора.")
        except ClassificationError as exc:
            warmup_errors.append(f"Классификатор: {exc}")
        try:
            await generator.generate(
                "Прогрев генератора.",
                [{"id": "warmup", "text": "Тестовый документ для прогрева генератора."}],
            )
        except GenerationError as exc:
            warmup_errors.append(f"Генератор: {exc}")

        for case in classification_cases:
            started = time.perf_counter()
            try:
                actual = (await classifier.classify(case["question"])).model_dump(mode="json")
            except ClassificationError as exc:
                classification_rows.append({
                    "question": case["question"],
                    "expected": case["expected"],
                    "actual": None,
                    "mismatches": [f"Ошибка запроса/формата: {exc}"],
                    "elapsed": None,
                })
                continue
            elapsed = time.perf_counter() - started
            classification_times.append(elapsed)
            classification_rows.append({
                "question": case["question"],
                "expected": case["expected"],
                "actual": actual,
                "mismatches": classification_mismatches(case["expected"], actual),
                "elapsed": elapsed,
            })

        for case in generation_cases:
            started = time.perf_counter()
            try:
                actual = (await generator.generate(case["question"], case["documents"])).model_dump(mode="json")
            except GenerationError as exc:
                generation_rows.append({
                    "name": case["name"],
                    "question": case["question"],
                    "expected": case["expected"],
                    "actual": None,
                    "mismatches": [f"Ошибка запроса/формата: {exc}"],
                    "elapsed": None,
                })
                continue
            elapsed = time.perf_counter() - started
            generation_times.append(elapsed)
            generation_rows.append({
                "name": case["name"],
                "question": case["question"],
                "expected": case["expected"],
                "actual": actual,
                "mismatches": generation_mismatches(case["expected"], actual),
                "elapsed": elapsed,
            })
    finally:
        await classifier.aclose()
        await generator.aclose()

    report = render_report(
        provider=args.provider,
        settings=settings,
        classification_rows=classification_rows,
        generation_rows=generation_rows,
        classification_times=classification_times,
        generation_times=generation_times,
        warmup_errors=warmup_errors,
        server_version=server_version,
        server_version_error=server_version_error,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(report)
    print(f"Отчёт записан: {args.output}")

    all_classification_passed = all(not row["mismatches"] for row in classification_rows)
    all_generation_passed = all(not row["mismatches"] for row in generation_rows)
    return 0 if (
        all_classification_passed
        and all_generation_passed
        and not warmup_errors
        and not server_version_error
    ) else 1


async def read_server_version(
    provider: str, base_url: str, timeout_s: float
) -> tuple[str, str | None]:
    if provider != "ollama":
        return "не запрашивалась: endpoint версии не стандартизован OpenAI API", None
    version_url = f"{base_url.rstrip('/').removesuffix('/v1')}/api/version"
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.get(version_url)
            response.raise_for_status()
            version = response.json().get("version")
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        return "не удалось получить", repr(exc)
    if not isinstance(version, str) or not version.strip():
        return "не удалось получить", "Ответ Ollama не содержит строковое поле version"
    return version, None


def render_report(
    *,
    provider: str,
    settings: AISettings,
    classification_rows: list[dict[str, Any]],
    generation_rows: list[dict[str, Any]],
    classification_times: list[float],
    generation_times: list[float],
    warmup_errors: list[str],
    server_version: str,
    server_version_error: str | None,
) -> str:
    total_classification = len(classification_rows)
    field_correct = {
        field: sum(
            row["actual"] is not None and row["actual"][field] == row["expected"][field]
            for row in classification_rows
        )
        for field in CLASSIFICATION_FIELDS
    }
    exact_classification = sum(
        row["actual"] is not None and not row["mismatches"] for row in classification_rows
    )
    successful_generation = sum(not row["mismatches"] for row in generation_rows)
    technical_errors = sum(row["actual"] is None for row in classification_rows + generation_rows)
    avg_classification = (
        f"{sum(classification_times) / len(classification_times):.1f} с"
        if classification_times else "нет успешных измерений"
    )
    avg_generation = (
        f"{sum(generation_times) / len(generation_times):.1f} с"
        if generation_times else "нет успешных измерений"
    )
    overall_pass = (
        exact_classification == total_classification
        and successful_generation == len(generation_rows)
        and not warmup_errors
        and not server_version_error
    )

    lines = [
        "# Результаты эксперимента 4: воспроизводимая базовая оценка LLM",
        "",
        f"- Дата: {datetime.now():%Y-%m-%d %H:%M}",
        f"- Машина: {platform.machine()}, {platform.platform()}",
        f"- Провайдер: {provider}",
        f"- Версия сервера: {server_version}",
        *([f"- Ошибка получения версии сервера: {server_version_error}"] if server_version_error else []),
        f"- Модель: {settings.llm_model}",
        f"- API URL: {settings.llm_base_url}",
        f"- Таймаут запроса: {settings.request_timeout_s:.0f} с",
        "- Параметры генерации: temperature=0; классификация max_tokens=100; "
        "генерация max_tokens=350 (см. `ai_clients/ollama.py`)",
        "- Прогрев: отдельный запрос для классификатора и генератора перед измерением",
        f"- Ошибки прогрева: {len(warmup_errors)}",
        f"- Ошибки запросов/формата в тестовых случаях: {technical_errors}",
        "",
        "## Классификация",
        "",
        f"- Точных совпадений по всем полям: {exact_classification}/{total_classification}",
        f"- Среднее время успешного запроса: {avg_classification}",
        "",
        "| Поле | Совпадений |",
        "|---|---:|",
        *[f"| `{field}` | {field_correct[field]}/{total_classification} |" for field in CLASSIFICATION_FIELDS],
        "",
        "| Вопрос | Ожидалось | Получено | Ошибки | Время |",
        "|---|---|---|---|---:|",
        *[
            f"| {row['question']} | {markdown_value(row['expected'])} | "
            f"{markdown_value(row['actual']) if row['actual'] is not None else 'ошибка'} | "
            f"{'; '.join(row['mismatches']) or '—'} | "
            f"{markdown_elapsed(row['elapsed'])} |"
            for row in classification_rows
        ],
        "",
        "## Генерация ответов",
        "",
        f"- Сценариев пройдено: {successful_generation}/{len(generation_rows)}",
        f"- Среднее время успешного запроса: {avg_generation}",
        "",
        "| Сценарий | Ожидаемые свойства | Результат модели | Проверка | Время |",
        "|---|---|---|---|---:|",
        *[
            f"| {row['name']} | {markdown_value(row['expected'])} | "
            f"{markdown_value(row['actual']) if row['actual'] is not None else 'ошибка'} | "
            f"{'; '.join(row['mismatches']) or 'пройдено'} | "
            f"{markdown_elapsed(row['elapsed'])} |"
            for row in generation_rows
        ],
        "",
        "## Критерий результата",
        "",
        "Прогон получает статус **ПРОЙДЕН** только если версия сервера зафиксирована, все метки классификации "
        "совпали с эталоном, все три сценария генерации выполнили ожидаемые условия, а прогрев прошёл без ошибок. "
        "Несовпадение модели сохраняется в отчёте и возвращает ненулевой код завершения.",
        "",
        f"**Итог:** {'ПРОЙДЕН' if overall_pass else 'НЕ ПРОЙДЕН'}",
        "",
    ]
    if warmup_errors:
        lines.extend(["### Ошибки прогрева", "", *[f"- {error}" for error in warmup_errors], ""])
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
