from dataclasses import dataclass
from enum import StrEnum


class Decision(StrEnum):
    AUTO = "auto"
    DRAFT = "draft"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class Thresholds:
    escalate_below: float = 0.55
    auto_from: float = 0.85
    auto_categories: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Verdict:
    decision: Decision
    reason: str


def decide(
    *,
    confidence: float,
    has_sources: bool,
    priority: str,
    sentiment: str,
    wants_human: bool,
    category: str,
    thresholds: Thresholds = Thresholds(),
) -> Verdict:
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence должен быть от 0 до 1, получено {confidence}")

    if wants_human:
        return Verdict(Decision.ESCALATE, "клиент просит оператора")
    if priority == "critical":
        return Verdict(Decision.ESCALATE, "критический приоритет")
    if sentiment == "negative":
        return Verdict(Decision.ESCALATE, "сильный негатив")
    if not has_sources:
        return Verdict(Decision.ESCALATE, "в ответе нет ссылок на источники")
    if confidence < thresholds.escalate_below:
        return Verdict(Decision.ESCALATE, f"низкая уверенность {confidence:.2f}")

    if category in thresholds.auto_categories and confidence >= thresholds.auto_from:
        return Verdict(Decision.AUTO, f"уверенность {confidence:.2f}, автоответ включён")

    return Verdict(Decision.DRAFT, f"черновик, уверенность {confidence:.2f}")