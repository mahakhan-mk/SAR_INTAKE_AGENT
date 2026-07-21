from __future__ import annotations

from enum import StrEnum


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    NOT_ASSESSED = "not_assessed"

    @property
    def label(self) -> str:
        return {
            RiskLevel.LOW: "Low",
            RiskLevel.MEDIUM: "Medium",
            RiskLevel.HIGH: "High",
            RiskLevel.CRITICAL: "Critical",
            RiskLevel.NOT_ASSESSED: "Not Assessed",
        }[self]

    @property
    def rank(self) -> int:
        return {
            RiskLevel.NOT_ASSESSED: 0,
            RiskLevel.LOW: 1,
            RiskLevel.MEDIUM: 2,
            RiskLevel.HIGH: 3,
            RiskLevel.CRITICAL: 4,
        }[self]


class AnalysisRunStatus(StrEnum):
    COMPLETED = "completed"
    COMPLETED_WITH_LIMITATIONS = "completed_with_limitations"
    FAILED = "failed"


class ExecutiveSummaryStatus(StrEnum):
    GENERATED = "generated"
    FALLBACK = "fallback"
    NOT_GENERATED = "not_generated"


class QuestionnaireType(StrEnum):
    TRIAGE = "triage"
