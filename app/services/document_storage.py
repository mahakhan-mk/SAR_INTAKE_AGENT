from __future__ import annotations

from dataclasses import dataclass
import inspect
import re
from typing import Protocol
from uuid import UUID

from app.config import Settings, get_settings

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
class StoredDocument:
    container: str
    key: str


@dataclass(frozen=True)
class OpenedDocument:
    content: bytes
    content_type: str


class AzureBlobDocumentStorageConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class AzureBlobDocumentStorageSettings:
    connection_string: str
    container_name: str

    @classmethod
    def from_settings(cls, settings: Settings) -> "AzureBlobDocumentStorageSettings":
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


class DocumentStorage(Protocol):
    async def store(
        self,
        *,
        assessment_id: UUID,
        document_id: UUID,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> StoredDocument:
        ...

    async def delete(
        self,
        *,
        container: str,
        key: str,
    ) -> None:
        ...

    async def open(
        self,
        *,
        container: str,
        key: str,
    ) -> OpenedDocument:
        ...


def make_safe_document_filename(filename: str) -> str:
    safe_filename = re.sub(r"[^A-Za-z0-9._-]+", "_", filename.strip()).strip("._")
    return safe_filename or "document"


def build_document_storage_key(
    *,
    assessment_id: UUID,
    document_id: UUID,
    filename: str,
) -> str:
    del assessment_id
    safe_filename = make_safe_document_filename(filename)
    return f"local-dev/documents/{document_id}/{safe_filename}"


class InMemoryDocumentStorage:
    def __init__(self, *, container: str = "sar-documents") -> None:
        self.container = container
        self.objects: dict[tuple[str, str], OpenedDocument] = {}

    async def store(
        self,
        *,
        assessment_id: UUID,
        document_id: UUID,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> StoredDocument:
        key = build_document_storage_key(
            assessment_id=assessment_id,
            document_id=document_id,
            filename=filename,
        )
        object_ref = (self.container, key)
        if object_ref in self.objects:
            raise FileExistsError(f"Document object already exists for key {key}.")
        self.objects[object_ref] = OpenedDocument(content=content, content_type=content_type)
        return StoredDocument(container=self.container, key=key)

    async def delete(
        self,
        *,
        container: str,
        key: str,
    ) -> None:
        self.objects.pop((container, key), None)

    async def open(
        self,
        *,
        container: str,
        key: str,
    ) -> OpenedDocument:
        document = self.objects.get((container, key))
        if document is None:
            raise FileNotFoundError(f"Document object was not found for key {key}.")
        return document


class AzureBlobDocumentStorage:
    def __init__(
        self,
        settings: AzureBlobDocumentStorageSettings | None = None,
    ) -> None:
        self.settings = settings or AzureBlobDocumentStorageSettings.from_settings(get_settings())

    @classmethod
    def from_settings(cls, settings: Settings) -> "AzureBlobDocumentStorage":
        return cls(AzureBlobDocumentStorageSettings.from_settings(settings))

    async def store(
        self,
        *,
        assessment_id: UUID,
        document_id: UUID,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> StoredDocument:
        key = build_document_storage_key(
            assessment_id=assessment_id,
            document_id=document_id,
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
                raise FileExistsError(f"Document object already exists for key {key}.") from exc
            finally:
                await _close_client(blob_client)
        finally:
            await _close_client(service_client)
        return StoredDocument(container=self.settings.container_name, key=key)

    async def delete(
        self,
        *,
        container: str,
        key: str,
    ) -> None:
        service_client = self._create_service_client()
        try:
            blob_client = service_client.get_blob_client(container=container, blob=key)
            try:
                await _maybe_await(blob_client.delete_blob())
            finally:
                await _close_client(blob_client)
        finally:
            await _close_client(service_client)

    async def open(
        self,
        *,
        container: str,
        key: str,
    ) -> OpenedDocument:
        service_client = self._create_service_client()
        try:
            blob_client = service_client.get_blob_client(container=container, blob=key)
            try:
                try:
                    downloader = await _maybe_await(blob_client.download_blob())
                    content = await _maybe_await(downloader.readall())
                    properties = await _maybe_await(blob_client.get_blob_properties())
                except ResourceNotFoundError as exc:
                    raise FileNotFoundError(f"Document object was not found for key {key}.") from exc
            finally:
                await _close_client(blob_client)
        finally:
            await _close_client(service_client)

        content_settings = getattr(properties, "content_settings", None)
        stored_content_type = getattr(content_settings, "content_type", None) if content_settings is not None else None
        return OpenedDocument(
            content=content,
            content_type=stored_content_type or "application/octet-stream",
        )

    def _create_service_client(self):
        if BlobServiceClient is None:
            raise AzureBlobDocumentStorageConfigurationError(
                "azure-storage-blob is not installed."
            )
        return BlobServiceClient.from_connection_string(self.settings.connection_string)

    @staticmethod
    def _create_content_settings(content_type: str):
        if ContentSettings is None:
            raise AzureBlobDocumentStorageConfigurationError(
                "azure-storage-blob is not installed."
            )
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
