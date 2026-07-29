from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from app.api.schemas import (
    ReportPreviewArchitectureDTO,
    ReportPreviewAssessmentDTO,
    ReportPreviewBusinessContactDetailsDTO,
    ReportPreviewBusinessContinuityDTO,
    ReportPreviewDataFlowDTO,
    ReportPreviewDataHostedDTO,
    ReportPreviewDocumentChecklistDTO,
    ReportPreviewHostingDTO,
    ReportPreviewResponseDTO,
    ReportPreviewRiskAssessmentDTO,
    ReportPreviewSolutionOverviewDTO,
    ReportPreviewThirdPartyMeasuresDTO,
    ReportPreviewVendorReputationDTO,
)
from app.models.report_preview import (
    REPORT_PREVIEW_QUESTION_CODE_TO_FIELD_NAME,
)


def test_report_preview_response_dto_serializes_expected_shape():
    dto = ReportPreviewResponseDTO(
        assessmentId="00000000-0000-0000-0000-000000000001",
        generatedAt=datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
        assessment=ReportPreviewAssessmentDTO(
            technologyName="Microsoft 365 Copilot",
            sourceSystem="ServiceNow",
            questionnaireVersion="2.0",
        ),
        riskAssessment=ReportPreviewRiskAssessmentDTO(
            inherentRiskLevel="high",
            executiveSummary="Deterministic summary text.",
        ),
        businessContactDetails=ReportPreviewBusinessContactDetailsDTO(
            businessUnit="Tax",
            sponsorBusinessOwner="Jane Smith",
        ),
        solutionOverview=ReportPreviewSolutionOverviewDTO(
            launchDate="2026-09-01",
            businessFunctionSolutionOverview="Supports analyst workflows.",
        ),
        architecture=ReportPreviewArchitectureDTO(
            architectureDetails=None,
        ),
        hosting=ReportPreviewHostingDTO(
            hostingModel="SaaS",
            hostedBy="Vendor",
            accessedBy="Internal users",
        ),
        dataHosted=ReportPreviewDataHostedDTO(
            dataResidency="United States",
            confidentiality="Confidential",
            integrity="High",
        ),
        dataFlow=ReportPreviewDataFlowDTO(
            dataFlow="Users submit data through the vendor portal.",
        ),
        businessContinuity=ReportPreviewBusinessContinuityDTO(
            businessContinuityRating="Tier 2",
            rpoRto="RPO 4 hours / RTO 8 hours",
            backupAndRestore="Vendor-managed backups",
        ),
        thirdPartyMeasures=ReportPreviewThirdPartyMeasuresDTO(
            thirdPartyAssessment="SOC 2 Type II",
            sla="24x7 support",
        ),
        documentChecklist=ReportPreviewDocumentChecklistDTO(summary=None),
        vendorReputation=ReportPreviewVendorReputationDTO(summary=None),
        limitations=["Architecture details were not provided."],
    )

    assert dto.model_dump(mode="json") == {
        "assessmentId": "00000000-0000-0000-0000-000000000001",
        "generatedAt": "2026-07-27T12:00:00Z",
        "assessment": {
            "technologyName": "Microsoft 365 Copilot",
            "sourceSystem": "ServiceNow",
            "questionnaireVersion": "2.0",
        },
        "riskAssessment": {
            "inherentRiskLevel": "high",
            "executiveSummary": "Deterministic summary text.",
            "status": None,
            "topRiskDrivers": [],
        },
        "businessContactDetails": {
            "businessUnit": "Tax",
            "sponsorBusinessOwner": "Jane Smith",
        },
        "solutionOverview": {
            "launchDate": "2026-09-01",
            "businessFunctionSolutionOverview": "Supports analyst workflows.",
        },
        "architecture": {
            "architectureDetails": None,
            "documentId": None,
            "filename": None,
            "contentType": None,
        },
        "hosting": {
            "hostingModel": "SaaS",
            "hostedBy": "Vendor",
            "accessedBy": "Internal users",
        },
        "dataHosted": {
            "dataResidency": "United States",
            "confidentiality": "Confidential",
            "integrity": "High",
        },
        "dataFlow": {
            "dataFlow": "Users submit data through the vendor portal.",
        },
        "businessContinuity": {
            "businessContinuityRating": "Tier 2",
            "rpoRto": "RPO 4 hours / RTO 8 hours",
            "backupAndRestore": "Vendor-managed backups",
        },
        "thirdPartyMeasures": {
            "thirdPartyAssessment": "SOC 2 Type II",
            "sla": "24x7 support",
        },
        "documentChecklist": {
            "summary": None,
            "status": None,
            "items": [],
            "missingRequiredCount": None,
        },
        "vendorReputation": {
            "summary": None,
        },
        "limitations": ["Architecture details were not provided."],
    }


def test_report_preview_response_dto_preserves_nulls_for_optional_fields():
    dto = ReportPreviewResponseDTO(
        assessmentId="00000000-0000-0000-0000-000000000001",
        generatedAt=datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
        assessment=ReportPreviewAssessmentDTO(),
        riskAssessment=ReportPreviewRiskAssessmentDTO(),
        businessContactDetails=ReportPreviewBusinessContactDetailsDTO(),
        solutionOverview=ReportPreviewSolutionOverviewDTO(),
        architecture=ReportPreviewArchitectureDTO(),
        hosting=ReportPreviewHostingDTO(),
        dataHosted=ReportPreviewDataHostedDTO(),
        dataFlow=ReportPreviewDataFlowDTO(),
        businessContinuity=ReportPreviewBusinessContinuityDTO(),
        thirdPartyMeasures=ReportPreviewThirdPartyMeasuresDTO(),
        documentChecklist=ReportPreviewDocumentChecklistDTO(),
        vendorReputation=ReportPreviewVendorReputationDTO(),
        limitations=None,
    )

    payload = dto.model_dump(mode="json")

    assert dto.assessmentId == UUID("00000000-0000-0000-0000-000000000001")
    assert payload["assessment"]["technologyName"] is None
    assert payload["riskAssessment"]["inherentRiskLevel"] is None
    assert payload["businessContactDetails"]["businessUnit"] is None
    assert payload["solutionOverview"]["launchDate"] is None
    assert payload["architecture"]["architectureDetails"] is None
    assert payload["hosting"]["hostingModel"] is None
    assert payload["dataHosted"]["dataResidency"] is None
    assert payload["dataFlow"]["dataFlow"] is None
    assert payload["businessContinuity"]["rpoRto"] is None
    assert payload["thirdPartyMeasures"]["thirdPartyAssessment"] is None
    assert payload["documentChecklist"]["summary"] is None
    assert payload["vendorReputation"]["summary"] is None
    assert payload["limitations"] is None


def test_report_preview_question_code_mapping_uses_only_explicit_seeded_codes():
    assert REPORT_PREVIEW_QUESTION_CODE_TO_FIELD_NAME == {
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
    assert "architecture.architectureDetails" not in REPORT_PREVIEW_QUESTION_CODE_TO_FIELD_NAME.values()
