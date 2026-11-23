
import pytest

from support_worker.decision import Decision, decide


def verdict(**overrides):
    args = dict(
        has_sources=True,
        rag_needs_escalation=False,
        priority="normal",
        sentiment="calm",
        wants_human=False,
    )
    args.update(overrides)
    return decide(**args)


@pytest.mark.parametrize("override", [
    {"wants_human": True},
    {"priority": "critical"},
    {"sentiment": "negative"},
    {"has_sources": False},
    {"rag_needs_escalation": True},
])
def test_escalate_triggers(override):
    assert verdict(**override).decision is Decision.ESCALATE


def test_escalate_when_client_requests_operator():
    result = verdict(wants_human=True)
    assert result.decision is Decision.ESCALATE
    assert result.reason == "клиент просит оператора"


def test_escalate_when_no_sources():
    result = verdict(has_sources=False)
    assert result.decision is Decision.ESCALATE
    assert result.reason == "не найдены источники"


def test_escalate_when_rag_cannot_prepare_answer():
    result = verdict(rag_needs_escalation=True)
    assert result.decision is Decision.ESCALATE


def test_auto_when_information_is_sufficient():
    assert verdict().decision is Decision.AUTO


def test_critical_priority_wins_over_other_conditions():
    result = verdict(priority="critical", sentiment="negative")
    assert result.decision is Decision.ESCALATE
    assert result.reason == "критический приоритет"


def test_negative_sentiment_causes_escalation():
    assert verdict(sentiment="negative").decision is Decision.ESCALATE
