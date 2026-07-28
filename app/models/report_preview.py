from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

REPORT_PREVIEW_QUESTION_CODE_TO_FIELD_NAME: dict[str, str] = {
    "what_business_unit_the_request_is_from": "businessContactDetails.businessUnit",
    "sponsoring_partner": "businessContactDetails.sponsorBusinessOwner",
    "when_is_the_expected_launch_date": "solutionOverview.launchDate",
    "what_is_the_function_and_purpose_of_the_application": "solutionOverview.businessFunctionSolutionOverview",
    "hosting_solution": "hosting.hostingModel",
    "solution_hosted_by": "hosting.hostedBy",
    "solution_accessed_by": "hosting.accessedBy",
    "where_does_the_data_reside_and_type_of_data_housed_or_processed_by_the_solution": "dataHosted.dataResidency",
    "what_is_the_information_classification_for_data_confidentiality": "dataHosted.confidentiality",
    "what_is_the_information_classification_for_data_integrity": "dataHosted.integrity",
    "please_describe_the_data_flows_of_the_solution": "dataFlow.dataFlow",
    "business_continuity_rating": "businessContinuity.businessContinuityRating",
    "what_are_the_required_or_expected_recovery_point_object_rpo_recovery_time_objective_rto_see_techology_definitions": "businessContinuity.rpoRto",
    "what_are_the_backup_and_restore_requirements": "businessContinuity.backupAndRestore",
    "has_a_security_assessment_on_3rd_parties_been_performed_and_reviewed_regularly_if_yes_please_provide_copy_of_the_report_i_e_soc_2_iso27k": "thirdPartyMeasures.thirdPartyAssessment",
    "is_there_an_sla_document_available_if_yes_please_provide_for_review": "thirdPartyMeasures.sla",
}


class ReportPreviewAssessmentDTO(BaseModel):
    technologyName: str | None = None
    sourceSystem: str | None = None
    questionnaireVersion: str | None = None


class ReportPreviewRiskAssessmentDTO(BaseModel):
    inherentRiskLevel: str | None = None
    executiveSummary: str | None = None


class ReportPreviewBusinessContactDetailsDTO(BaseModel):
    businessUnit: str | None = None
    sponsorBusinessOwner: str | None = None


class ReportPreviewSolutionOverviewDTO(BaseModel):
    launchDate: str | None = None
    businessFunctionSolutionOverview: str | None = None


class ReportPreviewArchitectureDTO(BaseModel):
    architectureDetails: str | None = None


class ReportPreviewHostingDTO(BaseModel):
    hostingModel: str | None = None
    hostedBy: str | None = None
    accessedBy: str | None = None


class ReportPreviewDataHostedDTO(BaseModel):
    dataResidency: str | None = None
    confidentiality: str | None = None
    integrity: str | None = None


class ReportPreviewDataFlowDTO(BaseModel):
    dataFlow: str | None = None


class ReportPreviewBusinessContinuityDTO(BaseModel):
    businessContinuityRating: str | None = None
    rpoRto: str | None = None
    backupAndRestore: str | None = None


class ReportPreviewThirdPartyMeasuresDTO(BaseModel):
    thirdPartyAssessment: str | None = None
    sla: str | None = None


class ReportPreviewDocumentChecklistDTO(BaseModel):
    summary: str | None = None


class ReportPreviewVendorReputationDTO(BaseModel):
    summary: str | None = None


class ReportPreviewResponseDTO(BaseModel):
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
    vendorReputation: ReportPreviewVendorReputationDTO
    limitations: list[str] | None = None


__all__ = [
    "REPORT_PREVIEW_QUESTION_CODE_TO_FIELD_NAME",
    "ReportPreviewAssessmentDTO",
    "ReportPreviewRiskAssessmentDTO",
    "ReportPreviewBusinessContactDetailsDTO",
    "ReportPreviewSolutionOverviewDTO",
    "ReportPreviewArchitectureDTO",
    "ReportPreviewHostingDTO",
    "ReportPreviewDataHostedDTO",
    "ReportPreviewDataFlowDTO",
    "ReportPreviewBusinessContinuityDTO",
    "ReportPreviewThirdPartyMeasuresDTO",
    "ReportPreviewDocumentChecklistDTO",
    "ReportPreviewVendorReputationDTO",
    "ReportPreviewResponseDTO",
]
