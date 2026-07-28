from __future__ import annotations

from datetime import datetime, timezone
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import (
    get_initial_sar_report_generation_service,
    get_initial_sar_report_repository,
    get_initial_sar_report_storage,
    get_session,
)
from app.api.errors import AssessmentNotFoundError
from app.main import app
from app.services.initial_sar_report_generation_service import GeneratedInitialSarReportResult
from app.services.initial_sar_report_storage import OpenedInitialSarReport

pytestmark = pytest.mark.asyncio


class GenerationServiceStub:
    def __init__(self, *, result: GeneratedInitialSarReportResult | None = None, error: Exception | None = None) -> None:
        self.result = result or GeneratedInitialSarReportResult(
            report_id=uuid.UUID("00000000-0000-0000-0000-000000000111"),
            filename="initial-sar-report.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            file_size_bytes=1234,
            sha256="sha-generated",
        )
        self.error = error
        self.generate_calls: list[dict[str, object]] = []
        self.compensation_calls: list[uuid.UUID] = []

    async def generate_report(self, session, *, assessment_id, source_workflow_version):
        self.generate_calls.append(
            {
                "assessment_id": assessment_id,
                "source_workflow_version": source_workflow_version,
            }
        )
        if self.error is not None:
            raise self.error
        return self.result

    async def compensate_failed_generation(self, session, report_id):
        self.compensation_calls.append(report_id)


class RepositoryStub:
    def __init__(self, *, report=None) -> None:
        self.report = report
        self.calls: list[uuid.UUID] = []

    async def get_report(self, session, report_id):
        self.calls.append(report_id)
        return self.report


class StorageStub:
    def __init__(self, *, opened_report: OpenedInitialSarReport | None = None, error: Exception | None = None) -> None:
        self.opened_report = opened_report or OpenedInitialSarReport(
            content=b"docx-content",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.error = error
        self.calls: list[tuple[str, str]] = []

    async def open_report(self, storage_container: str, storage_key: str) -> OpenedInitialSarReport:
        self.calls.append((storage_container, storage_key))
        if self.error is not None:
            raise self.error
        return self.opened_report


async def test_post_reports_generates_and_commits_once(session_factory, seeded_assessment):
    service = GenerationServiceStub()
    commit_calls = 0

    async with session_factory() as session:
        original_commit = session.commit

        async def commit_spy():
            nonlocal commit_calls
            commit_calls += 1
            await original_commit()

        session.commit = commit_spy

        async def override_get_session():
            yield session

        app.dependency_overrides[get_session] = override_get_session
        app.dependency_overrides[get_initial_sar_report_generation_service] = lambda: service
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
                response = await client.post(f"/api/v1/assessments/{seeded_assessment['assessment_id']}/reports")
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "reportId": "00000000-0000-0000-0000-000000000111",
        "filename": "initial-sar-report.docx",
        "contentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "fileSizeBytes": 1234,
        "sha256": "sha-generated",
    }
    assert service.generate_calls == [
        {
            "assessment_id": seeded_assessment["assessment_id"],
            "source_workflow_version": 1,
        }
    ]
    assert service.compensation_calls == []
    assert commit_calls == 1


async def test_post_reports_rolls_back_and_compensates_uploaded_blob_when_commit_fails(session_factory, seeded_assessment):
    service = GenerationServiceStub()
    rollback_calls = 0

    async with session_factory() as session:
        original_rollback = session.rollback

        async def commit_spy():
            raise RuntimeError("commit failed")

        async def rollback_spy():
            nonlocal rollback_calls
            rollback_calls += 1
            await original_rollback()

        session.commit = commit_spy
        session.rollback = rollback_spy

        async def override_get_session():
            yield session

        app.dependency_overrides[get_session] = override_get_session
        app.dependency_overrides[get_initial_sar_report_generation_service] = lambda: service
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
                with pytest.raises(RuntimeError, match="commit failed"):
                    await client.post(f"/api/v1/assessments/{seeded_assessment['assessment_id']}/reports")
        finally:
            app.dependency_overrides.clear()

    assert rollback_calls == 1
    assert service.compensation_calls == [uuid.UUID("00000000-0000-0000-0000-000000000111")]


async def test_post_reports_returns_404_for_missing_assessment(client, seeded_assessment):
    service = GenerationServiceStub(error=AssessmentNotFoundError())
    app.dependency_overrides[get_initial_sar_report_generation_service] = lambda: service
    try:
        response = await client.post(f"/api/v1/assessments/{seeded_assessment['assessment_id']}/reports")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json() == {"detail": "Assessment not found."}


async def test_get_report_metadata_excludes_storage_fields(client):
    report = type(
        "Report",
        (),
        {
            "id": uuid.UUID("00000000-0000-0000-0000-000000000211"),
            "assessment_id": uuid.UUID("00000000-0000-0000-0000-000000000212"),
            "source_workflow_version": 3,
            "report_version": 2,
            "original_filename": "initial-sar-report.docx",
            "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "file_size_bytes": 2345,
            "sha256": "sha-metadata",
            "limitations": ["Missing vendor reputation context."],
            "created_at": datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc),
            "stale_at": None,
            "storage_container": "sar-documents",
            "storage_key": "secret/blob/key.docx",
        },
    )()
    repository = RepositoryStub(report=report)
    app.dependency_overrides[get_initial_sar_report_repository] = lambda: repository
    try:
        response = await client.get("/api/v1/reports/00000000-0000-0000-0000-000000000211")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "reportId": "00000000-0000-0000-0000-000000000211",
        "assessmentId": "00000000-0000-0000-0000-000000000212",
        "sourceWorkflowVersion": 3,
        "reportVersion": 2,
        "originalFilename": "initial-sar-report.docx",
        "contentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "fileSizeBytes": 2345,
        "sha256": "sha-metadata",
        "limitations": ["Missing vendor reputation context."],
        "createdAt": "2026-07-28T12:00:00Z",
        "staleAt": None,
    }
    assert "storageContainer" not in response.text
    assert "storageKey" not in response.text


async def test_get_report_metadata_returns_404_for_missing_report(client):
    repository = RepositoryStub(report=None)
    app.dependency_overrides[get_initial_sar_report_repository] = lambda: repository
    try:
        response = await client.get(f"/api/v1/reports/{uuid.uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json() == {"detail": "Report not found."}


async def test_download_report_streams_attachment_and_returns_404_for_missing_blob(client):
    report = type(
        "Report",
        (),
        {
            "id": uuid.UUID("00000000-0000-0000-0000-000000000311"),
            "original_filename": "initial-sar-report.docx",
            "storage_container": "sar-documents",
            "storage_key": "reports/report.docx",
        },
    )()
    repository = RepositoryStub(report=report)
    storage = StorageStub()
    app.dependency_overrides[get_initial_sar_report_repository] = lambda: repository
    app.dependency_overrides[get_initial_sar_report_storage] = lambda: storage
    try:
        response = await client.get("/api/v1/reports/00000000-0000-0000-0000-000000000311/download")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.content == b"docx-content"
    assert response.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert response.headers["content-disposition"] == 'attachment; filename="initial-sar-report.docx"'
    assert storage.calls == [("sar-documents", "reports/report.docx")]

    missing_blob_storage = StorageStub(error=FileNotFoundError("missing blob"))
    app.dependency_overrides[get_initial_sar_report_repository] = lambda: repository
    app.dependency_overrides[get_initial_sar_report_storage] = lambda: missing_blob_storage
    try:
        missing_blob_response = await client.get("/api/v1/reports/00000000-0000-0000-0000-000000000311/download")
    finally:
        app.dependency_overrides.clear()

    assert missing_blob_response.status_code == 404
    assert missing_blob_response.json() == {"detail": "Report not found."}
