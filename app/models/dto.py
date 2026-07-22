from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import uuid

from pydantic import BaseModel

from app.models.enums import AnalysisRunStatus, ExecutiveSummaryStatus, RiskLevel


@dataclass(frozen=True)
class TriagedQuestionResponse:
    question_code: str
    question_id: uuid.UUID
    response_id: uuid.UUID
    selected_option_id: uuid.UUID
    selected_option_code: str
    question_text: str
    risk_domain: str
    is_required: bool
    why_it_matters: str
    selected_option_label: str
    risk_weight: float
    max_risk_weight: float
    risk_level: RiskLevel
    risk_signal: str
    confidence: float


@dataclass(frozen=True)
class TriagedQuestionLoadResult:
    question_responses: list[TriagedQuestionResponse]
    required_triage_question_count: int
    unresolved_response_ids: list[uuid.UUID] = field(default_factory=list)


@dataclass(frozen=True)
class ComputedQuestionRisk:
    question_code: str
    response_id: uuid.UUID
    question_definition_id: uuid.UUID | None
    selected_option_id: uuid.UUID | None
    selected_option_label: str
    question_text: str
    risk_domain: str
    risk_level: RiskLevel
    risk_weight: float
    max_risk_weight: float
    why_it_matters: str
    risk_signal: str
    explanation: str
    confidence: float
    input_snapshot: dict[str, object]


@dataclass(frozen=True)
class StoredAnalysisSnapshot:
    analysis_run_id: uuid.UUID
    status: AnalysisRunStatus
    triage_score: float | None
    inherent_score: float | None
    inherent_risk_level: RiskLevel
    executive_summary_status: ExecutiveSummaryStatus
    executive_summary_text: str | None
    executive_summary_model: str | None
    executive_summary_prompt_version: str | None
    executive_summary_input_hash: str | None
    executive_summary_generated_at: datetime | None
    error_summary: str | None
    question_results: list[ComputedQuestionRisk]


@dataclass(frozen=True)
class TopRiskDriverState:
    domain: str
    level: RiskLevel


@dataclass(frozen=True)
class InherentRiskScreenState:
    assessment_id: uuid.UUID
    analysis_run_id: uuid.UUID | None
    status: AnalysisRunStatus
    inherent_risk_level: RiskLevel
    high_risk_question_count: int
    top_risk_drivers: list[TopRiskDriverState]
    executive_summary_status: ExecutiveSummaryStatus
    executive_summary_text: str | None
    executive_summary_generated_at: datetime | None


class InherentRiskValueDTO(BaseModel):
    level: RiskLevel
    label: str
    highRiskQuestionCount: int
    sourceText: str


class TopRiskDriverDTO(BaseModel):
    domain: str
    level: RiskLevel


class ExecutiveSummaryDTO(BaseModel):
    text: str | None
    status: ExecutiveSummaryStatus
    generatedAt: datetime | None


class LinksDTO(BaseModel):
    aiAnalysis: str
    reportPreview: str


class InherentRiskResponseDTO(BaseModel):
    assessmentId: str
    analysisRunId: str | None
    status: AnalysisRunStatus
    inherentRisk: InherentRiskValueDTO
    topRiskDrivers: list[TopRiskDriverDTO]
    executiveSummary: ExecutiveSummaryDTO
    links: LinksDTO


class AnalysisRunCreateRequestDTO(BaseModel):
    force: bool = False


class AnalysisRunCreateResponseDTO(BaseModel):
    analysisRunId: str
    status: AnalysisRunStatus


class ExecutiveSummaryGenerateRequestDTO(BaseModel):
    force: bool = False


class ExecutiveSummaryGenerateEnvelopeDTO(BaseModel):
    text: str
    status: ExecutiveSummaryStatus
    generatedAt: datetime


class ExecutiveSummaryGenerateResponseDTO(BaseModel):
    assessmentId: str
    analysisRunId: str
    executiveSummary: ExecutiveSummaryGenerateEnvelopeDTO
