from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import uuid
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import DocumentChecklistItem, DocumentChecklistItemReview, DocumentChecklistRun
from app.models.enums import (
    ChecklistVerdict,
    DocumentChecklistRunStatus,
    DocumentChecklistSummaryStatus,
    DocumentType,
)


@dataclass(frozen=True)
class ChecklistItemInput:
    document_type: DocumentType | str
    base_verdict: ChecklistVerdict | str
    item_order: int | None = None


@dataclass(frozen=True)
class DocumentChecklistRunRecord:
    run: DocumentChecklistRun
    items: list[DocumentChecklistItem]


@dataclass(frozen=True)
class DocumentChecklistItemRecord:
    run: DocumentChecklistRun
    item: DocumentChecklistItem


class DocumentChecklistRepository:
    async def create_checklist_run(
        self,
        session: AsyncSession,
        *,
        assessment_id: UUID | str,
        items: Sequence[ChecklistItemInput | tuple[DocumentType | str, ChecklistVerdict | str] | dict[str, object]],
        status: DocumentChecklistRunStatus | str = DocumentChecklistRunStatus.DRAFT,
        summary_status: DocumentChecklistSummaryStatus | str = DocumentChecklistSummaryStatus.NOT_GENERATED,
        summary_text: str | None = None,
        input_snapshot: dict[str, object] | None = None,
        limitations: list[object] | None = None,
        error_summary: str | None = None,
    ) -> DocumentChecklistRunRecord:
        normalized_items = self._normalize_items(items)
        created_at = datetime.now(timezone.utc)
        run = DocumentChecklistRun(
            assessment_id=self._coerce_uuid(assessment_id),
            status=self._coerce_run_status(status),
            summary_status=self._coerce_summary_status(summary_status),
            summary_text=summary_text,
            input_snapshot=input_snapshot or {},
            limitations=limitations or [],
            error_summary=error_summary,
            created_at=created_at,
        )
        session.add(run)
        await session.flush()

        item_models = [
            DocumentChecklistItem(
                checklist_run_id=run.id,
                document_type=document_type,
                base_verdict=base_verdict,
                item_order=item_order,
            )
            for item_order, document_type, base_verdict in normalized_items
        ]
        session.add_all(item_models)
        await session.flush()
        return DocumentChecklistRunRecord(run=run, items=item_models)

    async def get_latest_checklist_run_with_items(
        self,
        session: AsyncSession,
        assessment_id: UUID | str,
    ) -> DocumentChecklistRunRecord | None:
        return await self.get_latest_assessment_checklist_run_with_items(session, assessment_id)

    async def get_latest_assessment_checklist_run_with_items(
        self,
        session: AsyncSession,
        assessment_id: UUID | str,
    ) -> DocumentChecklistRunRecord | None:
        run = (
            await session.execute(
                select(DocumentChecklistRun)
                .where(DocumentChecklistRun.assessment_id == self._coerce_uuid(assessment_id))
                .order_by(DocumentChecklistRun.created_at.desc(), DocumentChecklistRun.id.desc())
            )
        ).scalars().first()
        if run is None:
            return None

        items = (
            await session.execute(
                select(DocumentChecklistItem)
                .where(DocumentChecklistItem.checklist_run_id == run.id)
                .order_by(DocumentChecklistItem.item_order.asc(), DocumentChecklistItem.id.asc())
            )
        ).scalars().all()
        if len(items) != 3:
            raise ValueError(f"Checklist run {run.id} must have exactly 3 items.")
        return DocumentChecklistRunRecord(run=run, items=list(items))

    async def get_checklist_run_with_items(
        self,
        session: AsyncSession,
        *,
        assessment_id: UUID | str,
        run_id: UUID | str,
    ) -> DocumentChecklistRunRecord | None:
        run = (
            await session.execute(
                select(DocumentChecklistRun).where(
                    DocumentChecklistRun.id == self._coerce_uuid(run_id),
                    DocumentChecklistRun.assessment_id == self._coerce_uuid(assessment_id),
                )
            )
        ).scalars().first()
        if run is None:
            return None

        items = (
            await session.execute(
                select(DocumentChecklistItem)
                .where(DocumentChecklistItem.checklist_run_id == run.id)
                .order_by(DocumentChecklistItem.item_order.asc(), DocumentChecklistItem.id.asc())
            )
        ).scalars().all()
        if len(items) != 3:
            raise ValueError(f"Checklist run {run.id} must have exactly 3 items.")
        return DocumentChecklistRunRecord(run=run, items=list(items))

    async def update_run_status(
        self,
        session: AsyncSession,
        *,
        run: DocumentChecklistRun,
        status: DocumentChecklistRunStatus | str,
        error_summary: str | None = None,
    ) -> DocumentChecklistRun:
        run.status = self._coerce_run_status(status)
        run.error_summary = error_summary
        await session.flush()
        return run

    async def update_run_summary(
        self,
        session: AsyncSession,
        *,
        run: DocumentChecklistRun,
        summary_text: str | None,
        summary_status: DocumentChecklistSummaryStatus | str,
        summary_model: str | None,
        summary_prompt_version: str | None,
        summary_input_hash: str | None,
        summary_generated_at,
        error_summary: str | None,
    ) -> DocumentChecklistRun:
        run.summary_text = summary_text
        run.summary_status = self._coerce_summary_status(summary_status)
        run.summary_model = summary_model
        run.summary_prompt_version = summary_prompt_version
        run.summary_input_hash = summary_input_hash
        run.summary_generated_at = summary_generated_at
        run.error_summary = error_summary
        await session.flush()
        return run

    async def get_checklist_item_for_assessment(
        self,
        session: AsyncSession,
        *,
        assessment_id: UUID | str,
        item_id: UUID | str,
    ) -> DocumentChecklistItemRecord | None:
        row = (
            await session.execute(
                select(DocumentChecklistRun, DocumentChecklistItem)
                .join(DocumentChecklistItem, DocumentChecklistItem.checklist_run_id == DocumentChecklistRun.id)
                .where(
                    DocumentChecklistRun.assessment_id == self._coerce_uuid(assessment_id),
                    DocumentChecklistItem.id == self._coerce_uuid(item_id),
                )
            )
        ).first()
        if row is None:
            return None
        run, item = row
        return DocumentChecklistItemRecord(run=run, item=item)

    async def append_checklist_verdict_review(
        self,
        session: AsyncSession,
        *,
        assessment_id: UUID | str,
        document_type: DocumentType | str,
        reviewer_verdict: ChecklistVerdict | str | None,
        reason: str | None = None,
        reviewed_by: str | None = None,
        source_item_id: UUID | str | None = None,
    ) -> DocumentChecklistItemReview:
        review = DocumentChecklistItemReview(
            assessment_id=self._coerce_uuid(assessment_id),
            source_item_id=self._coerce_uuid(source_item_id) if source_item_id is not None else None,
            document_type=self._coerce_document_type(document_type),
            reviewer_verdict=self._coerce_verdict(reviewer_verdict) if reviewer_verdict is not None else None,
            reason=reason,
            reviewed_by=reviewed_by,
            created_at=datetime.now(timezone.utc),
        )
        session.add(review)
        await session.flush()
        return review

    async def get_latest_item_review(
        self,
        session: AsyncSession,
        *,
        assessment_id: UUID | str,
        document_type: DocumentType | str,
    ) -> DocumentChecklistItemReview | None:
        return (
            await session.execute(
                select(DocumentChecklistItemReview)
                .where(
                    DocumentChecklistItemReview.assessment_id == self._coerce_uuid(assessment_id),
                    DocumentChecklistItemReview.document_type == self._coerce_document_type(document_type),
                )
                .order_by(DocumentChecklistItemReview.created_at.desc(), DocumentChecklistItemReview.id.desc())
            )
        ).scalars().first()

    async def list_latest_item_reviews_by_assessment(
        self,
        session: AsyncSession,
        assessment_id: UUID | str,
    ) -> dict[str, DocumentChecklistItemReview]:
        ranked_reviews = (
            select(
                DocumentChecklistItemReview.id.label("review_id"),
                DocumentChecklistItemReview.document_type.label("document_type"),
                func.row_number()
                .over(
                    partition_by=DocumentChecklistItemReview.document_type,
                    order_by=(DocumentChecklistItemReview.created_at.desc(), DocumentChecklistItemReview.id.desc()),
                )
                .label("review_rank"),
            )
            .where(DocumentChecklistItemReview.assessment_id == self._coerce_uuid(assessment_id))
            .subquery()
        )

        reviews = (
            await session.execute(
                select(DocumentChecklistItemReview)
                .join(ranked_reviews, ranked_reviews.c.review_id == DocumentChecklistItemReview.id)
                .where(ranked_reviews.c.review_rank == 1)
            )
        ).scalars().all()
        return {review.document_type: review for review in reviews}

    async def list_latest_item_reviews_for_run_items(
        self,
        session: AsyncSession,
        *,
        assessment_id: UUID | str,
        item_ids: Sequence[UUID | str],
    ) -> dict[str, DocumentChecklistItemReview]:
        normalized_item_ids = [self._coerce_uuid(item_id) for item_id in item_ids]
        if not normalized_item_ids:
            return {}

        ranked_reviews = (
            select(
                DocumentChecklistItemReview.id.label("review_id"),
                DocumentChecklistItemReview.document_type.label("document_type"),
                func.row_number()
                .over(
                    partition_by=DocumentChecklistItemReview.source_item_id,
                    order_by=(
                        DocumentChecklistItemReview.created_at.desc(),
                        DocumentChecklistItemReview.id.desc(),
                    ),
                )
                .label("review_rank"),
            )
            .where(
                DocumentChecklistItemReview.assessment_id == self._coerce_uuid(assessment_id),
                DocumentChecklistItemReview.source_item_id.in_(normalized_item_ids),
            )
            .subquery()
        )
        reviews = (
            await session.execute(
                select(DocumentChecklistItemReview)
                .join(ranked_reviews, ranked_reviews.c.review_id == DocumentChecklistItemReview.id)
                .where(ranked_reviews.c.review_rank == 1)
            )
        ).scalars().all()
        return {review.document_type: review for review in reviews}

    @classmethod
    def _normalize_items(
        cls,
        items: Sequence[ChecklistItemInput | tuple[DocumentType | str, ChecklistVerdict | str] | dict[str, object]],
    ) -> list[tuple[int, str, str]]:
        if len(items) != 3:
            raise ValueError("A checklist run must contain exactly 3 items.")

        normalized: list[tuple[int, str, str]] = []
        for index, item in enumerate(items, start=1):
            if isinstance(item, ChecklistItemInput):
                document_type = item.document_type
                base_verdict = item.base_verdict
                item_order = item.item_order or index
            elif isinstance(item, dict):
                document_type = item["document_type"]
                base_verdict = item["base_verdict"]
                item_order = int(item.get("item_order") or index)
            else:
                document_type, base_verdict = item
                item_order = index
            normalized.append(
                (item_order, cls._coerce_document_type(document_type), cls._coerce_verdict(base_verdict))
            )

        orders = [item_order for item_order, _, _ in normalized]
        if sorted(orders) != [1, 2, 3]:
            raise ValueError("Checklist item orders must be exactly 1, 2, and 3.")

        document_types = [document_type for _, document_type, _ in normalized]
        expected_types = {member.value for member in DocumentType}
        if set(document_types) != expected_types:
            raise ValueError("A checklist run must contain SOC 2 Type II, ISO 27001, and Architecture Diagram.")

        return sorted(normalized, key=lambda item: item[0])

    @staticmethod
    def _coerce_document_type(document_type: DocumentType | str | object) -> str:
        value = document_type.value if isinstance(document_type, DocumentType) else document_type
        if value not in {member.value for member in DocumentType}:
            raise ValueError(f"Unsupported document type: {value}")
        return str(value)

    @staticmethod
    def _coerce_verdict(verdict: ChecklistVerdict | str | object) -> str:
        value = verdict.value if isinstance(verdict, ChecklistVerdict) else verdict
        if value not in {member.value for member in ChecklistVerdict}:
            raise ValueError(f"Unsupported checklist verdict: {value}")
        return str(value)

    @staticmethod
    def _coerce_run_status(status: DocumentChecklistRunStatus | str) -> str:
        value = status.value if isinstance(status, DocumentChecklistRunStatus) else status
        if value not in {member.value for member in DocumentChecklistRunStatus}:
            raise ValueError(f"Unsupported checklist run status: {value}")
        return value

    @staticmethod
    def _coerce_summary_status(status: DocumentChecklistSummaryStatus | str) -> str:
        value = status.value if isinstance(status, DocumentChecklistSummaryStatus) else status
        if value not in {member.value for member in DocumentChecklistSummaryStatus}:
            raise ValueError(f"Unsupported checklist summary status: {value}")
        return value

    @staticmethod
    def _coerce_uuid(value: UUID | str) -> UUID:
        return value if isinstance(value, UUID) else UUID(value)
