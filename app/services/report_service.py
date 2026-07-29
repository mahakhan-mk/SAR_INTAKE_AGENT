from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.assemblers.report_preview_assembler import ReportPreviewAssembler
from app.application.models import (
    DocumentChecklistItemReadState,
    DocumentChecklistReadState,
    ReportPreviewResult,
    TopRiskDriverState,
)
from app.domain.errors import AssessmentNotFoundError
from app.models.database import AssessmentDocument, DocumentChecklistItem, DocumentChecklistItemReview, DocumentChecklistRun
from app.models.enums import AnalysisRunStatus, AssessmentDocumentSystemType, RiskLevel
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.document_checklist_repository import DocumentChecklistRepository, DocumentChecklistRunRecord
from app.repositories.document_repository import DocumentRepository
from app.repositories.report_repository import InitialSarReportRepository
from app.services.inherent_risk_service import InherentRiskQueryService
from app.services.initial_sar_report_storage import InitialSarReportStorage


@dataclass(frozen=True)
class ReportPreviewAssessmentMetadata:
    questionnaire_version: str | None
    source_system: str | None


@dataclass(frozen=True)
class ReportPreviewAnalysisState:
    inherent_risk_level: RiskLevel
    executive_summary_text: str | None
    status: AnalysisRunStatus
    top_risk_drivers: list[TopRiskDriverState]


@dataclass(frozen=True)
class InitialSarReportMetadata:
    report_id: UUID
    assessment_id: UUID
    source_workflow_version: int
    report_version: int
    original_filename: str
    content_type: str
    file_size_bytes: int
    sha256: str
    limitations: list[object]
    created_at: datetime
    stale_at: datetime | None


@dataclass(frozen=True)
class DownloadedInitialSarReport:
    filename: str
    content_type: str
    content: bytes


class ReportPreviewService:
    def __init__(
        self,
        *,
        assessment_repository: AssessmentRepository,
        analysis_repository: AnalysisRepository,
        checklist_repository: DocumentChecklistRepository,
        document_repository: DocumentRepository,
        inherent_risk_service: InherentRiskQueryService,
        assembler: ReportPreviewAssembler,
    ) -> None:
        self.assessment_repository = assessment_repository
        self.analysis_repository = analysis_repository
        self.checklist_repository = checklist_repository
        self.document_repository = document_repository
        self.inherent_risk_service = inherent_risk_service
        self.assembler = assembler

    async def get_report_preview(
        self,
        session: AsyncSession,
        assessment_id: UUID,
    ) -> ReportPreviewResult:
        assessment = await self.assessment_repository.get_assessment(session, assessment_id)
        if assessment is None:
            raise AssessmentNotFoundError()

        assessment_metadata = await self._load_assessment_metadata(session, assessment_id)
        response_records = await self.assessment_repository.list_visible_assessment_responses(session, assessment_id)

        latest_run = await self.analysis_repository.get_latest_usable_analysis_run(session, assessment_id)
        analysis_snapshot = (
            await self.analysis_repository.get_snapshot_for_run(session, latest_run)
            if latest_run is not None
            else None
        )
        prepared_analysis_state = (
            ReportPreviewAnalysisState(
                inherent_risk_level=analysis_snapshot.inherent_risk_level,
                executive_summary_text=analysis_snapshot.executive_summary_text,
                status=analysis_snapshot.status,
                top_risk_drivers=self.inherent_risk_service.derive_top_risk_drivers(
                    analysis_snapshot.question_results
                ),
            )
            if analysis_snapshot is not None
            else None
        )

        checklist_record = await self.checklist_repository.get_latest_checklist_run_with_items(session, assessment_id)
        checklist_state = (
            await self._build_checklist_state(session, assessment_id, checklist_record)
            if checklist_record is not None
            else None
        )

        architecture_document = await self.document_repository.get_latest_active_document_for_assessment_type(
            session,
            assessment_id=assessment_id,
            system_document_type=AssessmentDocumentSystemType.ARCHITECTURE_DIAGRAM,
        )

        return self.assembler.to_dto(
            assessment=assessment,
            response_records=response_records,
            analysis_snapshot=prepared_analysis_state,
            checklist_state=checklist_state,
            architecture_document=architecture_document,
            questionnaire_version=assessment_metadata.questionnaire_version,
            source_system=assessment_metadata.source_system,
        )

    async def _load_assessment_metadata(
        self,
        session: AsyncSession,
        assessment_id: UUID,
    ) -> ReportPreviewAssessmentMetadata:
        overview = await self.assessment_repository.load_intake_overview(session, assessment_id)
        if overview is None:
            return ReportPreviewAssessmentMetadata(questionnaire_version=None, source_system=None)
        return ReportPreviewAssessmentMetadata(
            questionnaire_version=overview.header.questionnaire_version,
            source_system=overview.header.source_system,
        )

    async def _build_checklist_state(
        self,
        session: AsyncSession,
        assessment_id: UUID,
        run_record: DocumentChecklistRunRecord,
    ) -> DocumentChecklistReadState:
        latest_reviews = await self.checklist_repository.list_latest_item_reviews_by_assessment(session, assessment_id)
        snapshot_by_type = {
            str(item.get("documentType")): item
            for item in run_record.run.input_snapshot.get("items", [])
            if isinstance(item, dict) and item.get("documentType") is not None
        }

        item_states = [
            self._build_checklist_item_state(
                item=item,
                review=latest_reviews.get(item.document_type),
                snapshot=snapshot_by_type.get(item.document_type, {}),
            )
            for item in run_record.items
        ]
        return DocumentChecklistReadState(run=run_record.run, items=item_states)

    def _build_checklist_item_state(
        self,
        *,
        item: DocumentChecklistItem,
        review: DocumentChecklistItemReview | None,
        snapshot: dict[str, object],
    ) -> DocumentChecklistItemReadState:
        detected_document_id = self._first_snapshot_document_id(snapshot)
        reviewer_verdict = review.reviewer_verdict if review is not None else None
        return DocumentChecklistItemReadState(
            item=item,
            effective_verdict=reviewer_verdict or item.base_verdict,
            detected_file_status="uploaded" if detected_document_id is not None else "missing",
            detected_document_id=detected_document_id,
            reviewer_verdict=reviewer_verdict,
            reviewer_reason=review.reason if review is not None else None,
            vendor_certification_automatic_status=None,
            vendor_certification_analyst_status=None,
            vendor_certification_effective_status=None,
        )

    @staticmethod
    def _first_snapshot_document_id(snapshot: dict[str, object]) -> UUID | None:
        detected_document_ids = snapshot.get("detectedDocumentIds")
        if not isinstance(detected_document_ids, list) or not detected_document_ids:
            return None
        first_document_id = detected_document_ids[0]
        if not isinstance(first_document_id, (str, UUID)):
            return None
        return first_document_id if isinstance(first_document_id, UUID) else UUID(first_document_id)


class ReportDownloadService:
    def __init__(
        self,
        *,
        repository: InitialSarReportRepository,
        storage: InitialSarReportStorage,
    ) -> None:
        self.repository = repository
        self.storage = storage

    async def get_report_metadata(
        self,
        session: AsyncSession,
        report_id: UUID,
    ) -> InitialSarReportMetadata | None:
        report = await self.repository.get_report(session, report_id)
        if report is None:
            return None
        return InitialSarReportMetadata(
            report_id=report.id,
            assessment_id=report.assessment_id,
            source_workflow_version=report.source_workflow_version,
            report_version=report.report_version,
            original_filename=report.original_filename,
            content_type=report.content_type,
            file_size_bytes=report.file_size_bytes,
            sha256=report.sha256,
            limitations=list(report.limitations or []),
            created_at=report.created_at,
            stale_at=report.stale_at,
        )

    async def download_report(
        self,
        session: AsyncSession,
        report_id: UUID,
    ) -> DownloadedInitialSarReport | None:
        report = await self.repository.get_report(session, report_id)
        if report is None:
            return None
        opened_report = await self.storage.open_report(report.storage_container, report.storage_key)
        return DownloadedInitialSarReport(
            filename=report.original_filename,
            content_type=opened_report.content_type,
            content=opened_report.content,
        )
