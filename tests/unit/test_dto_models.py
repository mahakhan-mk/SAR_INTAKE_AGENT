from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.models.dto import (
    AIAnalysisQuestionRowDTO,
    AIAnalysisResponseDTO,
    AIAnalysisRunSummaryDTO,
    IntakeHeaderDTO,
    IntakeOverviewResponseDTO,
    IntakeQuestionDTO,
    IntakeQuestionUpdateRequestDTO,
    IntakeQuestionUpdateResponseDTO,
    IntakeSectionDTO,
    IntakeTriageQuestionDTO,
)
from app.models.enums import AnalysisRunStatus, RiskLevel


def test_intake_overview_response_dto_serializes_expected_shape():
    dto = IntakeOverviewResponseDTO(
        assessmentId="00000000-0000-0000-0000-000000000001",
        header=IntakeHeaderDTO(
            technologyName="Microsoft 365 Copilot",
            sourceSystem="ServiceNow",
            questionnaireVersion="triage-v1",
        ),
        sections=[
            IntakeSectionDTO(
                code="general",
                title="General",
                questions=[
                    IntakeQuestionDTO(
                        questionId="00000000-0000-0000-0000-000000000002",
                        questionCode="GEN-001",
                        label="What is the product name?",
                        answer="Microsoft 365 Copilot",
                        responseType="single_select",
                        required=True,
                        riskDomain="Operations",
                    )
                ],
            )
        ],
        triage=[
            IntakeTriageQuestionDTO(
                questionId="00000000-0000-0000-0000-000000000003",
                questionCode="TRIAGE-001",
                label="Does the tool handle sensitive data?",
                answer="Yes",
            )
        ],
    )

    assert dto.model_dump(mode="json") == {
        "assessmentId": "00000000-0000-0000-0000-000000000001",
        "header": {
            "technologyName": "Microsoft 365 Copilot",
            "sourceSystem": "ServiceNow",
            "questionnaireVersion": "triage-v1",
        },
        "sections": [
            {
                "code": "general",
                "title": "General",
                "questions": [
                    {
                        "questionId": "00000000-0000-0000-0000-000000000002",
                        "questionCode": "GEN-001",
                        "label": "What is the product name?",
                        "answer": "Microsoft 365 Copilot",
                        "responseType": "single_select",
                        "required": True,
                        "riskDomain": "Operations",
                    }
                ],
            }
        ],
        "triage": [
                {
                    "questionId": "00000000-0000-0000-0000-000000000003",
                    "questionCode": "TRIAGE-001",
                "label": "Does the tool handle sensitive data?",
                "answer": "Yes",
            }
        ],
    }


def test_ai_analysis_response_dto_serializes_expected_shape():
    dto = AIAnalysisResponseDTO(
        assessmentId="00000000-0000-0000-0000-000000000001",
        latestAnalysisRun=AIAnalysisRunSummaryDTO(
            analysisRunId="00000000-0000-0000-0000-000000000002",
            status=AnalysisRunStatus.COMPLETED,
            createdAt=datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc),
        ),
        questions=[
            AIAnalysisQuestionRowDTO(
                questionId="00000000-0000-0000-0000-000000000003",
                questionNumber="TRIAGE-001",
                questionText="Does the tool handle sensitive data?",
                domain="Security",
                selectedOptionId="00000000-0000-0000-0000-000000000004",
                answerValue="Yes",
                riskBand=RiskLevel.HIGH,
                riskScore=3.0,
                riskSignal="High signal",
                whyItMatters="Sensitive data increases potential impact.",
                aiExplanation="The selected answer indicates elevated exposure.",
                confidence=1.0,
                reviewerRemarks="Reviewed by analyst",
            )
        ],
    )

    assert dto.model_dump(mode="json") == {
        "assessmentId": "00000000-0000-0000-0000-000000000001",
        "latestAnalysisRun": {
            "analysisRunId": "00000000-0000-0000-0000-000000000002",
            "status": "completed",
            "createdAt": "2026-07-21T12:00:00Z",
        },
        "questions": [
            {
                "questionId": "00000000-0000-0000-0000-000000000003",
                "questionNumber": "TRIAGE-001",
                "questionText": "Does the tool handle sensitive data?",
                "domain": "Security",
                "selectedOptionId": "00000000-0000-0000-0000-000000000004",
                "answerValue": "Yes",
                "riskBand": "high",
                "riskScore": 3.0,
                "riskSignal": "High signal",
                "whyItMatters": "Sensitive data increases potential impact.",
                "aiExplanation": "The selected answer indicates elevated exposure.",
                "confidence": 1.0,
                "reviewerRemarks": "Reviewed by analyst",
            }
        ],
    }


def test_ai_analysis_question_row_dto_allows_nullable_analysis_fields():
    dto = AIAnalysisQuestionRowDTO(
        questionId="00000000-0000-0000-0000-000000000005",
        questionNumber="TRIAGE-002",
        questionText="Is the deployment externally accessible?",
        domain="Network Security",
        selectedOptionId=None,
        answerValue=None,
        riskBand=None,
        riskScore=None,
        riskSignal=None,
        whyItMatters=None,
        aiExplanation=None,
        confidence=None,
        reviewerRemarks=None,
    )

    assert dto.questionId == UUID("00000000-0000-0000-0000-000000000005")
    assert dto.riskBand is None
    assert dto.riskScore is None
    assert dto.aiExplanation is None
    assert dto.reviewerRemarks is None


def test_intake_question_update_request_rejects_when_both_fields_are_omitted():
    with pytest.raises(ValidationError) as exc_info:
        IntakeQuestionUpdateRequestDTO()

    assert "At least one of selectedOptionId or answerValue must be provided." in str(exc_info.value)


def test_intake_question_update_request_accepts_selected_option_only():
    dto = IntakeQuestionUpdateRequestDTO(selectedOptionId="00000000-0000-0000-0000-000000000001")

    assert dto.selectedOptionId == UUID("00000000-0000-0000-0000-000000000001")
    assert dto.answerValue is None
    assert dto.model_fields_set == {"selectedOptionId"}


def test_intake_question_update_request_accepts_explicit_null_for_clearing():
    dto = IntakeQuestionUpdateRequestDTO(selectedOptionId=None)

    assert dto.selectedOptionId is None
    assert dto.answerValue is None
    assert dto.model_fields_set == {"selectedOptionId"}


def test_intake_question_update_request_accepts_both_fields_as_explicit_null():
    dto = IntakeQuestionUpdateRequestDTO(selectedOptionId=None, answerValue=None)

    assert dto.selectedOptionId is None
    assert dto.answerValue is None
    assert dto.model_fields_set == {"selectedOptionId", "answerValue"}


def test_intake_question_update_response_dto_serializes_expected_shape():
    dto = IntakeQuestionUpdateResponseDTO(
        questionId="00000000-0000-0000-0000-000000000004",
        selectedOptionId="00000000-0000-0000-0000-000000000005",
        answerValue="Yes",
    )

    assert dto.model_dump(mode="json") == {
        "questionId": "00000000-0000-0000-0000-000000000004",
        "selectedOptionId": "00000000-0000-0000-0000-000000000005",
        "answerValue": "Yes",
    }
