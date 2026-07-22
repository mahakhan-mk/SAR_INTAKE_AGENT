from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import uuid

from app.models.enums import AnalysisRunStatus


@dataclass(frozen=True)
class AIAnalysisRunRecord:
    analysis_run_id: uuid.UUID
    status: AnalysisRunStatus
    created_at: datetime


@dataclass(frozen=True)
class AIAnalysisQuestionRowRecord:
    question_id: uuid.UUID
    question_number: str
    question_text: str
    domain: str | None
    response_id: uuid.UUID | None
    selected_option_id: uuid.UUID | None
    answer_value: object | None
    option_risk_band: str | None
    option_risk_weight: float | None
    option_why_it_matters: str | None
    option_risk_signal: str | None
    result_risk_level: str | None
    result_risk_score: float | None
    result_risk_impact: str | None
    result_explanation: str | None
    result_confidence: float | None
    reviewer_remarks: str | None


@dataclass(frozen=True)
class AIAnalysisViewRecord:
    assessment_id: uuid.UUID
    latest_run: AIAnalysisRunRecord | None
    questions: list[AIAnalysisQuestionRowRecord]
