from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_analysis_repository, get_session
from app.assemblers.ai_analysis_assembler import AIAnalysisAssembler
from app.models.dto import AIAnalysisResponseDTO
from app.repositories.analysis_repository import AnalysisRepository
from app.services.ai_analysis_service import AIAnalysisService

router = APIRouter(prefix="/api/v1/assessments", tags=["ai-analysis"])


def get_ai_analysis_service(
    analysis_repository: AnalysisRepository = Depends(get_analysis_repository),
) -> AIAnalysisService:
    return AIAnalysisService(
        analysis_repository=analysis_repository,
        assembler=AIAnalysisAssembler(),
    )


@router.get("/{assessment_id}/ai-analysis", response_model=AIAnalysisResponseDTO)
async def get_ai_analysis(
    assessment_id: UUID,
    session: AsyncSession = Depends(get_session),
    service: AIAnalysisService = Depends(get_ai_analysis_service),
) -> AIAnalysisResponseDTO:
    return await service.get_ai_analysis(session=session, assessment_id=assessment_id)
