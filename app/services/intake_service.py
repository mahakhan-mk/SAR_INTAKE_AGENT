
from __future__ import annotations

from sqlalchemy.orm import Session

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

    def get_intake_overview(
        self,
        session: Session,
        assessment_id: str,
    ) -> IntakeOverviewResponseDTO:
        overview = self.assessment_repository.load_intake_overview(session, assessment_id)
        if overview is None:
            raise AssessmentNotFoundError()
        return self.assembler.to_dto(overview)

    def update_question_response(
        self,
        session: Session,
        *,
        assessment_id: str,
        question_id: str,
        payload: IntakeQuestionUpdateRequestDTO,
    ) -> IntakeQuestionUpdateResponseDTO:
        try:
            assessment = self.assessment_repository.get_assessment(session, assessment_id)
            if assessment is None:
                raise AssessmentNotFoundError()

            question = self.assessment_repository.get_question(session, question_id)
            if question is None:
                raise IntakeQuestionNotFoundError(f"Question {question_id} was not found.")
            if not question.is_visible:
                raise IntakeQuestionHiddenError(f"Question {question_id} is not visible.")

            if "selectedOptionId" in payload.model_fields_set and payload.selectedOptionId is not None:
                option = self.assessment_repository.get_question_option(
                    session,
                    question_id=question.id,
                    option_id=payload.selectedOptionId,
                )
                if option is None:
                    raise IntakeQuestionOptionError(
                        f"Option {payload.selectedOptionId} does not belong to question {question_id}."
                    )

            existing_response = self.response_repository.get_response(session, assessment_id, question.id)
            selected_option_id = (
                payload.selectedOptionId
                if "selectedOptionId" in payload.model_fields_set
                else (existing_response.selected_option_id if existing_response else None)
            )
            answer_value = (
                payload.answerValue
                if "answerValue" in payload.model_fields_set
                else (existing_response.answer_value if existing_response else None)
            )

            response = self.response_repository.upsert_response(
                session,
                assessment_id=assessment.id,
                question_definition_id=question.id,
                selected_option_id=selected_option_id,
                answer_value=answer_value,
            )
            session.commit()
            return IntakeQuestionUpdateResponseDTO(
                questionId=response.question_definition_id,
                selectedOptionId=response.selected_option_id,
                answerValue=response.answer_value,
            )
        except Exception:
            session.rollback()
            raise
