from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.errors import AssessmentNotFoundError
from app.assemblers.intake_assembler import IntakeAssembler
from app.models.database import AssessmentResponse
from app.models.dto import IntakeQuestionUpdateRequestDTO
from app.models.enums import RiskLevel
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.response_repository import ResponseRepository
from app.services.intake_service import (
    IntakeQuestionHiddenError,
    IntakeQuestionNotFoundError,
    IntakeQuestionOptionError,
    IntakeService,
)
from tests.conftest import add_question_with_options, add_questionnaire_version, add_response

pytestmark = pytest.mark.asyncio


def build_service(response_repository: ResponseRepository | None = None) -> IntakeService:
    return IntakeService(
        assessment_repository=AssessmentRepository(),
        response_repository=response_repository or ResponseRepository(),
        assembler=IntakeAssembler(),
    )


async def test_get_intake_overview_successful(db_session, seeded_assessment):
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

    dto = await build_service().get_intake_overview(db_session, seeded_assessment["assessment_id"])

    assert dto.assessmentId == seeded_assessment["assessment_id"]
    assert dto.header.technologyName == "Copilot"
    assert dto.header.sourceSystem is None
    assert dto.header.questionnaireVersion == "intake-v1"
    assert dto.sections[0].code == "general"
    assert dto.sections[0].title == "General"
    assert dto.sections[0].questions[0].questionId == intake_question.id
    assert dto.sections[0].questions[0].questionCode == "GEN-001"
    assert dto.sections[0].questions[0].answer == "Selected"
    assert dto.triage[0].questionId == triage_question.id
    assert dto.triage[0].questionCode == "TRIAGE-001"
    assert dto.triage[0].answer == "Yes"


async def test_get_intake_overview_raises_assessment_not_found(db_session):
    with pytest.raises(AssessmentNotFoundError):
        await build_service().get_intake_overview(db_session, str(uuid4()))


async def test_update_question_response_creates_then_updates_successfully(db_session, seeded_assessment):
    question, options = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        options=[
            ("First", RiskLevel.HIGH, 3.0, "High signal"),
            ("Second", RiskLevel.MEDIUM, 2.0, "Medium signal"),
        ],
    )
    service = build_service()

    created = await service.update_question_response(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        question_id=question.id,
        payload=IntakeQuestionUpdateRequestDTO(selectedOptionId=options[0].id, answerValue="Initial"),
    )

    assert created.questionId == question.id
    assert created.selectedOptionId == options[0].id
    assert created.answerValue == "First"
    assert created.reviewerRemarks is None

    updated = await service.update_question_response(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        question_id=question.id,
        payload=IntakeQuestionUpdateRequestDTO(answerValue="Updated"),
    )

    assert updated.questionId == question.id
    assert updated.selectedOptionId is None
    assert updated.answerValue == "Updated"
    assert updated.reviewerRemarks is None


async def test_update_question_response_updates_only_reviewer_remarks(db_session, seeded_assessment):
    question, options = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        options=[("Selected", RiskLevel.HIGH, 3.0, "High signal")],
    )
    existing_response = await add_response(
        db_session,
        seeded_assessment["assessment_id"],
        question,
        options[0],
    )
    existing_response.reviewer_remarks = "Initial remarks"
    await db_session.commit()
    service = build_service()

    updated = await service.update_question_response(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        question_id=question.id,
        payload=IntakeQuestionUpdateRequestDTO(reviewerRemarks="Updated remarks"),
    )

    assert updated.questionId == question.id
    assert updated.selectedOptionId == options[0].id
    assert updated.answerValue == "Selected"
    assert updated.reviewerRemarks == "Updated remarks"

    stored_response = await ResponseRepository().get_response(db_session, seeded_assessment["assessment_id"], question.id)
    assert stored_response is not None
    assert stored_response.selected_option_id == options[0].id
    assert stored_response.answer_value == "Selected"
    assert stored_response.reviewer_remarks == "Updated remarks"


async def test_update_question_response_updates_reviewer_remarks_with_answer(db_session, seeded_assessment):
    question, _ = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        response_type="text",
        options=[],
    )
    service = build_service()

    updated = await service.update_question_response(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        question_id=question.id,
        payload=IntakeQuestionUpdateRequestDTO(answerValue="Updated answer", reviewerRemarks="Reviewed"),
    )

    assert updated.questionId == question.id
    assert updated.selectedOptionId is None
    assert updated.answerValue == "Updated answer"
    assert updated.reviewerRemarks == "Reviewed"


async def test_update_question_response_rejects_invalid_question(db_session, seeded_assessment):
    service = build_service()

    with pytest.raises(IntakeQuestionNotFoundError):
        await service.update_question_response(
            db_session,
            assessment_id=seeded_assessment["assessment_id"],
            question_id=str(uuid4()),
            payload=IntakeQuestionUpdateRequestDTO(answerValue="Updated"),
        )


async def test_update_question_response_rejects_hidden_question(db_session, seeded_assessment):
    question, _ = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        is_visible=False,
    )
    service = build_service()

    with pytest.raises(IntakeQuestionHiddenError):
        await service.update_question_response(
            db_session,
            assessment_id=seeded_assessment["assessment_id"],
            question_id=question.id,
            payload=IntakeQuestionUpdateRequestDTO(answerValue="Updated"),
        )


async def test_update_question_response_rejects_invalid_option(db_session, seeded_assessment):
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
    service = build_service()

    with pytest.raises(IntakeQuestionOptionError):
        await service.update_question_response(
            db_session,
            assessment_id=seeded_assessment["assessment_id"],
            question_id=question.id,
            payload=IntakeQuestionUpdateRequestDTO(selectedOptionId=other_options[0].id),
        )


async def test_update_question_response_allows_explicit_null_clearing(db_session, seeded_assessment):
    question, options = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        options=[("Selected", RiskLevel.HIGH, 3.0, "High signal")],
    )
    await add_response(
        db_session,
        seeded_assessment["assessment_id"],
        question,
        options[0],
        answer_value="Existing",
    )
    service = build_service()

    updated = await service.update_question_response(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        question_id=question.id,
        payload=IntakeQuestionUpdateRequestDTO(selectedOptionId=None, answerValue=None),
    )

    assert updated.questionId == question.id
    assert updated.selectedOptionId is None
    assert updated.answerValue is None
    assert updated.reviewerRemarks is None


async def test_update_question_response_clears_reviewer_remarks(db_session, seeded_assessment):
    question, options = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        options=[("Selected", RiskLevel.HIGH, 3.0, "High signal")],
    )
    existing_response = await add_response(
        db_session,
        seeded_assessment["assessment_id"],
        question,
        options[0],
    )
    existing_response.reviewer_remarks = "Needs review"
    await db_session.commit()
    service = build_service()

    updated = await service.update_question_response(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        question_id=question.id,
        payload=IntakeQuestionUpdateRequestDTO(reviewerRemarks=None),
    )

    assert updated.questionId == question.id
    assert updated.selectedOptionId == options[0].id
    assert updated.answerValue == "Selected"
    assert updated.reviewerRemarks is None


async def test_update_question_response_rolls_back_on_failure(db_session, seeded_assessment, monkeypatch):
    question, options = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        options=[("Selected", RiskLevel.HIGH, 3.0, "High signal")],
    )

    class FailingResponseRepository(ResponseRepository):
        async def upsert_response(self, session, **kwargs):
            raise RuntimeError("Persistence failed.")

    rollback_calls = 0
    original_rollback = db_session.rollback

    async def rollback_spy():
        nonlocal rollback_calls
        rollback_calls += 1
        return await original_rollback()

    monkeypatch.setattr(db_session, "rollback", rollback_spy)
    service = build_service(response_repository=FailingResponseRepository())

    with pytest.raises(RuntimeError, match="Persistence failed."):
        await service.update_question_response(
            db_session,
            assessment_id=seeded_assessment["assessment_id"],
            question_id=question.id,
            payload=IntakeQuestionUpdateRequestDTO(selectedOptionId=options[0].id),
        )

    assert rollback_calls == 1
