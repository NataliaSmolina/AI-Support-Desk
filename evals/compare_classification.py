"""Парное сравнение старого и нового промптов на одной конфигурации LLM."""
import argparse
import asyncio
import hashlib
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from ai_clients.config import AISettings
from ai_clients.llm import Classification, ClassificationError, LlmClassifier, SYSTEM_PROMPT
from ai_clients.readiness import LLMReadinessError, check_llm_ready
from evals.check_llm_baseline import CLASSIFICATION_FIELDS, classification_mismatches, read_server_version


def load_cases(path):
    cases = json.loads(path.read_text())
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"Пустой или некорректный набор: {path}")
    for case in cases:
        if not isinstance(case['question'], str) or not case['question'].strip():
            raise ValueError('Пустой вопрос')
        Classification.model_validate(case['expected'])
    return cases


def summarize(rows):
    total = len(rows)
    times = [row['elapsed_s'] for row in rows if row['actual'] is not None]
    return {
        'total': total,
        'errors': sum(row['actual'] is None for row in rows),
        'exact': sum(not row['mismatches'] for row in rows),
        'correct': {field: sum(row['actual'] is not None and row['actual'][field] == row['expected'][field]
                               for row in rows) for field in CLASSIFICATION_FIELDS},
        'mean_success_s': sum(times) / len(times) if times else None,
    }


async def evaluate_case(classifier, case):
    started = time.perf_counter()
    try:
        actual = (await classifier.classify(case['question'])).model_dump(mode='json')
        failures = classification_mismatches(case['expected'], actual)
    except ClassificationError as exc:
        actual, failures = None, [str(exc)]
    return {**case, 'actual': actual, 'mismatches': failures, 'elapsed_s': time.perf_counter() - started}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/week05-classification.json'))
    parser.add_argument('--limit', type=int, help='Smoke-прогон: первые N случаев каждого набора; не полная оценка')
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error('--limit должен быть положительным')
    settings = AISettings()
    try:
        await check_llm_ready(settings)
    except LLMReadinessError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    prompts = {'before': Path('evals/prompts/classifier_v1.txt').read_text().rstrip('\n'), 'after': SYSTEM_PROMPT}
    report = {'date_utc': datetime.now(timezone.utc).isoformat(), 'machine': platform.platform(),
              'settings': settings.model_dump(include={'llm_provider', 'llm_base_url', 'llm_model', 'request_timeout_s'}),
              'server_version': await read_server_version(settings.llm_provider, settings.llm_base_url, settings.llm_health_timeout_s),
              'partial': args.limit is not None, 'complete': False, 'prompts': prompts, 'datasets': {}, 'warmup_errors': {}}
    clients = {name: LlmClassifier(settings.llm_base_url, settings.llm_model, settings.request_timeout_s,
                                   provider=settings.llm_provider, system_prompt=prompt) for name, prompt in prompts.items()}
    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    save()
    try:
        for name, client in clients.items():
            try:
                await client.classify('Какие способы оплаты доступны?')
            except ClassificationError as exc:
                report['warmup_errors'][name] = str(exc)
            print(f"Прогрев {name}: {report['warmup_errors'].get(name, 'OK')}", flush=True)
            save()
        for dataset, path in [('baseline', Path('evals/data/classify_questions.json')),
                              ('validation', Path('evals/data/classify_validation.json'))]:
            cases = load_cases(path)
            data = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'rows': {name: [] for name in clients}}
            report['datasets'][dataset] = data
            for index, case in enumerate(cases[:args.limit]):
                # Чередуем порядок, чтобы второй промпт не получал систематическое преимущество прогрева.
                for name in (list(clients) if index % 2 == 0 else list(reversed(clients))):
                    row = await evaluate_case(clients[name], case)
                    data['rows'][name].append(row)
                    print(f"{dataset} {index+1}: {name}: {row['mismatches'] or 'OK'}", flush=True)
                    data['summary'] = {key: summarize(rows) for key, rows in data['rows'].items()}
                    save()
    finally:
        for client in clients.values():
            await client.aclose()
    report['complete'] = True
    save()
    for dataset, data in report['datasets'].items():
        for name, summary in data['summary'].items():
            print(f"{dataset} / {name}: exact={summary['exact']}/{summary['total']}; "
                  f"поля={summary['correct']}; ошибок={summary['errors']}; "
                  f"среднее успешных, с={summary['mean_success_s']}")
    print(f'Отчёт: {args.output}')
    return int(bool(report['warmup_errors']) or any(
        data['summary']['after']['exact'] != data['summary']['after']['total'] for data in report['datasets'].values()))


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
