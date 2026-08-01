from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import DATABASE_SCHEMA_TOKEN
from app.models.database import Base, SarAssessment
from app.models.enums import (
    AssessmentDocumentSystemType,
    ChecklistVerdict,
    DocumentChecklistRunStatus,
    DocumentChecklistSummaryStatus,
    DocumentType,
)
from app.repositories.document_checklist_repository import ChecklistItemInput, DocumentChecklistRepository
from app.repositories.document_repository import DocumentRepository
from app.services.document_checklist_service import DocumentChecklistExecutionService


@pytest_asyncio.fixture
async def session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        execution_options={"schema_translate_map": {DATABASE_SCHEMA_TOKEN: None}},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


def _service() -> DocumentChecklistExecutionService:
    return DocumentChecklistExecutionService(
        document_repository=DocumentRepository(),
        checklist_repository=DocumentChecklistRepository(),
    )


async def _create_assessment(session: AsyncSession, assessment_id: UUID) -> None:
    session.add(
        SarAssessment(
            id=assessment_id,
            technology_name="Vendor intake",
            vendor_name="Vendor",
            status="received",
        )
    )
    await session.flush()


async def _create_run(
    session: AsyncSession,
    *,
    assessment_id: UUID,
    base_verdicts: dict[str, str] | None = None,
    snapshot_detected_types: set[str] | None = None,
):
    checklist_repository = DocumentChecklistRepository()
    verdicts = base_verdicts or {}
    detected_types = snapshot_detected_types or set()
    items = [
        ChecklistItemInput(
            document_type=document_type,
            base_verdict=verdicts.get(document_type.value, ChecklistVerdict.NOT_APPLICABLE.value),
            item_order=index,
        )
        for index, document_type in enumerate(DocumentType, start=1)
    ]
    snapshot_items = [
        {
            "documentType": item.document_type.value,
            "detectedDocumentIds": [str(uuid4())] if item.document_type.value in detected_types else [],
        }
        for item in items
    ]
    return await checklist_repository.create_checklist_run(
        session,
        assessment_id=assessment_id,
        items=items,
        summary_status=DocumentChecklistSummaryStatus.GENERATED,
        input_snapshot={"items": snapshot_items},
    )


async def _create_document(
    session: AsyncSession,
    *,
    assessment_id: UUID,
    document_type: AssessmentDocumentSystemType | str,
    deleted: bool = False,
):
    document_id = uuid4()
    document = await DocumentRepository().create_assessment_document(
        session,
        document_id=document_id,
        assessment_id=assessment_id,
        original_filename=f"{document_id}.pdf",
        content_type="application/pdf",
        file_size_bytes=128,
        sha256=str(document_id),
        storage_container="documents",
        storage_key=f"{assessment_id}/{document_id}.pdf",
        upload_source="checklist_row",
        system_document_type=document_type,
        uploaded_by="analyst",
    )
    if deleted:
        document.deleted_at = datetime.now(UTC)
        document.deleted_by = "analyst"
        await session.flush()
    return document


async def _append_review(
    session: AsyncSession,
    *,
    assessment_id: UUID,
    source_item_id: UUID,
    document_type: DocumentType | str,
    reviewer_verdict: ChecklistVerdict | str | None,
):
    return await DocumentChecklistRepository().append_checklist_verdict_review(
        session,
        assessment_id=assessment_id,
        source_item_id=source_item_id,
        document_type=document_type,
        reviewer_verdict=reviewer_verdict,
        reason="Analyst reviewed",
        reviewed_by="analyst",
    )


async def _finalize(session: AsyncSession, *, assessment_id: UUID, run_id: UUID):
    return await _service().finalize_checklist(
        session,
        assessment_id=assessment_id,
        run_id=run_id,
    )


@pytest.mark.asyncio
async def test_required_item_with_matching_active_document_and_null_reviewer_verdict_completes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    assessment_id = uuid4()
    async with session_factory() as session:
        async with session.begin():
            await _create_assessment(session, assessment_id)
            run_record = await _create_run(
                session,
                assessment_id=assessment_id,
                base_verdicts={DocumentType.SOC2_TYPE_II.value: ChecklistVerdict.REQUIRED.value},
            )
            soc2_item = run_record.items[0]
            document = await _create_document(
                session,
                assessment_id=assessment_id,
                document_type=AssessmentDocumentSystemType.SOC2_TYPE_II,
            )
            await _append_review(
                session,
                assessment_id=assessment_id,
                source_item_id=soc2_item.id,
                document_type=DocumentType.SOC2_TYPE_II,
                reviewer_verdict=None,
            )

            state = await _finalize(session, assessment_id=assessment_id, run_id=run_record.run.id)

        assert state.run.status == DocumentChecklistRunStatus.COMPLETED.value
        assert state.run.error_summary is None
        soc2_state = next(item for item in state.items if item.item.document_type == DocumentType.SOC2_TYPE_II.value)
        assert soc2_state.effective_verdict == ChecklistVerdict.REQUIRED.value
        assert soc2_state.reviewer_verdict is None
        assert soc2_state.detected_document_id == document.id


@pytest.mark.asyncio
async def test_required_item_without_matching_current_document_returns_incomplete(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    assessment_id = uuid4()
    async with session_factory() as session:
        async with session.begin():
            await _create_assessment(session, assessment_id)
            run_record = await _create_run(
                session,
                assessment_id=assessment_id,
                base_verdicts={DocumentType.SOC2_TYPE_II.value: ChecklistVerdict.REQUIRED.value},
                snapshot_detected_types={DocumentType.SOC2_TYPE_II.value},
            )

            state = await _finalize(session, assessment_id=assessment_id, run_id=run_record.run.id)

        assert state.run.status == DocumentChecklistRunStatus.INCOMPLETE.value
        assert state.run.error_summary == "required documents are missing for SOC 2 Type II"
        soc2_state = next(item for item in state.items if item.item.document_type == DocumentType.SOC2_TYPE_II.value)
        assert soc2_state.detected_document_id is None


@pytest.mark.asyncio
async def test_required_item_with_only_soft_deleted_matching_document_returns_incomplete(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    assessment_id = uuid4()
    async with session_factory() as session:
        async with session.begin():
            await _create_assessment(session, assessment_id)
            run_record = await _create_run(
                session,
                assessment_id=assessment_id,
                base_verdicts={DocumentType.SOC2_TYPE_II.value: ChecklistVerdict.REQUIRED.value},
            )
            await _create_document(
                session,
                assessment_id=assessment_id,
                document_type=AssessmentDocumentSystemType.SOC2_TYPE_II,
                deleted=True,
            )

            state = await _finalize(session, assessment_id=assessment_id, run_id=run_record.run.id)

        assert state.run.status == DocumentChecklistRunStatus.INCOMPLETE.value
        assert state.run.error_summary == "required documents are missing for SOC 2 Type II"


@pytest.mark.asyncio
@pytest.mark.parametrize("override", [ChecklistVerdict.NOT_APPLICABLE, ChecklistVerdict.RECOMMENDED])
async def test_non_required_reviewer_overrides_do_not_require_a_document(
    session_factory: async_sessionmaker[AsyncSession],
    override: ChecklistVerdict,
) -> None:
    assessment_id = uuid4()
    async with session_factory() as session:
        async with session.begin():
            await _create_assessment(session, assessment_id)
            run_record = await _create_run(
                session,
                assessment_id=assessment_id,
                base_verdicts={DocumentType.SOC2_TYPE_II.value: ChecklistVerdict.REQUIRED.value},
            )
            soc2_item = run_record.items[0]
            await _append_review(
                session,
                assessment_id=assessment_id,
                source_item_id=soc2_item.id,
                document_type=DocumentType.SOC2_TYPE_II,
                reviewer_verdict=override,
            )

            state = await _finalize(session, assessment_id=assessment_id, run_id=run_record.run.id)

        assert state.run.status == DocumentChecklistRunStatus.COMPLETED.value
        soc2_state = next(item for item in state.items if item.item.document_type == DocumentType.SOC2_TYPE_II.value)
        assert soc2_state.effective_verdict == override.value
        assert soc2_state.detected_document_id is None


@pytest.mark.asyncio
async def test_reviewer_override_required_requires_current_active_matching_document(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    assessment_id = uuid4()
    async with session_factory() as session:
        async with session.begin():
            await _create_assessment(session, assessment_id)
            run_record = await _create_run(session, assessment_id=assessment_id)
            soc2_item = run_record.items[0]
            await _append_review(
                session,
                assessment_id=assessment_id,
                source_item_id=soc2_item.id,
                document_type=DocumentType.SOC2_TYPE_II,
                reviewer_verdict=ChecklistVerdict.REQUIRED,
            )

            state = await _finalize(session, assessment_id=assessment_id, run_id=run_record.run.id)

        assert state.run.status == DocumentChecklistRunStatus.INCOMPLETE.value
        assert state.run.error_summary == "required documents are missing for SOC 2 Type II"


@pytest.mark.asyncio
async def test_documents_uploaded_after_checklist_generation_are_recognized_during_finalization(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    assessment_id = uuid4()
    async with session_factory() as session:
        async with session.begin():
            await _create_assessment(session, assessment_id)
            run_record = await _create_run(
                session,
                assessment_id=assessment_id,
                base_verdicts={DocumentType.SOC2_TYPE_II.value: ChecklistVerdict.REQUIRED.value},
            )
            document = await _create_document(
                session,
                assessment_id=assessment_id,
                document_type=AssessmentDocumentSystemType.SOC2_TYPE_II,
            )

            state = await _finalize(session, assessment_id=assessment_id, run_id=run_record.run.id)

        assert state.run.status == DocumentChecklistRunStatus.COMPLETED.value
        soc2_state = next(item for item in state.items if item.item.document_type == DocumentType.SOC2_TYPE_II.value)
        assert soc2_state.detected_document_id == document.id


@pytest.mark.asyncio
async def test_finalization_matches_current_documents_by_system_document_type(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    assessment_id = uuid4()
    async with session_factory() as session:
        async with session.begin():
            await _create_assessment(session, assessment_id)
            run_record = await _create_run(
                session,
                assessment_id=assessment_id,
                base_verdicts={DocumentType.SOC2_TYPE_II.value: ChecklistVerdict.REQUIRED.value},
            )
            document = await _create_document(
                session,
                assessment_id=assessment_id,
                document_type=AssessmentDocumentSystemType.SOC2_TYPE_II,
            )
            await DocumentRepository().append_classification_review(
                session,
                document_id=document.id,
                document_type=DocumentType.ISO_27001,
                reason="Classification review should not drive checklist finalization.",
                reviewed_by="analyst",
            )

            state = await _finalize(session, assessment_id=assessment_id, run_id=run_record.run.id)

        assert state.run.status == DocumentChecklistRunStatus.COMPLETED.value
        soc2_state = next(item for item in state.items if item.item.document_type == DocumentType.SOC2_TYPE_II.value)
        assert soc2_state.detected_document_id == document.id


@pytest.mark.asyncio
async def test_latest_non_null_reviewer_verdict_is_used_when_later_review_is_null(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    assessment_id = uuid4()
    async with session_factory() as session:
        async with session.begin():
            await _create_assessment(session, assessment_id)
            run_record = await _create_run(
                session,
                assessment_id=assessment_id,
                base_verdicts={DocumentType.SOC2_TYPE_II.value: ChecklistVerdict.REQUIRED.value},
            )
            soc2_item = run_record.items[0]
            await _append_review(
                session,
                assessment_id=assessment_id,
                source_item_id=soc2_item.id,
                document_type=DocumentType.SOC2_TYPE_II,
                reviewer_verdict=ChecklistVerdict.NOT_APPLICABLE,
            )
            await _append_review(
                session,
                assessment_id=assessment_id,
                source_item_id=soc2_item.id,
                document_type=DocumentType.SOC2_TYPE_II,
                reviewer_verdict=None,
            )

            state = await _finalize(session, assessment_id=assessment_id, run_id=run_record.run.id)

        assert state.run.status == DocumentChecklistRunStatus.COMPLETED.value
        soc2_state = next(item for item in state.items if item.item.document_type == DocumentType.SOC2_TYPE_II.value)
        assert soc2_state.effective_verdict == ChecklistVerdict.NOT_APPLICABLE.value
