from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import uuid
from uuid import UUID

from app.models.database import DocumentChecklistItem, DocumentChecklistRun
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
    question_weight: int
    option_weight: float
    weighted_score: float
    max_option_weight: float
    max_weighted_score: float
    risk_level: RiskLevel
    risk_signal: str
    confidence: float


@dataclass(frozen=True)
class TriagedQuestionLoadResult:
    question_responses: list[TriagedQuestionResponse]
    required_triage_question_count: int
    unresolved_response_ids: list[uuid.UUID] = field(default_factory=list)
    validation_issues: list[object] = field(default_factory=list)


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
    question_weight: int | None
    option_weight: float | None
    weighted_score: float
    max_option_weight: float | None
    max_weighted_score: float
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
class AnalysisRunCreateResult:
    analysisRunId: UUID | str
    status: AnalysisRunStatus


@dataclass(frozen=True)
class ExecutiveSummaryGenerateEnvelope:
    text: str
    status: ExecutiveSummaryStatus
    generatedAt: datetime


@dataclass(frozen=True)
class ExecutiveSummaryGenerateResult:
    assessmentId: UUID
    analysisRunId: UUID
    executiveSummary: ExecutiveSummaryGenerateEnvelope


@dataclass(frozen=True)
class DocumentChecklistItemReadState:
    item: DocumentChecklistItem
    effective_verdict: str
    detected_file_status: str
    detected_document_id: UUID | None
    reviewer_verdict: str | None
    reviewer_reason: str | None
    vendor_certification_automatic_status: str | None
    vendor_certification_analyst_status: str | None
    vendor_certification_effective_status: str | None


@dataclass(frozen=True)
class DocumentChecklistReadState:
    run: DocumentChecklistRun
    items: list[DocumentChecklistItemReadState]


@dataclass(frozen=True)
class InitialSarReportAssessment:
    technologyName: str | None = None
    vendorName: str | None = None
    productName: str | None = None
    requestedBy: str | None = None
    createdAt: datetime | None = None
    sourceSystem: str | None = None
    questionnaireVersion: str | None = None


@dataclass(frozen=True)
class InitialSarReportRiskAssessment:
    analysisRunId: UUID | None = None
    inherentRiskLevel: str | None = None
    executiveSummary: str | None = None
    status: str | None = None
    topRiskDrivers: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class InitialSarReportBusinessContactDetails:
    businessUnit: str | None = None
    sponsorBusinessOwner: str | None = None


@dataclass(frozen=True)
class InitialSarReportSolutionOverview:
    launchDate: str | None = None
    businessFunctionSolutionOverview: str | None = None


@dataclass(frozen=True)
class InitialSarReportArchitecture:
    architectureDetails: str | None = None
    documentId: str | None = None
    filename: str | None = None
    contentType: str | None = None


@dataclass(frozen=True)
class InitialSarReportHosting:
    hostingModel: str | None = None
    hostedBy: str | None = None
    accessedBy: str | None = None


@dataclass(frozen=True)
class InitialSarReportDataHosted:
    dataResidency: str | None = None
    confidentiality: str | None = None
    integrity: str | None = None


@dataclass(frozen=True)
class InitialSarReportDataFlow:
    dataFlow: str | None = None


@dataclass(frozen=True)
class InitialSarReportBusinessContinuity:
    businessContinuityRating: str | None = None
    rpoRto: str | None = None
    backupAndRestore: str | None = None


@dataclass(frozen=True)
class InitialSarReportThirdPartyMeasures:
    thirdPartyAssessment: str | None = None
    sla: str | None = None


@dataclass(frozen=True)
class InitialSarReportDocumentChecklist:
    runId: UUID | None = None
    summary: str | None = None
    status: str | None = None
    items: list[dict[str, object]] = field(default_factory=list)
    missingRequiredCount: int | None = None


@dataclass(frozen=True)
class InitialSarReportVendorReputation:
    status: str | None = None
    summary: str | None = None
    rows: list[dict[str, object]] = field(default_factory=list)


@dataclass(frozen=True)
class InitialSarReportContext:
    assessmentId: UUID
    generatedAt: datetime
    assessment: InitialSarReportAssessment
    riskAssessment: InitialSarReportRiskAssessment
    businessContactDetails: InitialSarReportBusinessContactDetails
    solutionOverview: InitialSarReportSolutionOverview
    architecture: InitialSarReportArchitecture
    hosting: InitialSarReportHosting
    dataHosted: InitialSarReportDataHosted
    dataFlow: InitialSarReportDataFlow
    businessContinuity: InitialSarReportBusinessContinuity
    thirdPartyMeasures: InitialSarReportThirdPartyMeasures
    documentChecklist: InitialSarReportDocumentChecklist
    vendorReputation: InitialSarReportVendorReputation | None
    limitations: list[str] | None = None
