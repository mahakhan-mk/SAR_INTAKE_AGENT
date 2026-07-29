from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import AnalysisRunStatus, ChecklistVerdict, DocumentType, ExecutiveSummaryStatus, RiskLevel


class ApiSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class InherentRiskValueDTO(ApiSchema):
    level: RiskLevel
    label: str
    highRiskQuestionCount: int
    sourceText: str


class TopRiskDriverDTO(ApiSchema):
    domain: str
    level: RiskLevel


class ExecutiveSummaryDTO(ApiSchema):
    text: str | None
    status: ExecutiveSummaryStatus
    generatedAt: datetime | None


class LinksDTO(ApiSchema):
    aiAnalysis: str
    reportPreview: str


class InherentRiskResponseDTO(ApiSchema):
    assessmentId: UUID
    analysisRunId: UUID | None
    status: AnalysisRunStatus
    inherentRisk: InherentRiskValueDTO
    topRiskDrivers: list[TopRiskDriverDTO]
    executiveSummary: ExecutiveSummaryDTO
    links: LinksDTO


class AnalysisRunCreateRequestDTO(ApiSchema):
    force: bool = False


class AnalysisRunCreateResponseDTO(ApiSchema):
    analysisRunId: UUID | str
    status: AnalysisRunStatus


class ExecutiveSummaryGenerateRequestDTO(ApiSchema):
    force: bool = False


class ExecutiveSummaryGenerateEnvelopeDTO(ApiSchema):
    text: str
    status: ExecutiveSummaryStatus
    generatedAt: datetime


class ExecutiveSummaryGenerateResponseDTO(ApiSchema):
    assessmentId: UUID
    analysisRunId: UUID
    executiveSummary: ExecutiveSummaryGenerateEnvelopeDTO


class AIAnalysisRunSummaryDTO(ApiSchema):
    analysisRunId: UUID | None
    status: AnalysisRunStatus | None
    createdAt: datetime | None


class AIAnalysisQuestionRowDTO(ApiSchema):
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
    reviewerRemarks: str | None


class AIAnalysisResponseDTO(ApiSchema):
    assessmentId: UUID
    latestAnalysisRun: AIAnalysisRunSummaryDTO
    questions: list[AIAnalysisQuestionRowDTO]


class IntakeHeaderDTO(ApiSchema):
    technologyName: str | None
    sourceSystem: str | None
    questionnaireVersion: str | None


class IntakeQuestionDTO(ApiSchema):
    questionId: UUID
    questionCode: str
    label: str
    answer: str | None
    responseType: str
    required: bool
    riskDomain: str


class IntakeSectionDTO(ApiSchema):
    code: str
    title: str
    questions: list[IntakeQuestionDTO]


class IntakeTriageQuestionDTO(ApiSchema):
    questionId: UUID
    questionCode: str
    label: str
    answer: str | None


class IntakeOverviewResponseDTO(ApiSchema):
    assessmentId: UUID
    header: IntakeHeaderDTO
    sections: list[IntakeSectionDTO]
    triage: list[IntakeTriageQuestionDTO]


class IntakeQuestionUpdateRequestDTO(ApiSchema):
    selectedOptionId: UUID | None = None
    answerValue: str | None = None

    @model_validator(mode="after")
    def validate_at_least_one_field_was_provided(self) -> "IntakeQuestionUpdateRequestDTO":
        if "selectedOptionId" not in self.model_fields_set and "answerValue" not in self.model_fields_set:
            raise ValueError("At least one of selectedOptionId or answerValue must be provided.")
        return self


class IntakeQuestionUpdateResponseDTO(ApiSchema):
    questionId: UUID
    selectedOptionId: UUID | None
    answerValue: str | None


class DocumentChecklistItemResponseDTO(ApiSchema):
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


class DocumentChecklistResponseDTO(ApiSchema):
    run_id: UUID
    assessment_id: UUID
    status: str
    summary_text: str | None
    summary_status: str
    limitations: list[object]
    created_at: datetime
    items: list[DocumentChecklistItemResponseDTO]


class DocumentChecklistItemReviewRequestDTO(ApiSchema):
    reviewer_verdict: ChecklistVerdict | None = None
    reason: str | None = None
    reviewed_by: str | None = None

    @model_validator(mode="after")
    def require_reason_for_non_null_verdict(self) -> "DocumentChecklistItemReviewRequestDTO":
        if self.reviewer_verdict is not None and (self.reason is None or not self.reason.strip()):
            raise ValueError("reason is required when reviewer_verdict is provided.")
        return self


class AssessmentDocumentResponseDTO(ApiSchema):
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


class AssessmentDocumentListResponseDTO(ApiSchema):
    documents: list[AssessmentDocumentResponseDTO]


class DocumentClassificationReviewRequestDTO(ApiSchema):
    document_type: DocumentType
    reason: str
    reviewed_by: str | None = None

    @model_validator(mode="after")
    def require_reason(self) -> "DocumentClassificationReviewRequestDTO":
        if not self.reason.strip():
            raise ValueError("reason is required.")
        return self


class DocumentClassificationReviewResponseDTO(ApiSchema):
    review_id: UUID
    document_id: UUID
    assessment_id: UUID
    document_type: str
    reason: str
    reviewed_by: str | None
    created_at: datetime
    effective_document_type: str


class ReportPreviewAssessmentDTO(ApiSchema):
    technologyName: str | None = None
    sourceSystem: str | None = None
    questionnaireVersion: str | None = None


class ReportPreviewRiskAssessmentDTO(ApiSchema):
    inherentRiskLevel: str | None = None
    executiveSummary: str | None = None
    status: str | None = None
    topRiskDrivers: list[dict[str, str]] = Field(default_factory=list)


class ReportPreviewBusinessContactDetailsDTO(ApiSchema):
    businessUnit: str | None = None
    sponsorBusinessOwner: str | None = None


class ReportPreviewSolutionOverviewDTO(ApiSchema):
    launchDate: str | None = None
    businessFunctionSolutionOverview: str | None = None


class ReportPreviewArchitectureDTO(ApiSchema):
    architectureDetails: str | None = None
    documentId: str | None = None
    filename: str | None = None
    contentType: str | None = None


class ReportPreviewHostingDTO(ApiSchema):
    hostingModel: str | None = None
    hostedBy: str | None = None
    accessedBy: str | None = None


class ReportPreviewDataHostedDTO(ApiSchema):
    dataResidency: str | None = None
    confidentiality: str | None = None
    integrity: str | None = None


class ReportPreviewDataFlowDTO(ApiSchema):
    dataFlow: str | None = None


class ReportPreviewBusinessContinuityDTO(ApiSchema):
    businessContinuityRating: str | None = None
    rpoRto: str | None = None
    backupAndRestore: str | None = None


class ReportPreviewThirdPartyMeasuresDTO(ApiSchema):
    thirdPartyAssessment: str | None = None
    sla: str | None = None


class ReportPreviewDocumentChecklistDTO(ApiSchema):
    summary: str | None = None
    status: str | None = None
    items: list[dict[str, object]] = Field(default_factory=list)
    missingRequiredCount: int | None = None


class ReportPreviewVendorReputationDTO(ApiSchema):
    summary: str | None = None


class ReportPreviewResponseDTO(ApiSchema):
    assessmentId: UUID
    generatedAt: datetime
    assessment: ReportPreviewAssessmentDTO
    riskAssessment: ReportPreviewRiskAssessmentDTO
    businessContactDetails: ReportPreviewBusinessContactDetailsDTO
    solutionOverview: ReportPreviewSolutionOverviewDTO
    architecture: ReportPreviewArchitectureDTO
    hosting: ReportPreviewHostingDTO
    dataHosted: ReportPreviewDataHostedDTO
    dataFlow: ReportPreviewDataFlowDTO
    businessContinuity: ReportPreviewBusinessContinuityDTO
    thirdPartyMeasures: ReportPreviewThirdPartyMeasuresDTO
    documentChecklist: ReportPreviewDocumentChecklistDTO
    vendorReputation: ReportPreviewVendorReputationDTO | None
    limitations: list[str] | None = None
