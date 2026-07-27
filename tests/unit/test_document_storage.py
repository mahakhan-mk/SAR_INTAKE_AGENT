from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.models.database import AssessmentDocument
from app.repositories.document_repository import DocumentRepository
from app.services.document_service import DocumentService, DocumentUploadInput
from app.services.document_storage import (
    AzureBlobDocumentStorage,
    AzureBlobDocumentStorageSettings,
    InMemoryDocumentStorage,
    ResourceExistsError,
)
import app.services.document_storage as document_storage_module

pytestmark = pytest.mark.asyncio


class FakeBlobClient:
    def __init__(self, *, container: str, blob: str) -> None:
        self.container = container
        self.blob = blob
        self.upload_calls: list[dict[str, object]] = []
        self.delete_calls = 0
        self.closed = False

    async def upload_blob(self, data, *, overwrite: bool, content_settings):
        self.upload_calls.append(
            {
                "data": data,
                "overwrite": overwrite,
                "content_settings": content_settings,
            }
        )

    async def delete_blob(self):
        self.delete_calls += 1

    async def close(self) -> None:
        self.closed = True


class FakeBlobServiceClient:
    last_instance: "FakeBlobServiceClient | None" = None

    def __init__(self, connection_string: str) -> None:
        self.connection_string = connection_string
        self.closed = False
        self.blob_clients: list[FakeBlobClient] = []

    @classmethod
    def from_connection_string(cls, connection_string: str) -> "FakeBlobServiceClient":
        instance = cls(connection_string)
        cls.last_instance = instance
        return instance

    def get_blob_client(self, *, container: str, blob: str) -> FakeBlobClient:
        client = FakeBlobClient(container=container, blob=blob)
        self.blob_clients.append(client)
        return client

    async def close(self) -> None:
        self.closed = True


class FakeContentSettings:
    def __init__(self, *, content_type: str) -> None:
        self.content_type = content_type


async def test_azure_blob_storage_uses_stable_key_and_disables_overwrite(monkeypatch):
    monkeypatch.setattr(document_storage_module, "BlobServiceClient", FakeBlobServiceClient)
    monkeypatch.setattr(document_storage_module, "ContentSettings", FakeContentSettings)

    storage = AzureBlobDocumentStorage(
        AzureBlobDocumentStorageSettings(
            connection_string="UseDevelopmentStorage=true",
            container_name="sar-documents",
        )
    )
    assessment_id = uuid.uuid4()
    document_id = uuid.uuid4()

    stored = await storage.store(
        assessment_id=assessment_id,
        document_id=document_id,
        filename="SOC 2 report?.pdf",
        content_type="application/pdf",
        content=b"blob-bytes",
    )

    assert stored.container == "sar-documents"
    assert stored.key == f"local-dev/documents/{document_id}/SOC_2_report_.pdf"
    blob_client = FakeBlobServiceClient.last_instance.blob_clients[0]
    assert FakeBlobServiceClient.last_instance.connection_string == "UseDevelopmentStorage=true"
    assert blob_client.upload_calls[0]["data"] == b"blob-bytes"
    assert blob_client.upload_calls[0]["overwrite"] is False
    assert blob_client.upload_calls[0]["content_settings"].content_type == "application/pdf"
    assert blob_client.closed is True
    assert FakeBlobServiceClient.last_instance.closed is True


async def test_azure_blob_storage_maps_resource_exists_to_file_exists(monkeypatch):
    class FailingBlobClient(FakeBlobClient):
        async def upload_blob(self, data, *, overwrite: bool, content_settings):
            raise ResourceExistsError("exists")

    class FailingBlobServiceClient(FakeBlobServiceClient):
        def get_blob_client(self, *, container: str, blob: str) -> FailingBlobClient:
            client = FailingBlobClient(container=container, blob=blob)
            self.blob_clients.append(client)
            return client

    monkeypatch.setattr(document_storage_module, "BlobServiceClient", FailingBlobServiceClient)
    monkeypatch.setattr(document_storage_module, "ContentSettings", FakeContentSettings)

    storage = AzureBlobDocumentStorage(
        AzureBlobDocumentStorageSettings(
            connection_string="UseDevelopmentStorage=true",
            container_name="sar-documents",
        )
    )

    with pytest.raises(FileExistsError):
        await storage.store(
            assessment_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            filename="duplicate.pdf",
            content_type="application/pdf",
            content=b"blob-bytes",
        )


async def test_document_service_deletes_stored_blob_when_persistence_fails(
    db_session,
    seeded_assessment,
    monkeypatch,
):
    storage = InMemoryDocumentStorage()
    repository = DocumentRepository()

    async def fail_create(*args, **kwargs):
        raise RuntimeError("database flush failed")

    monkeypatch.setattr(repository, "create_assessment_document", fail_create)
    service = DocumentService(document_repository=repository, storage=storage)

    with pytest.raises(RuntimeError, match="database flush failed"):
        await service.upload_document(
            db_session,
            assessment_id=seeded_assessment["assessment_id"],
            upload=DocumentUploadInput(
                filename="compensate.pdf",
                content_type="application/pdf",
                content=b"compensate",
            ),
        )

    assert storage.objects == {}
    assert await db_session.scalar(select(func.count()).select_from(AssessmentDocument)) == 0


async def test_azure_blob_settings_are_created_from_config():
    settings = Settings(
        database_url="sqlite+aiosqlite:///./sar_assessment.db",
        database_schema=None,
        azure_blob_connection_string="UseDevelopmentStorage=true",
        azure_blob_container_name="sar-documents",
        azure_openai_endpoint=None,
        azure_openai_api_key=None,
        azure_openai_deployment=None,
        azure_openai_timeout_seconds=30.0,
        azure_openai_api_version=None,
    )

    resolved = AzureBlobDocumentStorageSettings.from_settings(settings)

    assert resolved.connection_string == "UseDevelopmentStorage=true"
    assert resolved.container_name == "sar-documents"
