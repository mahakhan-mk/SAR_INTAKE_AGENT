from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.dto import (
    IntakeHeaderDTO,
    IntakeOverviewResponseDTO,
    IntakeQuestionDTO,
    IntakeQuestionUpdateRequestDTO,
    IntakeQuestionUpdateResponseDTO,
    IntakeSectionDTO,
    IntakeTriageQuestionDTO,
)


def test_intake_overview_response_dto_serializes_expected_shape():
    dto = IntakeOverviewResponseDTO(
        assessmentId="assessment-1",
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
                        questionId="question-1",
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
                questionId="triage-1",
                questionCode="TRIAGE-001",
                label="Does the tool handle sensitive data?",
                answer="Yes",
            )
        ],
    )

    assert dto.model_dump() == {
        "assessmentId": "assessment-1",
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
                        "questionId": "question-1",
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
                "questionId": "triage-1",
                "questionCode": "TRIAGE-001",
                "label": "Does the tool handle sensitive data?",
                "answer": "Yes",
            }
        ],
    }


def test_intake_question_update_request_rejects_when_both_fields_are_omitted():
    with pytest.raises(ValidationError) as exc_info:
        IntakeQuestionUpdateRequestDTO()

    assert "At least one of selectedOptionId or answerValue must be provided." in str(exc_info.value)


def test_intake_question_update_request_accepts_selected_option_only():
    dto = IntakeQuestionUpdateRequestDTO(selectedOptionId="option-1")

    assert dto.selectedOptionId == "option-1"
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
        questionId="question-1",
        selectedOptionId="option-1",
        answerValue="Yes",
    )

    assert dto.model_dump() == {
        "questionId": "question-1",
        "selectedOptionId": "option-1",
        "answerValue": "Yes",
    }
