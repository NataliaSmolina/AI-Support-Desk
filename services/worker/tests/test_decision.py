import pytest

from support_worker.decision import Decision, Thresholds, decide

AUTO_ON = Thresholds(auto_categories=frozenset({"billing"}))


def verdict(**overrides):
    args = dict(confidence=0.9, has_sources=True, priority="normal", sentiment="calm",
                wants_human=False, category="billing", thresholds=AUTO_ON)
    args.update(overrides)
    return decide(**args).decision


@pytest.mark.parametrize("override", [
    {"wants_human": True},
    {"priority": "critical"},
    {"sentiment": "negative"},
    {"has_sources": False},
    {"confidence": 0.54},
])
def test_escalate_triggers(override):
    assert verdict(**override) is Decision.ESCALATE


def test_escalate_wins_over_high_confidence():
    assert verdict(confidence=0.99, priority="critical") is Decision.ESCALATE


def test_auto_when_enabled_and_confident():
    assert verdict() is Decision.AUTO


@pytest.mark.parametrize("confidence, expected", [
    (0.55, Decision.DRAFT),      
    (0.849, Decision.DRAFT),
    (0.85, Decision.AUTO),
])
def test_boundaries(confidence, expected):
    assert verdict(confidence=confidence) is expected


def test_pilot_mode_never_auto():
    assert verdict(confidence=0.99, thresholds=Thresholds()) is Decision.DRAFT


def test_auto_only_for_enabled_category():
    assert verdict(category="delivery") is Decision.DRAFT


def test_custom_thresholds():
    t = Thresholds(escalate_below=0.7, auto_from=0.95, auto_categories=frozenset({"billing"}))
    assert verdict(confidence=0.65, thresholds=t) is Decision.ESCALATE
    assert verdict(confidence=0.9, thresholds=t) is Decision.DRAFT


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_invalid_confidence_raises(bad):
    with pytest.raises(ValueError):
        verdict(confidence=bad)