
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_intake_service, get_session
from app.models.dto import (
    IntakeOverviewResponseDTO,
    IntakeQuestionUpdateRequestDTO,
    IntakeQuestionUpdateResponseDTO,
)
from app.services.intake_service import IntakeService

router = APIRouter(prefix="/api/v1/assessments", tags=["intake"])


@router.get("/{assessment_id}/intake", response_model=IntakeOverviewResponseDTO)
async def get_intake_overview(
    assessment_id: UUID,
    session: AsyncSession = Depends(get_session),
    service: IntakeService = Depends(get_intake_service),
) -> IntakeOverviewResponseDTO:
    return await service.get_intake_overview(session=session, assessment_id=assessment_id)


@router.patch(
    "/{assessment_id}/questions/{question_id}",
    response_model=IntakeQuestionUpdateResponseDTO,
)
async def update_question_response(
    assessment_id: UUID,
    question_id: UUID,
    payload: IntakeQuestionUpdateRequestDTO,
    session: AsyncSession = Depends(get_session),
    service: IntakeService = Depends(get_intake_service),
) -> IntakeQuestionUpdateResponseDTO:
    try:
        response = await service.update_question_response(
            session=session,
            assessment_id=assessment_id,
            question_id=question_id,
            payload=payload,
        )
        await session.commit()
        return response
    except Exception:
        await session.rollback()
        raise
