from __future__ import annotations

from dataclasses import dataclass
import uuid
from uuid import UUID


@dataclass(frozen=True)
class StoredDocument:
    container: str
    key: str


class DocumentStorage:
    async def store(
        self,
        *,
        assessment_id: UUID,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> StoredDocument:
        raise NotImplementedError


class InMemoryDocumentStorage(DocumentStorage):
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    async def store(
        self,
        *,
        assessment_id: UUID,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> StoredDocument:
        del content_type
        container = "sar-documents"
        key = f"{assessment_id}/{uuid.uuid4()}-{filename}"
        self.objects[(container, key)] = content
        return StoredDocument(container=container, key=key)
