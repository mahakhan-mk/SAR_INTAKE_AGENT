from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_executive_summary_service, get_inherent_risk_service, get_session
from app.models.dto import (
    AnalysisRunCreateRequestDTO,
    AnalysisRunCreateResponseDTO,
    ExecutiveSummaryGenerateRequestDTO,
    ExecutiveSummaryGenerateResponseDTO,
    InherentRiskResponseDTO,
)
from app.services.executive_summary_service import ExecutiveSummaryService
from app.services.inherent_risk_service import InherentRiskService

router = APIRouter(prefix="/api/v1/assessments", tags=["inherent-risk"])


@router.get("/{assessment_id}/inherent-risk", response_model=InherentRiskResponseDTO)
def get_inherent_risk(
    assessment_id: UUID,
    session: Session = Depends(get_session),
    service: InherentRiskService = Depends(get_inherent_risk_service),
) -> InherentRiskResponseDTO:
    return service.get_inherent_risk_screen(session=session, assessment_id=str(assessment_id))


@router.post("/{assessment_id}/analysis-runs", response_model=AnalysisRunCreateResponseDTO)
def create_analysis_run(
    assessment_id: UUID,
    payload: AnalysisRunCreateRequestDTO,
    session: Session = Depends(get_session),
    service: InherentRiskService = Depends(get_inherent_risk_service),
) -> AnalysisRunCreateResponseDTO:
    return service.create_analysis_run(
        session=session,
        assessment_id=str(assessment_id),
        force=payload.force,
    )


@router.post(
    "/{assessment_id}/inherent-risk/executive-summary",
    response_model=ExecutiveSummaryGenerateResponseDTO,
)
def generate_executive_summary(
    assessment_id: UUID,
    payload: ExecutiveSummaryGenerateRequestDTO,
    session: Session = Depends(get_session),
    service: ExecutiveSummaryService = Depends(get_executive_summary_service),
) -> ExecutiveSummaryGenerateResponseDTO:
    return service.generate(
        session=session,
        assessment_id=str(assessment_id),
        force=payload.force,
    )
