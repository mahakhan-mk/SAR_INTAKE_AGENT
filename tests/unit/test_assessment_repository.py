from __future__ import annotations

import pytest

from app.models.enums import RiskLevel
from app.repositories.assessment_repository import AssessmentRepository
from tests.conftest import add_question_with_option, add_response

pytestmark = pytest.mark.asyncio


async def test_load_active_triage_question_responses_uses_question_code_and_skips_invisible_questions(
    db_session,
    seeded_assessment,
):
    visible_question, visible_option = await add_question_with_option(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        risk_level=RiskLevel.HIGH,
        risk_weight=3.0,
        question_code="SEC-001",
        section_code=None,
        question_order=None,
        is_visible=True,
    )
    invisible_question, invisible_option = await add_question_with_option(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Privacy",
        risk_level=RiskLevel.MEDIUM,
        risk_weight=2.0,
        question_code="PRIV-001",
        section_code="privacy",
        question_order=2,
        is_visible=False,
    )

    await add_response(db_session, seeded_assessment["assessment_id"], visible_question, visible_option)
    await add_response(db_session, seeded_assessment["assessment_id"], invisible_question, invisible_option)

    result = await AssessmentRepository().load_active_triage_question_responses(
        db_session,
        seeded_assessment["assessment_id"],
    )

    assert result.required_triage_question_count == 1
    assert [item.question_code for item in result.question_responses] == ["SEC-001"]
    assert [item.question_id for item in result.question_responses] == [visible_question.id]


async def test_load_active_triage_question_responses_returns_empty_when_no_active_version(db_session):
    repository = AssessmentRepository()

    result = await repository.load_active_triage_question_responses(db_session, "missing-assessment-id")

    assert result.question_responses == []
    assert result.required_triage_question_count == 0
