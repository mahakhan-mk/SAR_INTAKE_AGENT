from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.database import DocumentChecklistItem, DocumentChecklistRun
from app.models.enums import (
    DocumentChecklistRunStatus,
    DocumentChecklistSummaryStatus,
    DocumentType,
)
from app.repositories.document_checklist_repository import DocumentChecklistRunRecord
from app.services.document_checklist_service import DocumentChecklistExecutionService


class FakeChecklistRepository:
    def __init__(self, run_record: DocumentChecklistRunRecord, reviews: dict[str, object]) -> None:
        self.run_record = run_record
        self.reviews = reviews

    async def get_checklist_run_with_items(self, session, *, assessment_id, run_id):
        if self.run_record.run.id == run_id and self.run_record.run.assessment_id == assessment_id:
            return self.run_record
        return None

    async def list_latest_item_reviews_for_run_items(self, session, *, assessment_id, item_ids):
        return dict(self.reviews)

    async def list_latest_item_reviews_by_assessment(self, session, assessment_id):
        raise AssertionError("finalization must use reviews tied to the requested run")

    async def update_run_status(self, session, *, run, status, error_summary=None):
        run.status = status.value if hasattr(status, "value") else str(status)
        run.error_summary = error_summary
        return run


def _run_record(*, detected: bool = False) -> DocumentChecklistRunRecord:
    assessment_id = uuid4()
    run_id = uuid4()
    items = [
        DocumentChecklistItem(
            id=uuid4(),
            checklist_run_id=run_id,
            document_type=document_type.value,
            base_verdict="Required",
            item_order=index,
        )
        for index, document_type in enumerate(DocumentType, start=1)
    ]
    snapshot_items = [
        {
            "documentType": item.document_type,
            "detectedDocumentIds": [str(uuid4())] if detected else [],
        }
        for item in items
    ]
    run = DocumentChecklistRun(
        id=run_id,
        assessment_id=assessment_id,
        status=DocumentChecklistRunStatus.DRAFT.value,
        summary_status=DocumentChecklistSummaryStatus.GENERATED.value,
        input_snapshot={"items": snapshot_items},
        limitations=[],
    )
    return DocumentChecklistRunRecord(run=run, items=items)


def _service(run_record: DocumentChecklistRunRecord, reviews: dict[str, object]):
    repository = FakeChecklistRepository(run_record, reviews)
    return DocumentChecklistExecutionService(
        document_repository=SimpleNamespace(),
        checklist_repository=repository,
        vendor_certification_repository=SimpleNamespace(),
        llm_client=SimpleNamespace(),
    )


@pytest.mark.asyncio
async def test_finalize_is_incomplete_without_current_run_reviewer_decisions() -> None:
    run_record = _run_record(detected=True)
    service = _service(run_record, reviews={})

    state = await service.finalize_checklist(
        object(),
        assessment_id=run_record.run.assessment_id,
        run_id=run_record.run.id,
    )

    assert state.run.status == DocumentChecklistRunStatus.INCOMPLETE.value
    assert "missing saved reviewer decisions" in (state.run.error_summary or "")


@pytest.mark.asyncio
async def test_finalize_completes_when_each_current_item_has_a_saved_decision() -> None:
    run_record = _run_record(detected=False)
    reviews = {
        item.document_type: SimpleNamespace(
            source_item_id=item.id,
            document_type=item.document_type,
            reviewer_verdict="N/A",
            reason="Reviewed and not applicable",
        )
        for item in run_record.items
    }
    service = _service(run_record, reviews=reviews)

    state = await service.finalize_checklist(
        object(),
        assessment_id=run_record.run.assessment_id,
        run_id=run_record.run.id,
    )

    assert state.run.status == DocumentChecklistRunStatus.COMPLETED.value
    assert all(item.effective_verdict == "N/A" for item in state.items)
