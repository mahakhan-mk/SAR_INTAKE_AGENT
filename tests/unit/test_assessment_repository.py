from __future__ import annotations

import pytest

from app.models.enums import RiskLevel
from app.repositories.assessment_repository import AssessmentRepository
from tests.conftest import add_question_with_option, add_questionnaire_version, add_response

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


async def test_list_visible_assessment_responses_projects_selected_option_fields_and_reviewer_remarks(
    db_session,
    seeded_assessment,
):
    intake_version = await add_questionnaire_version(
        db_session,
        questionnaire_type="intake",
        version="intake-v1",
    )
    intake_question, intake_option = await add_question_with_option(
        db_session,
        intake_version.id,
        risk_domain="Operations",
        risk_level=RiskLevel.LOW,
        risk_weight=0.0,
        question_code="INTAKE-001",
        section_code="general",
        prompt="Describe the tool",
    )
    triage_question, _ = await add_question_with_option(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        risk_level=RiskLevel.HIGH,
        risk_weight=3.0,
        question_code="TRIAGE-001",
        section_code="security_access",
        prompt="Does it handle sensitive data?",
    )
    hidden_question, hidden_option = await add_question_with_option(
        db_session,
        intake_version.id,
        risk_domain="Operations",
        risk_level=RiskLevel.LOW,
        risk_weight=0.0,
        question_code="INTAKE-HIDDEN",
        is_visible=False,
    )
    selected_response = await add_response(db_session, seeded_assessment["assessment_id"], intake_question, intake_option)
    selected_response.reviewer_remarks = "Reviewed by analyst"
    await add_response(
        db_session,
        seeded_assessment["assessment_id"],
        triage_question,
        option=None,
        answer_value="Free text answer",
    )
    await add_response(db_session, seeded_assessment["assessment_id"], hidden_question, hidden_option)
    await db_session.commit()

    records = await AssessmentRepository().list_visible_assessment_responses(
        db_session,
        seeded_assessment["assessment_id"],
    )

    assert [record.question_code for record in records] == ["INTAKE-001", "TRIAGE-001"]
    assert records[0].questionnaire_type == "intake"
    assert records[0].answer_value == intake_option.option_label
    assert records[0].selected_option_id == intake_option.id
    assert records[0].selected_option_code == intake_option.option_code
    assert records[0].selected_option_label == intake_option.option_label
    assert records[0].reviewer_remarks == "Reviewed by analyst"
    assert records[1].questionnaire_type == "triage"
    assert records[1].answer_value == "Free text answer"
    assert records[1].selected_option_id is None
