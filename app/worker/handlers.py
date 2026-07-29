from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from inspect import isawaitable
from typing import Awaitable, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import AssessmentNotFoundError, DocumentChecklistRunNotFoundError
from app.messaging.contracts import validate_command_payload
from app.messaging.envelope import MessageEnvelope
from app.models.enums import DocumentChecklistRunStatus
from app.repositories.report_repository import InitialSarReportRepository
from app.services.document_checklist_service import DocumentChecklistExecutionService
from app.services.executive_summary_service import ExecutiveSummaryService
from app.services.inherent_risk_service import InherentRiskExecutionService
from app.services.initial_sar_report_generation_service import InitialSarReportGenerationService

Callback = Callable[[], object | Awaitable[object]]


@dataclass(frozen=True, slots=True)
class CommandExecutionResult:
    event_type: str
    payload: dict[str, object]
    on_commit: Callback | None = None
    on_rollback: Callback | None = None

    async def committed(self) -> None:
        await _run(self.on_commit)

    async def rolled_back(self) -> None:
        await _run(self.on_rollback)


@dataclass(slots=True)
class AssessmentCommandHandlers:
    risk_service: InherentRiskExecutionService
    executive_summary_service: ExecutiveSummaryService
    checklist_service: DocumentChecklistExecutionService
    report_service: InitialSarReportGenerationService
    report_repository: InitialSarReportRepository

    async def calculate_risk(
        self,
        session: AsyncSession,
        envelope: MessageEnvelope,
    ) -> CommandExecutionResult:
        validate_command_payload(envelope.message_type, envelope.payload)
        result = await self.risk_service.create_analysis_run(
            session,
            envelope.assessment_id,
        )
        run_id = UUID(str(result.analysisRunId))
        await self.executive_summary_service.generate(
            session,
            envelope.assessment_id,
            run_id,
        )
        return CommandExecutionResult("assessment.risk.completed", {})

    async def recalculate_risk(
        self,
        session: AsyncSession,
        envelope: MessageEnvelope,
    ) -> CommandExecutionResult:
        validate_command_payload(envelope.message_type, envelope.payload)
        result = await self.risk_service.create_analysis_run(
            session,
            envelope.assessment_id,
            force=True,
        )
        run_id = UUID(str(result.analysisRunId))
        await self.executive_summary_service.generate(
            session,
            envelope.assessment_id,
            run_id,
            force=True,
        )
        await self.report_repository.mark_reports_stale(
            session,
            envelope.assessment_id,
            datetime.now(timezone.utc),
        )
        return CommandExecutionResult("assessment.risk.completed", {})

    async def generate_checklist(
        self,
        session: AsyncSession,
        envelope: MessageEnvelope,
    ) -> CommandExecutionResult:
        validate_command_payload(envelope.message_type, envelope.payload)
        await self.checklist_service.generate_checklist(
            session,
            envelope.assessment_id,
        )
        return CommandExecutionResult("assessment.checklist.generated", {})

    async def finalize_checklist(
        self,
        session: AsyncSession,
        envelope: MessageEnvelope,
    ) -> CommandExecutionResult:
        payload = validate_command_payload(envelope.message_type, envelope.payload)
        state = await self.checklist_service.finalize_checklist(
            session,
            assessment_id=envelope.assessment_id,
            run_id=UUID(str(payload["checklistRunId"])),
        )
        if state.run.status == DocumentChecklistRunStatus.INCOMPLETE.value:
            return CommandExecutionResult("assessment.checklist.incomplete", {})
        current_report = await self.report_repository.get_latest_report_for_assessment(
            session,
            envelope.assessment_id,
        )
        payload_out: dict[str, object] = {}
        if current_report is not None:
            await self.report_repository.mark_reports_stale(
                session,
                envelope.assessment_id,
                datetime.now(timezone.utc),
            )
            payload_out["regenerate"] = True
        return CommandExecutionResult("assessment.checklist.completed", payload_out)

    async def generate_report(
        self,
        session: AsyncSession,
        envelope: MessageEnvelope,
    ) -> CommandExecutionResult:
        validate_command_payload(envelope.message_type, envelope.payload)
        generated = await self.report_service.generate_report(
            session,
            assessment_id=envelope.assessment_id,
            source_workflow_version=envelope.expected_workflow_version or 0,
            regenerate=False,
        )
        return CommandExecutionResult(
            "assessment.report.completed",
            {},
            on_commit=lambda: self.report_service.finalize_successful_generation(
                session,
                generated.report_id,
            ),
            on_rollback=lambda: self.report_service.compensate_failed_generation(
                session,
                generated.report_id,
            ),
        )

    async def regenerate_report(
        self,
        session: AsyncSession,
        envelope: MessageEnvelope,
    ) -> CommandExecutionResult:
        validate_command_payload(envelope.message_type, envelope.payload)
        generated = await self.report_service.generate_report(
            session,
            assessment_id=envelope.assessment_id,
            source_workflow_version=envelope.expected_workflow_version or 0,
            regenerate=True,
        )
        return CommandExecutionResult(
            "assessment.report.completed",
            {},
            on_commit=lambda: self.report_service.finalize_successful_generation(
                session,
                generated.report_id,
            ),
            on_rollback=lambda: self.report_service.compensate_failed_generation(
                session,
                generated.report_id,
            ),
        )


async def _run(callback: Callback | None) -> None:
    if callback is None:
        return
    result = callback()
    if isawaitable(result):
        await result
