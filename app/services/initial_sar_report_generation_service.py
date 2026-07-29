from __future__ import annotations

from dataclasses import dataclass
import logging
import uuid
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.document_repository import DocumentRepository
from app.repositories.report_repository import InitialSarReportRepository
from app.services.initial_sar_report_renderer import InitialSarReportRenderer, RenderedInitialSarReport
from app.services.initial_sar_report_storage import InitialSarReportStorage, StoredInitialSarReport
from app.services.report_service import ReportPreviewService

logger = logging.getLogger(__name__)
_PENDING_UPLOADS_KEY = "pending_initial_sar_report_uploads"
_IMAGE_CONTENT_TYPES = {"image/png", "image/jpeg"}


@dataclass(frozen=True)
class GeneratedInitialSarReportResult:
    report_id: UUID
    filename: str
    content_type: str
    file_size_bytes: int
    sha256: str


class InitialSarReportGenerationService:
    def __init__(
        self,
        *,
        preview_service: ReportPreviewService,
        renderer: InitialSarReportRenderer,
        storage: InitialSarReportStorage,
        repository: InitialSarReportRepository,
        document_repository: DocumentRepository | None = None,
        document_storage: object | None = None,
    ) -> None:
        self.preview_service = preview_service
        self.renderer = renderer
        self.storage = storage
        self.repository = repository
        self.document_repository = document_repository or DocumentRepository()
        self.document_storage = document_storage

    async def generate_report(
        self,
        session: AsyncSession,
        *,
        assessment_id: UUID,
        source_workflow_version: int,
    ) -> GeneratedInitialSarReportResult:
        preview = await self.preview_service.get_report_preview(session, assessment_id)
        architecture_image_bytes = await self._load_architecture_image_bytes(session, assessment_id, preview)
        rendered_report = self.renderer.render(preview, architecture_image_bytes=architecture_image_bytes)

        report_id = uuid.uuid4()
        report_version = await self.repository.get_next_report_version(session, assessment_id)
        stored_report = await self.storage.store_report(
            report_id=report_id,
            assessment_id=assessment_id,
            filename=rendered_report.original_filename,
            content_type=rendered_report.content_type,
            content=rendered_report.bytes,
        )
        self._set_pending_upload(session, report_id, stored_report)

        try:
            await self.repository.create_completed_report(
                session,
                report_id=report_id,
                assessment_id=assessment_id,
                source_workflow_version=source_workflow_version,
                report_version=report_version,
                storage_container=stored_report.storage_container,
                storage_key=stored_report.storage_key,
                original_filename=rendered_report.original_filename,
                content_type=rendered_report.content_type,
                file_size_bytes=rendered_report.file_size_bytes,
                sha256=rendered_report.sha256,
                limitations=list(preview.limitations or []),
            )
        except Exception:
            await self.compensate_failed_generation(session, report_id)
            raise

        return GeneratedInitialSarReportResult(
            report_id=report_id,
            filename=rendered_report.original_filename,
            content_type=rendered_report.content_type,
            file_size_bytes=rendered_report.file_size_bytes,
            sha256=rendered_report.sha256,
        )

    async def compensate_failed_generation(self, session: AsyncSession, report_id: UUID) -> None:
        stored_report = self._pop_pending_upload(session, report_id)
        if stored_report is None:
            return
        try:
            await self.storage.delete_report(stored_report.storage_container, stored_report.storage_key)
        except Exception:
            logger.exception(
                "Failed to compensate stored Initial SAR report after persistence failure container=%s key=%s",
                stored_report.storage_container,
                stored_report.storage_key,
            )

    async def _load_architecture_image_bytes(self, session: AsyncSession, assessment_id: UUID, preview: object) -> bytes | None:
        document_id = getattr(getattr(preview, "architecture", None), "documentId", None)
        content_type = getattr(getattr(preview, "architecture", None), "contentType", None)
        opener = getattr(self.document_storage, "open", None)
        if not isinstance(document_id, (str, UUID)) or content_type not in _IMAGE_CONTENT_TYPES or opener is None:
            return None
        try:
            normalized_document_id = UUID(str(document_id))
        except ValueError:
            return None

        document = await self.document_repository.get_active_document(
            session,
            assessment_id=assessment_id,
            document_id=normalized_document_id,
        )
        if document is None:
            return None

        opened_document = await opener(container=document.storage_container, key=document.storage_key)
        opened_content_type = getattr(opened_document, "content_type", None)
        if opened_content_type not in _IMAGE_CONTENT_TYPES:
            return None
        return getattr(opened_document, "content", None)

    @staticmethod
    def _set_pending_upload(session: AsyncSession, report_id: UUID, stored_report: StoredInitialSarReport) -> None:
        session.info.setdefault(_PENDING_UPLOADS_KEY, {})[report_id] = stored_report

    @staticmethod
    def _pop_pending_upload(session: AsyncSession, report_id: UUID) -> StoredInitialSarReport | None:
        uploads = session.info.get(_PENDING_UPLOADS_KEY, {})
        stored_report = uploads.pop(report_id, None)
        if not uploads:
            session.info.pop(_PENDING_UPLOADS_KEY, None)
        return stored_report
