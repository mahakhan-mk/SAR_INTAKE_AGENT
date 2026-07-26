from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.assemblers.document_checklist_assembler import DocumentChecklistAssembler
from app.models.document_checklist import (
    AssessmentDocumentListResponseDTO,
    AssessmentDocumentResponseDTO,
    DocumentClassificationReviewRequestDTO,
    DocumentClassificationReviewResponseDTO,
)
from app.models.enums import AssessmentDocumentSystemType
from app.services.document_service import (
    AssessmentDocumentNotFoundError,
    DocumentService,
    DocumentUploadInput,
    DuplicateAssessmentDocumentError,
)

router = APIRouter(prefix="/api/v1/assessments", tags=["documents"])


@dataclass(frozen=True)
class ParsedMultipartFile:
    filename: str
    content_type: str
    content: bytes
    fields: dict[str, str]


def get_document_service() -> DocumentService:
    return DocumentService()


def get_document_assembler() -> DocumentChecklistAssembler:
    return DocumentChecklistAssembler()


@router.post("/{assessment_id}/documents", response_model=AssessmentDocumentResponseDTO)
async def upload_assessment_document(
    assessment_id: UUID,
    request: Request,
    system_document_type: AssessmentDocumentSystemType = Query(AssessmentDocumentSystemType.UNCLASSIFIED),
    uploaded_by: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    service: DocumentService = Depends(get_document_service),
    assembler: DocumentChecklistAssembler = Depends(get_document_assembler),
) -> AssessmentDocumentResponseDTO:
    try:
        parsed_upload = await _parse_multipart_upload(request)
        document = await service.upload_document(
            session,
            assessment_id=assessment_id,
            upload=DocumentUploadInput(
                filename=parsed_upload.filename,
                content_type=parsed_upload.content_type,
                content=parsed_upload.content,
                system_document_type=parsed_upload.fields.get("system_document_type", system_document_type.value),
                uploaded_by=parsed_upload.fields.get("uploaded_by", uploaded_by),
            ),
        )
        response = assembler.to_document_dto(document)
        await session.commit()
        return response
    except AssessmentDocumentNotFoundError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="Assessment not found.") from exc
    except DuplicateAssessmentDocumentError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Duplicate active document content.") from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        raise


@router.get("/{assessment_id}/documents", response_model=AssessmentDocumentListResponseDTO)
async def list_assessment_documents(
    assessment_id: UUID,
    session: AsyncSession = Depends(get_session),
    service: DocumentService = Depends(get_document_service),
    assembler: DocumentChecklistAssembler = Depends(get_document_assembler),
) -> AssessmentDocumentListResponseDTO:
    try:
        documents = await service.list_active_documents(session, assessment_id=assessment_id)
        return assembler.to_document_list_dto(documents)
    except AssessmentDocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Assessment not found.") from exc


@router.delete("/{assessment_id}/documents/{document_id}", response_model=AssessmentDocumentResponseDTO)
async def delete_assessment_document(
    assessment_id: UUID,
    document_id: UUID,
    deleted_by: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    service: DocumentService = Depends(get_document_service),
    assembler: DocumentChecklistAssembler = Depends(get_document_assembler),
) -> AssessmentDocumentResponseDTO:
    try:
        document = await service.soft_delete_document(
            session,
            assessment_id=assessment_id,
            document_id=document_id,
            deleted_by=deleted_by,
        )
        response = assembler.to_document_dto(document)
        await session.commit()
        return response
    except AssessmentDocumentNotFoundError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="Document not found.") from exc
    except Exception:
        await session.rollback()
        raise


@router.post(
    "/{assessment_id}/documents/{document_id}/classification-reviews",
    response_model=DocumentClassificationReviewResponseDTO,
)
async def create_document_classification_review(
    assessment_id: UUID,
    document_id: UUID,
    payload: DocumentClassificationReviewRequestDTO,
    session: AsyncSession = Depends(get_session),
    service: DocumentService = Depends(get_document_service),
    assembler: DocumentChecklistAssembler = Depends(get_document_assembler),
) -> DocumentClassificationReviewResponseDTO:
    try:
        review = await service.append_classification_review(
            session,
            assessment_id=assessment_id,
            document_id=document_id,
            document_type=payload.document_type,
            reason=payload.reason,
            reviewed_by=payload.reviewed_by,
        )
        response = assembler.to_classification_review_dto(
            review=review,
            assessment_id=assessment_id,
            effective_document_type=review.document_type,
        )
        await session.commit()
        return response
    except AssessmentDocumentNotFoundError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="Document not found.") from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        raise


async def _parse_multipart_upload(request: Request) -> ParsedMultipartFile:
    content_type = request.headers.get("content-type", "")
    boundary = _extract_boundary(content_type)
    if boundary is None:
        raise ValueError("multipart/form-data content type is required.")

    fields: dict[str, str] = {}
    file_payload: tuple[str, str, bytes] | None = None
    body = await request.body()
    delimiter = b"--" + boundary
    for raw_part in body.split(delimiter):
        part = raw_part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        if part.endswith(b"--"):
            part = part[:-2].rstrip(b"\r\n")
        if b"\r\n\r\n" not in part:
            continue
        header_bytes, content = part.split(b"\r\n\r\n", 1)
        headers = _parse_part_headers(header_bytes)
        disposition = headers.get("content-disposition", "")
        name = _extract_disposition_value(disposition, "name")
        filename = _extract_disposition_value(disposition, "filename")
        if not name:
            continue
        if filename is not None:
            file_payload = (filename, headers.get("content-type", "application/octet-stream"), content)
        else:
            fields[name] = content.decode("utf-8")

    if file_payload is None:
        raise ValueError("A document file is required.")
    filename, file_content_type, file_content = file_payload
    return ParsedMultipartFile(
        filename=filename,
        content_type=file_content_type,
        content=file_content,
        fields=fields,
    )


def _extract_boundary(content_type: str) -> bytes | None:
    for segment in content_type.split(";"):
        segment = segment.strip()
        if segment.startswith("boundary="):
            return segment.removeprefix("boundary=").strip('"').encode("utf-8")
    return None


def _parse_part_headers(header_bytes: bytes) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in header_bytes.decode("utf-8").split("\r\n"):
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers[name.strip().lower()] = value.strip()
    return headers


def _extract_disposition_value(disposition: str, key: str) -> str | None:
    prefix = f'{key}="'
    for segment in disposition.split(";"):
        segment = segment.strip()
        if segment.startswith(prefix) and segment.endswith('"'):
            return segment[len(prefix) : -1]
    return None
