
from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AssessmentNotFoundError
from app.assemblers.intake_assembler import IntakeAssembler
from app.models.dto import (
    IntakeOverviewResponseDTO,
    IntakeQuestionUpdateRequestDTO,
    IntakeQuestionUpdateResponseDTO,
)
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.response_repository import ResponseRepository


class IntakeQuestionNotFoundError(LookupError):
    pass


class IntakeQuestionHiddenError(LookupError):
    pass


class IntakeQuestionOptionError(ValueError):
    pass


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
    ) -> IntakeOverviewResponseDTO:
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
        payload: IntakeQuestionUpdateRequestDTO,
    ) -> IntakeQuestionUpdateResponseDTO:
        try:
            assessment = await self.assessment_repository.get_assessment(session, assessment_id)
            if assessment is None:
                raise AssessmentNotFoundError()

            question = await self.assessment_repository.get_question(session, question_id)
            if question is None:
                raise IntakeQuestionNotFoundError(f"Question {question_id} was not found.")
            if not question.is_visible:
                raise IntakeQuestionHiddenError(f"Question {question_id} is not visible.")

            if "selectedOptionId" in payload.model_fields_set and payload.selectedOptionId is not None:
                option = await self.assessment_repository.get_question_option(
                    session,
                    question_id=question.id,
                    option_id=payload.selectedOptionId,
                )
                if option is None:
                    raise IntakeQuestionOptionError(
                        f"Option {payload.selectedOptionId} does not belong to question {question_id}."
                    )
            else:
                option = None

            existing_response = await self.response_repository.get_response(session, assessment_id, question.id)
            existing_answer_value = self.assessment_repository.normalize_answer_value(
                existing_response.answer_value if existing_response else None
            )
            answer_value = (
                option.label
                if "selectedOptionId" in payload.model_fields_set and payload.selectedOptionId is not None
                else (
                    payload.answerValue
                    if "answerValue" in payload.model_fields_set
                    else existing_answer_value
                )
            )
            if "selectedOptionId" in payload.model_fields_set and payload.selectedOptionId is None:
                answer_value = (
                    payload.answerValue
                    if "answerValue" in payload.model_fields_set
                    else existing_answer_value
                )

            selected_option_id = payload.selectedOptionId if "selectedOptionId" in payload.model_fields_set else None
            if "selectedOptionId" not in payload.model_fields_set and answer_value is not None:
                matched_option = await self.assessment_repository.get_question_option_by_label(
                    session,
                    question_id=question.id,
                    option_label=answer_value,
                )
                selected_option_id = matched_option.id if matched_option is not None else None
            reviewer_remarks = (
                payload.reviewerRemarks
                if "reviewerRemarks" in payload.model_fields_set
                else (existing_response.reviewer_remarks if existing_response else None)
            )

            response = await self.response_repository.upsert_response(
                session,
                assessment_id=assessment.id,
                question_definition_id=question.id,
                selected_option_id=selected_option_id,
                answer_value=answer_value,
                reviewer_remarks=reviewer_remarks,
                reviewer_remarks_was_provided="reviewerRemarks" in payload.model_fields_set,
            )
            await session.commit()
            return IntakeQuestionUpdateResponseDTO(
                questionId=str(response.question_definition_id),
                selectedOptionId=str(response.selected_option_id) if response.selected_option_id is not None else None,
                answerValue=self.assessment_repository.normalize_answer_value(response.answer_value),
                reviewerRemarks=response.reviewer_remarks,
            )
        except Exception:
            await session.rollback()
            raise
