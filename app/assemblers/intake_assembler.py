
from __future__ import annotations

from app.models.dto import (
    IntakeHeaderDTO,
    IntakeOverviewResponseDTO,
    IntakeQuestionDTO,
    IntakeSectionDTO,
    IntakeTriageQuestionDTO,
)
from app.models.intake import IntakeOverviewRecord

SECTION_TITLES: dict[str, str] = {
    "general": "General",
    "hosting_data": "Hosting & Data",
    "solution": "Solution",
    "operations": "Operations",
    "security_access": "Security & Access",
    "findings": "Findings",
}


class IntakeAssembler:
    def to_dto(self, record: IntakeOverviewRecord) -> IntakeOverviewResponseDTO:
        return IntakeOverviewResponseDTO(
            assessmentId=str(record.assessment_id),
            header=IntakeHeaderDTO(
                technologyName=record.header.technology_name,
                sourceSystem=record.header.source_system,
                questionnaireVersion=record.header.questionnaire_version,
            ),
            sections=[
                IntakeSectionDTO(
                    code=self._require_section_code(section.code),
                    title=self._section_title(section.code),
                    questions=[
                        IntakeQuestionDTO(
                            questionId=str(question.question_id),
                            questionCode=question.question_code,
                            label=question.label,
                            answer=question.answer,
                            responseType=question.response_type,
                            required=question.required,
                            riskDomain=question.risk_domain,
                        )
                        for question in section.questions
                    ],
                )
                for section in record.sections
            ],
            triage=[
                IntakeTriageQuestionDTO(
                    questionId=str(question.question_id),
                    questionCode=question.question_code,
                    label=question.label,
                    answer=question.answer,
                )
                for question in record.triage
            ],
        )

    @staticmethod
    def _require_section_code(section_code: str | None) -> str:
        if section_code is None:
            raise ValueError("Unknown intake section code: None")
        return section_code

    def _section_title(self, section_code: str | None) -> str:
        code = self._require_section_code(section_code)
        title = SECTION_TITLES.get(code)
        if title is None:
            raise ValueError(f"Unknown intake section code: {code}")
        return title
