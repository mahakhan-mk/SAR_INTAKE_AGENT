from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    AssessmentResponse,
    QuestionAnalysisRun,
    QuestionDefinition,
    QuestionOption,
    QuestionRiskResult,
)
from app.models.enums import AnalysisRunStatus, RiskLevel
from app.repositories.analysis_repository import AnalysisRepository

pytestmark = pytest.mark.asyncio


async def create_triage_question(
    session: AsyncSession,
    questionnaire_version_id: uuid.UUID,
    *,
    question_code: str,
    question_text: str,
    risk_domain: str,
    question_order: int,
    is_visible: bool = True,
    options: list[tuple[str, RiskLevel, float, str, str]] | None = None,
) -> tuple[QuestionDefinition, list[QuestionOption]]:
    question = QuestionDefinition(
        id=uuid.uuid4(),
        questionnaire_version_id=questionnaire_version_id,
        question_code=question_code,
        question_text=question_text,
        response_type="single_select",
        is_required=True,
        section_code="triage",
        question_order=question_order,
        risk_domain=risk_domain,
        is_visible=is_visible,
    )
    session.add(question)
    await session.flush()

    resolved_options = options or [("Selected", RiskLevel.LOW, 0.0, "Default signal", "Default rationale")]
    option_models: list[QuestionOption] = []
    for index, (label, risk_band, risk_weight, risk_signal, why_it_matters) in enumerate(resolved_options, start=1):
        option = QuestionOption(
            id=uuid.uuid4(),
            question_id=question.id,
            option_code=f"{question_code}-OPTION-{index}",
            option_label=label,
            risk_weight=risk_weight,
            display_order=index,
            risk_band=risk_band.value,
            risk_signal=risk_signal,
            why_it_matters=why_it_matters,
        )
        option_models.append(option)
    session.add_all(option_models)
    await session.commit()
    return question, option_models


async def create_response(
    session: AsyncSession,
    *,
    assessment_id: uuid.UUID,
    question_id: uuid.UUID,
    answer_value: object,
    reviewer_remarks: str | None = None,
) -> AssessmentResponse:
    response = AssessmentResponse(
        id=uuid.uuid4(),
        assessment_id=assessment_id,
        question_id=question_id,
        answer_value=answer_value,
        response_status="answered",
        reviewer_remarks=reviewer_remarks,
    )
    session.add(response)
    await session.commit()
    return response


async def create_run(
    session: AsyncSession,
    *,
    assessment_id: uuid.UUID,
    status: AnalysisRunStatus,
    created_at: datetime,
) -> QuestionAnalysisRun:
    run = QuestionAnalysisRun(
        id=uuid.uuid4(),
        assessment_id=assessment_id,
        status=status.value,
        scoring_rule_version="inherent-risk-v1",
        inherent_risk_level=RiskLevel.HIGH.value,
        created_at=created_at,
    )
    session.add(run)
    await session.commit()
    return run


async def create_result(
    session: AsyncSession,
    *,
    analysis_run_id: uuid.UUID,
    response_id: uuid.UUID,
    risk_domain: str,
    risk_level: RiskLevel,
    risk_score: float,
    risk_impact: str,
    explanation: str,
    confidence: float,
    risk_signal: str = "Stored signal",
) -> QuestionRiskResult:
    result = QuestionRiskResult(
        id=uuid.uuid4(),
        analysis_run_id=analysis_run_id,
        response_id=response_id,
        risk_domain=risk_domain,
        risk_score=risk_score,
        risk_level=risk_level.value,
        risk_impact=risk_impact,
        explanation=explanation,
        confidence=confidence,
        input_snapshot={"joinedBy": "response_id"},
        risk_signal=risk_signal,
    )
    session.add(result)
    await session.commit()
    return result


async def test_load_ai_analysis_view_selects_latest_eligible_run(db_session, seeded_assessment):
    question, options = await create_triage_question(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        question_code="TRIAGE-001",
        question_text="Question one",
        risk_domain="Security",
        question_order=1,
        options=[("Yes", RiskLevel.HIGH, 3.0, "Option signal", "Option rationale")],
    )
    response = await create_response(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        question_id=question.id,
        answer_value="Yes",
    )

    base_time = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    older_completed = await create_run(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        status=AnalysisRunStatus.COMPLETED,
        created_at=base_time,
    )
    await create_result(
        db_session,
        analysis_run_id=older_completed.id,
        response_id=response.id,
        risk_domain="Security",
        risk_level=RiskLevel.LOW,
        risk_score=1.0,
        risk_impact="Older impact",
        explanation="Older explanation",
        confidence=0.4,
    )
    await create_run(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        status=AnalysisRunStatus.FAILED,
        created_at=base_time + timedelta(days=1),
    )
    latest_eligible = await create_run(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        status=AnalysisRunStatus.COMPLETED_WITH_LIMITATIONS,
        created_at=base_time + timedelta(days=2),
    )
    await create_result(
        db_session,
        analysis_run_id=latest_eligible.id,
        response_id=response.id,
        risk_domain="Security",
        risk_level=RiskLevel.HIGH,
        risk_score=3.0,
        risk_impact="Latest impact",
        explanation="Latest explanation",
        confidence=0.9,
    )

    view = await AnalysisRepository().load_ai_analysis_view(db_session, seeded_assessment["assessment_id"])

    assert view is not None
    assert view.latest_run is not None
    assert view.latest_run.analysis_run_id == latest_eligible.id
    assert view.latest_run.status == AnalysisRunStatus.COMPLETED_WITH_LIMITATIONS
    assert view.questions[0].result_explanation == "Latest explanation"
    assert view.questions[0].selected_option_id == options[0].id


async def test_load_ai_analysis_view_orders_eight_visible_triage_rows(db_session, seeded_assessment):
    expected_codes: list[str] = []
    for index in range(8, 0, -1):
        question, _ = await create_triage_question(
            db_session,
            seeded_assessment["questionnaire_version_id"],
            question_code=f"TRIAGE-{index:03d}",
            question_text=f"Question {index}",
            risk_domain="Security",
            question_order=index,
        )
        expected_codes.append(question.question_code)

    view = await AnalysisRepository().load_ai_analysis_view(db_session, seeded_assessment["assessment_id"])

    assert view is not None
    assert len(view.questions) == 8
    assert [row.question_number for row in view.questions] == sorted(expected_codes)


async def test_load_ai_analysis_view_excludes_hidden_questions(db_session, seeded_assessment):
    visible_question, _ = await create_triage_question(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        question_code="TRIAGE-VISIBLE",
        question_text="Visible question",
        risk_domain="Security",
        question_order=1,
        is_visible=True,
    )
    await create_triage_question(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        question_code="TRIAGE-HIDDEN",
        question_text="Hidden question",
        risk_domain="Security",
        question_order=2,
        is_visible=False,
    )

    view = await AnalysisRepository().load_ai_analysis_view(db_session, seeded_assessment["assessment_id"])

    assert view is not None
    assert [row.question_id for row in view.questions] == [visible_question.id]


async def test_load_ai_analysis_view_resolves_option_metadata(db_session, seeded_assessment):
    question, options = await create_triage_question(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        question_code="TRIAGE-001",
        question_text="Metadata question",
        risk_domain="Operations",
        question_order=1,
        options=[("Approved", RiskLevel.MEDIUM, 2.0, "Operational signal", "Operational rationale")],
    )
    await create_response(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        question_id=question.id,
        answer_value="Approved",
        reviewer_remarks="Checked manually",
    )

    view = await AnalysisRepository().load_ai_analysis_view(db_session, seeded_assessment["assessment_id"])

    assert view is not None
    row = view.questions[0]
    assert row.selected_option_id == options[0].id
    assert row.answer_value == "Approved"
    assert row.option_risk_band == RiskLevel.MEDIUM.value
    assert row.option_risk_weight == 2.0
    assert row.option_why_it_matters == "Operational rationale"
    assert row.option_risk_signal == "Operational signal"
    assert row.reviewer_remarks == "Checked manually"


async def test_load_ai_analysis_view_joins_risk_result_by_response_id(db_session, seeded_assessment):
    first_question, _ = await create_triage_question(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        question_code="TRIAGE-001",
        question_text="First question",
        risk_domain="Security",
        question_order=1,
    )
    second_question, _ = await create_triage_question(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        question_code="TRIAGE-002",
        question_text="Second question",
        risk_domain="Privacy",
        question_order=2,
    )
    first_response = await create_response(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        question_id=first_question.id,
        answer_value="Selected",
    )
    second_response = await create_response(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        question_id=second_question.id,
        answer_value="Selected",
    )
    run = await create_run(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        status=AnalysisRunStatus.COMPLETED,
        created_at=datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc),
    )
    await create_result(
        db_session,
        analysis_run_id=run.id,
        response_id=second_response.id,
        risk_domain="Privacy",
        risk_level=RiskLevel.CRITICAL,
        risk_score=4.0,
        risk_impact="Second impact",
        explanation="Second explanation",
        confidence=0.8,
    )
    await create_result(
        db_session,
        analysis_run_id=run.id,
        response_id=first_response.id,
        risk_domain="Security",
        risk_level=RiskLevel.HIGH,
        risk_score=3.0,
        risk_impact="First impact",
        explanation="First explanation",
        confidence=0.7,
    )

    view = await AnalysisRepository().load_ai_analysis_view(db_session, seeded_assessment["assessment_id"])

    assert view is not None
    rows_by_question = {row.question_id: row for row in view.questions}
    assert rows_by_question[first_question.id].result_explanation == "First explanation"
    assert rows_by_question[first_question.id].result_risk_level == RiskLevel.HIGH.value
    assert rows_by_question[second_question.id].result_explanation == "Second explanation"
    assert rows_by_question[second_question.id].result_risk_level == RiskLevel.CRITICAL.value


async def test_load_ai_analysis_view_without_completed_run_returns_nullable_analysis_fields(
    db_session,
    seeded_assessment,
):
    question, options = await create_triage_question(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        question_code="TRIAGE-001",
        question_text="Question without analysis",
        risk_domain="Security",
        question_order=1,
        options=[("Yes", RiskLevel.HIGH, 3.0, "Signal", "Rationale")],
    )
    response = await create_response(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        question_id=question.id,
        answer_value={"selectedResponse": "Yes"},
        reviewer_remarks="Pending analysis",
    )
    del response

    view = await AnalysisRepository().load_ai_analysis_view(db_session, seeded_assessment["assessment_id"])

    assert view is not None
    assert view.latest_run is None
    row = view.questions[0]
    assert row.selected_option_id == options[0].id
    assert row.result_risk_level is None
    assert row.result_risk_score is None
    assert row.result_risk_impact is None
    assert row.result_explanation is None
    assert row.result_confidence is None
    assert row.reviewer_remarks == "Pending analysis"


async def test_load_ai_analysis_view_returns_none_for_unknown_assessment(db_session):
    view = await AnalysisRepository().load_ai_analysis_view(db_session, uuid.uuid4())

    assert view is None
