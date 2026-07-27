
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
        question_id: UUID | str,
    ) -> AssessmentResponse | None:
        return (
            await session.execute(
                select(AssessmentResponse).where(
                    AssessmentResponse.assessment_id == self._coerce_uuid(assessment_id),
                    AssessmentResponse.question_id == self._coerce_uuid(question_id),
                )
            )
        ).scalars().first()

    async def upsert_response(
        self,
        session: AsyncSession,
        *,
        assessment_id: UUID | str,
        question_id: UUID | str,
        answer_value: object | None,
    ) -> AssessmentResponse:
        response = await self.get_response(session, assessment_id, question_id)
        if response is None:
            response = AssessmentResponse(
                assessment_id=self._coerce_uuid(assessment_id),
                question_id=self._coerce_uuid(question_id),
                answer_value=answer_value,
            )
            session.add(response)
        else:
            response.answer_value = answer_value

        await session.flush()
        return response

    @staticmethod
    def _coerce_uuid(value: UUID | str) -> UUID:
        return value if isinstance(value, UUID) else UUID(value)
