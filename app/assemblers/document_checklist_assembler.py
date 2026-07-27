from __future__ import annotations

from app.models.document_checklist import (
    AssessmentDocumentListResponseDTO,
    AssessmentDocumentResponseDTO,
    DocumentClassificationReviewResponseDTO,
    DocumentChecklistItemResponseDTO,
    DocumentChecklistReadState,
    DocumentChecklistResponseDTO,
)


class DocumentChecklistAssembler:
    def to_document_dto(self, document) -> AssessmentDocumentResponseDTO:
        return AssessmentDocumentResponseDTO(
            document_id=document.id,
            assessment_id=document.assessment_id,
            original_filename=document.original_filename,
            content_type=document.content_type,
            file_size_bytes=document.file_size_bytes,
            sha256=document.sha256,
            system_document_type=document.system_document_type,
            upload_source=document.upload_source,
            uploaded_by=document.uploaded_by,
            created_at=document.created_at,
            deleted_at=document.deleted_at,
        )

    def to_document_list_dto(self, documents) -> AssessmentDocumentListResponseDTO:
        return AssessmentDocumentListResponseDTO(
            documents=[self.to_document_dto(document) for document in documents],
        )

    def to_classification_review_dto(
        self,
        *,
        review,
        assessment_id,
        effective_document_type: str,
    ) -> DocumentClassificationReviewResponseDTO:
        return DocumentClassificationReviewResponseDTO(
            review_id=review.id,
            document_id=review.document_id,
            assessment_id=assessment_id,
            document_type=review.document_type,
            reason=review.reason,
            reviewed_by=review.reviewed_by,
            created_at=review.created_at,
            effective_document_type=effective_document_type,
        )

    def to_dto(self, state: DocumentChecklistReadState) -> DocumentChecklistResponseDTO:
        return DocumentChecklistResponseDTO(
            run_id=state.run.id,
            assessment_id=state.run.assessment_id,
            status=state.run.status,
            summary_text=state.run.summary_text,
            summary_status=state.run.summary_status,
            limitations=state.run.limitations,
            created_at=state.run.created_at,
            items=[
                self.to_item_dto(item_state)
                for item_state in state.items
            ],
        )

    def to_item_dto(self, item_state) -> DocumentChecklistItemResponseDTO:
        return DocumentChecklistItemResponseDTO(
            item_id=item_state.item.id,
            document_type=item_state.item.document_type,
            item_order=item_state.item.item_order,
            base_verdict=item_state.item.base_verdict,
            effective_verdict=item_state.effective_verdict,
            detected_file_status=item_state.detected_file_status,
            detected_document_id=item_state.detected_document_id,
            reviewer_verdict=item_state.reviewer_verdict,
            reviewer_reason=item_state.reviewer_reason,
            vendor_certification_automatic_status=item_state.vendor_certification_automatic_status,
            vendor_certification_analyst_status=item_state.vendor_certification_analyst_status,
            vendor_certification_effective_status=item_state.vendor_certification_effective_status,
        )
