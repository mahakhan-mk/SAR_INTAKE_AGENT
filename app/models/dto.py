from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, model_validator

from app.models.enums import AnalysisRunStatus, ExecutiveSummaryStatus, RiskLevel


@dataclass(frozen=True)
class TriagedQuestionResponse:
    question_code: str
    question_id: str
    response_id: str
    question_text: str
    risk_domain: str
    is_required: bool
    why_it_matters: str
    selected_option_id: str | None
    selected_option_label: str
    risk_weight: float
    max_risk_weight: float
    risk_level: RiskLevel
    risk_signal: str
    confidence: float
    resolved_from_answer_value: bool = False


@dataclass(frozen=True)
class TriagedQuestionLoadResult:
    question_responses: list[TriagedQuestionResponse]
    required_triage_question_count: int
    used_answer_value_resolution: bool = False
    unresolved_response_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ComputedQuestionRisk:
    question_code: str
    response_id: str
    question_definition_id: str
    selected_option_id: str | None
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
    input_snapshot: str


@dataclass(frozen=True)
class StoredAnalysisSnapshot:
    analysis_run_id: str
    status: AnalysisRunStatus
    triage_score: float | None
    inherent_score: float | None
    overall_risk_level: RiskLevel
    executive_summary_status: ExecutiveSummaryStatus
    executive_summary_text: str | None
    executive_summary_model: str | None
    executive_summary_prompt_version: str | None
    executive_summary_input_hash: str | None
    executive_summary_generated_at: datetime | None
    limitation_summary: str | None
    failure_reason: str | None
    source_text: str
    question_results: list[ComputedQuestionRisk]


@dataclass(frozen=True)
class TopRiskDriverState:
    domain: str
    level: RiskLevel


@dataclass(frozen=True)
class InherentRiskScreenState:
    assessment_id: str
    analysis_run_id: str | None
    status: AnalysisRunStatus
    inherent_risk_level: RiskLevel
    high_risk_question_count: int
    top_risk_drivers: list[TopRiskDriverState]
    executive_summary_status: ExecutiveSummaryStatus
    executive_summary_text: str | None
    executive_summary_generated_at: datetime | None
    source_text: str


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


class IntakeHeaderDTO(BaseModel):
    technologyName: str | None
    sourceSystem: str | None
    questionnaireVersion: str | None


class IntakeQuestionDTO(BaseModel):
    questionId: str
    questionCode: str
    label: str
    answer: str | None
    responseType: str
    required: bool
    riskDomain: str


class IntakeSectionDTO(BaseModel):
    code: str
    title: str
    questions: list[IntakeQuestionDTO]


class IntakeTriageQuestionDTO(BaseModel):
    questionId: str
    questionCode: str
    label: str
    answer: str | None


class IntakeOverviewResponseDTO(BaseModel):
    assessmentId: str
    header: IntakeHeaderDTO
    sections: list[IntakeSectionDTO]
    triage: list[IntakeTriageQuestionDTO]


class IntakeQuestionUpdateRequestDTO(BaseModel):
    selectedOptionId: str | None = None
    answerValue: str | None = None

    @model_validator(mode="after")
    def validate_at_least_one_field_was_provided(self) -> "IntakeQuestionUpdateRequestDTO":
        if "selectedOptionId" not in self.model_fields_set and "answerValue" not in self.model_fields_set:
            raise ValueError("At least one of selectedOptionId or answerValue must be provided.")
        return self


class IntakeQuestionUpdateResponseDTO(BaseModel):
    questionId: str
    selectedOptionId: str | None
    answerValue: str | None
