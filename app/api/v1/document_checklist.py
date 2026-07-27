from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.assemblers.document_checklist_assembler import DocumentChecklistAssembler
from app.models.document_checklist import (
    DocumentChecklistItemResponseDTO,
    DocumentChecklistItemReviewRequestDTO,
    DocumentChecklistResponseDTO,
)
from app.services.document_checklist_service import (
    DocumentChecklistItemNotFoundError,
    DocumentChecklistRunNotFoundError,
    DocumentChecklistService,
)

router = APIRouter(prefix="/api/v1/assessments", tags=["document-checklist"])


def get_document_checklist_service() -> DocumentChecklistService:
    return DocumentChecklistService()


def get_document_checklist_assembler() -> DocumentChecklistAssembler:
    return DocumentChecklistAssembler()


@router.post(
    "/{assessment_id}/document-checklist/runs",
    response_model=DocumentChecklistResponseDTO,
)
async def create_document_checklist_run(
    assessment_id: UUID,
    session: AsyncSession = Depends(get_session),
    service: DocumentChecklistService = Depends(get_document_checklist_service),
    assembler: DocumentChecklistAssembler = Depends(get_document_checklist_assembler),
) -> DocumentChecklistResponseDTO:
    try:
        generated = await service.generate_checklist(session, assessment_id)
        state = await service.finalize_checklist(
            session,
            assessment_id=assessment_id,
            run_id=generated.run.id,
        )
        response = assembler.to_dto(state)
        await session.commit()
        return response
    except DocumentChecklistRunNotFoundError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="Document checklist run not found.") from exc
    except Exception:
        await session.rollback()
        raise


@router.get(
    "/{assessment_id}/document-checklist",
    response_model=DocumentChecklistResponseDTO,
)
async def get_document_checklist(
    assessment_id: UUID,
    session: AsyncSession = Depends(get_session),
    service: DocumentChecklistService = Depends(get_document_checklist_service),
    assembler: DocumentChecklistAssembler = Depends(get_document_checklist_assembler),
) -> DocumentChecklistResponseDTO:
    try:
        state = await service.get_checklist(session, assessment_id)
        return assembler.to_dto(state)
    except DocumentChecklistRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Document checklist run not found.") from exc


@router.post(
    "/{assessment_id}/document-checklist/items/{item_id}/reviews",
    response_model=DocumentChecklistItemResponseDTO,
)
async def create_document_checklist_item_review(
    assessment_id: UUID,
    item_id: UUID,
    payload: DocumentChecklistItemReviewRequestDTO,
    session: AsyncSession = Depends(get_session),
    service: DocumentChecklistService = Depends(get_document_checklist_service),
    assembler: DocumentChecklistAssembler = Depends(get_document_checklist_assembler),
) -> DocumentChecklistItemResponseDTO:
    try:
        state = await service.apply_reviewer_override(
            session,
            assessment_id=assessment_id,
            item_id=item_id,
            reviewer_verdict=payload.reviewer_verdict,
            reason=payload.reason,
            reviewed_by=payload.reviewed_by,
        )
        response = assembler.to_item_dto(state)
        await session.commit()
        return response
    except DocumentChecklistItemNotFoundError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail="Document checklist item not found.") from exc
    except Exception:
        await session.rollback()
        raise
