from __future__ import annotations

from datetime import datetime
from io import BytesIO
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_initial_sar_report_generation_service,
    get_initial_sar_report_repository,
    get_initial_sar_report_storage,
    get_report_preview_service,
    get_session,
)
from app.api.errors import AssessmentNotFoundError
from app.repositories.report_repository import InitialSarReportRepository
from app.services.initial_sar_report_generation_service import (
    GeneratedInitialSarReportResult,
    InitialSarReportGenerationService,
)
from app.services.initial_sar_report_storage import InitialSarReportStorage
from app.services.report_service import ReportPreviewService

router = APIRouter(prefix="/api/v1", tags=["reports"])


class InitialSarReportMetadataDTO(BaseModel):
    reportId: UUID
    assessmentId: UUID
    sourceWorkflowVersion: int
    reportVersion: int
    originalFilename: str
    contentType: str
    fileSizeBytes: int
    sha256: str
    limitations: list[object]
    createdAt: datetime
    staleAt: datetime | None


class InitialSarReportCreateResponseDTO(BaseModel):
    reportId: UUID
    filename: str
    contentType: str
    fileSizeBytes: int
    sha256: str


@router.get("/assessments/{assessment_id}/report-preview")
async def get_report_preview(
    assessment_id: UUID,
    session: AsyncSession = Depends(get_session),
    service: ReportPreviewService = Depends(get_report_preview_service),
) -> dict[str, object]:
    dto = await service.get_report_preview(session=session, assessment_id=assessment_id)
    return dto.model_dump(mode="json", serialize_as_any=True)


@router.post("/assessments/{assessment_id}/reports", response_model=InitialSarReportCreateResponseDTO)
async def create_initial_sar_report(
    assessment_id: UUID,
    session: AsyncSession = Depends(get_session),
    service: InitialSarReportGenerationService = Depends(get_initial_sar_report_generation_service),
) -> InitialSarReportCreateResponseDTO:
    result: GeneratedInitialSarReportResult | None = None
    try:
        result = await service.generate_report(
            session,
            assessment_id=assessment_id,
            source_workflow_version=1,
        )
        await session.commit()
        return InitialSarReportCreateResponseDTO(
            reportId=result.report_id,
            filename=result.filename,
            contentType=result.content_type,
            fileSizeBytes=result.file_size_bytes,
            sha256=result.sha256,
        )
    except AssessmentNotFoundError as exc:
        await session.rollback()
        if result is not None:
            await service.compensate_failed_generation(session, result.report_id)
        raise HTTPException(status_code=404, detail="Assessment not found.") from exc
    except Exception:
        await session.rollback()
        if result is not None:
            await service.compensate_failed_generation(session, result.report_id)
        raise


@router.get("/reports/{report_id}", response_model=InitialSarReportMetadataDTO)
async def get_initial_sar_report(
    report_id: UUID,
    session: AsyncSession = Depends(get_session),
    repository: InitialSarReportRepository = Depends(get_initial_sar_report_repository),
) -> InitialSarReportMetadataDTO:
    report = await repository.get_report(session, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    return InitialSarReportMetadataDTO(
        reportId=report.id,
        assessmentId=report.assessment_id,
        sourceWorkflowVersion=report.source_workflow_version,
        reportVersion=report.report_version,
        originalFilename=report.original_filename,
        contentType=report.content_type,
        fileSizeBytes=report.file_size_bytes,
        sha256=report.sha256,
        limitations=list(report.limitations or []),
        createdAt=report.created_at,
        staleAt=report.stale_at,
    )


@router.get("/reports/{report_id}/download")
async def download_initial_sar_report(
    report_id: UUID,
    session: AsyncSession = Depends(get_session),
    repository: InitialSarReportRepository = Depends(get_initial_sar_report_repository),
    storage: InitialSarReportStorage = Depends(get_initial_sar_report_storage),
) -> StreamingResponse:
    report = await repository.get_report(session, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    try:
        opened_report = await storage.open_report(report.storage_container, report.storage_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Report not found.") from exc
    headers = {"Content-Disposition": f'attachment; filename="{report.original_filename}"'}
    return StreamingResponse(
        BytesIO(opened_report.content),
        media_type=opened_report.content_type,
        headers=headers,
    )
