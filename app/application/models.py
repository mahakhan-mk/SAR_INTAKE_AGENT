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


@dataclass(frozen=True)
class InherentRiskValue:
    level: RiskLevel
    label: str
    highRiskQuestionCount: int
    sourceText: str


@dataclass(frozen=True)
class InherentRiskTopRiskDriver:
    domain: str
    level: RiskLevel


@dataclass(frozen=True)
class InherentRiskExecutiveSummary:
    text: str | None
    status: ExecutiveSummaryStatus
    generatedAt: datetime | None


@dataclass(frozen=True)
class InherentRiskLinks:
    aiAnalysis: str
    reportPreview: str


@dataclass(frozen=True)
class InherentRiskResponse:
    assessmentId: UUID
    analysisRunId: UUID | None
    status: AnalysisRunStatus
    inherentRisk: InherentRiskValue
    topRiskDrivers: list[InherentRiskTopRiskDriver]
    executiveSummary: InherentRiskExecutiveSummary
    links: InherentRiskLinks


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
class AIAnalysisRunSummary:
    analysisRunId: UUID | None
    status: AnalysisRunStatus | None
    createdAt: datetime | None


@dataclass(frozen=True)
class AIAnalysisQuestionRow:
    questionId: UUID
    questionNumber: str
    questionText: str
    domain: str
    selectedOptionId: UUID | None
    answerValue: str | None
    riskBand: RiskLevel | None
    riskScore: float | None
    riskSignal: str | None
    whyItMatters: str | None
    aiExplanation: str | None
    confidence: float | None
    reviewerRemarks: str | None


@dataclass(frozen=True)
class AIAnalysisResult:
    assessmentId: UUID
    latestAnalysisRun: AIAnalysisRunSummary
    questions: list[AIAnalysisQuestionRow]


@dataclass(frozen=True)
class IntakeHeader:
    technologyName: str | None
    sourceSystem: str | None
    questionnaireVersion: str | None


@dataclass(frozen=True)
class IntakeQuestion:
    questionId: UUID
    questionCode: str
    label: str
    answer: str | None
    responseType: str
    required: bool
    riskDomain: str


@dataclass(frozen=True)
class IntakeSection:
    code: str
    title: str
    questions: list[IntakeQuestion]


@dataclass(frozen=True)
class IntakeTriageQuestion:
    questionId: UUID
    questionCode: str
    label: str
    answer: str | None


@dataclass(frozen=True)
class IntakeOverviewResult:
    assessmentId: UUID
    header: IntakeHeader
    sections: list[IntakeSection]
    triage: list[IntakeTriageQuestion]


@dataclass(frozen=True)
class IntakeQuestionUpdateCommand:
    selected_option_id: UUID | None
    answer_value: str | None
    fields_set: frozenset[str]


@dataclass(frozen=True)
class IntakeQuestionUpdateResult:
    questionId: UUID
    selectedOptionId: UUID | None
    answerValue: str | None


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
class DocumentChecklistItemResponse:
    item_id: UUID
    document_type: str
    item_order: int
    base_verdict: str
    effective_verdict: str
    detected_file_status: str
    detected_document_id: UUID | None
    reviewer_verdict: str | None
    reviewer_reason: str | None
    vendor_certification_automatic_status: str | None
    vendor_certification_analyst_status: str | None
    vendor_certification_effective_status: str | None


@dataclass(frozen=True)
class DocumentChecklistResponse:
    run_id: UUID
    assessment_id: UUID
    status: str
    summary_text: str | None
    summary_status: str
    limitations: list[object]
    created_at: datetime
    items: list[DocumentChecklistItemResponse]


@dataclass(frozen=True)
class AssessmentDocumentResponse:
    document_id: UUID
    assessment_id: UUID
    original_filename: str
    content_type: str
    file_size_bytes: int
    sha256: str
    system_document_type: str
    upload_source: str
    uploaded_by: str | None
    created_at: datetime
    deleted_at: datetime | None


@dataclass(frozen=True)
class AssessmentDocumentListResponse:
    documents: list[AssessmentDocumentResponse]


@dataclass(frozen=True)
class DocumentClassificationReviewResponse:
    review_id: UUID
    document_id: UUID
    assessment_id: UUID
    document_type: str
    reason: str
    reviewed_by: str | None
    created_at: datetime
    effective_document_type: str


@dataclass(frozen=True)
class ReportPreviewAssessment:
    technologyName: str | None = None
    sourceSystem: str | None = None
    questionnaireVersion: str | None = None


@dataclass(frozen=True)
class ReportPreviewRiskAssessment:
    inherentRiskLevel: str | None = None
    executiveSummary: str | None = None
    status: str | None = None
    topRiskDrivers: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class ReportPreviewBusinessContactDetails:
    businessUnit: str | None = None
    sponsorBusinessOwner: str | None = None


@dataclass(frozen=True)
class ReportPreviewSolutionOverview:
    launchDate: str | None = None
    businessFunctionSolutionOverview: str | None = None


@dataclass(frozen=True)
class ReportPreviewArchitecture:
    architectureDetails: str | None = None
    documentId: str | None = None
    filename: str | None = None
    contentType: str | None = None


@dataclass(frozen=True)
class ReportPreviewHosting:
    hostingModel: str | None = None
    hostedBy: str | None = None
    accessedBy: str | None = None


@dataclass(frozen=True)
class ReportPreviewDataHosted:
    dataResidency: str | None = None
    confidentiality: str | None = None
    integrity: str | None = None


@dataclass(frozen=True)
class ReportPreviewDataFlow:
    dataFlow: str | None = None


@dataclass(frozen=True)
class ReportPreviewBusinessContinuity:
    businessContinuityRating: str | None = None
    rpoRto: str | None = None
    backupAndRestore: str | None = None


@dataclass(frozen=True)
class ReportPreviewThirdPartyMeasures:
    thirdPartyAssessment: str | None = None
    sla: str | None = None


@dataclass(frozen=True)
class ReportPreviewDocumentChecklist:
    summary: str | None = None
    status: str | None = None
    items: list[dict[str, object]] = field(default_factory=list)
    missingRequiredCount: int | None = None


@dataclass(frozen=True)
class ReportPreviewVendorReputation:
    summary: str | None = None


@dataclass(frozen=True)
class ReportPreviewResult:
    assessmentId: UUID
    generatedAt: datetime
    assessment: ReportPreviewAssessment
    riskAssessment: ReportPreviewRiskAssessment
    businessContactDetails: ReportPreviewBusinessContactDetails
    solutionOverview: ReportPreviewSolutionOverview
    architecture: ReportPreviewArchitecture
    hosting: ReportPreviewHosting
    dataHosted: ReportPreviewDataHosted
    dataFlow: ReportPreviewDataFlow
    businessContinuity: ReportPreviewBusinessContinuity
    thirdPartyMeasures: ReportPreviewThirdPartyMeasures
    documentChecklist: ReportPreviewDocumentChecklist
    vendorReputation: ReportPreviewVendorReputation | None
    limitations: list[str] | None = None
