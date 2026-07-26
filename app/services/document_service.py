from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import AssessmentDocument, DocumentClassificationReview
from app.models.enums import AssessmentDocumentSystemType, DocumentType
from app.repositories.document_repository import DocumentRepository
from app.services.document_storage import DocumentStorage, InMemoryDocumentStorage


MAX_DOCUMENT_SIZE_BYTES = 25 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "text/plain",
}


class AssessmentDocumentNotFoundError(LookupError):
    pass


class DuplicateAssessmentDocumentError(ValueError):
    pass


@dataclass(frozen=True)
class DocumentUploadInput:
    filename: str
    content_type: str
    content: bytes
    system_document_type: str = AssessmentDocumentSystemType.UNCLASSIFIED.value
    uploaded_by: str | None = None


class DocumentService:
    def __init__(
        self,
        *,
        document_repository: DocumentRepository | None = None,
        storage: DocumentStorage | None = None,
    ) -> None:
        self.document_repository = document_repository or DocumentRepository()
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

        stored_document = await self.storage.store(
            assessment_id=assessment_id,
            filename=upload.filename,
            content_type=upload.content_type,
            content=upload.content,
        )
        return await self.document_repository.create_assessment_document(
            session,
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

    async def list_active_documents(
        self,
        session: AsyncSession,
        *,
        assessment_id: UUID,
    ) -> list[AssessmentDocument]:
        if not await self.document_repository.assessment_exists(session, assessment_id):
            raise AssessmentDocumentNotFoundError()
        return await self.document_repository.list_active_assessment_documents(session, assessment_id)

    async def soft_delete_document(
        self,
        session: AsyncSession,
        *,
        assessment_id: UUID,
        document_id: UUID,
        deleted_by: str | None = None,
    ) -> AssessmentDocument:
        document = await self.document_repository.get_active_document(
            session,
            assessment_id=assessment_id,
            document_id=document_id,
        )
        if document is None:
            raise AssessmentDocumentNotFoundError()
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
        document = await self.document_repository.get_active_document(
            session,
            assessment_id=assessment_id,
            document_id=document_id,
        )
        if document is None:
            raise AssessmentDocumentNotFoundError()
        return await self.document_repository.append_classification_review(
            session,
            document_id=document.id,
            document_type=document_type,
            reason=reason,
            reviewed_by=reviewed_by,
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
