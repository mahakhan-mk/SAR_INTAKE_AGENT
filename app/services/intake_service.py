
from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.assemblers.intake_assembler import IntakeAssembler
from app.application.models import IntakeOverviewResult, IntakeQuestionUpdateCommand, IntakeQuestionUpdateResult
from app.domain.errors import (
    AssessmentNotFoundError,
    IntakeQuestionHiddenError,
    IntakeQuestionNotFoundError,
    IntakeQuestionOptionError,
)
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.response_repository import ResponseRepository


class IntakeService:
    def __init__(
        self,
        assessment_repository: AssessmentRepository,
        response_repository: ResponseRepository,
        assembler: IntakeAssembler,
    ) -> None:
        self.assessment_repository = assessment_repository
        self.response_repository = response_repository
        self.assembler = assembler

    async def get_intake_overview(
        self,
        session: AsyncSession,
        assessment_id: UUID,
    ) -> IntakeOverviewResult:
        overview = await self.assessment_repository.load_intake_overview(session, assessment_id)
        if overview is None:
            raise AssessmentNotFoundError()
        return self.assembler.to_dto(overview)

    async def update_question_response(
        self,
        session: AsyncSession,
        *,
        assessment_id: UUID,
        question_id: UUID,
        payload: IntakeQuestionUpdateCommand,
    ) -> IntakeQuestionUpdateResult:
        assessment = await self.assessment_repository.get_assessment(session, assessment_id)
        if assessment is None:
            raise AssessmentNotFoundError()

        question = await self.assessment_repository.get_question(session, question_id)
        if question is None:
            raise IntakeQuestionNotFoundError(f"Question {question_id} was not found.")
        if not question.is_visible:
            raise IntakeQuestionHiddenError(f"Question {question_id} is not visible.")

        if "selectedOptionId" in payload.fields_set and payload.selected_option_id is not None:
            option = await self.assessment_repository.get_question_option(
                session,
                question_id=question.id,
                option_id=payload.selected_option_id,
            )
            if option is None:
                raise IntakeQuestionOptionError(
                    f"Option {payload.selected_option_id} does not belong to question {question_id}."
                )
        else:
            option = None

        existing_response = await self.response_repository.get_response(session, assessment_id, question.id)
        if "selectedOptionId" in payload.fields_set and payload.selected_option_id is not None:
            answer_value: dict[str, str] | str | None = {
                "optionCode": option.option_code,
                "optionLabel": option.option_label,
                "selectedOptionId": str(option.id),
            }
        elif "answerValue" in payload.fields_set:
            answer_value = payload.answer_value
        else:
            answer_value = existing_response.answer_value if existing_response else None

        response = await self.response_repository.upsert_response(
            session,
            assessment_id=assessment.id,
            question_id=question.id,
            answer_value=answer_value,
        )
        normalized_answer_value = self.assessment_repository.normalize_answer_value(response.answer_value)
        return IntakeQuestionUpdateResult(
            questionId=response.question_id,
            selectedOptionId=self._extract_selected_option_id(response.answer_value, normalized_answer_value),
            answerValue=normalized_answer_value,
        )

    @staticmethod
    def _extract_selected_option_id(
        answer_value: object | None,
        normalized_answer_value: str | None,
    ) -> UUID | None:
        if isinstance(answer_value, dict):
            selected_option_id = answer_value.get("selectedOptionId")
            if isinstance(selected_option_id, str):
                try:
                    return UUID(selected_option_id)
                except ValueError:
                    return None
        if normalized_answer_value is None:
            return None
        return None
