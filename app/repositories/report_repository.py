from __future__ import annotations

from datetime import datetime
import uuid
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import InitialSarReport, SarAssessment


class InitialSarReportRepository:
    async def create_completed_report(
        self,
        session: AsyncSession,
        *,
        report_id: UUID | str | None = None,
        assessment_id: UUID | str,
        source_workflow_version: int,
        report_version: int,
        storage_container: str,
        storage_key: str,
        original_filename: str,
        content_type: str,
        file_size_bytes: int,
        sha256: str,
        limitations: list[object] | None = None,
    ) -> InitialSarReport:
        report = InitialSarReport(
            id=self._coerce_uuid(report_id) if report_id is not None else uuid.uuid4(),
            assessment_id=self._coerce_uuid(assessment_id),
            source_workflow_version=source_workflow_version,
            report_version=report_version,
            storage_container=storage_container,
            storage_key=storage_key,
            original_filename=original_filename,
            content_type=content_type,
            file_size_bytes=file_size_bytes,
            sha256=sha256,
            limitations=limitations or [],
        )
        session.add(report)
        await session.flush()
        return report

    async def get_report(
        self,
        session: AsyncSession,
        report_id: UUID | str,
    ) -> InitialSarReport | None:
        return await session.get(InitialSarReport, self._coerce_uuid(report_id))

    async def get_latest_report_for_assessment(
        self,
        session: AsyncSession,
        assessment_id: UUID | str,
    ) -> InitialSarReport | None:
        return (
            await session.execute(
                select(InitialSarReport)
                .where(
                    InitialSarReport.assessment_id == self._coerce_uuid(assessment_id),
                    InitialSarReport.stale_at.is_(None),
                )
                .order_by(
                    InitialSarReport.created_at.desc(),
                    InitialSarReport.report_version.desc(),
                    InitialSarReport.id.desc(),
                )
            )
        ).scalars().first()

    async def get_report_by_version(
        self,
        session: AsyncSession,
        assessment_id: UUID | str,
        report_version: int,
    ) -> InitialSarReport | None:
        return (
            await session.execute(
                select(InitialSarReport).where(
                    InitialSarReport.assessment_id == self._coerce_uuid(assessment_id),
                    InitialSarReport.report_version == report_version,
                )
            )
        ).scalars().first()

    async def get_next_report_version(
        self,
        session: AsyncSession,
        assessment_id: UUID | str,
    ) -> int:
        normalized_assessment_id = self._coerce_uuid(assessment_id)
        assessment = (
            await session.execute(
                select(SarAssessment)
                .where(SarAssessment.id == normalized_assessment_id)
                .with_for_update()
            )
        ).scalars().first()
        if assessment is None:
            raise LookupError(f"assessment {normalized_assessment_id} was not found")
        latest_version = (
            await session.execute(
                select(func.coalesce(func.max(InitialSarReport.report_version), 0)).where(
                    InitialSarReport.assessment_id == normalized_assessment_id
                )
            )
        ).scalar_one()
        return int(latest_version) + 1

    async def mark_reports_stale(
        self,
        session: AsyncSession,
        assessment_id: UUID | str,
        stale_at: datetime,
    ) -> int:
        reports = (
            await session.execute(
                select(InitialSarReport).where(
                    InitialSarReport.assessment_id == self._coerce_uuid(assessment_id),
                    InitialSarReport.stale_at.is_(None),
                )
            )
        ).scalars().all()

        for report in reports:
            report.stale_at = stale_at

        await session.flush()
        return len(reports)

    @staticmethod
    def _coerce_uuid(value: UUID | str) -> UUID:
        return value if isinstance(value, UUID) else UUID(str(value))
