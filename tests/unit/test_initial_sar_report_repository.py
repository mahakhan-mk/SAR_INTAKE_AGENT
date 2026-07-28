from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

import pytest

from app.models.database import InitialSarReport
from app.repositories.report_repository import InitialSarReportRepository

pytestmark = pytest.mark.asyncio


async def test_create_completed_report_flushes_without_committing(db_session, seeded_assessment, monkeypatch):
    commit_calls = 0
    rollback_calls = 0

    async def commit_spy():
        nonlocal commit_calls
        commit_calls += 1
        raise AssertionError("InitialSarReportRepository must not commit.")

    async def rollback_spy():
        nonlocal rollback_calls
        rollback_calls += 1
        raise AssertionError("InitialSarReportRepository must not rollback.")

    monkeypatch.setattr(db_session, "commit", commit_spy)
    monkeypatch.setattr(db_session, "rollback", rollback_spy)

    repository = InitialSarReportRepository()
    report = await repository.create_completed_report(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        source_workflow_version=12,
        report_version=1,
        storage_container="sar-reports",
        storage_key=f"{seeded_assessment['assessment_id']}/reports/report-v1.docx",
        original_filename="assessment-report-v1.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size_bytes=2048,
        sha256="sha-256-v1",
        limitations=[{"type": "warning", "message": "Missing attachment"}],
    )

    assert commit_calls == 0
    assert rollback_calls == 0
    assert report.id is not None
    stored = await db_session.get(InitialSarReport, report.id)
    assert stored is not None
    assert stored.report_version == 1
    assert stored.limitations == [{"type": "warning", "message": "Missing attachment"}]


async def test_get_next_report_version_increments_from_existing_versions(db_session, seeded_assessment):
    repository = InitialSarReportRepository()

    assert await repository.get_next_report_version(db_session, seeded_assessment["assessment_id"]) == 1

    await repository.create_completed_report(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        source_workflow_version=7,
        report_version=1,
        storage_container="sar-reports",
        storage_key=f"{seeded_assessment['assessment_id']}/reports/report-v1.docx",
        original_filename="assessment-report-v1.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size_bytes=1024,
        sha256="sha-report-v1",
    )
    await repository.create_completed_report(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        source_workflow_version=8,
        report_version=2,
        storage_container="sar-reports",
        storage_key=f"{seeded_assessment['assessment_id']}/reports/report-v2.docx",
        original_filename="assessment-report-v2.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size_bytes=1025,
        sha256="sha-report-v2",
    )

    assert await repository.get_next_report_version(db_session, seeded_assessment["assessment_id"]) == 3


async def test_get_latest_report_for_assessment_returns_latest_non_stale_report(db_session, seeded_assessment):
    repository = InitialSarReportRepository()
    older = await repository.create_completed_report(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        source_workflow_version=3,
        report_version=1,
        storage_container="sar-reports",
        storage_key=f"{seeded_assessment['assessment_id']}/reports/report-v1.docx",
        original_filename="assessment-report-v1.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size_bytes=900,
        sha256="sha-report-older",
    )
    latest = await repository.create_completed_report(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        source_workflow_version=4,
        report_version=2,
        storage_container="sar-reports",
        storage_key=f"{seeded_assessment['assessment_id']}/reports/report-v2.docx",
        original_filename="assessment-report-v2.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size_bytes=901,
        sha256="sha-report-latest",
    )
    older.created_at = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    older.stale_at = datetime(2026, 7, 20, 13, 0, tzinfo=timezone.utc)
    latest.created_at = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    await db_session.commit()

    report = await repository.get_latest_report_for_assessment(db_session, seeded_assessment["assessment_id"])

    assert report is not None
    assert report.id == latest.id


async def test_get_report_and_get_report_by_version_load_historical_rows(db_session, seeded_assessment):
    repository = InitialSarReportRepository()
    report = await repository.create_completed_report(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        source_workflow_version=5,
        report_version=4,
        storage_container="sar-reports",
        storage_key=f"{seeded_assessment['assessment_id']}/reports/report-v4.docx",
        original_filename="assessment-report-v4.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size_bytes=1400,
        sha256="sha-report-v4",
        limitations=[],
    )
    report.stale_at = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
    await db_session.commit()

    loaded_by_id = await repository.get_report(db_session, report.id)
    loaded_by_version = await repository.get_report_by_version(
        db_session,
        seeded_assessment["assessment_id"],
        4,
    )

    assert loaded_by_id is not None
    assert loaded_by_id.id == report.id
    assert loaded_by_version is not None
    assert loaded_by_version.id == report.id
    assert loaded_by_version.stale_at == datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)


async def test_mark_reports_stale_updates_only_current_reports_for_assessment(db_session, seeded_assessment):
    repository = InitialSarReportRepository()
    current_first = await repository.create_completed_report(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        source_workflow_version=9,
        report_version=1,
        storage_container="sar-reports",
        storage_key=f"{seeded_assessment['assessment_id']}/reports/report-v1.docx",
        original_filename="assessment-report-v1.docx",
        content_type="application/pdf",
        file_size_bytes=500,
        sha256="sha-current-first",
    )
    current_second = await repository.create_completed_report(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        source_workflow_version=10,
        report_version=2,
        storage_container="sar-reports",
        storage_key=f"{seeded_assessment['assessment_id']}/reports/report-v2.pdf",
        original_filename="assessment-report-v2.pdf",
        content_type="application/pdf",
        file_size_bytes=600,
        sha256="sha-current-second",
    )
    already_stale = await repository.create_completed_report(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        source_workflow_version=8,
        report_version=3,
        storage_container="sar-reports",
        storage_key=f"{seeded_assessment['assessment_id']}/reports/report-v3.pdf",
        original_filename="assessment-report-v3.pdf",
        content_type="application/pdf",
        file_size_bytes=700,
        sha256="sha-already-stale",
    )
    other_assessment_id = uuid.uuid4()
    db_session.add(
        InitialSarReport(
            id=uuid.uuid4(),
            assessment_id=other_assessment_id,
            source_workflow_version=1,
            report_version=1,
            storage_container="sar-reports",
            storage_key=f"{other_assessment_id}/reports/report-v1.pdf",
            original_filename="other-report-v1.pdf",
            content_type="application/pdf",
            file_size_bytes=800,
            sha256="sha-other-assessment",
            limitations=[],
        )
    )
    already_stale.stale_at = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    await db_session.commit()

    stale_at = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    marked_count = await repository.mark_reports_stale(
        db_session,
        seeded_assessment["assessment_id"],
        stale_at,
    )

    assert marked_count == 2
    assert current_first.stale_at == stale_at
    assert current_second.stale_at == stale_at
    assert already_stale.stale_at == datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)

    latest_current = await repository.get_latest_report_for_assessment(db_session, seeded_assessment["assessment_id"])
    assert latest_current is None
