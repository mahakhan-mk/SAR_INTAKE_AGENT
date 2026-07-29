from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_ai_analysis_query_service, get_session
from app.api.schemas import AIAnalysisResponseDTO
from app.services.ai_analysis_service import AIAnalysisQueryService

router = APIRouter(prefix="/api/v1/assessments", tags=["ai-analysis"])


@router.get("/{assessment_id}/ai-analysis", response_model=AIAnalysisResponseDTO)
async def get_ai_analysis(
    assessment_id: UUID,
    session: AsyncSession = Depends(get_session),
    service: AIAnalysisQueryService = Depends(get_ai_analysis_query_service),
) -> AIAnalysisResponseDTO:
    result = await service.get_ai_analysis(session=session, assessment_id=assessment_id)
    return AIAnalysisResponseDTO.model_validate(result)
