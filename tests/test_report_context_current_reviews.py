from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.database import DocumentChecklistItem, DocumentChecklistRun
from app.repositories.document_checklist_repository import DocumentChecklistRunRecord
from app.services.report_context_service import InitialSarReportContextService


class CurrentRunReviewRepository:
    def __init__(self, review: object) -> None:
        self.review = review
        self.requested_item_ids: list[object] = []

    async def list_latest_item_reviews_for_run_items(
        self,
        session,
        *,
        assessment_id,
        item_ids,
    ):
        self.requested_item_ids = list(item_ids)
        return {self.review.document_type: self.review}

    async def list_latest_item_reviews_by_assessment(self, session, assessment_id):
        raise AssertionError("report context must not reuse a review from an older checklist run")


def _service(repository: CurrentRunReviewRepository) -> InitialSarReportContextService:
    return InitialSarReportContextService(
        assessment_repository=SimpleNamespace(),
        analysis_repository=SimpleNamespace(),
        checklist_repository=repository,
        document_repository=SimpleNamespace(),
        inherent_risk_service=SimpleNamespace(),
        assembler=SimpleNamespace(),
        vendor_reputation_repository=SimpleNamespace(),
    )


@pytest.mark.asyncio
async def test_report_context_uses_only_reviews_tied_to_current_run_items() -> None:
    assessment_id = uuid4()
    run_id = uuid4()
    item = DocumentChecklistItem(
        id=uuid4(),
        checklist_run_id=run_id,
        document_type="SOC 2 Type II",
        base_verdict="Required",
        item_order=1,
    )
    run = DocumentChecklistRun(
        id=run_id,
        assessment_id=assessment_id,
        status="completed",
        summary_status="generated",
        input_snapshot={
            "items": [
                {
                    "documentType": item.document_type,
                    "detectedDocumentIds": [],
                }
            ]
        },
        limitations=[],
    )
    review = SimpleNamespace(
        document_type=item.document_type,
        reviewer_verdict="N/A",
        reason="Current run decision",
    )
    repository = CurrentRunReviewRepository(review)

    state = await _service(repository)._build_checklist_state(
        object(),
        assessment_id,
        DocumentChecklistRunRecord(run=run, items=[item]),
    )

    assert repository.requested_item_ids == [item.id]
    assert state.items[0].effective_verdict == "N/A"
    assert state.items[0].reviewer_reason == "Current run decision"
