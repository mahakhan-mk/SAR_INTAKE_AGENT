from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AssessmentNotFoundError
from app.assemblers.ai_analysis_assembler import AIAnalysisAssembler
from app.models.dto import AIAnalysisResponseDTO
from app.repositories.analysis_repository import AnalysisRepository


class AIAnalysisService:
    def __init__(
        self,
        analysis_repository: AnalysisRepository,
        assembler: AIAnalysisAssembler,
    ) -> None:
        self.analysis_repository = analysis_repository
        self.assembler = assembler

    async def get_ai_analysis(
        self,
        session: AsyncSession,
        assessment_id: uuid.UUID,
    ) -> AIAnalysisResponseDTO:
        view = await self.analysis_repository.load_ai_analysis_view(session, assessment_id)
        if view is None:
            raise AssessmentNotFoundError()
        return self.assembler.to_dto(view)
