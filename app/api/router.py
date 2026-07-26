from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.ai_analysis import router as ai_analysis_router
from app.api.v1.document_checklist import router as document_checklist_router
from app.api.v1.documents import router as documents_router
from app.api.v1.inherent_risk import router as inherent_risk_router
from app.api.v1.intake import router as intake_router

api_router = APIRouter()
api_router.include_router(intake_router)
api_router.include_router(inherent_risk_router)
api_router.include_router(ai_analysis_router)
api_router.include_router(document_checklist_router)
api_router.include_router(documents_router)
