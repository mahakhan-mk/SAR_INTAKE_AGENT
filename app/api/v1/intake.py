
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_intake_service
from app.database import get_db
from app.models.dto import (
    IntakeOverviewResponseDTO,
    IntakeQuestionUpdateRequestDTO,
    IntakeQuestionUpdateResponseDTO,
)
from app.services.intake_service import IntakeService

router = APIRouter(prefix="/api/v1/assessments", tags=["intake"])


@router.get("/{assessment_id}/intake", response_model=IntakeOverviewResponseDTO)
def get_intake_overview(
    assessment_id: UUID,
    session: Session = Depends(get_db),
    service: IntakeService = Depends(get_intake_service),
) -> IntakeOverviewResponseDTO:
    return service.get_intake_overview(session=session, assessment_id=str(assessment_id))


@router.patch(
    "/{assessment_id}/questions/{question_id}",
    response_model=IntakeQuestionUpdateResponseDTO,
)
def update_question_response(
    assessment_id: UUID,
    question_id: UUID,
    payload: IntakeQuestionUpdateRequestDTO,
    session: Session = Depends(get_db),
    service: IntakeService = Depends(get_intake_service),
) -> IntakeQuestionUpdateResponseDTO:
    return service.update_question_response(
        session=session,
        assessment_id=str(assessment_id),
        question_id=str(question_id),
        payload=payload,
    )
