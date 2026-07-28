from __future__ import annotations

from datetime import datetime, timezone
import uuid

import pytest

from app.assemblers.report_preview_assembler import ReportPreviewAssembler
from app.models.database import AssessmentDocument, QuestionAnalysisRun, QuestionRiskResult
from app.models.enums import (
    AnalysisRunStatus,
    AssessmentDocumentSystemType,
    ChecklistVerdict,
    DocumentType,
    RiskLevel,
)
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.document_checklist_repository import ChecklistItemInput, DocumentChecklistRepository
from app.repositories.document_repository import DocumentRepository
from app.services.report_service import ReportPreviewService
from tests.conftest import add_question_with_options, add_questionnaire_version, add_response

pytestmark = pytest.mark.asyncio


def build_service(
    *,
    assessment_repository: AssessmentRepository | None = None,
    analysis_repository: AnalysisRepository | None = None,
    checklist_repository: DocumentChecklistRepository | None = None,
    document_repository: DocumentRepository | None = None,
) -> ReportPreviewService:
    return ReportPreviewService(
        assessment_repository=assessment_repository or AssessmentRepository(),
        analysis_repository=analysis_repository or AnalysisRepository(),
        checklist_repository=checklist_repository or DocumentChecklistRepository(),
        document_repository=document_repository or DocumentRepository(),
        assembler=ReportPreviewAssembler(),
    )


async def test_get_report_preview_returns_complete_response(db_session, seeded_assessment):
    await seed_report_preview_inputs(db_session, seeded_assessment)

    dto = await build_service().get_report_preview(db_session, seeded_assessment["assessment_id"])
    payload = dto.model_dump(mode="json", serialize_as_any=True)

    assert payload["assessmentId"] == str(seeded_assessment["assessment_id"])
    assert payload["assessment"]["technologyName"] == "Copilot"
    assert payload["assessment"]["questionnaireVersion"] == "intake-v2"
    assert payload["riskAssessment"]["status"] == "completed_with_limitations"
    assert payload["riskAssessment"]["inherentRiskLevel"] == "high"
    assert payload["riskAssessment"]["topRiskDrivers"] == [
        {"domain": "Security", "level": "critical"},
        {"domain": "Operations", "level": "high"},
    ]
    assert payload["solutionOverview"]["launchDate"] == "2026-09-01"
    assert payload["documentChecklist"]["missingRequiredCount"] == 2
    assert payload["architecture"] == {
        "architectureDetails": None,
        "documentId": str(TEST_ARCHITECTURE_DOCUMENT_ID),
        "filename": "architecture.pdf",
        "contentType": "application/pdf",
    }
    assert payload["vendorReputation"] is None
    assert payload["limitations"] == ["Vendor reputation is unavailable."]


async def test_get_report_preview_service_does_not_trigger_generation_or_blob_access(db_session, seeded_assessment):
    await seed_report_preview_inputs(db_session, seeded_assessment)

    class GuardChecklistRepository(DocumentChecklistRepository):
        async def create_checklist_run(self, *args, **kwargs):
            raise AssertionError("Report preview must not generate a checklist run.")

        async def update_run_summary(self, *args, **kwargs):
            raise AssertionError("Report preview must not generate checklist summaries.")

    class GuardDocumentRepository(DocumentRepository):
        async def list_active_documents_by_assessment(self, *args, **kwargs):
            raise AssertionError("Report preview must not enumerate active documents for Blob-like access.")

        async def create_assessment_document(self, *args, **kwargs):
            raise AssertionError("Report preview must not upload or create documents.")

        async def append_classification_review(self, *args, **kwargs):
            raise AssertionError("Report preview must not create classification reviews.")

    dto = await build_service(
        checklist_repository=GuardChecklistRepository(),
        document_repository=GuardDocumentRepository(),
    ).get_report_preview(db_session, seeded_assessment["assessment_id"])

    payload = dto.model_dump(mode="json", serialize_as_any=True)
    assert payload["architecture"]["documentId"] == str(TEST_ARCHITECTURE_DOCUMENT_ID)
    assert payload["documentChecklist"]["summary"] == "Checklist summary text."


TEST_ARCHITECTURE_DOCUMENT_ID = uuid.UUID("00000000-0000-0000-0000-000000000301")


async def seed_report_preview_inputs(db_session, seeded_assessment: dict[str, uuid.UUID]) -> None:
    intake_version = await add_questionnaire_version(
        db_session,
        questionnaire_type="intake",
        version="intake-v2",
    )
    mapped_questions = [
        (
            "what_business_unit_the_request_is_from",
            "general",
            "single_select",
            {"optionLabel": "Tax"},
            [("Tax", RiskLevel.LOW, 0.0, "Low signal")],
        ),
        (
            "sponsoring_partner",
            "general",
            "text",
            "Jane Smith",
            [("Placeholder", RiskLevel.LOW, 0.0, "Low signal")],
        ),
        (
            "when_is_the_expected_launch_date",
            "solution",
            "text",
            "2026-09-01",
            [("Placeholder", RiskLevel.LOW, 0.0, "Low signal")],
        ),
        (
            "what_is_the_function_and_purpose_of_the_application",
            "general",
            "text",
            "Supports analyst workflows.",
            [("Placeholder", RiskLevel.LOW, 0.0, "Low signal")],
        ),
    ]
    for question_code, section_code, response_type, answer_value, options in mapped_questions:
        question, option_models = await add_question_with_options(
            db_session,
            intake_version.id,
            risk_domain="Operations",
            question_code=question_code,
            section_code=section_code,
            response_type=response_type,
            options=options,
        )
        selected_option = option_models[0] if response_type == "single_select" else None
        await add_response(
            db_session,
            seeded_assessment["assessment_id"],
            question,
            selected_option,
            answer_value=answer_value,
        )

    security_question, security_options = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        question_code="TRIAGE-SEC-001",
        options=[
            ("Selected", RiskLevel.CRITICAL, 4.0, "Critical security signal."),
            ("Fallback", RiskLevel.LOW, 1.0, "Low signal."),
        ],
    )
    operations_question, operations_options = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Operations",
        question_code="TRIAGE-OPS-001",
        options=[
            ("Selected", RiskLevel.HIGH, 3.0, "Operational signal."),
            ("Fallback", RiskLevel.LOW, 1.0, "Low signal."),
        ],
    )
    security_response = await add_response(
        db_session,
        seeded_assessment["assessment_id"],
        security_question,
        security_options[0],
    )
    operations_response = await add_response(
        db_session,
        seeded_assessment["assessment_id"],
        operations_question,
        operations_options[0],
    )

    run = QuestionAnalysisRun(
        id=uuid.uuid4(),
        assessment_id=seeded_assessment["assessment_id"],
        status=AnalysisRunStatus.COMPLETED_WITH_LIMITATIONS.value,
        scoring_rule_version="preview-v1",
        triage_score=3.5,
        inherent_score=80.0,
        inherent_risk_level=RiskLevel.HIGH.value,
        executive_summary_text="Deterministic executive summary.",
        executive_summary_model="gpt-5-test",
        executive_summary_prompt_version="v1",
        executive_summary_input_hash="preview-hash",
        executive_summary_generated_at=datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
    )
    db_session.add(run)
    await db_session.flush()
    db_session.add_all(
        [
            QuestionRiskResult(
                id=uuid.uuid4(),
                analysis_run_id=run.id,
                response_id=security_response.id,
                risk_domain="Security",
                risk_score=4.0,
                risk_level=RiskLevel.CRITICAL.value,
                risk_impact="Critical rationale.",
                explanation="Critical explanation.",
                confidence=1.0,
                risk_signal="Critical security signal.",
                input_snapshot={
                    "questionCode": security_question.question_code,
                    "questionId": str(security_question.id),
                    "questionText": security_question.question_text,
                    "selectedOptionId": str(security_options[0].id),
                    "selectedOptionLabel": security_options[0].option_label,
                    "selectedResponse": security_options[0].option_label,
                    "riskWeight": 4.0,
                    "maxRiskWeight": 4.0,
                    "whyItMatters": "Critical rationale.",
                    "riskSignal": "Critical security signal.",
                },
            ),
            QuestionRiskResult(
                id=uuid.uuid4(),
                analysis_run_id=run.id,
                response_id=operations_response.id,
                risk_domain="Operations",
                risk_score=3.0,
                risk_level=RiskLevel.HIGH.value,
                risk_impact="Operational rationale.",
                explanation="Operational explanation.",
                confidence=1.0,
                risk_signal="Operational signal.",
                input_snapshot={
                    "questionCode": operations_question.question_code,
                    "questionId": str(operations_question.id),
                    "questionText": operations_question.question_text,
                    "selectedOptionId": str(operations_options[0].id),
                    "selectedOptionLabel": operations_options[0].option_label,
                    "selectedResponse": operations_options[0].option_label,
                    "riskWeight": 3.0,
                    "maxRiskWeight": 3.0,
                    "whyItMatters": "Operational rationale.",
                    "riskSignal": "Operational signal.",
                },
            ),
        ]
    )

    checklist_run = await DocumentChecklistRepository().create_checklist_run(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        status="draft_with_limitations",
        summary_text="Checklist summary text.",
        items=[
            ChecklistItemInput(DocumentType.SOC2_TYPE_II, ChecklistVerdict.REQUIRED, 1),
            ChecklistItemInput(DocumentType.ISO_27001, ChecklistVerdict.REQUIRED, 2),
            ChecklistItemInput(DocumentType.ARCHITECTURE_DIAGRAM, ChecklistVerdict.REQUIRED, 3),
        ],
        input_snapshot={
            "assessmentId": str(seeded_assessment["assessment_id"]),
            "items": [
                {
                    "documentType": DocumentType.SOC2_TYPE_II.value,
                    "detectedDocumentIds": [],
                },
                {
                    "documentType": DocumentType.ISO_27001.value,
                    "detectedDocumentIds": [str(uuid.uuid4())],
                },
                {
                    "documentType": DocumentType.ARCHITECTURE_DIAGRAM.value,
                    "detectedDocumentIds": [],
                },
            ],
        },
        limitations=[],
    )
    await DocumentChecklistRepository().append_checklist_verdict_review(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        source_item_id=checklist_run.items[1].id,
        document_type=DocumentType.ISO_27001,
        reviewer_verdict=ChecklistVerdict.NOT_APPLICABLE,
        reason="Provided separately.",
    )

    db_session.add(
        AssessmentDocument(
            id=TEST_ARCHITECTURE_DOCUMENT_ID,
            assessment_id=seeded_assessment["assessment_id"],
            original_filename="architecture.pdf",
            content_type="application/pdf",
            file_size_bytes=128,
            sha256="sha-architecture",
            storage_container="sar-documents",
            storage_key="sensitive/path/architecture.pdf",
            upload_source="sar_request",
            system_document_type=AssessmentDocumentSystemType.ARCHITECTURE_DIAGRAM.value,
            created_at=datetime(2026, 7, 27, 11, 30, tzinfo=timezone.utc),
            document_metadata={},
        )
    )
    await db_session.commit()
