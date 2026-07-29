from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_session
from app.api.errors import register_exception_handlers
from app.api.router import api_router
from app.api.schemas import AIAnalysisQuestionRowDTO, AIAnalysisResponseDTO, AIAnalysisRunSummaryDTO
from app.api.dependencies import get_ai_analysis_query_service
from app.models.enums import AnalysisRunStatus, RiskLevel

class FakeAIAnalysisQueryService:
    def __init__(self, response: AIAnalysisResponseDTO) -> None:
        self.get_ai_analysis = AsyncMock(return_value=response)


def build_ai_analysis_dto() -> AIAnalysisResponseDTO:
    return AIAnalysisResponseDTO(
        assessmentId="00000000-0000-0000-0000-000000000100",
        latestAnalysisRun=AIAnalysisRunSummaryDTO(
            analysisRunId="00000000-0000-0000-0000-000000000200",
            status=AnalysisRunStatus.COMPLETED,
            createdAt=datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc),
        ),
        questions=[
            AIAnalysisQuestionRowDTO(
                questionId="00000000-0000-0000-0000-000000000300",
                questionNumber="TRIAGE-001",
                questionText="Does the tool handle sensitive data?",
                domain="Security",
                selectedOptionId="00000000-0000-0000-0000-000000000400",
                answerValue="Yes",
                riskBand=RiskLevel.HIGH,
                riskScore=3.0,
                riskSignal="Configured signal.",
                whyItMatters="Configured rationale.",
                aiExplanation="Stored explanation.",
                confidence=1.0,
                reviewerRemarks="Reviewed.",
            )
        ],
    )


def build_test_app(service: FakeAIAnalysisQueryService) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(api_router)

    async def override_get_session():
        yield object()

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_ai_analysis_query_service] = lambda: service
    return app


def flatten_routes(routes: list[object]) -> list[APIRoute]:
    flattened: list[APIRoute] = []
    for route in routes:
        if isinstance(route, APIRoute):
            flattened.append(route)
            continue
        nested_router = getattr(route, "original_router", None)
        if nested_router is not None:
            flattened.extend(flatten_routes(nested_router.routes))
    return flattened


def get_api_routes() -> list[APIRoute]:
    return flatten_routes(list(api_router.routes))


def test_ai_analysis_router_is_included_in_main_api_router():
    routes = get_api_routes()
    assert any(
        route.path == "/api/v1/assessments/{assessment_id}/ai-analysis" and "GET" in route.methods
        for route in routes
    )


async def test_get_ai_analysis_route_resolves_successfully():
    dto = build_ai_analysis_dto()
    service = FakeAIAnalysisQueryService(dto)
    app = build_test_app(service)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/v1/assessments/00000000-0000-0000-0000-000000000100/ai-analysis")

    assert response.status_code == 200
    assert response.json() == dto.model_dump(mode="json")
    service.get_ai_analysis.assert_awaited_once()


test_get_ai_analysis_route_resolves_successfully = pytest.mark.asyncio(
    test_get_ai_analysis_route_resolves_successfully
)


def test_existing_routes_remain_registered():
    route_signatures = {(route.path, tuple(sorted(route.methods))) for route in get_api_routes()}

    assert ("/api/v1/assessments/{assessment_id}/intake", ("GET",)) in route_signatures
    assert (
        "/api/v1/assessments/{assessment_id}/questions/{question_id}",
        ("PATCH",),
    ) in route_signatures
    assert ("/api/v1/assessments/{assessment_id}/inherent-risk", ("GET",)) in route_signatures
    assert ("/api/v1/assessments/{assessment_id}/analysis-runs", ("POST",)) in route_signatures


def test_no_duplicate_routes_are_introduced():
    route_counts = Counter((route.path, tuple(sorted(route.methods))) for route in get_api_routes())

    assert all(count == 1 for count in route_counts.values())
