from __future__ import annotations

import pytest
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, Uuid, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError

from app.config import DATABASE_SCHEMA_TOKEN
from app.models.database import AssessmentResponse, QuestionAnalysisRun, QuestionDefinition, QuestionRiskResult
from app.models.enums import RiskLevel
from tests.conftest import add_question_with_option, add_response

@pytest.mark.asyncio
async def test_question_definition_columns_match_questionnaire_schema(db_session, seeded_assessment):
    question, _ = await add_question_with_option(
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

    async_connection = await db_session.connection()

    def inspect_columns(sync_connection):
        return {
            column["name"]: column
            for column in inspect(sync_connection).get_columns("question_definitions")
        }

    columns = await async_connection.run_sync(inspect_columns)

    assert isinstance(QuestionDefinition.__table__.c.questionnaire_version_id.type, Uuid)
    assert isinstance(columns["question_code"]["type"], Text)
    assert columns["question_code"]["nullable"] is False
    assert "question_text" in columns
    assert "response_type" in columns
    assert isinstance(columns["section_code"]["type"], Text)
    assert columns["section_code"]["nullable"] is True
    assert isinstance(columns["question_order"]["type"], Integer)
    assert columns["question_order"]["nullable"] is True
    assert isinstance(columns["risk_domain"]["type"], Text)
    assert columns["risk_domain"]["nullable"] is True
    assert isinstance(columns["is_visible"]["type"], Boolean)
    assert columns["is_visible"]["nullable"] is False
    assert isinstance(columns["is_required"]["type"], Boolean)
    assert columns["is_required"]["nullable"] is False


@pytest.mark.asyncio
async def test_question_definition_allows_null_section_code_and_question_order(db_session, seeded_assessment):
    question, _ = await add_question_with_option(
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


@pytest.mark.asyncio
async def test_assessment_responses_enforce_one_row_per_assessment_question(db_session, seeded_assessment):
    question, option = await add_question_with_option(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        risk_level=RiskLevel.HIGH,
        risk_weight=3.0,
    )
    await add_response(db_session, seeded_assessment["assessment_id"], question, option)

    duplicate = AssessmentResponse(
        assessment_id=seeded_assessment["assessment_id"],
        question_definition_id=question.id,
        answer_value=option.label,
    )
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()

    async_connection = await db_session.connection()

    def inspect_unique_constraints(sync_connection):
        return inspect(sync_connection).get_unique_constraints("assessment_responses")

    unique_constraints = await async_connection.run_sync(inspect_unique_constraints)
    assert any(
        constraint["name"] == "uq_assessment_responses_assessment_question"
        and constraint["column_names"] == ["assessment_id", "question_id"]
        for constraint in unique_constraints
    )


def test_question_analysis_run_mapping_matches_shared_analysis_run_table():
    table = QuestionAnalysisRun.__table__
    foreign_keys = {fk.parent.name: fk.target_fullname for fk in table.foreign_keys}

    assert table.name == "question_analysis_runs"
    assert table.schema == DATABASE_SCHEMA_TOKEN
    assert list(table.primary_key.columns.keys()) == ["id"]
    assert foreign_keys == {"assessment_id": "sar_assessments.id"}

    uuid_columns = ["id", "assessment_id"]
    for column_name in uuid_columns:
        assert isinstance(table.c[column_name].type, Uuid)

    assert isinstance(table.c.status.type, String)
    assert table.c.status.nullable is False
    assert isinstance(table.c.scoring_config_version.type, String)
    assert table.c.scoring_config_version.nullable is False
    assert isinstance(table.c.triage_score.type, Float)
    assert table.c.triage_score.nullable is True
    assert isinstance(table.c.inherent_score.type, Float)
    assert table.c.inherent_score.nullable is True
    assert isinstance(table.c.inherent_risk_level.type, String)
    assert table.c.inherent_risk_level.nullable is True
    assert isinstance(table.c.overall_risk_level.type, String)
    assert table.c.overall_risk_level.nullable is True
    assert isinstance(table.c.executive_summary.type, Text)
    assert table.c.executive_summary.nullable is True
    assert isinstance(table.c.executive_summary_model.type, Text)
    assert table.c.executive_summary_model.nullable is True
    assert isinstance(table.c.executive_summary_prompt_version.type, Text)
    assert table.c.executive_summary_prompt_version.nullable is True
    assert isinstance(table.c.executive_summary_input_hash.type, Text)
    assert table.c.executive_summary_input_hash.nullable is True
    assert isinstance(table.c.executive_summary_generated_at.type, DateTime)
    assert table.c.executive_summary_generated_at.nullable is True
    assert isinstance(table.c.source_text.type, Text)
    assert table.c.source_text.nullable is False
    assert isinstance(table.c.failure_reason.type, Text)
    assert table.c.failure_reason.nullable is True
    assert isinstance(table.c.limitation_summary.type, Text)
    assert table.c.limitation_summary.nullable is True
    assert isinstance(table.c.created_at.type, DateTime)
    assert table.c.created_at.nullable is False


def test_question_risk_result_mapping_matches_shared_analysis_result_table():
    table = QuestionRiskResult.__table__
    foreign_keys = {fk.parent.name: fk.target_fullname for fk in table.foreign_keys}
    jsonb_type = table.c.input_snapshot.type.dialect_impl(postgresql.dialect())

    assert table.name == "question_risk_results"
    assert table.schema == DATABASE_SCHEMA_TOKEN
    assert list(table.primary_key.columns.keys()) == ["id"]
    assert foreign_keys == {
        "analysis_run_id": "question_analysis_runs.id",
        "question_definition_id": "question_definitions.id",
        "response_id": "assessment_responses.id",
    }

    uuid_columns = ["id", "analysis_run_id", "response_id", "question_definition_id", "selected_option_id"]
    for column_name in uuid_columns:
        assert isinstance(table.c[column_name].type, Uuid)

    assert table.c.analysis_run_id.nullable is False
    assert table.c.response_id.nullable is False
    assert table.c.question_definition_id.nullable is False
    assert table.c.selected_option_id.nullable is True
    assert isinstance(table.c.question_text.type, Text)
    assert table.c.question_text.nullable is False
    assert isinstance(table.c.risk_domain.type, String)
    assert table.c.risk_domain.nullable is False
    assert isinstance(table.c.risk_level.type, String)
    assert table.c.risk_level.nullable is False
    assert isinstance(table.c.risk_weight.type, Float)
    assert table.c.risk_weight.nullable is False
    assert isinstance(table.c.why_it_matters.type, Text)
    assert table.c.why_it_matters.nullable is False
    assert isinstance(table.c.risk_signal.type, Text)
    assert table.c.risk_signal.nullable is False
    assert isinstance(table.c.ai_explanation.type, Text)
    assert table.c.ai_explanation.nullable is True
    assert isinstance(table.c.ai_confidence.type, Float)
    assert table.c.ai_confidence.nullable is True
    assert table.c.input_snapshot.nullable is True
    assert isinstance(jsonb_type, JSONB)
    assert isinstance(table.c.created_at.type, DateTime)
    assert table.c.created_at.nullable is False
