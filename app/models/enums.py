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


class DocumentType(StrEnum):
    SOC2_TYPE_II = "SOC 2 Type II"
    ISO_27001 = "ISO 27001"
    ARCHITECTURE_DIAGRAM = "Architecture Diagram"


class AssessmentDocumentSystemType(StrEnum):
    SOC2_TYPE_II = "SOC 2 Type II"
    ISO_27001 = "ISO 27001"
    ARCHITECTURE_DIAGRAM = "Architecture Diagram"
    UNCLASSIFIED = "Unclassified"


class ChecklistVerdict(StrEnum):
    REQUIRED = "Required"
    RECOMMENDED = "Recommended"
    NOT_APPLICABLE = "N/A"


class DocumentChecklistRunStatus(StrEnum):
    DRAFT = "draft"
    DRAFT_WITH_LIMITATIONS = "draft_with_limitations"
    SUBMITTED = "submitted"
    FAILED = "failed"


class DocumentChecklistSummaryStatus(StrEnum):
    NOT_GENERATED = "not_generated"
    GENERATED = "generated"
    FALLBACK = "fallback"
    FAILED = "failed"
