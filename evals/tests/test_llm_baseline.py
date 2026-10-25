from ai_clients.config import AISettings

from evals.check_llm_baseline import (
    classification_mismatches,
    generation_mismatches,
    markdown_elapsed,
    render_report,
)


def test_classification_mismatches_checks_every_label():
    expected = {
        "category": "billing",
        "priority": "normal",
        "sentiment": "calm",
        "wants_human": False,
    }
    assert classification_mismatches(expected, expected) == []
    assert classification_mismatches(expected, {**expected, "priority": "low"}) == [
        "priority: ожидалось 'normal', получено 'low'"
    ]


def test_generation_mismatches_checks_answer_sources_and_escalation():
    expected = {
        "answer_present": True,
        "source_ids": ["price", "time"],
        "needs_escalation": False,
        "required_facts": ["350 рублей", "3-5 рабочих дней"],
    }
    actual = {
        "answer": "Цена — 350 рублей. Срок — 3–5 рабочих дней.",
        "source_ids": ["price"],
        "needs_escalation": False,
    }
    assert generation_mismatches(expected, actual) == [
        "источники: ожидались ['price', 'time'], получены ['price']"
    ]


def test_generation_mismatches_checks_required_answer_facts():
    expected = {
        "answer_present": True,
        "source_ids": ["refund"],
        "needs_escalation": False,
        "required_facts": ["10 рабочих дней", "исходный способ оплаты"],
    }
    actual = {
        "answer": "Деньги вернут в течение 10 рабочих дней.",
        "source_ids": ["refund"],
        "needs_escalation": False,
    }

    assert generation_mismatches(expected, actual) == [
        "в ответе отсутствует обязательный факт: 'исходный способ оплаты'"
    ]


def test_generation_mismatches_requires_escalation_without_answer():
    expected = {
        "answer_present": False,
        "source_ids": [],
        "needs_escalation": True,
    }
    actual = {"answer": "Нет.", "source_ids": [], "needs_escalation": False}
    assert generation_mismatches(expected, actual) == [
        "наличие ответа: ожидалось False, получено True",
        "эскалация: ожидалось True, получено False",
    ]


def test_report_marks_quality_mismatch_as_failed():
    classification_rows = [{
        "question": "Вопрос",
        "expected": {"category": "billing", "priority": "normal", "sentiment": "calm", "wants_human": False},
        "actual": {"category": "billing", "priority": "low", "sentiment": "calm", "wants_human": False},
        "mismatches": ["priority: ожидалось 'normal', получено 'low'"],
        "elapsed": 1.0,
    }]
    report = render_report(
        provider="ollama",
        settings=AISettings(),
        classification_rows=classification_rows,
        generation_rows=[],
        classification_times=[1.0],
        generation_times=[],
        warmup_errors=[],
        server_version="0.1.0",
        server_version_error=None,
    )
    assert "Точных совпадений по всем полям: 0/1" in report
    assert "**Итог:** НЕ ПРОЙДЕН" in report


def test_markdown_elapsed_for_missing_request():
    assert markdown_elapsed(None) == "—"
