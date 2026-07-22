from __future__ import annotations

from collections import Counter
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.api.dependencies import get_session
from app.api.errors import AssessmentNotFoundError
from app.api.router import api_router
from app.api.v1.ai_analysis import get_ai_analysis_service
from app.main import app, lifespan


class FakeAIAnalysisService:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.get_ai_analysis = AsyncMock(side_effect=self._call)

    async def _call(self, *, session, assessment_id):
        if self.error is not None:
            raise self.error
        return None


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


def test_ai_analysis_route_is_registered_on_app():
    routes = flatten_routes(list(app.routes))

    assert any(
        route.path == "/api/v1/assessments/{assessment_id}/ai-analysis" and "GET" in route.methods
        for route in routes
    )


def test_intake_and_inherent_risk_routes_remain_registered():
    route_signatures = {(route.path, tuple(sorted(route.methods))) for route in flatten_routes(list(app.routes))}

    assert ("/api/v1/assessments/{assessment_id}/intake", ("GET",)) in route_signatures
    assert ("/api/v1/assessments/{assessment_id}/inherent-risk", ("GET",)) in route_signatures
    assert ("/api/v1/assessments/{assessment_id}/analysis-runs", ("POST",)) in route_signatures


def test_api_router_is_included_only_once():
    included_routers = [route for route in app.routes if getattr(route, "original_router", None) is api_router]

    assert len(included_routers) == 1

    route_counts = Counter((route.path, tuple(sorted(route.methods))) for route in flatten_routes(list(app.routes)))
    assert all(count == 1 for count in route_counts.values())


@pytest.mark.asyncio
async def test_existing_exception_handlers_remain_active():
    service = FakeAIAnalysisService(error=AssessmentNotFoundError())

    async def override_get_session():
        yield object()

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_ai_analysis_service] = lambda: service

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/api/v1/assessments/00000000-0000-0000-0000-000000000100/ai-analysis")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json() == {"detail": "Assessment not found."}
    service.get_ai_analysis.assert_awaited_once()


@pytest.mark.asyncio
async def test_existing_startup_behavior_is_preserved(monkeypatch):
    init_db_calls = 0

    async def init_db_spy():
        nonlocal init_db_calls
        init_db_calls += 1

    monkeypatch.setattr(main_module, "init_db", init_db_spy)

    async with lifespan(app):
        pass

    assert app.title == "SAR Assessment Service"
    assert init_db_calls == 1
