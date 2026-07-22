from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class IntakeHeaderRecord:
    technology_name: str | None
    source_system: str | None
    questionnaire_version: str | None


@dataclass(frozen=True)
class IntakeQuestionRecord:
    question_id: UUID
    question_code: str
    label: str
    answer: str | None
    response_type: str
    required: bool
    risk_domain: str
    section_code: str | None
    response_id: UUID | None
    selected_option_id: UUID | None
    answer_value: str | None


@dataclass(frozen=True)
class IntakeSectionRecord:
    code: str | None
    questions: list[IntakeQuestionRecord]


@dataclass(frozen=True)
class IntakeTriageQuestionRecord:
    question_id: UUID
    question_code: str
    label: str
    answer: str | None
    response_id: UUID | None
    selected_option_id: UUID | None
    answer_value: str | None


@dataclass(frozen=True)
class IntakeOverviewRecord:
    assessment_id: UUID
    header: IntakeHeaderRecord
    sections: list[IntakeSectionRecord]
    triage: list[IntakeTriageQuestionRecord]
