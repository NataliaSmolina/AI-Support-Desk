
from dataclasses import dataclass
from enum import StrEnum


class Decision(StrEnum):
    AUTO = "auto"
    DRAFT = "draft"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class Verdict:
    decision: Decision
    reason: str


def decide(
    *,
    has_sources: bool,
    rag_needs_escalation: bool,
    priority: str,
    sentiment: str,
    wants_human: bool,
) -> Verdict:
    if wants_human:
        return Verdict(Decision.ESCALATE, "клиент просит оператора")

    if priority == "critical":
        return Verdict(Decision.ESCALATE, "критический приоритет")

    if sentiment == "negative":
        return Verdict(Decision.ESCALATE, "негатив клиента")

    if not has_sources:
        return Verdict(Decision.ESCALATE, "не найдены источники")

    if rag_needs_escalation:
        return Verdict(Decision.ESCALATE, "RAG не смог подготовить достоверный ответ")

    return Verdict(Decision.DRAFT, "информации достаточно для подготовки черновика")
