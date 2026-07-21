from __future__ import annotations

import pytest
from sqlalchemy import Boolean, Integer, String, inspect
from sqlalchemy.exc import IntegrityError

from app.models.database import AssessmentResponse
from app.models.enums import RiskLevel
from tests.conftest import add_question_with_option, add_response


def test_question_definition_columns_match_questionnaire_schema(db_session, seeded_assessment):
    question, _ = add_question_with_option(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        risk_level=RiskLevel.HIGH,
        risk_weight=3.0,
        question_code="SEC-001",
        section_code="general",
        is_visible=True,
        is_required=True,
        question_order=7,
    )

    assert question.question_code == "SEC-001"
    assert question.section_code == "general"
    assert question.question_order == 7
    assert question.is_visible is True
    assert question.is_required is True

    columns = {column["name"]: column for column in inspect(db_session.get_bind()).get_columns("question_definitions")}

    assert isinstance(columns["question_code"]["type"], String)
    assert columns["question_code"]["type"].length == 255
    assert columns["question_code"]["nullable"] is False
    assert isinstance(columns["section_code"]["type"], String)
    assert columns["section_code"]["type"].length == 64
    assert columns["section_code"]["nullable"] is True
    assert isinstance(columns["question_order"]["type"], Integer)
    assert columns["question_order"]["nullable"] is True
    assert isinstance(columns["risk_domain"]["type"], String)
    assert columns["risk_domain"]["type"].length == 128
    assert columns["risk_domain"]["nullable"] is False
    assert isinstance(columns["is_visible"]["type"], Boolean)
    assert columns["is_visible"]["nullable"] is False
    assert isinstance(columns["is_required"]["type"], Boolean)
    assert columns["is_required"]["nullable"] is False


def test_question_definition_allows_null_section_code_and_question_order(db_session, seeded_assessment):
    question, _ = add_question_with_option(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        risk_level=RiskLevel.HIGH,
        risk_weight=3.0,
        question_code="SEC-002-LONG-CODE-SUPPORT",
        section_code=None,
        question_order=None,
        is_visible=True,
        is_required=False,
    )

    assert question.section_code is None
    assert question.question_order is None


def test_assessment_responses_enforce_one_row_per_assessment_question(db_session, seeded_assessment):
    question, option = add_question_with_option(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        risk_level=RiskLevel.HIGH,
        risk_weight=3.0,
    )
    add_response(db_session, seeded_assessment["assessment_id"], question, option)

    duplicate = AssessmentResponse(
        assessment_id=seeded_assessment["assessment_id"],
        question_definition_id=question.id,
        selected_option_id=option.id,
    )
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()

    unique_constraints = inspect(db_session.get_bind()).get_unique_constraints("assessment_responses")
    assert any(
        constraint["name"] == "uq_assessment_responses_assessment_question"
        and constraint["column_names"] == ["assessment_id", "question_definition_id"]
        for constraint in unique_constraints
    )
