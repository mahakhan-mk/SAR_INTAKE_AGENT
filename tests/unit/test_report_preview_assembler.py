from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

from app.assemblers.report_preview_assembler import ReportPreviewAssembler
from app.models.enums import AnalysisRunStatus, RiskLevel


def build_assessment() -> SimpleNamespace:
    return SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        technology_name="Microsoft 365 Copilot",
        source_system="ServiceNow",
        questionnaire_version="2.0",
    )


def build_response(question_code: str, answer_value: object) -> SimpleNamespace:
    return SimpleNamespace(
        question_code=question_code,
        answer_value=answer_value,
    )


def build_analysis_snapshot() -> SimpleNamespace:
    return SimpleNamespace(
        status=AnalysisRunStatus.COMPLETED_WITH_LIMITATIONS,
        inherent_risk_level=RiskLevel.HIGH,
        executive_summary_text="Deterministic executive summary.",
        question_results=[
            SimpleNamespace(
                risk_domain="Security",
                risk_level=RiskLevel.CRITICAL,
                risk_weight=4.0,
            ),
            SimpleNamespace(
                risk_domain="Operations",
                risk_level=RiskLevel.HIGH,
                risk_weight=3.0,
            ),
            SimpleNamespace(
                risk_domain="Security",
                risk_level=RiskLevel.HIGH,
                risk_weight=2.0,
            ),
        ],
    )


def build_checklist_state() -> SimpleNamespace:
    return SimpleNamespace(
        run=SimpleNamespace(
            status="draft_with_limitations",
            summary_text="Checklist summary text.",
        ),
        items=[
            SimpleNamespace(
                item=SimpleNamespace(
                    id=UUID("00000000-0000-0000-0000-000000000101"),
                    document_type="SOC 2 Type II",
                    base_verdict="Required",
                ),
                effective_verdict="Required",
                detected_file_status="missing",
                detected_document_id=None,
                reviewer_verdict=None,
                reviewer_reason=None,
            ),
            SimpleNamespace(
                item=SimpleNamespace(
                    id=UUID("00000000-0000-0000-0000-000000000102"),
                    document_type="ISO 27001",
                    base_verdict="Required",
                ),
                effective_verdict="N/A",
                detected_file_status="uploaded",
                detected_document_id=UUID("00000000-0000-0000-0000-000000000202"),
                reviewer_verdict="N/A",
                reviewer_reason="Provided separately.",
            ),
            SimpleNamespace(
                item=SimpleNamespace(
                    id=UUID("00000000-0000-0000-0000-000000000103"),
                    document_type="Architecture Diagram",
                    base_verdict="Required",
                ),
                effective_verdict="Required",
                detected_file_status="missing",
                detected_document_id=None,
                reviewer_verdict=None,
                reviewer_reason=None,
            ),
        ],
    )


def build_architecture_document() -> SimpleNamespace:
    return SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000301"),
        original_filename="architecture-diagram.pdf",
        content_type="application/pdf",
        storage_container="sar-documents",
        storage_key="secret/blob/path.pdf",
        blob_url="https://example.blob.core.windows.net/sar-documents/secret/blob/path.pdf",
        sas_token="secret-token",
        account_key="secret-key",
    )


def test_full_input_maps_to_expected_report_preview_shape():
    assembler = ReportPreviewAssembler()

    dto = assembler.to_dto(
        assessment=build_assessment(),
        response_records=[
            build_response("what_business_unit_the_request_is_from", "Tax"),
            build_response("sponsoring_partner", "Jane Smith"),
            build_response("when_is_the_expected_launch_date", "2026-09-01"),
            build_response("what_is_the_function_and_purpose_of_the_application", "Supports analyst workflows."),
            build_response("hosting_solution", "SaaS"),
            build_response("solution_hosted_by", "Vendor"),
            build_response("solution_accessed_by", "Internal users"),
            build_response(
                "where_does_the_data_reside_and_type_of_data_housed_or_processed_by_the_solution",
                "United States",
            ),
            build_response("what_is_the_information_classification_for_data_confidentiality", "Confidential"),
            build_response("what_is_the_information_classification_for_data_integrity", "High"),
            build_response("please_describe_the_data_flows_of_the_solution", "Inbound from users, outbound to vendor."),
            build_response("business_continuity_rating", "Tier 2"),
            build_response(
                "what_are_the_required_or_expected_recovery_point_object_rpo_recovery_time_objective_rto_see_techology_definitions",
                "RPO 4 hours / RTO 8 hours",
            ),
            build_response("what_are_the_backup_and_restore_requirements", "Vendor-managed backups"),
            build_response(
                "has_a_security_assessment_on_3rd_parties_been_performed_and_reviewed_regularly_if_yes_please_provide_copy_of_the_report_i_e_soc_2_iso27k",
                "SOC 2 Type II",
            ),
            build_response("is_there_an_sla_document_available_if_yes_please_provide_for_review", "24x7 support"),
        ],
        analysis_snapshot=build_analysis_snapshot(),
        checklist_state=build_checklist_state(),
        architecture_document=build_architecture_document(),
        generated_at=datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
        questionnaire_version="2.0",
        source_system="ServiceNow",
    )

    assert dto.model_dump(mode="json", serialize_as_any=True) == {
        "assessmentId": "00000000-0000-0000-0000-000000000001",
        "generatedAt": "2026-07-27T12:00:00Z",
        "assessment": {
            "technologyName": "Microsoft 365 Copilot",
            "sourceSystem": "ServiceNow",
            "questionnaireVersion": "2.0",
        },
        "riskAssessment": {
            "inherentRiskLevel": "high",
            "executiveSummary": "Deterministic executive summary.",
            "status": "completed_with_limitations",
            "topRiskDrivers": [
                {"domain": "Security", "level": "critical"},
                {"domain": "Operations", "level": "high"},
            ],
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
            "documentId": "00000000-0000-0000-0000-000000000301",
            "filename": "architecture-diagram.pdf",
            "contentType": "application/pdf",
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
            "dataFlow": "Inbound from users, outbound to vendor.",
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
            "summary": "Checklist summary text.",
            "status": "draft_with_limitations",
            "items": [
                {
                    "itemId": "00000000-0000-0000-0000-000000000101",
                    "documentType": "SOC 2 Type II",
                    "baseVerdict": "Required",
                    "effectiveVerdict": "Required",
                    "detectedFileStatus": "missing",
                    "detectedDocumentId": None,
                    "reviewerVerdict": None,
                    "reviewerReason": None,
                },
                {
                    "itemId": "00000000-0000-0000-0000-000000000102",
                    "documentType": "ISO 27001",
                    "baseVerdict": "Required",
                    "effectiveVerdict": "N/A",
                    "detectedFileStatus": "uploaded",
                    "detectedDocumentId": "00000000-0000-0000-0000-000000000202",
                    "reviewerVerdict": "N/A",
                    "reviewerReason": "Provided separately.",
                },
                {
                    "itemId": "00000000-0000-0000-0000-000000000103",
                    "documentType": "Architecture Diagram",
                    "baseVerdict": "Required",
                    "effectiveVerdict": "Required",
                    "detectedFileStatus": "missing",
                    "detectedDocumentId": None,
                    "reviewerVerdict": None,
                    "reviewerReason": None,
                },
            ],
            "missingRequiredCount": 2,
        },
        "vendorReputation": None,
        "limitations": ["Vendor reputation is unavailable."],
    }


def test_missing_analysis_produces_partial_valid_dto():
    assembler = ReportPreviewAssembler()

    dto = assembler.to_dto(
        assessment=build_assessment(),
        response_records=[],
        analysis_snapshot=None,
        checklist_state=build_checklist_state(),
        architecture_document=build_architecture_document(),
    )
    payload = dto.model_dump(mode="json", serialize_as_any=True)

    assert payload["riskAssessment"]["status"] is None
    assert payload["riskAssessment"]["inherentRiskLevel"] is None
    assert payload["riskAssessment"]["executiveSummary"] is None
    assert payload["riskAssessment"]["topRiskDrivers"] == []
    assert "Risk assessment is unavailable." in payload["limitations"]


def test_missing_checklist_produces_partial_valid_dto():
    assembler = ReportPreviewAssembler()

    dto = assembler.to_dto(
        assessment=build_assessment(),
        response_records=[],
        analysis_snapshot=build_analysis_snapshot(),
        checklist_state=None,
        architecture_document=build_architecture_document(),
    )
    payload = dto.model_dump(mode="json", serialize_as_any=True)

    assert payload["documentChecklist"] == {
        "summary": None,
        "status": None,
        "items": [],
        "missingRequiredCount": None,
    }
    assert "Document checklist is unavailable." in payload["limitations"]


def test_missing_architecture_document_produces_null_metadata():
    assembler = ReportPreviewAssembler()

    dto = assembler.to_dto(
        assessment=build_assessment(),
        response_records=[],
        analysis_snapshot=build_analysis_snapshot(),
        checklist_state=build_checklist_state(),
        architecture_document=None,
    )
    payload = dto.model_dump(mode="json", serialize_as_any=True)

    assert payload["architecture"] == {
        "architectureDetails": None,
        "documentId": None,
        "filename": None,
        "contentType": None,
    }
    assert "Architecture document metadata is unavailable." in payload["limitations"]


def test_explicit_question_mapping_populates_only_mapped_fields():
    assembler = ReportPreviewAssembler()

    dto = assembler.to_dto(
        assessment=build_assessment(),
        response_records=[
            build_response("what_business_unit_the_request_is_from", "Consulting"),
            build_response("when_is_the_expected_launch_date", "2027-01-15"),
            build_response("hosting_solution", {"optionLabel": "On Prem"}),
            build_response("business_continuity_rating", "Tier 1"),
        ],
    )
    payload = dto.model_dump(mode="json", serialize_as_any=True)

    assert payload["businessContactDetails"]["businessUnit"] == "Consulting"
    assert payload["solutionOverview"]["launchDate"] == "2027-01-15"
    assert payload["hosting"]["hostingModel"] == "On Prem"
    assert payload["businessContinuity"]["businessContinuityRating"] == "Tier 1"


def test_unknown_question_code_is_ignored():
    assembler = ReportPreviewAssembler()

    dto = assembler.to_dto(
        assessment=build_assessment(),
        response_records=[
            build_response("not_a_real_code", "Should not appear"),
            build_response(
                "are_there_architecture_or_other_documents_available_that_can_be_leveraged_to_evaluate_this_solution_for_example_technical_architectural_document_diagram_if_yes_please_provide_for_review",
                "Yes",
            ),
        ],
    )
    payload = dto.model_dump(mode="json", serialize_as_any=True)

    assert payload["businessContactDetails"]["businessUnit"] is None
    assert payload["architecture"]["architectureDetails"] is None


def test_checklist_missing_required_count_uses_effective_verdict():
    assembler = ReportPreviewAssembler()

    dto = assembler.to_dto(
        assessment=build_assessment(),
        response_records=[],
        checklist_state=build_checklist_state(),
    )
    payload = dto.model_dump(mode="json", serialize_as_any=True)

    assert payload["documentChecklist"]["missingRequiredCount"] == 2


def test_output_does_not_expose_blob_storage_fields():
    assembler = ReportPreviewAssembler()

    dto = assembler.to_dto(
        assessment=build_assessment(),
        response_records=[],
        architecture_document=build_architecture_document(),
    )
    payload_text = str(dto.model_dump(mode="json", serialize_as_any=True))

    assert "storage_container" not in payload_text
    assert "storage_key" not in payload_text
    assert "blob_url" not in payload_text
    assert "sas_token" not in payload_text
    assert "account_key" not in payload_text


def test_launch_date_remains_under_solution_overview():
    assembler = ReportPreviewAssembler()

    dto = assembler.to_dto(
        assessment=build_assessment(),
        response_records=[build_response("when_is_the_expected_launch_date", "2026-12-31")],
    )
    payload = dto.model_dump(mode="json", serialize_as_any=True)

    assert payload["solutionOverview"]["launchDate"] == "2026-12-31"
    assert "launchDate" not in payload["assessment"]
    assert "launchDate" not in payload["riskAssessment"]


def test_architecture_details_remains_null_when_no_mapped_response_exists():
    assembler = ReportPreviewAssembler()

    dto = assembler.to_dto(
        assessment=build_assessment(),
        response_records=[
            build_response(
                "are_there_architecture_or_other_documents_available_that_can_be_leveraged_to_evaluate_this_solution_for_example_technical_architectural_document_diagram_if_yes_please_provide_for_review",
                "Diagram attached",
            )
        ],
        architecture_document=build_architecture_document(),
    )
    payload = dto.model_dump(mode="json", serialize_as_any=True)

    assert payload["architecture"]["architectureDetails"] is None
    assert payload["architecture"]["filename"] == "architecture-diagram.pdf"
