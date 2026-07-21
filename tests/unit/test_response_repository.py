from __future__ import annotations

from sqlalchemy import select

from app.models.database import AssessmentResponse
from app.models.enums import RiskLevel
from app.repositories.response_repository import ResponseRepository
from tests.conftest import add_question_with_options


def test_upsert_response_creates_then_updates_single_assessment_response(db_session, seeded_assessment):
    question, options = add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        options=[
            ("First option", RiskLevel.HIGH, 3.0, "High signal"),
            ("Second option", RiskLevel.MEDIUM, 2.0, "Medium signal"),
        ],
    )
    first_option, second_option = options

    repository = ResponseRepository()

    created = repository.upsert_response(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        question_definition_id=question.id,
        selected_option_id=first_option.id,
        answer_value="Initial",
    )
    updated = repository.upsert_response(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        question_definition_id=question.id,
        selected_option_id=second_option.id,
        answer_value="Updated",
    )

    stored_responses = db_session.execute(
        select(AssessmentResponse).where(
            AssessmentResponse.assessment_id == seeded_assessment["assessment_id"],
            AssessmentResponse.question_definition_id == question.id,
        )
    ).scalars().all()

    assert created.id == updated.id
    assert len(stored_responses) == 1
    assert stored_responses[0].selected_option_id == second_option.id
    assert stored_responses[0].answer_value == "Updated"
