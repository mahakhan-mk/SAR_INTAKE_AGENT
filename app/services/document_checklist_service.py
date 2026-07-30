from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.models import DocumentChecklistItemReadState, DocumentChecklistReadState
from app.domain.errors import DocumentChecklistRunNotFoundError, sanitize_failure_summary
from app.llm.client import AzureExecutiveSummaryClient
from app.llm.executive_summary import ExecutiveSummaryPromptLoader
from app.models.database import DocumentChecklistItem, DocumentChecklistRun
from app.models.enums import (
    ChecklistVerdict,
    DocumentChecklistRunStatus,
    DocumentChecklistSummaryStatus,
    DocumentType,
)
from app.repositories.document_checklist_repository import (
    ChecklistItemInput,
    DocumentChecklistRepository,
)
from app.repositories.document_repository import AssessmentDocumentRecord, DocumentRepository
from app.repositories.vendor_certification_repository import VendorCertificationRecord, VendorCertificationRepository


CHECKLIST_DOCUMENT_TYPES = (
    DocumentType.SOC2_TYPE_II,
    DocumentType.ISO_27001,
    DocumentType.ARCHITECTURE_DIAGRAM,
)
CERTIFICATION_DOCUMENT_TYPES = {
    DocumentType.SOC2_TYPE_II.value,
    DocumentType.ISO_27001.value,
}
CERTIFICATION_SUPPORTING_STATUSES = {"Available", "Under NDA"}


@dataclass(frozen=True)
class DocumentChecklistItemState:
    item: DocumentChecklistItem
    detected_file: bool
    base_verdict: str
    reviewer_verdict: str | None
    effective_verdict: str


@dataclass(frozen=True)
class DocumentChecklistGenerationResult:
    run: DocumentChecklistRun
    items: list[DocumentChecklistItemState]


class _DocumentChecklistReadStateBuilder:
    def __init__(
        self,
        *,
        checklist_repository: DocumentChecklistRepository | None = None,
    ) -> None:
        self.checklist_repository = checklist_repository or DocumentChecklistRepository()

    async def _build_read_state(
        self,
        session: AsyncSession,
        assessment_id: UUID,
        run_record,
        reviews_by_type: dict[str, object] | None = None,
    ) -> DocumentChecklistReadState:
        latest_reviews = reviews_by_type
        if latest_reviews is None:
            latest_reviews = await self.checklist_repository.list_latest_item_reviews_by_assessment(
                session,
                assessment_id,
            )
        snapshot_by_type = {
            str(item.get("documentType")): item
            for item in run_record.run.input_snapshot.get("items", [])
            if isinstance(item, dict) and item.get("documentType") is not None
        }

        item_states: list[DocumentChecklistItemReadState] = []
        for item in run_record.items:
            item_states.append(
                self._build_item_read_state_from_snapshot(
                    item=item,
                    snapshot=snapshot_by_type.get(item.document_type, {}),
                    review=latest_reviews.get(item.document_type),
                )
            )

        return DocumentChecklistReadState(run=run_record.run, items=item_states)

    async def _build_item_read_state(
        self,
        session: AsyncSession,
        *,
        assessment_id: UUID,
        run: DocumentChecklistRun,
        item: DocumentChecklistItem,
    ) -> DocumentChecklistItemReadState:
        review = await self.checklist_repository.get_latest_item_review(
            session,
            assessment_id=assessment_id,
            document_type=item.document_type,
        )
        snapshot = {}
        for snapshot_item in run.input_snapshot.get("items", []):
            if isinstance(snapshot_item, dict) and snapshot_item.get("documentType") == item.document_type:
                snapshot = snapshot_item
                break
        return self._build_item_read_state_from_snapshot(item=item, snapshot=snapshot, review=review)

    def _build_item_read_state_from_snapshot(
        self,
        *,
        item: DocumentChecklistItem,
        snapshot: dict[str, object],
        review,
    ) -> DocumentChecklistItemReadState:
        certification = snapshot.get("certification") if isinstance(snapshot, dict) else None
        if not isinstance(certification, dict):
            certification = {}

        detected_document_id = self._first_snapshot_document_id(snapshot)
        reviewer_verdict = review.reviewer_verdict if review is not None else None
        return DocumentChecklistItemReadState(
            item=item,
            effective_verdict=reviewer_verdict or item.base_verdict,
            detected_file_status="uploaded" if detected_document_id is not None else "missing",
            detected_document_id=detected_document_id,
            reviewer_verdict=reviewer_verdict,
            reviewer_reason=review.reason if review is not None else None,
            vendor_certification_automatic_status=self._optional_str(certification.get("automaticStatus")),
            vendor_certification_analyst_status=self._optional_str(certification.get("analystStatus")),
            vendor_certification_effective_status=self._optional_str(certification.get("effectiveStatus")),
        )

    @staticmethod
    def _coerce_uuid(value: UUID | str) -> UUID:
        return value if isinstance(value, UUID) else UUID(value)

    @classmethod
    def _first_snapshot_document_id(cls, snapshot: dict[str, object]) -> UUID | None:
        detected_document_ids = snapshot.get("detectedDocumentIds")
        if not isinstance(detected_document_ids, list) or not detected_document_ids:
            return None
        first_document_id = detected_document_ids[0]
        return cls._coerce_uuid(first_document_id) if isinstance(first_document_id, str | UUID) else None

    @staticmethod
    def _optional_str(value: object) -> str | None:
        return str(value) if value is not None else None


class DocumentChecklistExecutionService(_DocumentChecklistReadStateBuilder):
    def __init__(
        self,
        *,
        document_repository: DocumentRepository | None = None,
        checklist_repository: DocumentChecklistRepository | None = None,
        vendor_certification_repository: VendorCertificationRepository | None = None,
        prompt_loader: ExecutiveSummaryPromptLoader | None = None,
        llm_client: AzureExecutiveSummaryClient | None = None,
    ) -> None:
        super().__init__(checklist_repository=checklist_repository)
        self.document_repository = document_repository or DocumentRepository()
        self.vendor_certification_repository = vendor_certification_repository or VendorCertificationRepository()
        self.prompt_loader = prompt_loader or ExecutiveSummaryPromptLoader(
            Path(__file__).resolve().parents[1] / "prompts" / "document_checklist_summary.yaml"
        )
        self.llm_client = llm_client

    async def generate_checklist(
        self,
        session: AsyncSession,
        assessment_id: UUID | str,
    ) -> DocumentChecklistGenerationResult:
        normalized_assessment_id = self._coerce_uuid(assessment_id)
        documents = await self.document_repository.list_active_documents_by_assessment(session, normalized_assessment_id)
        latest_reviews = await self.checklist_repository.list_latest_item_reviews_by_assessment(
            session,
            normalized_assessment_id,
        )
        certification = await self.vendor_certification_repository.get_latest_eligible_hitl_review(
            session,
            normalized_assessment_id,
        )

        detected_documents = self._detected_documents_by_type(documents)
        snapshot_items: list[dict[str, object]] = []
        item_inputs: list[ChecklistItemInput] = []
        pending_states: list[dict[str, object]] = []

        for item_order, document_type in enumerate(CHECKLIST_DOCUMENT_TYPES, start=1):
            document_type_value = document_type.value
            detected_document_ids = detected_documents.get(document_type_value, [])
            detected_file = bool(detected_document_ids)
            certification_snapshot = self._certification_snapshot(document_type, certification)
            base_verdict = self._base_verdict(detected_file, certification_snapshot)
            review = latest_reviews.get(document_type_value)
            reviewer_verdict = review.reviewer_verdict if review is not None else None
            effective_verdict = reviewer_verdict or base_verdict

            item_inputs.append(
                ChecklistItemInput(
                    document_type=document_type,
                    base_verdict=base_verdict,
                    item_order=item_order,
                )
            )
            item_snapshot = {
                "itemOrder": item_order,
                "documentType": document_type_value,
                "detectedFile": detected_file,
                "detectedDocumentIds": [str(document_id) for document_id in detected_document_ids],
                "baseVerdict": base_verdict,
                "reviewerVerdict": reviewer_verdict,
                "effectiveVerdict": effective_verdict,
                "latestReviewId": str(review.id) if review is not None else None,
                "certification": certification_snapshot,
            }
            snapshot_items.append(item_snapshot)
            pending_states.append(
                {
                    "detected_file": detected_file,
                    "base_verdict": base_verdict,
                    "reviewer_verdict": reviewer_verdict,
                    "effective_verdict": effective_verdict,
                }
            )

        run_record = await self.checklist_repository.create_checklist_run(
            session,
            assessment_id=normalized_assessment_id,
            items=item_inputs,
            input_snapshot={
                "assessmentId": str(normalized_assessment_id),
                "items": snapshot_items,
                "vendorCertificationHitlReviewId": (
                    str(certification.hitl_review_id) if certification is not None else None
                ),
            },
        )
        await self._generate_summary(session, run_record=run_record, snapshot_items=snapshot_items)

        item_states = [
            DocumentChecklistItemState(
                item=item,
                detected_file=bool(state["detected_file"]),
                base_verdict=str(state["base_verdict"]),
                reviewer_verdict=(
                    str(state["reviewer_verdict"]) if state["reviewer_verdict"] is not None else None
                ),
                effective_verdict=str(state["effective_verdict"]),
            )
            for item, state in zip(run_record.items, pending_states, strict=True)
        ]
        return DocumentChecklistGenerationResult(run=run_record.run, items=item_states)

    async def generate_checklist_run(
        self,
        session: AsyncSession,
        assessment_id: UUID | str,
    ) -> DocumentChecklistGenerationResult:
        return await self.generate_checklist(session, assessment_id)

    async def finalize_checklist(
        self,
        session: AsyncSession,
        *,
        assessment_id: UUID | str,
        run_id: UUID | str,
    ) -> DocumentChecklistReadState:
        normalized_assessment_id = self._coerce_uuid(assessment_id)
        run_record = await self.checklist_repository.get_checklist_run_with_items(
            session,
            assessment_id=normalized_assessment_id,
            run_id=run_id,
        )
        if run_record is None:
            raise DocumentChecklistRunNotFoundError()

        current_reviews = await self.checklist_repository.list_latest_item_reviews_for_run_items(
            session,
            assessment_id=normalized_assessment_id,
            item_ids=[item.id for item in run_record.items],
        )
        state = await self._build_read_state(
            session,
            normalized_assessment_id,
            run_record,
            reviews_by_type=current_reviews,
        )
        required_types = {item.document_type for item in run_record.items}
        saved_decision_types = {
            document_type
            for document_type, review in current_reviews.items()
            if review.reviewer_verdict is not None
        }
        missing_review_types = sorted(required_types - saved_decision_types)
        missing_required_documents = sorted(
            item.item.document_type
            for item in state.items
            if item.effective_verdict == ChecklistVerdict.REQUIRED.value
            and item.detected_document_id is None
        )

        if missing_review_types or missing_required_documents:
            reasons: list[str] = []
            if missing_review_types:
                reasons.append(
                    "missing saved reviewer decisions for " + ", ".join(missing_review_types)
                )
            if missing_required_documents:
                reasons.append(
                    "required documents are missing for " + ", ".join(missing_required_documents)
                )
            await self.checklist_repository.update_run_status(
                session,
                run=run_record.run,
                status=DocumentChecklistRunStatus.INCOMPLETE,
                error_summary="; ".join(reasons),
            )
            return await self._build_read_state(
                session,
                normalized_assessment_id,
                run_record,
                reviews_by_type=current_reviews,
            )

        completed_status = (
            DocumentChecklistRunStatus.COMPLETED_WITH_LIMITATIONS
            if run_record.run.limitations
            or run_record.run.summary_status == DocumentChecklistSummaryStatus.FAILED.value
            else DocumentChecklistRunStatus.COMPLETED
        )
        await self.checklist_repository.update_run_status(
            session,
            run=run_record.run,
            status=completed_status,
            error_summary=None,
        )
        return await self._build_read_state(
            session,
            normalized_assessment_id,
            run_record,
            reviews_by_type=current_reviews,
        )

    async def _generate_summary(
        self,
        session: AsyncSession,
        *,
        run_record,
        snapshot_items: list[dict[str, object]],
    ) -> None:
        prompt = self.prompt_loader.load()
        input_payload = self._build_summary_payload(run_record.run, snapshot_items)
        input_hash = self._build_input_hash(input_payload)
        generated_at = datetime.now(timezone.utc)

        try:
            llm_client = self.llm_client or AzureExecutiveSummaryClient()
            summary_text = llm_client.generate_summary(prompt, self._renderable_summary_payload(input_payload))
            await self.checklist_repository.update_run_summary(
                session,
                run=run_record.run,
                summary_text=summary_text,
                summary_status=DocumentChecklistSummaryStatus.GENERATED,
                summary_model=llm_client.model_name,
                summary_prompt_version=prompt.version,
                summary_input_hash=input_hash,
                summary_generated_at=generated_at,
                error_summary=None,
            )
        except Exception as exc:
            await self.checklist_repository.update_run_summary(
                session,
                run=run_record.run,
                summary_text=None,
                summary_status=DocumentChecklistSummaryStatus.FAILED,
                summary_model=self.llm_client.model_name if self.llm_client is not None else None,
                summary_prompt_version=prompt.version,
                summary_input_hash=input_hash,
                summary_generated_at=generated_at,
                error_summary=sanitize_failure_summary(
                    exc,
                    fallback="Checklist generation returned invalid structured output.",
                    max_length=500,
                ),
            )

    @staticmethod
    def _detected_documents_by_type(documents: list[AssessmentDocumentRecord]) -> dict[str, list[uuid.UUID]]:
        detected_documents: dict[str, list[uuid.UUID]] = {}
        for document in documents:
            if document.effective_document_type not in {member.value for member in DocumentType}:
                continue
            detected_documents.setdefault(document.effective_document_type, []).append(document.document.id)
        return detected_documents

    @staticmethod
    def _certification_snapshot(
        document_type: DocumentType,
        certification: VendorCertificationRecord | None,
    ) -> dict[str, object] | None:
        if document_type.value not in CERTIFICATION_DOCUMENT_TYPES:
            return None
        if certification is None:
            return {
                "automaticStatus": None,
                "analystStatus": None,
                "effectiveStatus": None,
            }
        if document_type == DocumentType.SOC2_TYPE_II:
            return {
                "automaticStatus": certification.soc2_auto_status,
                "analystStatus": certification.soc2_analyst_status,
                "effectiveStatus": certification.soc2_status,
            }
        return {
            "automaticStatus": certification.iso27001_auto_status,
            "analystStatus": certification.iso27001_analyst_status,
            "effectiveStatus": certification.iso27001_status,
        }

    @staticmethod
    def _base_verdict(detected_file: bool, certification_snapshot: dict[str, object] | None) -> str:
        if detected_file:
            return ChecklistVerdict.NOT_APPLICABLE.value
        if certification_snapshot is None:
            return ChecklistVerdict.REQUIRED.value
        if certification_snapshot.get("effectiveStatus") in CERTIFICATION_SUPPORTING_STATUSES:
            return ChecklistVerdict.RECOMMENDED.value
        return ChecklistVerdict.REQUIRED.value

    @staticmethod
    def _build_summary_payload(run: DocumentChecklistRun, snapshot_items: list[dict[str, object]]) -> dict[str, object]:
        checklist_items = [
            {
                "documentType": item["documentType"],
                "detectedFileStatus": "uploaded" if item["detectedFile"] else "missing",
                "detectedDocumentIds": item["detectedDocumentIds"],
                "baseVerdict": item["baseVerdict"],
                "effectiveHitlVerdict": item["effectiveVerdict"],
                "reviewerVerdict": item["reviewerVerdict"],
            }
            for item in snapshot_items
        ]
        vendor_certification = [
            {
                "documentType": item["documentType"],
                "automaticStatus": item["certification"].get("automaticStatus"),
                "analystStatus": item["certification"].get("analystStatus"),
                "effectiveStatus": item["certification"].get("effectiveStatus"),
            }
            for item in snapshot_items
            if isinstance(item.get("certification"), dict)
        ]
        return {
            "assessmentId": str(run.assessment_id),
            "checklistItems": checklist_items,
            "vendorCertification": vendor_certification,
            "limitations": run.limitations,
        }

    @staticmethod
    def _renderable_summary_payload(payload: dict[str, object]) -> dict[str, object]:
        return {
            "assessment_id": payload["assessmentId"],
            "checklist_items_json": json.dumps(payload["checklistItems"], indent=2, sort_keys=True),
            "vendor_certification_json": json.dumps(payload["vendorCertification"], indent=2, sort_keys=True),
            "limitations_json": json.dumps(payload["limitations"], indent=2, sort_keys=True),
        }

    @staticmethod
    def _build_input_hash(payload: dict[str, object]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
