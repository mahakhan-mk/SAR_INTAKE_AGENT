from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_session
from app.api.errors import register_exception_handlers
from app.api.schemas import AIAnalysisQuestionRowDTO, AIAnalysisResponseDTO, AIAnalysisRunSummaryDTO
from app.api.dependencies import get_ai_analysis_query_service
from app.api.v1.ai_analysis import router
from app.domain.errors import AssessmentNotFoundError
from app.models.enums import AnalysisRunStatus, RiskLevel

pytestmark = pytest.mark.asyncio


class FakeAIAnalysisQueryService:
    def __init__(self, response: AIAnalysisResponseDTO | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.get_ai_analysis = AsyncMock(side_effect=self._call)

    async def _call(self, *, session, assessment_id):
        if self.error is not None:
            raise self.error
        return self.response


@pytest.fixture()
async def ai_analysis_client():
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    yield app


def build_dto() -> AIAnalysisResponseDTO:
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
                reviewerRemarks="Reviewed.",
            )
        ],
    )


async def test_valid_assessment_returns_200_with_dto_payload(ai_analysis_client):
    dto = build_dto()
    service = FakeAIAnalysisQueryService(response=dto)
    dummy_session = object()

    async def override_get_session():
        yield dummy_session

    ai_analysis_client.dependency_overrides[get_ai_analysis_query_service] = lambda: service
    ai_analysis_client.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(transport=ASGITransport(app=ai_analysis_client), base_url="http://testserver") as client:
        response = await client.get("/api/v1/assessments/00000000-0000-0000-0000-000000000100/ai-analysis")

    assert response.status_code == 200
    assert response.json() == dto.model_dump(mode="json")
    assert "aiExplanation" not in response.json()["questions"][0]
    assert "confidence" not in response.json()["questions"][0]
    service.get_ai_analysis.assert_awaited_once_with(
        session=dummy_session,
        assessment_id=uuid.UUID("00000000-0000-0000-0000-000000000100"),
    )


async def test_assessment_uuid_is_passed_to_the_service(ai_analysis_client):
    dto = build_dto()
    service = FakeAIAnalysisQueryService(response=dto)
    dummy_session = object()
    assessment_id = uuid.uuid4()

    async def override_get_session():
        yield dummy_session

    ai_analysis_client.dependency_overrides[get_ai_analysis_query_service] = lambda: service
    ai_analysis_client.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(transport=ASGITransport(app=ai_analysis_client), base_url="http://testserver") as client:
        await client.get(f"/api/v1/assessments/{assessment_id}/ai-analysis")

    called_kwargs = service.get_ai_analysis.await_args.kwargs
    assert called_kwargs["assessment_id"] == assessment_id
    assert called_kwargs["session"] is dummy_session


async def test_unknown_assessment_uses_existing_404_error_response(ai_analysis_client):
    service = FakeAIAnalysisQueryService(error=AssessmentNotFoundError())
    dummy_session = object()

    async def override_get_session():
        yield dummy_session

    ai_analysis_client.dependency_overrides[get_ai_analysis_query_service] = lambda: service
    ai_analysis_client.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(transport=ASGITransport(app=ai_analysis_client), base_url="http://testserver") as client:
        response = await client.get(f"/api/v1/assessments/{uuid.uuid4()}/ai-analysis")

    assert response.status_code == 404
    assert response.json() == {"detail": "Assessment not found."}
    service.get_ai_analysis.assert_awaited_once()


async def test_invalid_uuid_returns_422(ai_analysis_client):
    service = FakeAIAnalysisQueryService(response=build_dto())
    dummy_session = object()

    async def override_get_session():
        yield dummy_session

    ai_analysis_client.dependency_overrides[get_ai_analysis_query_service] = lambda: service
    ai_analysis_client.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(transport=ASGITransport(app=ai_analysis_client), base_url="http://testserver") as client:
        response = await client.get("/api/v1/assessments/not-a-uuid/ai-analysis")

    assert response.status_code == 422
    service.get_ai_analysis.assert_not_awaited()


async def test_service_is_called_exactly_once(ai_analysis_client):
    service = FakeAIAnalysisQueryService(response=build_dto())
    dummy_session = object()

    async def override_get_session():
        yield dummy_session

    ai_analysis_client.dependency_overrides[get_ai_analysis_query_service] = lambda: service
    ai_analysis_client.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(transport=ASGITransport(app=ai_analysis_client), base_url="http://testserver") as client:
        response = await client.get("/api/v1/assessments/00000000-0000-0000-0000-000000000100/ai-analysis")

    assert response.status_code == 200
    assert service.get_ai_analysis.await_count == 1
