from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.enums import RiskLevel
from tests.conftest import add_question_with_options, add_questionnaire_version, add_response

pytestmark = pytest.mark.asyncio


async def test_get_intake_overview_successful(client, db_session, seeded_assessment):
    intake_version = await add_questionnaire_version(
        db_session,
        questionnaire_type="intake",
        version="intake-v1",
    )
    intake_question, intake_options = await add_question_with_options(
        db_session,
        intake_version.id,
        risk_domain="Operations",
        question_code="GEN-001",
        section_code="general",
        prompt="What is the solution called?",
        options=[("Selected", RiskLevel.LOW, 0.0, "Low signal")],
    )
    triage_question, triage_options = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        question_code="TRIAGE-001",
        section_code="security_access",
        prompt="Does it handle sensitive data?",
        options=[("Yes", RiskLevel.HIGH, 3.0, "High signal")],
    )
    await add_response(db_session, seeded_assessment["assessment_id"], intake_question, intake_options[0])
    await add_response(db_session, seeded_assessment["assessment_id"], triage_question, triage_options[0])

    response = await client.get(f"/api/v1/assessments/{seeded_assessment['assessment_id']}/intake")

    assert response.status_code == 200
    assert response.json() == {
        "assessmentId": str(seeded_assessment["assessment_id"]),
        "header": {
            "technologyName": "Copilot",
            "sourceSystem": None,
            "questionnaireVersion": "intake-v1",
        },
        "sections": [
            {
                "code": "general",
                "title": "General",
                "questions": [
                    {
                        "questionId": str(intake_question.id),
                        "questionCode": "GEN-001",
                        "label": "What is the solution called?",
                        "answer": "Selected",
                        "responseType": "single_select",
                        "required": True,
                        "riskDomain": "Operations",
                    }
                ],
            }
        ],
        "triage": [
            {
                "questionId": str(triage_question.id),
                "questionCode": "TRIAGE-001",
                "label": "Does it handle sensitive data?",
                "answer": "Yes",
            }
        ],
    }


async def test_get_intake_overview_returns_404_for_missing_assessment(client):
    response = await client.get(f"/api/v1/assessments/{uuid4()}/intake")

    assert response.status_code == 404
    assert response.json() == {"detail": "Assessment not found."}


async def test_patch_question_response_successful(client, db_session, seeded_assessment):
    question, options = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        options=[("Selected", RiskLevel.HIGH, 3.0, "High signal")],
    )

    response = await client.patch(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/questions/{question.id}",
        json={"selectedOptionId": str(options[0].id), "answerValue": "Selected"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "questionId": str(question.id),
        "selectedOptionId": str(options[0].id),
        "answerValue": "Selected",
    }


async def test_patch_question_response_returns_404_for_invalid_question(client, seeded_assessment):
    response = await client.patch(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/questions/{uuid4()}",
        json={"answerValue": "Updated"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Question not found."}


async def test_patch_question_response_returns_404_for_hidden_question(client, db_session, seeded_assessment):
    question, _ = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        is_visible=False,
    )

    response = await client.patch(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/questions/{question.id}",
        json={"answerValue": "Updated"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Question is not visible."}


async def test_patch_question_response_returns_400_for_invalid_option(client, db_session, seeded_assessment):
    question, _ = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        options=[("Allowed", RiskLevel.HIGH, 3.0, "High signal")],
    )
    other_question, other_options = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Privacy",
        options=[("Wrong", RiskLevel.MEDIUM, 2.0, "Medium signal")],
    )
    del other_question

    response = await client.patch(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/questions/{question.id}",
        json={"selectedOptionId": str(other_options[0].id)},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Selected option is invalid for the question."}


async def test_patch_question_response_rejects_empty_body(client, db_session, seeded_assessment):
    question, _ = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
    )

    response = await client.patch(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/questions/{question.id}",
        json={},
    )

    assert response.status_code == 422
    assert "At least one of selectedOptionId or answerValue must be provided." in str(response.json())
