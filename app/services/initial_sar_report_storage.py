from __future__ import annotations

from dataclasses import dataclass
import inspect
from typing import Protocol
from uuid import UUID

from app.config import Settings, get_settings
from app.services.document_storage import AzureBlobDocumentStorageConfigurationError, make_safe_document_filename

try:
    from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
    from azure.storage.blob import ContentSettings
    from azure.storage.blob.aio import BlobServiceClient
except ImportError:  # pragma: no cover - exercised through mocked globals in unit tests.
    BlobServiceClient = None
    ContentSettings = None

    class ResourceExistsError(Exception):
        pass

    class ResourceNotFoundError(Exception):
        pass


@dataclass(frozen=True)
class StoredInitialSarReport:
    storage_container: str
    storage_key: str


@dataclass(frozen=True)
class OpenedInitialSarReport:
    content: bytes
    content_type: str


@dataclass(frozen=True)
class AzureBlobInitialSarReportStorageSettings:
    connection_string: str
    container_name: str

    @classmethod
    def from_settings(cls, settings: Settings) -> "AzureBlobInitialSarReportStorageSettings":
        missing = [
            name
            for name, value in [
                ("AZURE_BLOB_CONNECTION_STRING", settings.azure_blob_connection_string),
                ("AZURE_BLOB_CONTAINER_NAME", settings.azure_blob_container_name),
            ]
            if not value
        ]
        if missing:
            raise AzureBlobDocumentStorageConfigurationError(
                f"Missing Azure Blob Storage configuration: {', '.join(missing)}."
            )
        return cls(
            connection_string=settings.azure_blob_connection_string or "",
            container_name=settings.azure_blob_container_name or "",
        )


class InitialSarReportStorage(Protocol):
    async def store_report(
        self,
        *,
        report_id: UUID,
        assessment_id: UUID,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> StoredInitialSarReport:
        ...

    async def delete_report(
        self,
        storage_container: str,
        storage_key: str,
    ) -> None:
        ...

    async def open_report(
        self,
        storage_container: str,
        storage_key: str,
    ) -> OpenedInitialSarReport:
        ...


def build_initial_sar_report_storage_key(
    *,
    report_id: UUID,
    assessment_id: UUID,
    filename: str,
) -> str:
    del assessment_id
    safe_filename = make_safe_document_filename(filename)
    return f"local-dev/reports/{report_id}/{safe_filename}"


class InMemoryInitialSarReportStorage:
    def __init__(self, *, container: str = "sar-documents") -> None:
        self.container = container
        self.objects: dict[tuple[str, str], OpenedInitialSarReport] = {}

    async def store_report(
        self,
        *,
        report_id: UUID,
        assessment_id: UUID,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> StoredInitialSarReport:
        key = build_initial_sar_report_storage_key(
            report_id=report_id,
            assessment_id=assessment_id,
            filename=filename,
        )
        object_ref = (self.container, key)
        if object_ref in self.objects:
            raise FileExistsError(f"Initial SAR report object already exists for key {key}.")
        self.objects[object_ref] = OpenedInitialSarReport(content=content, content_type=content_type)
        return StoredInitialSarReport(storage_container=self.container, storage_key=key)

    async def delete_report(
        self,
        storage_container: str,
        storage_key: str,
    ) -> None:
        self.objects.pop((storage_container, storage_key), None)

    async def open_report(
        self,
        storage_container: str,
        storage_key: str,
    ) -> OpenedInitialSarReport:
        report = self.objects.get((storage_container, storage_key))
        if report is None:
            raise FileNotFoundError(f"Initial SAR report object was not found for key {storage_key}.")
        return report


class AzureBlobInitialSarReportStorage:
    def __init__(
        self,
        settings: AzureBlobInitialSarReportStorageSettings | None = None,
    ) -> None:
        self.settings = settings or AzureBlobInitialSarReportStorageSettings.from_settings(get_settings())

    @classmethod
    def from_settings(cls, settings: Settings) -> "AzureBlobInitialSarReportStorage":
        return cls(AzureBlobInitialSarReportStorageSettings.from_settings(settings))

    async def store_report(
        self,
        *,
        report_id: UUID,
        assessment_id: UUID,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> StoredInitialSarReport:
        key = build_initial_sar_report_storage_key(
            report_id=report_id,
            assessment_id=assessment_id,
            filename=filename,
        )
        service_client = self._create_service_client()
        try:
            blob_client = service_client.get_blob_client(container=self.settings.container_name, blob=key)
            try:
                await _maybe_await(
                    blob_client.upload_blob(
                        content,
                        overwrite=False,
                        content_settings=self._create_content_settings(content_type),
                    )
                )
            except ResourceExistsError as exc:
                raise FileExistsError(f"Initial SAR report object already exists for key {key}.") from exc
            finally:
                await _close_client(blob_client)
        finally:
            await _close_client(service_client)
        return StoredInitialSarReport(
            storage_container=self.settings.container_name,
            storage_key=key,
        )

    async def delete_report(
        self,
        storage_container: str,
        storage_key: str,
    ) -> None:
        service_client = self._create_service_client()
        try:
            blob_client = service_client.get_blob_client(container=storage_container, blob=storage_key)
            try:
                try:
                    await _maybe_await(blob_client.delete_blob())
                except ResourceNotFoundError:
                    return
            finally:
                await _close_client(blob_client)
        finally:
            await _close_client(service_client)

    async def open_report(
        self,
        storage_container: str,
        storage_key: str,
    ) -> OpenedInitialSarReport:
        service_client = self._create_service_client()
        try:
            blob_client = service_client.get_blob_client(container=storage_container, blob=storage_key)
            try:
                try:
                    downloader = await _maybe_await(blob_client.download_blob())
                    content = await _maybe_await(downloader.readall())
                    properties = await _maybe_await(blob_client.get_blob_properties())
                except ResourceNotFoundError as exc:
                    raise FileNotFoundError(
                        f"Initial SAR report object was not found for key {storage_key}."
                    ) from exc
            finally:
                await _close_client(blob_client)
        finally:
            await _close_client(service_client)

        content_settings = getattr(properties, "content_settings", None)
        stored_content_type = getattr(content_settings, "content_type", None) if content_settings is not None else None
        return OpenedInitialSarReport(
            content=content,
            content_type=stored_content_type or "application/octet-stream",
        )

    def _create_service_client(self):
        if BlobServiceClient is None:
            raise AzureBlobDocumentStorageConfigurationError("azure-storage-blob is not installed.")
        return BlobServiceClient.from_connection_string(self.settings.connection_string)

    @staticmethod
    def _create_content_settings(content_type: str):
        if ContentSettings is None:
            raise AzureBlobDocumentStorageConfigurationError("azure-storage-blob is not installed.")
        return ContentSettings(content_type=content_type)


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def _close_client(client) -> None:
    close = getattr(client, "close", None)
    if close is None:
        return
    await _maybe_await(close())
