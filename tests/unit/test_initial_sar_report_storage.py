from __future__ import annotations

import uuid

import pytest

from app.config import Settings
from app.services.initial_sar_report_storage import (
    AzureBlobInitialSarReportStorage,
    AzureBlobInitialSarReportStorageSettings,
    InMemoryInitialSarReportStorage,
    OpenedInitialSarReport,
    ResourceExistsError,
    ResourceNotFoundError,
    build_initial_sar_report_storage_key,
)
import app.services.initial_sar_report_storage as initial_sar_report_storage_module


class FakeDownloadStream:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    async def readall(self) -> bytes:
        return self.payload


class FakeBlobProperties:
    def __init__(self, *, content_type: str | None) -> None:
        self.content_settings = FakeContentSettings(content_type=content_type) if content_type is not None else None


class FakeBlobClient:
    def __init__(self, *, container: str, blob: str) -> None:
        self.container = container
        self.blob = blob
        self.upload_calls: list[dict[str, object]] = []
        self.delete_calls = 0
        self.download_calls = 0
        self.get_properties_calls = 0
        self.closed = False
        self.download_payload = b"opened-report"
        self.properties = FakeBlobProperties(content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

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

    async def download_blob(self):
        self.download_calls += 1
        return FakeDownloadStream(self.download_payload)

    async def get_blob_properties(self):
        self.get_properties_calls += 1
        return self.properties

    async def close(self) -> None:
        self.closed = True


class FakeBlobServiceClient:
    last_instance: "FakeBlobServiceClient | None" = None
    instances: list["FakeBlobServiceClient"] = []

    def __init__(self, connection_string: str) -> None:
        self.connection_string = connection_string
        self.closed = False
        self.blob_clients: list[FakeBlobClient] = []

    @classmethod
    def from_connection_string(cls, connection_string: str) -> "FakeBlobServiceClient":
        instance = cls(connection_string)
        cls.last_instance = instance
        cls.instances.append(instance)
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


@pytest.mark.asyncio
async def test_azure_initial_sar_report_storage_stores_and_opens_and_deletes(monkeypatch):
    FakeBlobServiceClient.instances = []
    FakeBlobServiceClient.last_instance = None
    monkeypatch.setattr(initial_sar_report_storage_module, "BlobServiceClient", FakeBlobServiceClient)
    monkeypatch.setattr(initial_sar_report_storage_module, "ContentSettings", FakeContentSettings)

    storage = AzureBlobInitialSarReportStorage(
        AzureBlobInitialSarReportStorageSettings(
            connection_string="UseDevelopmentStorage=true",
            container_name="sar-documents",
        )
    )
    assessment_id = uuid.uuid4()
    report_id = uuid.uuid4()

    stored = await storage.store_report(
        report_id=report_id,
        assessment_id=assessment_id,
        filename="Initial SAR Report?.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=b"report-bytes",
    )
    opened = await storage.open_report(stored.storage_container, stored.storage_key)
    await storage.delete_report(stored.storage_container, stored.storage_key)

    assert stored.storage_container == "sar-documents"
    assert stored.storage_key == f"local-dev/reports/{report_id}/Initial_SAR_Report_.docx"

    assert len(FakeBlobServiceClient.instances) == 3
    store_service_client, open_service_client, delete_service_client = FakeBlobServiceClient.instances
    assert store_service_client.connection_string == "UseDevelopmentStorage=true"

    store_client = store_service_client.blob_clients[0]
    open_client = open_service_client.blob_clients[0]
    delete_client = delete_service_client.blob_clients[0]
    assert store_client.upload_calls[0]["data"] == b"report-bytes"
    assert store_client.upload_calls[0]["overwrite"] is False
    assert store_client.upload_calls[0]["content_settings"].content_type == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert opened == OpenedInitialSarReport(
        content=b"opened-report",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert open_client.download_calls == 1
    assert open_client.get_properties_calls == 1
    assert delete_client.delete_calls == 1
    assert all(client.closed for service_client in FakeBlobServiceClient.instances for client in service_client.blob_clients)
    assert all(service_client.closed for service_client in FakeBlobServiceClient.instances)


@pytest.mark.asyncio
async def test_azure_initial_sar_report_storage_maps_missing_blob_on_open(monkeypatch):
    class MissingOpenBlobClient(FakeBlobClient):
        async def download_blob(self):
            raise ResourceNotFoundError("missing")

    class MissingOpenBlobServiceClient(FakeBlobServiceClient):
        def get_blob_client(self, *, container: str, blob: str) -> MissingOpenBlobClient:
            client = MissingOpenBlobClient(container=container, blob=blob)
            self.blob_clients.append(client)
            return client

    MissingOpenBlobServiceClient.instances = []
    MissingOpenBlobServiceClient.last_instance = None
    monkeypatch.setattr(initial_sar_report_storage_module, "BlobServiceClient", MissingOpenBlobServiceClient)
    monkeypatch.setattr(initial_sar_report_storage_module, "ContentSettings", FakeContentSettings)

    storage = AzureBlobInitialSarReportStorage(
        AzureBlobInitialSarReportStorageSettings(
            connection_string="UseDevelopmentStorage=true",
            container_name="sar-documents",
        )
    )

    with pytest.raises(FileNotFoundError, match="missing-key"):
        await storage.open_report("sar-documents", "missing-key")


@pytest.mark.asyncio
async def test_azure_initial_sar_report_storage_ignores_missing_blob_on_delete(monkeypatch):
    class MissingDeleteBlobClient(FakeBlobClient):
        async def delete_blob(self):
            raise ResourceNotFoundError("missing")

    class MissingDeleteBlobServiceClient(FakeBlobServiceClient):
        def get_blob_client(self, *, container: str, blob: str) -> MissingDeleteBlobClient:
            client = MissingDeleteBlobClient(container=container, blob=blob)
            self.blob_clients.append(client)
            return client

    MissingDeleteBlobServiceClient.instances = []
    MissingDeleteBlobServiceClient.last_instance = None
    monkeypatch.setattr(initial_sar_report_storage_module, "BlobServiceClient", MissingDeleteBlobServiceClient)
    monkeypatch.setattr(initial_sar_report_storage_module, "ContentSettings", FakeContentSettings)

    storage = AzureBlobInitialSarReportStorage(
        AzureBlobInitialSarReportStorageSettings(
            connection_string="UseDevelopmentStorage=true",
            container_name="sar-documents",
        )
    )

    await storage.delete_report("sar-documents", "missing-key")

    service_client = MissingDeleteBlobServiceClient.last_instance
    assert service_client is not None
    assert service_client.blob_clients[0].closed is True
    assert service_client.closed is True


@pytest.mark.asyncio
async def test_azure_initial_sar_report_storage_maps_resource_exists_to_file_exists(monkeypatch):
    class ExistingBlobClient(FakeBlobClient):
        async def upload_blob(self, data, *, overwrite: bool, content_settings):
            raise ResourceExistsError("exists")

    class ExistingBlobServiceClient(FakeBlobServiceClient):
        def get_blob_client(self, *, container: str, blob: str) -> ExistingBlobClient:
            client = ExistingBlobClient(container=container, blob=blob)
            self.blob_clients.append(client)
            return client

    ExistingBlobServiceClient.instances = []
    ExistingBlobServiceClient.last_instance = None
    monkeypatch.setattr(initial_sar_report_storage_module, "BlobServiceClient", ExistingBlobServiceClient)
    monkeypatch.setattr(initial_sar_report_storage_module, "ContentSettings", FakeContentSettings)

    storage = AzureBlobInitialSarReportStorage(
        AzureBlobInitialSarReportStorageSettings(
            connection_string="UseDevelopmentStorage=true",
            container_name="sar-documents",
        )
    )

    with pytest.raises(FileExistsError):
        await storage.store_report(
            report_id=uuid.uuid4(),
            assessment_id=uuid.uuid4(),
            filename="duplicate.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            content=b"report-bytes",
        )


@pytest.mark.asyncio
async def test_in_memory_initial_sar_report_storage_supports_store_open_delete_and_missing_behavior():
    storage = InMemoryInitialSarReportStorage(container="sar-documents")
    report_id = uuid.uuid4()
    assessment_id = uuid.uuid4()

    stored = await storage.store_report(
        report_id=report_id,
        assessment_id=assessment_id,
        filename="Executive Summary / v1?.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=b"stored-in-memory",
    )
    opened = await storage.open_report(stored.storage_container, stored.storage_key)

    assert stored.storage_key == f"local-dev/reports/{report_id}/Executive_Summary_v1_.docx"
    assert opened == OpenedInitialSarReport(
        content=b"stored-in-memory",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    await storage.delete_report(stored.storage_container, stored.storage_key)

    with pytest.raises(FileNotFoundError):
        await storage.open_report(stored.storage_container, stored.storage_key)


@pytest.mark.asyncio
async def test_initial_sar_report_storage_settings_are_created_from_config():
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

    resolved = AzureBlobInitialSarReportStorageSettings.from_settings(settings)

    assert resolved.connection_string == "UseDevelopmentStorage=true"
    assert resolved.container_name == "sar-documents"


def test_build_initial_sar_report_storage_key_uses_safe_filename():
    report_id = uuid.UUID("00000000-0000-0000-0000-000000000123")
    assessment_id = uuid.UUID("00000000-0000-0000-0000-000000000456")

    key = build_initial_sar_report_storage_key(
        report_id=report_id,
        assessment_id=assessment_id,
        filename=" Initial SAR: Draft #1 .docx ",
    )

    assert key == "local-dev/reports/00000000-0000-0000-0000-000000000123/Initial_SAR_Draft_1_.docx"
