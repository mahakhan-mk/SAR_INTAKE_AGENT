from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest

from app.api.errors import AssessmentNotFoundError
from app.models.ai_analysis import AIAnalysisQuestionRowRecord, AIAnalysisRunRecord, AIAnalysisViewRecord
from app.models.dto import AIAnalysisQuestionRowDTO, AIAnalysisResponseDTO, AIAnalysisRunSummaryDTO
from app.models.enums import AnalysisRunStatus, RiskLevel
from app.services.ai_analysis_service import AIAnalysisService

pytestmark = pytest.mark.asyncio


def build_view_record() -> AIAnalysisViewRecord:
    return AIAnalysisViewRecord(
        assessment_id=uuid.UUID("00000000-0000-0000-0000-000000000100"),
        latest_run=AIAnalysisRunRecord(
            analysis_run_id=uuid.UUID("00000000-0000-0000-0000-000000000200"),
            status=AnalysisRunStatus.COMPLETED,
            created_at=datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc),
        ),
        questions=[
            AIAnalysisQuestionRowRecord(
                question_id=uuid.UUID("00000000-0000-0000-0000-000000000300"),
                question_number="TRIAGE-001",
                question_text="Does the tool handle sensitive data?",
                domain="Security",
                response_id=uuid.UUID("00000000-0000-0000-0000-000000000400"),
                selected_option_id=uuid.UUID("00000000-0000-0000-0000-000000000500"),
                answer_value="Yes",
                option_risk_band=RiskLevel.HIGH.value,
                option_risk_weight=3.0,
                option_why_it_matters="Configured rationale.",
                option_risk_signal="Configured signal.",
                result_risk_level=RiskLevel.HIGH.value,
                result_risk_score=3.0,
                result_risk_impact="Stored impact.",
                result_explanation="Stored explanation.",
                result_confidence=1.0,
                reviewer_remarks="Reviewed.",
            )
        ],
    )


def build_response_dto() -> AIAnalysisResponseDTO:
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
                selectedOptionId="00000000-0000-0000-0000-000000000500",
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


def build_service(
    *,
    repository_result: AIAnalysisViewRecord | None = None,
    assembler_result: AIAnalysisResponseDTO | None = None,
) -> tuple[AIAnalysisService, AsyncMock, MagicMock]:
    repository = AsyncMock()
    repository.load_ai_analysis_view = AsyncMock(return_value=repository_result)
    assembler = MagicMock()
    assembler.to_dto = MagicMock(return_value=assembler_result)
    return AIAnalysisService(analysis_repository=repository, assembler=assembler), repository, assembler


async def test_repository_is_called_with_the_assessment_uuid():
    session = object()
    assessment_id = uuid.uuid4()
    record = build_view_record()
    dto = build_response_dto()
    service, repository, assembler = build_service(repository_result=record, assembler_result=dto)

    await service.get_ai_analysis(session, assessment_id)

    repository.load_ai_analysis_view.assert_awaited_once_with(session, assessment_id)
    assembler.to_dto.assert_called_once_with(record)


async def test_assembler_receives_the_repository_result():
    session = object()
    assessment_id = uuid.uuid4()
    record = build_view_record()
    dto = build_response_dto()
    service, repository, assembler = build_service(repository_result=record, assembler_result=dto)

    await service.get_ai_analysis(session, assessment_id)

    assembler.to_dto.assert_called_once_with(record)
    repository.load_ai_analysis_view.assert_awaited_once_with(session, assessment_id)


async def test_assembled_dto_is_returned_unchanged():
    session = object()
    assessment_id = uuid.uuid4()
    record = build_view_record()
    dto = build_response_dto()
    service, repository, assembler = build_service(repository_result=record, assembler_result=dto)

    result = await service.get_ai_analysis(session, assessment_id)

    assert result is dto
    repository.load_ai_analysis_view.assert_awaited_once_with(session, assessment_id)
    assembler.to_dto.assert_called_once_with(record)


async def test_unknown_assessment_raises_the_existing_not_found_exception():
    session = object()
    assessment_id = uuid.uuid4()
    service, repository, assembler = build_service(repository_result=None, assembler_result=None)

    with pytest.raises(AssessmentNotFoundError):
        await service.get_ai_analysis(session, assessment_id)

    repository.load_ai_analysis_view.assert_awaited_once_with(session, assessment_id)
    assembler.to_dto.assert_not_called()


async def test_repository_and_assembler_are_each_called_once():
    session = object()
    assessment_id = uuid.uuid4()
    record = build_view_record()
    dto = build_response_dto()
    service, repository, assembler = build_service(repository_result=record, assembler_result=dto)

    await service.get_ai_analysis(session, assessment_id)

    assert repository.load_ai_analysis_view.await_count == 1
    assert assembler.to_dto.call_count == 1
