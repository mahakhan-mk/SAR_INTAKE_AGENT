from __future__ import annotations

from uuid import UUID

import pytest

from app.api.schemas import IntakeQuestionDTO, IntakeTriageQuestionDTO
from app.assemblers.intake_assembler import IntakeAssembler
from app.models.intake import (
    IntakeHeaderRecord,
    IntakeOverviewRecord,
    IntakeQuestionRecord,
    IntakeSectionRecord,
    IntakeTriageQuestionRecord,
)


def build_record(
    *,
    source_system: str | None = None,
    sections: list[IntakeSectionRecord] | None = None,
    triage: list[IntakeTriageQuestionRecord] | None = None,
) -> IntakeOverviewRecord:
    return IntakeOverviewRecord(
        assessment_id=UUID("00000000-0000-0000-0000-000000000100"),
        header=IntakeHeaderRecord(
            technology_name="Microsoft 365 Copilot",
            source_system=source_system,
            questionnaire_version="intake-v1",
        ),
        sections=sections or [],
        triage=triage or [],
    )


@pytest.mark.parametrize(
    ("section_code", "expected_title"),
    [
        ("general", "General"),
        ("hosting_data", "Hosting & Data"),
        ("solution", "Solution"),
        ("operations", "Operations"),
        ("security_access", "Security & Access"),
        ("findings", "Findings"),
    ],
)
def test_all_section_title_mappings(section_code: str, expected_title: str):
    assembler = IntakeAssembler()
    record = build_record(
        sections=[
            IntakeSectionRecord(
                code=section_code,
                questions=[],
            )
        ]
    )

    dto = assembler.to_dto(record)

    assert dto.sections[0].code == section_code
    assert dto.sections[0].title == expected_title


def test_question_field_mapping_and_preserved_ordering():
    assembler = IntakeAssembler()
    record = build_record(
        sections=[
            IntakeSectionRecord(
                code="general",
                questions=[
                    IntakeQuestionRecord(
                        question_id=UUID("00000000-0000-0000-0000-000000000002"),
                        question_code="GEN-002",
                        label="Second question",
                        answer="No",
                        response_type="single_select",
                        required=False,
                        risk_domain="Operations",
                        section_code="general",
                        response_id=UUID("00000000-0000-0000-0000-000000000202"),
                        selected_option_id=UUID("00000000-0000-0000-0000-000000000302"),
                        answer_value="No",
                    ),
                    IntakeQuestionRecord(
                        question_id=UUID("00000000-0000-0000-0000-000000000001"),
                        question_code="GEN-001",
                        label="First question",
                        answer="Yes",
                        response_type="text",
                        required=True,
                        risk_domain="Security",
                        section_code="general",
                        response_id=UUID("00000000-0000-0000-0000-000000000201"),
                        selected_option_id=None,
                        answer_value="Yes",
                    ),
                ],
            ),
            IntakeSectionRecord(
                code="operations",
                questions=[
                    IntakeQuestionRecord(
                        question_id=UUID("00000000-0000-0000-0000-000000000003"),
                        question_code="OPS-001",
                        label="Operations question",
                        answer=None,
                        response_type="single_select",
                        required=True,
                        risk_domain="Operations",
                        section_code="operations",
                        response_id=None,
                        selected_option_id=None,
                        answer_value=None,
                    )
                ],
            ),
        ]
    )

    dto = assembler.to_dto(record)

    assert [section.code for section in dto.sections] == ["general", "operations"]
    assert [question.questionId for question in dto.sections[0].questions] == [
        UUID("00000000-0000-0000-0000-000000000002"),
        UUID("00000000-0000-0000-0000-000000000001"),
    ]
    assert IntakeQuestionDTO.model_validate(dto.sections[0].questions[0]).model_dump(mode="json") == {
        "questionId": "00000000-0000-0000-0000-000000000002",
        "questionCode": "GEN-002",
        "label": "Second question",
        "answer": "No",
        "responseType": "single_select",
        "required": False,
        "riskDomain": "Operations",
    }
    assert IntakeQuestionDTO.model_validate(dto.sections[0].questions[1]).model_dump(mode="json") == {
        "questionId": "00000000-0000-0000-0000-000000000001",
        "questionCode": "GEN-001",
        "label": "First question",
        "answer": "Yes",
        "responseType": "text",
        "required": True,
        "riskDomain": "Security",
    }


def test_triage_mapping():
    assembler = IntakeAssembler()
    record = build_record(
        triage=[
            IntakeTriageQuestionRecord(
                question_id=UUID("00000000-0000-0000-0000-000000000402"),
                question_code="TRIAGE-002",
                label="Second triage question",
                answer="No",
                response_id=UUID("00000000-0000-0000-0000-000000000502"),
                selected_option_id=UUID("00000000-0000-0000-0000-000000000602"),
                answer_value="No",
            ),
            IntakeTriageQuestionRecord(
                question_id=UUID("00000000-0000-0000-0000-000000000401"),
                question_code="TRIAGE-001",
                label="First triage question",
                answer="Yes",
                response_id=UUID("00000000-0000-0000-0000-000000000501"),
                selected_option_id=UUID("00000000-0000-0000-0000-000000000601"),
                answer_value="Yes",
            ),
        ]
    )

    dto = assembler.to_dto(record)

    assert [question.questionId for question in dto.triage] == [
        UUID("00000000-0000-0000-0000-000000000402"),
        UUID("00000000-0000-0000-0000-000000000401"),
    ]
    assert IntakeTriageQuestionDTO.model_validate(dto.triage[0]).model_dump(mode="json") == {
        "questionId": "00000000-0000-0000-0000-000000000402",
        "questionCode": "TRIAGE-002",
        "label": "Second triage question",
        "answer": "No",
    }


def test_nullable_source_system_is_preserved():
    assembler = IntakeAssembler()
    record = build_record(source_system=None)

    dto = assembler.to_dto(record)

    assert dto.header.technologyName == "Microsoft 365 Copilot"
    assert dto.header.sourceSystem is None
    assert dto.header.questionnaireVersion == "intake-v1"


def test_unknown_section_code_raises_clear_error():
    assembler = IntakeAssembler()
    record = build_record(
        sections=[
            IntakeSectionRecord(
                code="alpha",
                questions=[],
            )
        ]
    )

    with pytest.raises(ValueError, match="Unknown intake section code: alpha"):
        assembler.to_dto(record)
