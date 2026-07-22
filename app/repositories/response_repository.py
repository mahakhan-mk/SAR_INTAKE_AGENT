
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import AssessmentResponse


class ResponseRepository:
    async def get_response(
        self,
        session: AsyncSession,
        assessment_id: UUID | str,
        question_definition_id: UUID | str,
    ) -> AssessmentResponse | None:
        return (
            await session.execute(
                select(AssessmentResponse).where(
                    AssessmentResponse.assessment_id == self._coerce_uuid(assessment_id),
                    AssessmentResponse.question_definition_id == self._coerce_uuid(question_definition_id),
                )
            )
        ).scalars().first()

    async def upsert_response(
        self,
        session: AsyncSession,
        *,
        assessment_id: UUID | str,
        question_definition_id: UUID | str,
        selected_option_id: UUID | str | None,
        answer_value: str | None,
        reviewer_remarks: str | None = None,
        reviewer_remarks_was_provided: bool = False,
    ) -> AssessmentResponse:
        response = await self.get_response(session, assessment_id, question_definition_id)
        if response is None:
            response = AssessmentResponse(
                assessment_id=self._coerce_uuid(assessment_id),
                question_definition_id=self._coerce_uuid(question_definition_id),
                answer_value=answer_value,
                reviewer_remarks=reviewer_remarks if reviewer_remarks_was_provided else None,
            )
            response.selected_option_id = self._coerce_uuid(selected_option_id) if selected_option_id is not None else None
            session.add(response)
        else:
            response.answer_value = answer_value
            response.selected_option_id = self._coerce_uuid(selected_option_id) if selected_option_id is not None else None
            if reviewer_remarks_was_provided:
                response.reviewer_remarks = reviewer_remarks

        await session.flush()
        return response

    @staticmethod
    def _coerce_uuid(value: UUID | str) -> UUID:
        return value if isinstance(value, UUID) else UUID(value)
