from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_report_preview_service, get_session
from app.services.report_service import ReportPreviewService

router = APIRouter(prefix="/api/v1/assessments", tags=["report-preview"])


@router.get("/{assessment_id}/report-preview")
async def get_report_preview(
    assessment_id: UUID,
    session: AsyncSession = Depends(get_session),
    service: ReportPreviewService = Depends(get_report_preview_service),
) -> dict[str, object]:
    dto = await service.get_report_preview(session=session, assessment_id=assessment_id)
    return dto.model_dump(mode="json", serialize_as_any=True)
