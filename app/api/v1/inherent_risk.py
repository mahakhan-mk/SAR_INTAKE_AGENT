from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

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
async def get_inherent_risk(
    assessment_id: UUID,
    session: AsyncSession = Depends(get_session),
    service: InherentRiskService = Depends(get_inherent_risk_service),
) -> InherentRiskResponseDTO:
    return await service.get_inherent_risk_screen(session=session, assessment_id=str(assessment_id))


@router.post("/{assessment_id}/analysis-runs", response_model=AnalysisRunCreateResponseDTO)
async def create_analysis_run(
    assessment_id: UUID,
    payload: AnalysisRunCreateRequestDTO,
    session: AsyncSession = Depends(get_session),
    service: InherentRiskService = Depends(get_inherent_risk_service),
) -> AnalysisRunCreateResponseDTO:
    return await service.create_analysis_run(
        session=session,
        assessment_id=str(assessment_id),
        force=payload.force,
    )


@router.post(
    "/{assessment_id}/inherent-risk/executive-summary",
    response_model=ExecutiveSummaryGenerateResponseDTO,
)
async def generate_executive_summary(
    assessment_id: UUID,
    payload: ExecutiveSummaryGenerateRequestDTO,
    session: AsyncSession = Depends(get_session),
    service: ExecutiveSummaryService = Depends(get_executive_summary_service),
) -> ExecutiveSummaryGenerateResponseDTO:
    return await service.generate(
        session=session,
        assessment_id=str(assessment_id),
        force=payload.force,
    )
