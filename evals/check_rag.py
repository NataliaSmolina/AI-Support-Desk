"""Реальный RAG-прогон: Markdown → kb-index → PostgreSQL → TEI → LLM.

Из корня: uv run python -m evals.check_rag --demo --index-demo
"""

import argparse
import asyncio
import json
import platform
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
from pydantic import ValidationError

from ai_clients.config import AISettings, RagSettings
from ai_clients.rag import RagError, RagResult, open_rag
from ai_clients.tei import TeiEmbedder
from evals.check_llm_baseline import generation_mismatches, read_server_version

ROOT = Path(__file__).resolve().parents[1]
DEMO_DSN = "postgresql://rag_eval:rag_eval@127.0.0.1:5436/rag_eval"


async def index_demo(ai: AISettings) -> None:
    # Загружаем только в выделенную БД: обычный DATABASE_URL здесь не используется.
    from kb_index.chunker import MarkdownHeaderChunker
    from kb_index.database import DBLoader
    from kb_index.embedder import TeiEmbedderAdapter
    from kb_index.loader import LocalDirectoryLoader
    from kb_index.pipeline import Pipeline

    pool = await asyncpg.create_pool(DEMO_DSN, min_size=1, max_size=2, timeout=10)
    tei = TeiEmbedder(ai.tei_embed_url, ai.request_timeout_s)
    try:
        pipeline = Pipeline(
            LocalDirectoryLoader(str(ROOT / "evals/data/rag_kb")), MarkdownHeaderChunker(),
            TeiEmbedderAdapter(tei), DBLoader(pool), embed_batch_size=8,
        )
        await pipeline.run()
    finally:
        await tei.aclose()
        await pool.close()


def check_result(expected: dict, result: RagResult) -> list[str]:
    # Файлы в эталоне стабильны; хэши реальных чанков зависят от пути и содержимого.
    source_map = {c.id: Path(c.source_file).name for c in result.retrieved_chunks}
    actual = result.model_dump(mode="json")
    actual["source_ids"] = sorted({source_map.get(i, f"unknown:{i}") for i in result.source_ids})
    translated = {**expected, "source_ids": expected["source_files"]}
    failures = generation_mismatches(translated, actual)
    if len(result.source_ids) != len(set(result.source_ids)):
        failures.append("Генератор повторил идентификатор источника")
    retrieved_files = {Path(c.source_file).name for c in result.retrieved_chunks}
    for name in expected["source_files"]:
        if name not in retrieved_files:
            failures.append(f"Поиск не вернул обязательный источник: {name}")
    return failures


def error_types(error: BaseException) -> list[str]:
    """Только имена классов причин, без текста запроса, документов или DSN."""
    names = []
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        names.append(type(error).__name__)
        error = error.__cause__
    return names


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Использовать отдельную БД на порту 5436")
    parser.add_argument("--index-demo", action="store_true", help="Загрузить тестовые статьи; только с --demo")
    parser.add_argument("--question", help="Один произвольный вопрос вместо трёх сценариев")
    parser.add_argument("--top-k", type=int)
    parser.add_argument("--max-distance", type=float)
    parser.add_argument("--output", type=Path, default=Path("/tmp/rag-results.json"))
    args = parser.parse_args()
    if args.index_demo and not args.demo:
        parser.error("--index-demo разрешён только с --demo, чтобы не изменять рабочую БД")
    ai = AISettings()
    overrides = {}
    if args.demo:
        overrides.update(database_url=DEMO_DSN, embedding_dimension=1024, rag_top_k=2)
    if args.top_k is not None:
        overrides["rag_top_k"] = args.top_k
    if args.max_distance is not None:
        overrides["rag_max_distance"] = args.max_distance
    try:
        settings = RagSettings(**overrides)
    except ValidationError:
        print("Проверьте DATABASE_URL, EMBEDDING_DIMENSION и настройки RAG в .env", file=sys.stderr)
        return 1
    report = {
        "date_utc": datetime.now(timezone.utc).isoformat(), "machine": platform.platform(),
        "llm_model": ai.llm_model, "llm_provider": ai.llm_provider,
        "tei_url": ai.tei_embed_url, "embedding_model": "BAAI/bge-m3 (ожидаемая модель)",
        "top_k": settings.rag_top_k, "max_distance": settings.rag_max_distance,
        "request_timeout_s": ai.request_timeout_s, "demo": args.demo,
        "complete": False, "rows": [],
    }

    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    save()
    if args.index_demo:
        print("Индексация тестовых Markdown в отдельную БД rag_eval...", flush=True)
        started = time.perf_counter()
        try:
            await index_demo(ai)
        except (asyncpg.PostgresError, OSError, TimeoutError, RuntimeError, ValueError) as exc:
            report["startup_error"] = (
                f"Не удалось индексировать демо ({type(exc).__name__}): "
                "проверьте TEI, тестовую БД и миграции"
            )
            save()
            print(report["startup_error"], file=sys.stderr)
            return 1
        report["indexing_s"] = time.perf_counter() - started
    report["llm_version"], report["llm_version_error"] = await read_server_version(
        ai.llm_provider, ai.llm_base_url, ai.llm_health_timeout_s,
    )
    cases = ([{"name": "Произвольный вопрос", "question": args.question}]
             if args.question is not None else
             json.loads((ROOT / "evals/data/rag_cases.json").read_text()))
    try:
        async with open_rag(ai, settings) as rag:
            for case in cases:
                print(f"Вопрос: {case['question']}", flush=True)
                try:
                    result = await rag.answer_question(case["question"])
                    failures = check_result(case["expected"], result) if "expected" in case else []
                    row = {**case, "result": result.model_dump(mode="json"), "mismatches": failures}
                    print(f"Ответ: {result.answer}\nЭскалация: {result.needs_escalation}; причина: {result.reason}")
                    for chunk in result.retrieved_chunks:
                        print(f"  {Path(chunk.source_file).name}: distance={chunk.distance:.4f}; id={chunk.id}")
                    print(f"Время этапов: {result.timings.model_dump()}")
                    print(f"Проверка: {failures or 'OK'}", flush=True)
                except RagError as exc:
                    row = {**case, "result": None, "stage": exc.stage,
                           "error_types": error_types(exc), "mismatches": [str(exc)],
                           "retrieved_chunks": [asdict(c) for c in exc.retrieved_chunks],
                           "timings": exc.timings}
                    print(f"Ошибка этапа {exc.stage}: {exc}", file=sys.stderr, flush=True)
                except ValueError as exc:
                    row = {**case, "result": None, "stage": "input", "mismatches": [str(exc)]}
                report["rows"].append(row)
                save()
    except RagError as exc:
        report["startup_error"] = str(exc)
        save()
        print(str(exc), file=sys.stderr)
        return 1
    report["complete"] = True
    report["passed"] = all(not row["mismatches"] for row in report["rows"])
    save()
    print(f"Отчёт: {args.output}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
