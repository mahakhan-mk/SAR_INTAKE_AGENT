from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import uuid
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import AssessmentDocument, DocumentClassificationReview, SarAssessment
from app.models.enums import AssessmentDocumentSystemType, DocumentType


@dataclass(frozen=True)
class AssessmentDocumentRecord:
    document: AssessmentDocument
    effective_document_type: str
    latest_review_id: uuid.UUID | None
    latest_review_reason: str | None
    latest_reviewed_by: str | None


class DocumentRepository:
    async def assessment_exists(self, session: AsyncSession, assessment_id: UUID | str) -> bool:
        return (
            await session.execute(
                select(SarAssessment.id).where(SarAssessment.id == self._coerce_uuid(assessment_id))
            )
        ).first() is not None

    async def create_assessment_document(
        self,
        session: AsyncSession,
        *,
        document_id: UUID | str | None = None,
        assessment_id: UUID | str,
        original_filename: str,
        content_type: str,
        file_size_bytes: int,
        sha256: str,
        storage_container: str,
        storage_key: str,
        upload_source: str,
        system_document_type: AssessmentDocumentSystemType | str,
        uploaded_by: str | None = None,
        document_metadata: dict[str, object] | None = None,
    ) -> AssessmentDocument:
        document = AssessmentDocument(
            id=self._coerce_uuid(document_id) if document_id is not None else uuid.uuid4(),
            assessment_id=self._coerce_uuid(assessment_id),
            original_filename=original_filename,
            content_type=content_type,
            file_size_bytes=file_size_bytes,
            sha256=sha256,
            storage_container=storage_container,
            storage_key=storage_key,
            upload_source=upload_source,
            system_document_type=self.validate_system_document_type(system_document_type),
            uploaded_by=uploaded_by,
            document_metadata=document_metadata or {},
        )
        session.add(document)
        await session.flush()
        return document

    async def list_active_assessment_documents(
        self,
        session: AsyncSession,
        assessment_id: UUID | str,
    ) -> list[AssessmentDocument]:
        return list(
            (
                await session.execute(
                    select(AssessmentDocument)
                    .where(
                        AssessmentDocument.assessment_id == self._coerce_uuid(assessment_id),
                        AssessmentDocument.deleted_at.is_(None),
                    )
                    .order_by(AssessmentDocument.created_at.desc(), AssessmentDocument.id.desc())
                )
            ).scalars().all()
        )

    async def get_active_document(
        self,
        session: AsyncSession,
        *,
        assessment_id: UUID | str,
        document_id: UUID | str,
    ) -> AssessmentDocument | None:
        return (
            await session.execute(
                select(AssessmentDocument).where(
                    AssessmentDocument.assessment_id == self._coerce_uuid(assessment_id),
                    AssessmentDocument.id == self._coerce_uuid(document_id),
                    AssessmentDocument.deleted_at.is_(None),
                )
            )
        ).scalars().first()

    async def get_active_document_by_sha256(
        self,
        session: AsyncSession,
        *,
        assessment_id: UUID | str,
        sha256: str,
    ) -> AssessmentDocument | None:
        return (
            await session.execute(
                select(AssessmentDocument).where(
                    AssessmentDocument.assessment_id == self._coerce_uuid(assessment_id),
                    AssessmentDocument.sha256 == sha256,
                    AssessmentDocument.deleted_at.is_(None),
                )
            )
        ).scalars().first()

    async def get_latest_active_document_for_assessment_type(
        self,
        session: AsyncSession,
        *,
        assessment_id: UUID | str,
        system_document_type: AssessmentDocumentSystemType | str,
    ) -> AssessmentDocument | None:
        return (
            await session.execute(
                select(AssessmentDocument).where(
                    AssessmentDocument.assessment_id == self._coerce_uuid(assessment_id),
                    AssessmentDocument.system_document_type == self.validate_system_document_type(system_document_type),
                    AssessmentDocument.deleted_at.is_(None),
                )
                .order_by(AssessmentDocument.created_at.desc(), AssessmentDocument.id.desc())
            )
        ).scalars().first()

    async def list_active_documents_by_assessment(
        self,
        session: AsyncSession,
        assessment_id: UUID | str,
    ) -> list[AssessmentDocumentRecord]:
        ranked_reviews = self._ranked_classification_reviews_subquery()

        rows = (
            await session.execute(
                select(
                    AssessmentDocument,
                    ranked_reviews.c.review_id,
                    ranked_reviews.c.review_document_type,
                    ranked_reviews.c.reason,
                    ranked_reviews.c.reviewed_by,
                )
                .outerjoin(
                    ranked_reviews,
                    and_(
                        ranked_reviews.c.document_id == AssessmentDocument.id,
                        ranked_reviews.c.review_rank == 1,
                    ),
                )
                .where(
                    AssessmentDocument.assessment_id == self._coerce_uuid(assessment_id),
                    AssessmentDocument.deleted_at.is_(None),
                )
                .order_by(AssessmentDocument.created_at.desc(), AssessmentDocument.id.desc())
            )
        ).all()

        return [
            AssessmentDocumentRecord(
                document=document,
                effective_document_type=review_document_type or document.system_document_type,
                latest_review_id=review_id,
                latest_review_reason=reason,
                latest_reviewed_by=reviewed_by,
            )
            for document, review_id, review_document_type, reason, reviewed_by in rows
        ]

    async def append_classification_review(
        self,
        session: AsyncSession,
        *,
        document_id: UUID | str,
        document_type: DocumentType | str,
        reason: str,
        reviewed_by: str | None = None,
    ) -> DocumentClassificationReview:
        if not reason.strip():
            raise ValueError("Classification review reason is required.")

        review = DocumentClassificationReview(
            document_id=self._coerce_uuid(document_id),
            document_type=self._coerce_document_type(document_type),
            reason=reason,
            reviewed_by=reviewed_by,
            created_at=datetime.now(timezone.utc),
        )
        session.add(review)
        await session.flush()
        return review

    async def get_latest_classification_review(
        self,
        session: AsyncSession,
        *,
        assessment_id: UUID | str,
        document_type: DocumentType | str,
    ) -> DocumentClassificationReview | None:
        return (
            await session.execute(
                select(DocumentClassificationReview)
                .join(AssessmentDocument, AssessmentDocument.id == DocumentClassificationReview.document_id)
                .where(
                    AssessmentDocument.assessment_id == self._coerce_uuid(assessment_id),
                    AssessmentDocument.deleted_at.is_(None),
                    DocumentClassificationReview.document_type == self._coerce_document_type(document_type),
                )
                .order_by(DocumentClassificationReview.created_at.desc(), DocumentClassificationReview.id.desc())
            )
        ).scalars().first()

    @staticmethod
    def validate_system_document_type(document_type: AssessmentDocumentSystemType | str) -> str:
        value = document_type.value if isinstance(document_type, AssessmentDocumentSystemType) else document_type
        if value not in {member.value for member in AssessmentDocumentSystemType}:
            raise ValueError(f"Unsupported assessment document system type: {value}")
        return value

    @staticmethod
    def _coerce_document_type(document_type: DocumentType | str) -> str:
        value = document_type.value if isinstance(document_type, DocumentType) else document_type
        if value not in {member.value for member in DocumentType}:
            raise ValueError(f"Unsupported document type: {value}")
        return value

    @staticmethod
    def _coerce_uuid(value: UUID | str) -> UUID:
        return value if isinstance(value, UUID) else UUID(value)

    @staticmethod
    def _ranked_classification_reviews_subquery():
        return (
            select(
                DocumentClassificationReview.id.label("review_id"),
                DocumentClassificationReview.document_id.label("document_id"),
                DocumentClassificationReview.document_type.label("review_document_type"),
                DocumentClassificationReview.reason.label("reason"),
                DocumentClassificationReview.reviewed_by.label("reviewed_by"),
                func.row_number()
                .over(
                    partition_by=DocumentClassificationReview.document_id,
                    order_by=(DocumentClassificationReview.created_at.desc(), DocumentClassificationReview.id.desc()),
                )
                .label("review_rank"),
            )
        ).subquery()
