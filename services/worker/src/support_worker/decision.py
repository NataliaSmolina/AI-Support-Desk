
from dataclasses import dataclass
from enum import StrEnum


class Decision(StrEnum):
    AUTO = "auto"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class Verdict:
    decision: Decision
    reason: str


def classification_escalation(
    *,
    priority: str,
    sentiment: str,
    wants_human: bool,
) -> Verdict | None:
    if wants_human:
        return Verdict(Decision.ESCALATE, "клиент просит оператора")

    if priority == "critical":
        return Verdict(Decision.ESCALATE, "критический приоритет")

    if sentiment == "negative":
        return Verdict(Decision.ESCALATE, "негатив клиента")

    return None


def decide(
    *,
    has_sources: bool,
    rag_needs_escalation: bool,
    priority: str,
    sentiment: str,
    wants_human: bool,
) -> Verdict:
    verdict = classification_escalation(
        priority=priority, sentiment=sentiment, wants_human=wants_human,
    )
    if verdict is not None:
        return verdict

    if not has_sources:
        return Verdict(Decision.ESCALATE, "не найдены источники")

    if rag_needs_escalation:
        return Verdict(Decision.ESCALATE, "RAG не смог подготовить достоверный ответ")

    return Verdict(Decision.AUTO, "информации достаточно для ответа клиенту")
