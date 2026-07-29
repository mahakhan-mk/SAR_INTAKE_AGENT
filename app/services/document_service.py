from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import logging
import uuid
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import AssessmentDocumentNotFoundError, DuplicateAssessmentDocumentError
from app.models.database import AssessmentDocument, DocumentClassificationReview
from app.models.enums import AssessmentDocumentSystemType, DocumentType
from app.repositories.document_repository import DocumentRepository
from app.services.document_storage import DocumentStorage, InMemoryDocumentStorage, OpenedDocument, StoredDocument

logger = logging.getLogger(__name__)


MAX_DOCUMENT_SIZE_BYTES = 25 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "text/plain",
}


@dataclass(frozen=True)
class DocumentUploadInput:
    filename: str
    content_type: str
    content: bytes
    system_document_type: str = AssessmentDocumentSystemType.UNCLASSIFIED.value
    uploaded_by: str | None = None


@dataclass(frozen=True)
class DownloadedDocument:
    filename: str
    content_type: str
    content: bytes


class _DocumentServiceBase:
    def __init__(
        self,
        *,
        document_repository: DocumentRepository | None = None,
    ) -> None:
        self.document_repository = document_repository or DocumentRepository()

    async def _get_active_document_or_raise(
        self,
        session: AsyncSession,
        *,
        assessment_id: UUID,
        document_id: UUID,
    ) -> AssessmentDocument:
        document = await self.document_repository.get_active_document(
            session,
            assessment_id=assessment_id,
            document_id=document_id,
        )
        if document is None:
            raise AssessmentDocumentNotFoundError()
        return document


class DocumentQueryService(_DocumentServiceBase):
    async def list_active_documents(
        self,
        session: AsyncSession,
        *,
        assessment_id: UUID,
    ) -> list[AssessmentDocument]:
        if not await self.document_repository.assessment_exists(session, assessment_id):
            raise AssessmentDocumentNotFoundError()
        return await self.document_repository.list_active_assessment_documents(session, assessment_id)

    async def get_document_metadata(
        self,
        session: AsyncSession,
        *,
        assessment_id: UUID,
        document_id: UUID,
    ) -> AssessmentDocument:
        return await self._get_active_document_or_raise(
            session,
            assessment_id=assessment_id,
            document_id=document_id,
        )


class DocumentCommandService(_DocumentServiceBase):
    def __init__(
        self,
        *,
        document_repository: DocumentRepository | None = None,
        storage: DocumentStorage | None = None,
    ) -> None:
        super().__init__(document_repository=document_repository)
        self.storage = storage or InMemoryDocumentStorage()

    async def upload_document(
        self,
        session: AsyncSession,
        *,
        assessment_id: UUID,
        upload: DocumentUploadInput,
    ) -> AssessmentDocument:
        self._validate_upload(upload)
        system_document_type = self.document_repository.validate_system_document_type(upload.system_document_type)
        if not await self.document_repository.assessment_exists(session, assessment_id):
            raise AssessmentDocumentNotFoundError()

        sha256 = hashlib.sha256(upload.content).hexdigest()
        duplicate = await self.document_repository.get_active_document_by_sha256(
            session,
            assessment_id=assessment_id,
            sha256=sha256,
        )
        if duplicate is not None:
            raise DuplicateAssessmentDocumentError()

        document_id = uuid.uuid4()
        stored_document = await self.storage.store(
            assessment_id=assessment_id,
            document_id=document_id,
            filename=upload.filename,
            content_type=upload.content_type,
            content=upload.content,
        )
        try:
            return await self.document_repository.create_assessment_document(
                session,
                document_id=document_id,
                assessment_id=assessment_id,
                original_filename=upload.filename,
                content_type=upload.content_type,
                file_size_bytes=len(upload.content),
                sha256=sha256,
                storage_container=stored_document.container,
                storage_key=stored_document.key,
                upload_source="sar_request",
                system_document_type=system_document_type,
                uploaded_by=upload.uploaded_by,
                document_metadata={},
            )
        except Exception:
            await self._delete_stored_document_quietly(stored_document)
            raise

    async def soft_delete_document(
        self,
        session: AsyncSession,
        *,
        assessment_id: UUID,
        document_id: UUID,
        deleted_by: str | None = None,
    ) -> AssessmentDocument:
        document = await self._get_active_document_or_raise(
            session,
            assessment_id=assessment_id,
            document_id=document_id,
        )
        document.deleted_at = datetime.now(timezone.utc)
        document.deleted_by = deleted_by
        await session.flush()
        return document

    async def append_classification_review(
        self,
        session: AsyncSession,
        *,
        assessment_id: UUID,
        document_id: UUID,
        document_type: DocumentType | str,
        reason: str,
        reviewed_by: str | None = None,
    ) -> DocumentClassificationReview:
        document = await self._get_active_document_or_raise(
            session,
            assessment_id=assessment_id,
            document_id=document_id,
        )
        return await self.document_repository.append_classification_review(
            session,
            document_id=document.id,
            document_type=document_type,
            reason=reason,
            reviewed_by=reviewed_by,
        )

    async def compensate_failed_upload(self, document: AssessmentDocument) -> None:
        await self._delete_stored_document_quietly(
            StoredDocument(
                container=document.storage_container,
                key=document.storage_key,
            )
        )

    @staticmethod
    def _validate_upload(upload: DocumentUploadInput) -> None:
        filename = upload.filename.strip()
        if not filename or "/" in filename or "\\" in filename:
            raise ValueError("A valid filename is required.")
        if upload.content_type not in ALLOWED_CONTENT_TYPES:
            raise ValueError("Unsupported document content type.")
        if not upload.content:
            raise ValueError("Uploaded document must not be empty.")
        if len(upload.content) > MAX_DOCUMENT_SIZE_BYTES:
            raise ValueError("Uploaded document is too large.")

    async def _delete_stored_document_quietly(self, stored_document) -> None:
        try:
            await self.storage.delete(
                container=stored_document.container,
                key=stored_document.key,
            )
        except Exception:
            logger.exception(
                "Failed to compensate stored document after persistence failure container=%s key=%s",
                stored_document.container,
                stored_document.key,
            )


class DocumentDownloadService(_DocumentServiceBase):
    def __init__(
        self,
        *,
        document_repository: DocumentRepository | None = None,
        storage: DocumentStorage | None = None,
    ) -> None:
        super().__init__(document_repository=document_repository)
        self.storage = storage or InMemoryDocumentStorage()

    async def get_document_metadata(
        self,
        session: AsyncSession,
        *,
        assessment_id: UUID,
        document_id: UUID,
    ) -> AssessmentDocument:
        return await self._get_active_document_or_raise(
            session,
            assessment_id=assessment_id,
            document_id=document_id,
        )

    async def download_document(
        self,
        session: AsyncSession,
        *,
        assessment_id: UUID,
        document_id: UUID,
    ) -> DownloadedDocument:
        document = await self._get_active_document_or_raise(
            session,
            assessment_id=assessment_id,
            document_id=document_id,
        )
        opened_document: OpenedDocument = await self.storage.open(
            container=document.storage_container,
            key=document.storage_key,
        )
        return DownloadedDocument(
            filename=document.original_filename,
            content_type=opened_document.content_type,
            content=opened_document.content,
        )

