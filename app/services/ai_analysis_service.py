from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.assemblers.ai_analysis_assembler import AIAnalysisAssembler
from app.application.models import AIAnalysisResult
from app.domain.errors import AssessmentNotFoundError
from app.repositories.analysis_repository import AnalysisRepository


class AIAnalysisQueryService:
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
    ) -> AIAnalysisResult:
        view = await self.analysis_repository.load_ai_analysis_view(session, assessment_id)
        if view is None:
            raise AssessmentNotFoundError()
        return self.assembler.to_dto(view)

