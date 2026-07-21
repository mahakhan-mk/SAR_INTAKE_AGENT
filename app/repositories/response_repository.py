
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.database import AssessmentResponse


class ResponseRepository:
    def get_response(
        self,
        session: Session,
        assessment_id: str,
        question_definition_id: str,
    ) -> AssessmentResponse | None:
        return session.execute(
            select(AssessmentResponse).where(
                AssessmentResponse.assessment_id == assessment_id,
                AssessmentResponse.question_definition_id == question_definition_id,
            )
        ).scalars().first()

    def upsert_response(
        self,
        session: Session,
        *,
        assessment_id: str,
        question_definition_id: str,
        selected_option_id: str | None,
        answer_value: str | None,
    ) -> AssessmentResponse:
        response = self.get_response(session, assessment_id, question_definition_id)
        if response is None:
            response = AssessmentResponse(
                assessment_id=assessment_id,
                question_definition_id=question_definition_id,
                selected_option_id=selected_option_id,
                answer_value=answer_value,
            )
            session.add(response)
        else:
            response.selected_option_id = selected_option_id
            response.answer_value = answer_value

        session.flush()
        return response
