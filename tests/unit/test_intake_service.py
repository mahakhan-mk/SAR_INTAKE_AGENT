from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.assemblers.intake_assembler import IntakeAssembler
from app.application.models import IntakeQuestionUpdateCommand
from app.domain.errors import (
    AssessmentNotFoundError,
    IntakeQuestionHiddenError,
    IntakeQuestionNotFoundError,
    IntakeQuestionOptionError,
)
from app.models.database import AssessmentResponse
from app.models.enums import RiskLevel
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.response_repository import ResponseRepository
from app.services.intake_service import IntakeService
from tests.conftest import add_question_with_options, add_questionnaire_version, add_response

pytestmark = pytest.mark.asyncio


def build_service(response_repository: ResponseRepository | None = None) -> IntakeService:
    return IntakeService(
        assessment_repository=AssessmentRepository(),
        response_repository=response_repository or ResponseRepository(),
        assembler=IntakeAssembler(),
    )


def update_command(**kwargs) -> IntakeQuestionUpdateCommand:
    return IntakeQuestionUpdateCommand(
        selected_option_id=kwargs.get("selectedOptionId"),
        answer_value=kwargs.get("answerValue"),
        fields_set=frozenset(kwargs),
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
        payload=update_command(selectedOptionId=options[0].id, answerValue="Initial"),
    )

    assert created.questionId == question.id
    assert created.selectedOptionId == options[0].id
    assert created.answerValue == "First"
    stored_created = await db_session.scalar(select(AssessmentResponse))
    assert stored_created is not None
    assert stored_created.answer_value == {
        "optionCode": options[0].option_code,
        "optionLabel": options[0].option_label,
        "selectedOptionId": str(options[0].id),
    }
    assert not hasattr(stored_created, "selected_option_id")

    updated = await service.update_question_response(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        question_id=question.id,
        payload=update_command(answerValue="Updated"),
    )

    assert updated.questionId == question.id
    assert updated.selectedOptionId is None
    assert updated.answerValue == "Updated"
    db_session.expire_all()
    reloaded = await db_session.scalar(select(AssessmentResponse))
    assert reloaded is not None
    assert reloaded.answer_value == "Updated"
    assert not hasattr(reloaded, "selected_option_id")


async def test_update_question_response_rejects_invalid_question(db_session, seeded_assessment):
    service = build_service()

    with pytest.raises(IntakeQuestionNotFoundError):
        await service.update_question_response(
            db_session,
            assessment_id=seeded_assessment["assessment_id"],
            question_id=str(uuid4()),
            payload=update_command(answerValue="Updated"),
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
            payload=update_command(answerValue="Updated"),
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
            payload=update_command(selectedOptionId=other_options[0].id),
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
        payload=update_command(selectedOptionId=None, answerValue=None),
    )

    assert updated.questionId == question.id
    assert updated.selectedOptionId is None
    assert updated.answerValue is None
    stored = await db_session.scalar(select(AssessmentResponse))
    assert stored is not None
    assert stored.answer_value is None


async def test_update_question_response_selected_option_id_survives_database_reload(db_session, seeded_assessment):
    question, options = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        options=[("Selected", RiskLevel.HIGH, 3.0, "High signal")],
    )

    service = build_service()

    await service.update_question_response(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        question_id=question.id,
        payload=update_command(selectedOptionId=options[0].id),
    )

    expected_option_code = options[0].option_code
    expected_option_label = options[0].option_label
    expected_option_id = options[0].id
    db_session.expire_all()
    reloaded = await db_session.scalar(select(AssessmentResponse))
    assert reloaded is not None
    assert reloaded.answer_value == {
        "optionCode": expected_option_code,
        "optionLabel": expected_option_label,
        "selectedOptionId": str(expected_option_id),
    }
    assert build_service()._extract_selected_option_id(
        reloaded.answer_value,
        AssessmentRepository().normalize_answer_value(reloaded.answer_value),
    ) == expected_option_id


async def test_update_question_response_service_does_not_manage_transaction_on_failure(
    db_session,
    seeded_assessment,
    monkeypatch,
):
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
    commit_calls = 0
    original_commit = db_session.commit
    original_rollback = db_session.rollback

    async def commit_spy():
        nonlocal commit_calls
        commit_calls += 1
        return await original_commit()

    async def rollback_spy():
        nonlocal rollback_calls
        rollback_calls += 1
        return await original_rollback()

    monkeypatch.setattr(db_session, "commit", commit_spy)
    monkeypatch.setattr(db_session, "rollback", rollback_spy)
    service = build_service(response_repository=FailingResponseRepository())

    with pytest.raises(RuntimeError, match="Persistence failed."):
        await service.update_question_response(
            db_session,
            assessment_id=seeded_assessment["assessment_id"],
            question_id=question.id,
            payload=update_command(selectedOptionId=options[0].id),
        )

    assert rollback_calls == 0
    assert commit_calls == 0
