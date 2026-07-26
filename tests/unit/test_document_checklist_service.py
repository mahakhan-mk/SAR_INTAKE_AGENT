from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

import pytest
from sqlalchemy import func, select

from app.models.database import AssessmentDocument, DocumentChecklistItem, DocumentChecklistItemReview, DocumentChecklistRun
from app.models.enums import ChecklistVerdict, DocumentType
from app.repositories.document_checklist_repository import DocumentChecklistRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.vendor_certification_repository import (
    vendor_reputation_hitl_reviews,
    vendor_reputation_jobs,
)
from app.services.document_checklist_service import DocumentChecklistService

pytestmark = pytest.mark.asyncio


BASE_TIME = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)


class FakeSummaryClient:
    model_name = "gpt-5-test"

    def __init__(self, *, summary: str = "Generated checklist summary.", error: Exception | None = None) -> None:
        self.summary = summary
        self.error = error
        self.calls = 0
        self.payloads: list[dict[str, object]] = []

    def generate_summary(self, prompt, payload):
        self.calls += 1
        self.payloads.append(payload)
        if self.error is not None:
            raise self.error
        return self.summary


async def test_generate_checklist_detects_uploaded_and_missing_documents(db_session, seeded_assessment):
    await add_document(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        filename="soc2.pdf",
        system_document_type=DocumentType.SOC2_TYPE_II.value,
    )
    await db_session.commit()

    result = await DocumentChecklistService().generate_checklist_run(db_session, seeded_assessment["assessment_id"])

    assert [state.item.document_type for state in result.items] == [
        DocumentType.SOC2_TYPE_II.value,
        DocumentType.ISO_27001.value,
        DocumentType.ARCHITECTURE_DIAGRAM.value,
    ]
    assert [state.item.item_order for state in result.items] == [1, 2, 3]
    assert _state_by_type(result)[DocumentType.SOC2_TYPE_II.value].detected_file is True
    assert _state_by_type(result)[DocumentType.SOC2_TYPE_II.value].base_verdict == ChecklistVerdict.NOT_APPLICABLE.value
    assert _state_by_type(result)[DocumentType.ISO_27001.value].detected_file is False
    assert _state_by_type(result)[DocumentType.ISO_27001.value].base_verdict == ChecklistVerdict.REQUIRED.value
    assert _state_by_type(result)[DocumentType.ARCHITECTURE_DIAGRAM.value].base_verdict == ChecklistVerdict.REQUIRED.value


async def test_generate_checklist_uses_manual_classification_override(db_session, seeded_assessment):
    document = await add_document(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        filename="diagram.pdf",
        system_document_type="Unclassified",
    )
    review = await DocumentRepository().append_classification_review(
        db_session,
        document_id=document.id,
        document_type=DocumentType.ARCHITECTURE_DIAGRAM,
        reason="Reviewer identified a diagram.",
    )
    review.created_at = BASE_TIME + timedelta(minutes=1)
    await db_session.commit()

    result = await DocumentChecklistService().generate_checklist_run(db_session, seeded_assessment["assessment_id"])

    architecture = _state_by_type(result)[DocumentType.ARCHITECTURE_DIAGRAM.value]
    assert architecture.detected_file is True
    assert architecture.base_verdict == ChecklistVerdict.NOT_APPLICABLE.value
    assert _snapshot_item(result.run, DocumentType.ARCHITECTURE_DIAGRAM)["detectedDocumentIds"] == [str(document.id)]


async def test_generate_checklist_ignores_soft_deleted_documents(db_session, seeded_assessment):
    await add_document(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        filename="deleted-soc2.pdf",
        system_document_type=DocumentType.SOC2_TYPE_II.value,
        deleted_at=BASE_TIME + timedelta(minutes=1),
    )
    await db_session.commit()

    result = await DocumentChecklistService().generate_checklist_run(db_session, seeded_assessment["assessment_id"])

    soc2 = _state_by_type(result)[DocumentType.SOC2_TYPE_II.value]
    assert soc2.detected_file is False
    assert soc2.base_verdict == ChecklistVerdict.REQUIRED.value


async def test_vendor_reputation_available_keeps_file_missing_but_influences_verdict(db_session, seeded_assessment):
    await add_vendor_certification(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        soc2_auto_status="Available",
        iso27001_auto_status="Missing",
    )
    await db_session.commit()

    result = await DocumentChecklistService().generate_checklist_run(db_session, seeded_assessment["assessment_id"])

    soc2 = _state_by_type(result)[DocumentType.SOC2_TYPE_II.value]
    assert soc2.detected_file is False
    assert soc2.base_verdict == ChecklistVerdict.RECOMMENDED.value
    snapshot = _snapshot_item(result.run, DocumentType.SOC2_TYPE_II)
    assert snapshot["detectedFile"] is False
    assert snapshot["certification"] == {
        "automaticStatus": "Available",
        "analystStatus": None,
        "effectiveStatus": "Available",
    }


async def test_analyst_certification_status_overrides_automatic_status(db_session, seeded_assessment):
    await add_vendor_certification(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        soc2_auto_status="Missing",
        soc2_reviewer_status="Available",
        iso27001_auto_status="Available",
        iso27001_reviewer_status="Not Available",
    )
    await db_session.commit()

    result = await DocumentChecklistService().generate_checklist_run(db_session, seeded_assessment["assessment_id"])

    soc2_snapshot = _snapshot_item(result.run, DocumentType.SOC2_TYPE_II)["certification"]
    iso_snapshot = _snapshot_item(result.run, DocumentType.ISO_27001)["certification"]
    assert soc2_snapshot == {
        "automaticStatus": "Missing",
        "analystStatus": "Available",
        "effectiveStatus": "Available",
    }
    assert iso_snapshot == {
        "automaticStatus": "Available",
        "analystStatus": "Not Available",
        "effectiveStatus": "Not Available",
    }
    assert _state_by_type(result)[DocumentType.SOC2_TYPE_II.value].base_verdict == ChecklistVerdict.RECOMMENDED.value
    assert _state_by_type(result)[DocumentType.ISO_27001.value].base_verdict == ChecklistVerdict.REQUIRED.value


async def test_checklist_reviewer_override_changes_effective_verdict_not_base_or_file_status(
    db_session,
    seeded_assessment,
):
    await DocumentChecklistRepository().append_checklist_verdict_review(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        document_type=DocumentType.ARCHITECTURE_DIAGRAM,
        reviewer_verdict=ChecklistVerdict.NOT_APPLICABLE,
        reason="Reviewer waived the diagram.",
    )
    await db_session.commit()

    result = await DocumentChecklistService().generate_checklist_run(db_session, seeded_assessment["assessment_id"])

    architecture = _state_by_type(result)[DocumentType.ARCHITECTURE_DIAGRAM.value]
    assert architecture.detected_file is False
    assert architecture.base_verdict == ChecklistVerdict.REQUIRED.value
    assert architecture.item.base_verdict == ChecklistVerdict.REQUIRED.value
    assert architecture.reviewer_verdict == ChecklistVerdict.NOT_APPLICABLE.value
    assert architecture.effective_verdict == ChecklistVerdict.NOT_APPLICABLE.value


async def test_null_reviewer_override_falls_back_to_base_verdict(db_session, seeded_assessment):
    await DocumentChecklistRepository().append_checklist_verdict_review(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        document_type=DocumentType.SOC2_TYPE_II,
        reviewer_verdict=None,
    )
    await db_session.commit()

    result = await DocumentChecklistService().generate_checklist_run(db_session, seeded_assessment["assessment_id"])

    soc2 = _state_by_type(result)[DocumentType.SOC2_TYPE_II.value]
    assert soc2.base_verdict == ChecklistVerdict.REQUIRED.value
    assert soc2.reviewer_verdict is None
    assert soc2.effective_verdict == ChecklistVerdict.REQUIRED.value


async def test_latest_reviewer_override_wins(db_session, seeded_assessment):
    repository = DocumentChecklistRepository()
    older = await repository.append_checklist_verdict_review(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        document_type=DocumentType.ISO_27001,
        reviewer_verdict=ChecklistVerdict.RECOMMENDED,
    )
    latest = await repository.append_checklist_verdict_review(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        document_type=DocumentType.ISO_27001,
        reviewer_verdict=ChecklistVerdict.NOT_APPLICABLE,
    )
    older.created_at = BASE_TIME
    latest.created_at = BASE_TIME + timedelta(minutes=1)
    await db_session.commit()

    result = await DocumentChecklistService().generate_checklist_run(db_session, seeded_assessment["assessment_id"])

    iso = _state_by_type(result)[DocumentType.ISO_27001.value]
    assert iso.reviewer_verdict == ChecklistVerdict.NOT_APPLICABLE.value
    assert iso.effective_verdict == ChecklistVerdict.NOT_APPLICABLE.value
    assert _snapshot_item(result.run, DocumentType.ISO_27001)["latestReviewId"] == str(latest.id)


async def test_generation_creates_new_run_per_invocation_with_exactly_three_items(db_session, seeded_assessment):
    service = DocumentChecklistService()

    first = await service.generate_checklist_run(db_session, seeded_assessment["assessment_id"])
    second = await service.generate_checklist_run(db_session, seeded_assessment["assessment_id"])

    run_count = await db_session.scalar(select(func.count()).select_from(DocumentChecklistRun))
    item_count = await db_session.scalar(select(func.count()).select_from(DocumentChecklistItem))
    assert first.run.id != second.run.id
    assert run_count == 2
    assert item_count == 6
    assert [state.item.item_order for state in second.items] == [1, 2, 3]


async def test_generation_flushes_without_committing(db_session, seeded_assessment, monkeypatch):
    commit_calls = 0

    async def commit_spy():
        nonlocal commit_calls
        commit_calls += 1
        raise AssertionError("Document checklist generation must not commit.")

    monkeypatch.setattr(db_session, "commit", commit_spy)

    result = await DocumentChecklistService().generate_checklist_run(db_session, seeded_assessment["assessment_id"])

    assert commit_calls == 0
    assert result.run.id is not None
    assert all(state.item.id is not None for state in result.items)
    assert await db_session.get(DocumentChecklistRun, result.run.id) is not None


async def test_generation_calls_llm_once_and_stores_summary(db_session, seeded_assessment):
    fake_client = FakeSummaryClient(summary="Checklist summary.")

    result = await DocumentChecklistService(llm_client=fake_client).generate_checklist_run(
        db_session,
        seeded_assessment["assessment_id"],
    )

    assert fake_client.calls == 1
    assert fake_client.payloads[0]["assessment_id"] == str(seeded_assessment["assessment_id"])
    assert "detectedFileStatus" in fake_client.payloads[0]["checklist_items_json"]
    assert "effectiveHitlVerdict" in fake_client.payloads[0]["checklist_items_json"]
    assert "automaticStatus" in fake_client.payloads[0]["vendor_certification_json"]
    assert result.run.summary_text == "Checklist summary."
    assert result.run.summary_status == "generated"
    assert result.run.summary_model == "gpt-5-test"
    assert result.run.summary_prompt_version == "1.0"
    assert result.run.summary_input_hash is not None
    assert result.run.summary_generated_at is not None
    assert result.run.error_summary is None


async def test_generation_preserves_run_and_items_when_llm_fails(db_session, seeded_assessment):
    fake_client = FakeSummaryClient(error=RuntimeError("LLM unavailable."))

    result = await DocumentChecklistService(llm_client=fake_client).generate_checklist_run(
        db_session,
        seeded_assessment["assessment_id"],
    )

    assert fake_client.calls == 1
    assert result.run.id is not None
    assert len(result.items) == 3
    assert [state.item.base_verdict for state in result.items] == ["Required", "Required", "Required"]
    assert result.run.summary_text is None
    assert result.run.summary_status == "failed"
    assert result.run.summary_model == "gpt-5-test"
    assert result.run.summary_prompt_version == "1.0"
    assert result.run.summary_input_hash is not None
    assert result.run.summary_generated_at is not None
    assert result.run.error_summary == "LLM unavailable."


async def test_review_repository_flushes_without_committing(db_session, seeded_assessment, monkeypatch):
    commit_calls = 0

    async def commit_spy():
        nonlocal commit_calls
        commit_calls += 1
        raise AssertionError("Document checklist repository must not commit.")

    monkeypatch.setattr(db_session, "commit", commit_spy)

    review = await DocumentChecklistRepository().append_checklist_verdict_review(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        document_type=DocumentType.SOC2_TYPE_II,
        reviewer_verdict=ChecklistVerdict.RECOMMENDED,
        reason="Reviewer accepted certification.",
    )

    assert commit_calls == 0
    assert review.id is not None
    assert await db_session.get(DocumentChecklistItemReview, review.id) is not None


async def test_review_service_flushes_without_committing(db_session, seeded_assessment, monkeypatch):
    run = await DocumentChecklistService().generate_checklist_run(db_session, seeded_assessment["assessment_id"])
    item = run.items[0].item
    commit_calls = 0

    async def commit_spy():
        nonlocal commit_calls
        commit_calls += 1
        raise AssertionError("Document checklist service must not commit.")

    monkeypatch.setattr(db_session, "commit", commit_spy)

    result = await DocumentChecklistService().append_item_review(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        item_id=item.id,
        reviewer_verdict=ChecklistVerdict.RECOMMENDED,
        reason="Reviewer accepted certification.",
    )

    assert commit_calls == 0
    assert result.item.id == item.id
    assert result.effective_verdict == ChecklistVerdict.RECOMMENDED.value


async def add_document(
    session,
    *,
    assessment_id: uuid.UUID,
    filename: str,
    system_document_type: str,
    deleted_at: datetime | None = None,
) -> AssessmentDocument:
    document = AssessmentDocument(
        id=uuid.uuid4(),
        assessment_id=assessment_id,
        original_filename=filename,
        content_type="application/pdf",
        file_size_bytes=128,
        sha256=f"sha-{uuid.uuid4()}",
        storage_container="sar-documents",
        storage_key=f"{assessment_id}/{filename}",
        upload_source="sar_request",
        system_document_type=system_document_type,
        created_at=BASE_TIME,
        deleted_at=deleted_at,
        document_metadata={},
    )
    session.add(document)
    await session.flush()
    return document


async def add_vendor_certification(
    session,
    *,
    assessment_id: uuid.UUID,
    soc2_auto_status: str,
    iso27001_auto_status: str,
    soc2_reviewer_status: str | None = None,
    iso27001_reviewer_status: str | None = None,
) -> None:
    job_id = uuid.uuid4()
    await session.execute(
        vendor_reputation_jobs.insert(),
        [
            {
                "id": job_id,
                "assessment_id": assessment_id,
                "vendor_name": "Vendor",
                "product_name": "Product",
                "pipeline_profile": "vendor_reputation_default",
                "status": "review_submitted",
                "requires_analyst_review": True,
                "created_at": BASE_TIME,
                "updated_at": BASE_TIME,
                "limitations": [],
                "metadata": {},
            }
        ],
    )
    await session.execute(
        vendor_reputation_hitl_reviews.insert(),
        [
            {
                "id": uuid.uuid4(),
                "job_id": job_id,
                "trust_center_scraped_char_count": 0,
                "soc2_auto_status": soc2_auto_status,
                "soc2_reviewer_status": soc2_reviewer_status,
                "iso27001_auto_status": iso27001_auto_status,
                "iso27001_reviewer_status": iso27001_reviewer_status,
                "review_status": "pending",
                "limitations": [],
                "metadata": {},
                "created_at": BASE_TIME,
                "updated_at": BASE_TIME,
            }
        ],
    )


def _state_by_type(result) -> dict[str, object]:
    return {state.item.document_type: state for state in result.items}


def _snapshot_item(run: DocumentChecklistRun, document_type: DocumentType | str) -> dict[str, object]:
    document_type_value = document_type.value if isinstance(document_type, DocumentType) else document_type
    return next(item for item in run.input_snapshot["items"] if item["documentType"] == document_type_value)
