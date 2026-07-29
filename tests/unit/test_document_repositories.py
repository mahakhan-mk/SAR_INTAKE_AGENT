from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import uuid

import pytest

from app.models.database import (
    AssessmentDocument,
    DocumentClassificationReview,
)
from app.models.enums import ChecklistVerdict, DocumentType
from app.repositories.document_checklist_repository import ChecklistItemInput, DocumentChecklistRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.vendor_certification_repository import (
    VendorCertificationRepository,
    vendor_reputation_hitl_reviews,
    vendor_reputation_jobs,
)
from app.services.document_service import DocumentCommandService, DocumentUploadInput

pytestmark = pytest.mark.asyncio


def create_document(
    *,
    assessment_id: uuid.UUID,
    filename: str,
    system_document_type: str,
    created_at: datetime,
    deleted_at: datetime | None = None,
) -> AssessmentDocument:
    return AssessmentDocument(
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
        created_at=created_at,
        deleted_at=deleted_at,
        document_metadata={},
    )


async def test_document_repository_lists_active_documents_with_latest_effective_classification(
    db_session,
    seeded_assessment,
):
    repository = DocumentRepository()
    base_time = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    active_document = create_document(
        assessment_id=seeded_assessment["assessment_id"],
        filename="soc2.pdf",
        system_document_type="Unclassified",
        created_at=base_time,
    )
    deleted_document = create_document(
        assessment_id=seeded_assessment["assessment_id"],
        filename="deleted.pdf",
        system_document_type=DocumentType.ISO_27001.value,
        created_at=base_time + timedelta(minutes=1),
        deleted_at=base_time + timedelta(minutes=2),
    )
    db_session.add_all([active_document, deleted_document])
    await db_session.flush()

    older_review = await repository.append_classification_review(
        db_session,
        document_id=active_document.id,
        document_type=DocumentType.ARCHITECTURE_DIAGRAM,
        reason="Initial classification.",
        reviewed_by="reviewer-1",
    )
    latest_review = await repository.append_classification_review(
        db_session,
        document_id=active_document.id,
        document_type=DocumentType.SOC2_TYPE_II,
        reason="Auditor report.",
        reviewed_by="reviewer-2",
    )
    older_review.created_at = base_time + timedelta(minutes=3)
    latest_review.created_at = base_time + timedelta(minutes=4)
    await db_session.commit()

    documents = await repository.list_active_documents_by_assessment(db_session, seeded_assessment["assessment_id"])

    assert [record.document.id for record in documents] == [active_document.id]
    assert documents[0].effective_document_type == DocumentType.SOC2_TYPE_II.value
    assert documents[0].latest_review_id == latest_review.id
    assert documents[0].latest_reviewed_by == "reviewer-2"


async def test_document_repository_loads_latest_review_for_assessment_and_document_type(
    db_session,
    seeded_assessment,
):
    repository = DocumentRepository()
    base_time = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    document = create_document(
        assessment_id=seeded_assessment["assessment_id"],
        filename="iso.pdf",
        system_document_type="Unclassified",
        created_at=base_time,
    )
    db_session.add(document)
    await db_session.flush()

    older_review = await repository.append_classification_review(
        db_session,
        document_id=document.id,
        document_type=DocumentType.ISO_27001,
        reason="Older review.",
    )
    latest_review = await repository.append_classification_review(
        db_session,
        document_id=document.id,
        document_type=DocumentType.ISO_27001,
        reason="Latest review.",
    )
    older_review.created_at = base_time + timedelta(minutes=1)
    latest_review.created_at = base_time + timedelta(minutes=2)
    await db_session.commit()

    review = await repository.get_latest_classification_review(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        document_type=DocumentType.ISO_27001,
    )

    assert review is not None
    assert review.id == latest_review.id


async def test_document_classification_repository_flushes_without_committing(
    db_session,
    seeded_assessment,
    monkeypatch,
):
    document = create_document(
        assessment_id=seeded_assessment["assessment_id"],
        filename="classify.pdf",
        system_document_type="Unclassified",
        created_at=datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc),
    )
    db_session.add(document)
    await db_session.flush()
    commit_calls = 0

    async def commit_spy():
        nonlocal commit_calls
        commit_calls += 1
        raise AssertionError("Document repository must not commit.")

    monkeypatch.setattr(db_session, "commit", commit_spy)

    review = await DocumentRepository().append_classification_review(
        db_session,
        document_id=document.id,
        document_type=DocumentType.SOC2_TYPE_II,
        reason="Reviewer identified SOC 2.",
    )

    assert commit_calls == 0
    assert review.id is not None
    assert await db_session.get(DocumentClassificationReview, review.id) is not None


async def test_document_classification_service_flushes_without_committing(
    db_session,
    seeded_assessment,
    monkeypatch,
):
    document = create_document(
        assessment_id=seeded_assessment["assessment_id"],
        filename="service-classify.pdf",
        system_document_type="Unclassified",
        created_at=datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc),
    )
    db_session.add(document)
    await db_session.flush()
    commit_calls = 0

    async def commit_spy():
        nonlocal commit_calls
        commit_calls += 1
        raise AssertionError("Document service must not commit.")

    monkeypatch.setattr(db_session, "commit", commit_spy)

    review = await DocumentCommandService().append_classification_review(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        document_id=document.id,
        document_type=DocumentType.ARCHITECTURE_DIAGRAM,
        reason="Reviewer identified a diagram.",
    )

    assert commit_calls == 0
    assert review.id is not None
    assert review.document_type == DocumentType.ARCHITECTURE_DIAGRAM.value


async def test_document_repository_creates_document_without_committing(db_session, seeded_assessment, monkeypatch):
    commit_calls = 0

    async def commit_spy():
        nonlocal commit_calls
        commit_calls += 1
        raise AssertionError("Document repository must not commit.")

    monkeypatch.setattr(db_session, "commit", commit_spy)

    document = await DocumentRepository().create_assessment_document(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        original_filename="soc2.pdf",
        content_type="application/pdf",
        file_size_bytes=7,
        sha256="sha-repository",
        storage_container="sar-documents",
        storage_key=f"{seeded_assessment['assessment_id']}/repository-soc2.pdf",
        upload_source="sar_request",
        system_document_type=DocumentType.SOC2_TYPE_II.value,
        document_metadata={},
    )

    assert commit_calls == 0
    assert document.id is not None
    assert await db_session.get(AssessmentDocument, document.id) is not None


async def test_document_service_uploads_document_without_committing(db_session, seeded_assessment, monkeypatch):
    commit_calls = 0

    async def commit_spy():
        nonlocal commit_calls
        commit_calls += 1
        raise AssertionError("Document service must not commit.")

    monkeypatch.setattr(db_session, "commit", commit_spy)

    document = await DocumentCommandService().upload_document(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        upload=DocumentUploadInput(
            filename="soc2.pdf",
            content_type="application/pdf",
            content=b"service",
            system_document_type=DocumentType.SOC2_TYPE_II.value,
        ),
    )

    assert commit_calls == 0
    assert document.id is not None
    assert document.sha256 == hashlib.sha256(b"service").hexdigest()


async def test_document_checklist_repository_creates_and_reads_latest_three_ordered_items(
    db_session,
    seeded_assessment,
):
    repository = DocumentChecklistRepository()
    older = await repository.create_checklist_run(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        items=[
            ChecklistItemInput(DocumentType.SOC2_TYPE_II, ChecklistVerdict.RECOMMENDED, 1),
            ChecklistItemInput(DocumentType.ISO_27001, ChecklistVerdict.RECOMMENDED, 2),
            ChecklistItemInput(DocumentType.ARCHITECTURE_DIAGRAM, ChecklistVerdict.RECOMMENDED, 3),
        ],
    )
    latest = await repository.create_checklist_run(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        items=[
            ChecklistItemInput(DocumentType.SOC2_TYPE_II, ChecklistVerdict.REQUIRED, 1),
            ChecklistItemInput(DocumentType.ISO_27001, ChecklistVerdict.RECOMMENDED, 2),
            ChecklistItemInput(DocumentType.ARCHITECTURE_DIAGRAM, ChecklistVerdict.NOT_APPLICABLE, 3),
        ],
    )
    older.run.created_at = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    latest.run.created_at = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    await db_session.commit()

    result = await repository.get_latest_checklist_run_with_items(db_session, seeded_assessment["assessment_id"])

    assert result is not None
    assert result.run.id == latest.run.id
    assert [item.item_order for item in result.items] == [1, 2, 3]
    assert [item.document_type for item in result.items] == [
        DocumentType.SOC2_TYPE_II.value,
        DocumentType.ISO_27001.value,
        DocumentType.ARCHITECTURE_DIAGRAM.value,
    ]
    assert [item.base_verdict for item in result.items] == ["Required", "Recommended", "N/A"]


async def test_document_checklist_repository_requires_exactly_three_allowed_items(db_session, seeded_assessment):
    repository = DocumentChecklistRepository()

    with pytest.raises(ValueError, match="exactly 3"):
        await repository.create_checklist_run(
            db_session,
            assessment_id=seeded_assessment["assessment_id"],
            items=[
                ChecklistItemInput(DocumentType.SOC2_TYPE_II, ChecklistVerdict.REQUIRED, 1),
                ChecklistItemInput(DocumentType.ISO_27001, ChecklistVerdict.RECOMMENDED, 2),
            ],
        )

    with pytest.raises(ValueError, match="SOC 2 Type II"):
        await repository.create_checklist_run(
            db_session,
            assessment_id=seeded_assessment["assessment_id"],
            items=[
                ChecklistItemInput(DocumentType.SOC2_TYPE_II, ChecklistVerdict.REQUIRED, 1),
                ChecklistItemInput(DocumentType.ISO_27001, ChecklistVerdict.RECOMMENDED, 2),
                ChecklistItemInput(DocumentType.ISO_27001, ChecklistVerdict.NOT_APPLICABLE, 3),
            ],
        )


async def test_document_checklist_repository_appends_and_loads_latest_verdict_reviews(
    db_session,
    seeded_assessment,
):
    repository = DocumentChecklistRepository()
    run = await repository.create_checklist_run(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        items=[
            ChecklistItemInput(DocumentType.SOC2_TYPE_II, ChecklistVerdict.RECOMMENDED, 1),
            ChecklistItemInput(DocumentType.ISO_27001, ChecklistVerdict.RECOMMENDED, 2),
            ChecklistItemInput(DocumentType.ARCHITECTURE_DIAGRAM, ChecklistVerdict.RECOMMENDED, 3),
        ],
    )
    source_item = run.items[0]
    older_review = await repository.append_checklist_verdict_review(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        source_item_id=source_item.id,
        document_type=DocumentType.SOC2_TYPE_II,
        reviewer_verdict=ChecklistVerdict.RECOMMENDED,
        reason="Initial reviewer decision.",
    )
    latest_review = await repository.append_checklist_verdict_review(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        source_item_id=source_item.id,
        document_type=DocumentType.SOC2_TYPE_II,
        reviewer_verdict=ChecklistVerdict.REQUIRED,
        reason="Override to required.",
    )
    architecture_review = await repository.append_checklist_verdict_review(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        document_type=DocumentType.ARCHITECTURE_DIAGRAM,
        reviewer_verdict=ChecklistVerdict.NOT_APPLICABLE,
    )
    base_time = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    older_review.created_at = base_time
    latest_review.created_at = base_time + timedelta(minutes=1)
    architecture_review.created_at = base_time + timedelta(minutes=2)
    await db_session.commit()

    latest_soc2 = await repository.get_latest_item_review(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        document_type=DocumentType.SOC2_TYPE_II,
    )
    latest_reviews = await repository.list_latest_item_reviews_by_assessment(
        db_session,
        seeded_assessment["assessment_id"],
    )

    assert latest_soc2 is not None
    assert latest_soc2.id == latest_review.id
    assert latest_reviews[DocumentType.SOC2_TYPE_II.value].reviewer_verdict == ChecklistVerdict.REQUIRED.value
    assert latest_reviews[DocumentType.ARCHITECTURE_DIAGRAM.value].id == architecture_review.id


async def test_document_checklist_repository_returns_latest_run_from_standardized_method(
    db_session,
    seeded_assessment,
):
    repository = DocumentChecklistRepository()
    first = await repository.create_checklist_run(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        items=[
            ChecklistItemInput(DocumentType.SOC2_TYPE_II, ChecklistVerdict.RECOMMENDED, 1),
            ChecklistItemInput(DocumentType.ISO_27001, ChecklistVerdict.RECOMMENDED, 2),
            ChecklistItemInput(DocumentType.ARCHITECTURE_DIAGRAM, ChecklistVerdict.RECOMMENDED, 3),
        ],
    )
    second = await repository.create_checklist_run(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        items=[
            ChecklistItemInput(DocumentType.SOC2_TYPE_II, ChecklistVerdict.REQUIRED, 1),
            ChecklistItemInput(DocumentType.ISO_27001, ChecklistVerdict.RECOMMENDED, 2),
            ChecklistItemInput(DocumentType.ARCHITECTURE_DIAGRAM, ChecklistVerdict.NOT_APPLICABLE, 3),
        ],
    )
    first.run.created_at = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    second.run.created_at = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    await db_session.commit()

    latest = await repository.get_latest_assessment_checklist_run_with_items(
        db_session,
        seeded_assessment["assessment_id"],
    )

    assert latest is not None
    assert latest.run.id == second.run.id


async def test_document_repository_returns_latest_active_document_by_type(db_session, seeded_assessment):
    repository = DocumentRepository()
    older = create_document(
        assessment_id=seeded_assessment["assessment_id"],
        filename="older-soc2.pdf",
        system_document_type=DocumentType.SOC2_TYPE_II.value,
        created_at=datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc),
    )
    latest = create_document(
        assessment_id=seeded_assessment["assessment_id"],
        filename="latest-soc2.pdf",
        system_document_type=DocumentType.SOC2_TYPE_II.value,
        created_at=datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc),
    )
    deleted = create_document(
        assessment_id=seeded_assessment["assessment_id"],
        filename="deleted-soc2.pdf",
        system_document_type=DocumentType.SOC2_TYPE_II.value,
        created_at=datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc),
        deleted_at=datetime(2026, 7, 22, 13, 0, tzinfo=timezone.utc),
    )
    db_session.add_all([older, latest, deleted])
    await db_session.commit()

    document = await repository.get_latest_active_document_for_assessment_type(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        system_document_type=DocumentType.SOC2_TYPE_II.value,
    )

    assert document is not None
    assert document.id == latest.id


async def test_vendor_certification_repository_reads_latest_eligible_hitl_review_with_reviewer_overrides(
    db_session,
    seeded_assessment,
):
    base_time = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    older_job_id = uuid.uuid4()
    latest_failed_job_id = uuid.uuid4()
    latest_eligible_job_id = uuid.uuid4()
    latest_review_id = uuid.uuid4()
    await db_session.execute(
        vendor_reputation_jobs.insert(),
        [
            _vendor_job_row(
                older_job_id,
                seeded_assessment["assessment_id"],
                "completed",
                base_time,
            ),
            _vendor_job_row(
                latest_failed_job_id,
                seeded_assessment["assessment_id"],
                "failed",
                base_time + timedelta(days=2),
            ),
            _vendor_job_row(
                latest_eligible_job_id,
                seeded_assessment["assessment_id"],
                "review_submitted",
                base_time + timedelta(days=1),
            ),
        ],
    )
    await db_session.execute(
        vendor_reputation_hitl_reviews.insert(),
        [
            _hitl_review_row(uuid.uuid4(), older_job_id, "Missing", "Missing", base_time),
            _hitl_review_row(uuid.uuid4(), latest_failed_job_id, "Available", "Available", base_time),
            _hitl_review_row(
                latest_review_id,
                latest_eligible_job_id,
                "Missing",
                "Under NDA",
                base_time,
                soc2_reviewer_status="Available",
                iso27001_reviewer_status="Not Available",
            ),
        ],
    )
    await db_session.commit()

    result = await VendorCertificationRepository().get_latest_eligible_hitl_review(
        db_session,
        seeded_assessment["assessment_id"],
    )

    assert result is not None
    assert result.job_id == latest_eligible_job_id
    assert result.hitl_review_id == latest_review_id
    assert result.soc2_status == "Available"
    assert result.iso27001_status == "Not Available"


def _vendor_job_row(job_id: uuid.UUID, assessment_id: uuid.UUID, status: str, created_at: datetime) -> dict[str, object]:
    return {
        "id": job_id,
        "assessment_id": assessment_id,
        "vendor_name": "Microsoft",
        "product_name": "Copilot",
        "pipeline_profile": "vendor_reputation_default",
        "status": status,
        "requires_analyst_review": True,
        "created_at": created_at,
        "updated_at": created_at,
        "limitations": [],
        "metadata": {},
    }


def _hitl_review_row(
    review_id: uuid.UUID,
    job_id: uuid.UUID,
    soc2_auto_status: str,
    iso27001_auto_status: str,
    created_at: datetime,
    *,
    soc2_reviewer_status: str | None = None,
    iso27001_reviewer_status: str | None = None,
) -> dict[str, object]:
    return {
        "id": review_id,
        "job_id": job_id,
        "trust_center_scraped_char_count": 0,
        "soc2_auto_status": soc2_auto_status,
        "soc2_reviewer_status": soc2_reviewer_status,
        "iso27001_auto_status": iso27001_auto_status,
        "iso27001_reviewer_status": iso27001_reviewer_status,
        "review_status": "pending",
        "limitations": [],
        "metadata": {},
        "created_at": created_at,
        "updated_at": created_at,
    }
