from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.enums import RiskLevel
from app.repositories.assessment_repository import AssessmentRepository
from tests.conftest import add_question_with_option, add_questionnaire_version, add_response

pytestmark = pytest.mark.asyncio


async def test_load_intake_overview_orders_visible_intake_questions_by_section_then_question_order(
    db_session,
    seeded_assessment,
):
    intake_version = await add_questionnaire_version(
        db_session,
        questionnaire_type="intake",
        version="intake-v1",
    )
    await add_question_with_option(
        db_session,
        intake_version.id,
        risk_domain="Operations",
        risk_level=RiskLevel.LOW,
        risk_weight=0.0,
        question_code="B-002",
        section_code="beta",
        question_order=2,
        prompt="Beta question",
    )
    await add_question_with_option(
        db_session,
        intake_version.id,
        risk_domain="Operations",
        risk_level=RiskLevel.LOW,
        risk_weight=0.0,
        question_code="A-002",
        section_code="alpha",
        question_order=2,
        prompt="Alpha question two",
    )
    await add_question_with_option(
        db_session,
        intake_version.id,
        risk_domain="Operations",
        risk_level=RiskLevel.LOW,
        risk_weight=0.0,
        question_code="A-001",
        section_code="alpha",
        question_order=1,
        prompt="Alpha question one",
    )

    overview = await AssessmentRepository().load_intake_overview(db_session, seeded_assessment["assessment_id"])

    assert overview is not None
    assert overview.header.questionnaire_version == "intake-v1"
    assert [section.code for section in overview.sections] == ["alpha", "beta"]
    assert [question.question_code for question in overview.sections[0].questions] == ["A-001", "A-002"]
    assert [question.question_code for question in overview.sections[1].questions] == ["B-002"]


async def test_load_intake_overview_excludes_hidden_questions_from_intake_and_triage(
    db_session,
    seeded_assessment,
):
    intake_version = await add_questionnaire_version(
        db_session,
        questionnaire_type="intake",
        version="intake-v1",
    )
    await add_question_with_option(
        db_session,
        intake_version.id,
        risk_domain="Operations",
        risk_level=RiskLevel.LOW,
        risk_weight=0.0,
        question_code="INTAKE-VISIBLE",
        is_visible=True,
    )
    await add_question_with_option(
        db_session,
        intake_version.id,
        risk_domain="Operations",
        risk_level=RiskLevel.LOW,
        risk_weight=0.0,
        question_code="INTAKE-HIDDEN",
        is_visible=False,
    )
    await add_question_with_option(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        risk_level=RiskLevel.HIGH,
        risk_weight=3.0,
        question_code="TRIAGE-VISIBLE",
        is_visible=True,
    )
    await add_question_with_option(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        risk_level=RiskLevel.HIGH,
        risk_weight=3.0,
        question_code="TRIAGE-HIDDEN",
        is_visible=False,
    )

    overview = await AssessmentRepository().load_intake_overview(db_session, seeded_assessment["assessment_id"])

    assert overview is not None
    assert [question.question_code for section in overview.sections for question in section.questions] == [
        "INTAKE-VISIBLE"
    ]
    assert [question.question_code for question in overview.triage] == ["TRIAGE-VISIBLE"]


async def test_load_intake_overview_orders_visible_triage_questions_by_question_order(
    db_session,
    seeded_assessment,
):
    intake_version = await add_questionnaire_version(
        db_session,
        questionnaire_type="intake",
        version="intake-v1",
    )
    await add_question_with_option(
        db_session,
        intake_version.id,
        risk_domain="Operations",
        risk_level=RiskLevel.LOW,
        risk_weight=0.0,
        question_code="INTAKE-001",
    )
    await add_question_with_option(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        risk_level=RiskLevel.HIGH,
        risk_weight=3.0,
        question_code="TRIAGE-002",
        question_order=2,
    )
    await add_question_with_option(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        risk_level=RiskLevel.HIGH,
        risk_weight=3.0,
        question_code="TRIAGE-001",
        question_order=1,
    )

    overview = await AssessmentRepository().load_intake_overview(db_session, seeded_assessment["assessment_id"])

    assert overview is not None
    assert [question.question_code for question in overview.triage] == ["TRIAGE-001", "TRIAGE-002"]


async def test_load_intake_overview_joins_selected_option_label_into_answer(
    db_session,
    seeded_assessment,
):
    intake_version = await add_questionnaire_version(
        db_session,
        questionnaire_type="intake",
        version="intake-v1",
    )
    question, option = await add_question_with_option(
        db_session,
        intake_version.id,
        risk_domain="Operations",
        risk_level=RiskLevel.LOW,
        risk_weight=0.0,
        question_code="INTAKE-001",
        label="Selected option",
        prompt="Choose one",
    )
    await add_response(db_session, seeded_assessment["assessment_id"], question, option)

    overview = await AssessmentRepository().load_intake_overview(db_session, seeded_assessment["assessment_id"])

    assert overview is not None
    intake_question = overview.sections[0].questions[0]
    assert intake_question.answer == "Selected option"
    assert intake_question.response_type == "single_select"
    assert intake_question.selected_option_id == option.id


async def test_load_intake_overview_returns_none_when_assessment_is_missing(db_session):
    overview = await AssessmentRepository().load_intake_overview(db_session, str(uuid4()))

    assert overview is None
