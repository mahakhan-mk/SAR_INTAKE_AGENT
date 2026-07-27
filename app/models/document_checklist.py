from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, model_validator

from app.models.database import DocumentChecklistItem, DocumentChecklistRun
from app.models.enums import ChecklistVerdict, DocumentType


@dataclass(frozen=True)
class DocumentChecklistItemReadState:
    item: DocumentChecklistItem
    effective_verdict: str
    detected_file_status: str
    detected_document_id: UUID | None
    reviewer_verdict: str | None
    reviewer_reason: str | None
    vendor_certification_automatic_status: str | None
    vendor_certification_analyst_status: str | None
    vendor_certification_effective_status: str | None


@dataclass(frozen=True)
class DocumentChecklistReadState:
    run: DocumentChecklistRun
    items: list[DocumentChecklistItemReadState]


class DocumentChecklistItemResponseDTO(BaseModel):
    item_id: UUID
    document_type: str
    item_order: int
    base_verdict: str
    effective_verdict: str
    detected_file_status: str
    detected_document_id: UUID | None
    reviewer_verdict: str | None
    reviewer_reason: str | None
    vendor_certification_automatic_status: str | None
    vendor_certification_analyst_status: str | None
    vendor_certification_effective_status: str | None


class DocumentChecklistResponseDTO(BaseModel):
    run_id: UUID
    assessment_id: UUID
    status: str
    summary_text: str | None
    summary_status: str
    limitations: list[object]
    created_at: datetime
    items: list[DocumentChecklistItemResponseDTO]


class DocumentChecklistItemReviewRequestDTO(BaseModel):
    reviewer_verdict: ChecklistVerdict | None = None
    reason: str | None = None
    reviewed_by: str | None = None

    @model_validator(mode="after")
    def require_reason_for_non_null_verdict(self) -> "DocumentChecklistItemReviewRequestDTO":
        if self.reviewer_verdict is not None and (self.reason is None or not self.reason.strip()):
            raise ValueError("reason is required when reviewer_verdict is provided.")
        return self


class AssessmentDocumentResponseDTO(BaseModel):
    document_id: UUID
    assessment_id: UUID
    original_filename: str
    content_type: str
    file_size_bytes: int
    sha256: str
    system_document_type: str
    upload_source: str
    uploaded_by: str | None
    created_at: datetime
    deleted_at: datetime | None


class AssessmentDocumentListResponseDTO(BaseModel):
    documents: list[AssessmentDocumentResponseDTO]


class DocumentClassificationReviewRequestDTO(BaseModel):
    document_type: DocumentType
    reason: str
    reviewed_by: str | None = None

    @model_validator(mode="after")
    def require_reason(self) -> "DocumentClassificationReviewRequestDTO":
        if not self.reason.strip():
            raise ValueError("reason is required.")
        return self


class DocumentClassificationReviewResponseDTO(BaseModel):
    review_id: UUID
    document_id: UUID
    assessment_id: UUID
    document_type: str
    reason: str
    reviewed_by: str | None
    created_at: datetime
    effective_document_type: str
