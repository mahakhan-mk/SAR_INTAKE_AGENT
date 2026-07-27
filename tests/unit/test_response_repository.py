from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.database import AssessmentResponse
from app.models.enums import RiskLevel
from app.repositories.response_repository import ResponseRepository
from tests.conftest import add_question_with_options

pytestmark = pytest.mark.asyncio


async def test_upsert_response_creates_then_updates_single_assessment_response(db_session, seeded_assessment):
    question, options = await add_question_with_options(
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

    created = await repository.upsert_response(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        question_id=question.id,
        answer_value={
            "optionCode": first_option.option_code,
            "optionLabel": first_option.option_label,
            "selectedOptionId": str(first_option.id),
        },
    )
    updated = await repository.upsert_response(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        question_id=question.id,
        answer_value={
            "optionCode": second_option.option_code,
            "optionLabel": second_option.option_label,
            "selectedOptionId": str(second_option.id),
        },
    )

    stored_responses = (
        await db_session.execute(
            select(AssessmentResponse).where(
                AssessmentResponse.assessment_id == seeded_assessment["assessment_id"],
                AssessmentResponse.question_id == question.id,
            )
        )
    ).scalars().all()

    assert created.id == updated.id
    assert len(stored_responses) == 1
    assert not hasattr(stored_responses[0], "selected_option_id")
    assert stored_responses[0].answer_value == {
        "optionCode": second_option.option_code,
        "optionLabel": second_option.option_label,
        "selectedOptionId": str(second_option.id),
    }
