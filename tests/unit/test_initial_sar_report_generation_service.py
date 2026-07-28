from __future__ import annotations

from types import SimpleNamespace
import uuid

import pytest

from app.api.errors import AssessmentNotFoundError
from app.services.initial_sar_report_generation_service import InitialSarReportGenerationService
from app.services.initial_sar_report_renderer import RenderedInitialSarReport
from app.services.initial_sar_report_storage import OpenedInitialSarReport, StoredInitialSarReport
from tests.unit.test_initial_sar_report_renderer import build_preview_dto

pytestmark = pytest.mark.asyncio


class PreviewServiceStub:
    def __init__(self, *, preview=None, error: Exception | None = None) -> None:
        self.preview = preview
        self.error = error
        self.calls: list[uuid.UUID] = []

    async def get_report_preview(self, session, assessment_id):
        self.calls.append(assessment_id)
        if self.error is not None:
            raise self.error
        return self.preview


class RendererStub:
    def __init__(self, *, rendered_report: RenderedInitialSarReport | None = None, error: Exception | None = None) -> None:
        self.rendered_report = rendered_report or RenderedInitialSarReport(
            bytes=b"docx-bytes",
            original_filename="initial-sar-report.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            file_size_bytes=10,
            sha256="sha-docx",
        )
        self.error = error
        self.calls: list[dict[str, object]] = []

    def render(self, preview, *, architecture_image_bytes=None):
        self.calls.append(
            {
                "preview": preview,
                "architecture_image_bytes": architecture_image_bytes,
            }
        )
        if self.error is not None:
            raise self.error
        return self.rendered_report


class StorageStub:
    def __init__(self, *, stored_report: StoredInitialSarReport | None = None, store_error: Exception | None = None) -> None:
        self.stored_report = stored_report or StoredInitialSarReport(
            storage_container="sar-documents",
            storage_key="local-dev/reports/report-1/initial-sar-report.docx",
        )
        self.store_error = store_error
        self.store_calls: list[dict[str, object]] = []
        self.delete_calls: list[tuple[str, str]] = []

    async def store_report(self, **kwargs):
        self.store_calls.append(kwargs)
        if self.store_error is not None:
            raise self.store_error
        return self.stored_report

    async def delete_report(self, storage_container: str, storage_key: str) -> None:
        self.delete_calls.append((storage_container, storage_key))


class RepositoryStub:
    def __init__(self, *, next_version: int = 1, create_error: Exception | None = None) -> None:
        self.next_version = next_version
        self.create_error = create_error
        self.next_version_calls: list[uuid.UUID] = []
        self.create_calls: list[dict[str, object]] = []

    async def get_next_report_version(self, session, assessment_id):
        self.next_version_calls.append(assessment_id)
        return self.next_version

    async def create_completed_report(self, session, **kwargs):
        self.create_calls.append(kwargs)
        if self.create_error is not None:
            raise self.create_error
        return SimpleNamespace(id=kwargs["report_id"])


class DocumentRepositoryStub:
    def __init__(self, *, document=None) -> None:
        self.document = document
        self.calls: list[dict[str, object]] = []

    async def get_active_document(self, session, *, assessment_id, document_id):
        self.calls.append({"assessment_id": assessment_id, "document_id": document_id})
        return self.document


class DocumentStorageStub:
    def __init__(self, *, opened_document: OpenedInitialSarReport | None = None) -> None:
        self.opened_document = opened_document or OpenedInitialSarReport(
            content=b"architecture-image",
            content_type="image/png",
        )
        self.calls: list[dict[str, str]] = []

    async def open(self, *, container: str, key: str) -> OpenedInitialSarReport:
        self.calls.append({"container": container, "key": key})
        return self.opened_document


async def test_generate_report_orchestrates_preview_render_upload_and_flush_only_persistence(db_session, monkeypatch):
    preview = build_preview_dto()
    architecture_document_id = uuid.UUID("00000000-0000-0000-0000-000000000111")
    object.__setattr__(preview.architecture, "documentId", str(architecture_document_id))
    preview_service = PreviewServiceStub(preview=preview)
    renderer = RendererStub()
    storage = StorageStub()
    repository = RepositoryStub(next_version=4)
    document_repository = DocumentRepositoryStub(
        document=SimpleNamespace(storage_container="sar-documents", storage_key="documents/architecture.png")
    )
    document_storage = DocumentStorageStub()

    async def commit_spy():
        raise AssertionError("InitialSarReportGenerationService must not commit.")

    async def rollback_spy():
        raise AssertionError("InitialSarReportGenerationService must not rollback.")

    monkeypatch.setattr(db_session, "commit", commit_spy)
    monkeypatch.setattr(db_session, "rollback", rollback_spy)

    service = InitialSarReportGenerationService(
        preview_service=preview_service,
        renderer=renderer,
        storage=storage,
        repository=repository,
        document_repository=document_repository,
        document_storage=document_storage,
    )

    result = await service.generate_report(
        db_session,
        assessment_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        source_workflow_version=12,
    )

    assert result.filename == "initial-sar-report.docx"
    assert result.content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert result.file_size_bytes == 10
    assert result.sha256 == "sha-docx"
    assert preview_service.calls == [uuid.UUID("00000000-0000-0000-0000-000000000001")]
    assert renderer.calls[0]["architecture_image_bytes"] == b"architecture-image"
    assert storage.store_calls[0]["filename"] == "initial-sar-report.docx"
    assert repository.next_version_calls == [uuid.UUID("00000000-0000-0000-0000-000000000001")]
    assert repository.create_calls[0]["report_version"] == 4
    assert repository.create_calls[0]["source_workflow_version"] == 12
    assert repository.create_calls[0]["storage_container"] == "sar-documents"
    assert repository.create_calls[0]["storage_key"] == "local-dev/reports/report-1/initial-sar-report.docx"
    assert repository.create_calls[0]["limitations"] == ["Architecture details were not provided."]
    assert storage.delete_calls == []
    assert document_repository.calls == [
        {
            "assessment_id": uuid.UUID("00000000-0000-0000-0000-000000000001"),
            "document_id": architecture_document_id,
        }
    ]
    assert document_storage.calls == [{"container": "sar-documents", "key": "documents/architecture.png"}]


async def test_generate_report_propagates_missing_assessment_without_side_effects(db_session):
    preview_service = PreviewServiceStub(error=AssessmentNotFoundError())
    renderer = RendererStub()
    storage = StorageStub()
    repository = RepositoryStub()

    service = InitialSarReportGenerationService(
        preview_service=preview_service,
        renderer=renderer,
        storage=storage,
        repository=repository,
    )

    with pytest.raises(AssessmentNotFoundError):
        await service.generate_report(db_session, assessment_id=uuid.uuid4(), source_workflow_version=1)

    assert renderer.calls == []
    assert storage.store_calls == []
    assert repository.next_version_calls == []
    assert repository.create_calls == []


async def test_generate_report_stops_when_rendering_fails(db_session):
    preview_service = PreviewServiceStub(preview=build_preview_dto())
    renderer = RendererStub(error=RuntimeError("render failed"))
    storage = StorageStub()
    repository = RepositoryStub()

    service = InitialSarReportGenerationService(
        preview_service=preview_service,
        renderer=renderer,
        storage=storage,
        repository=repository,
    )

    with pytest.raises(RuntimeError, match="render failed"):
        await service.generate_report(db_session, assessment_id=uuid.uuid4(), source_workflow_version=1)

    assert storage.store_calls == []
    assert repository.next_version_calls == []
    assert repository.create_calls == []


async def test_generate_report_stops_when_blob_upload_fails(db_session):
    preview_service = PreviewServiceStub(preview=build_preview_dto())
    renderer = RendererStub()
    storage = StorageStub(store_error=RuntimeError("blob upload failed"))
    repository = RepositoryStub()

    service = InitialSarReportGenerationService(
        preview_service=preview_service,
        renderer=renderer,
        storage=storage,
        repository=repository,
    )

    with pytest.raises(RuntimeError, match="blob upload failed"):
        await service.generate_report(db_session, assessment_id=uuid.uuid4(), source_workflow_version=1)

    assert len(repository.next_version_calls) == 1
    assert repository.create_calls == []
    assert storage.delete_calls == []


async def test_generate_report_deletes_uploaded_blob_when_repository_flush_fails(db_session):
    preview_service = PreviewServiceStub(preview=build_preview_dto())
    renderer = RendererStub()
    storage = StorageStub(
        stored_report=StoredInitialSarReport(
            storage_container="sar-documents",
            storage_key="local-dev/reports/report-1/generated.docx",
        )
    )
    repository = RepositoryStub(create_error=RuntimeError("repository flush failed"))

    service = InitialSarReportGenerationService(
        preview_service=preview_service,
        renderer=renderer,
        storage=storage,
        repository=repository,
    )

    with pytest.raises(RuntimeError, match="repository flush failed"):
        await service.generate_report(db_session, assessment_id=uuid.uuid4(), source_workflow_version=1)

    assert storage.delete_calls == [("sar-documents", "local-dev/reports/report-1/generated.docx")]
