from __future__ import annotations

import os
from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, Table, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import get_session
from app.database import create_engine_from_url, get_db
from app.main import app
from app.models.database import AssessmentResponse, Base, SarAssessment
from app.models.enums import QuestionnaireType, RiskLevel
from tests.conftest import add_question_with_options, add_questionnaire_version

POSTGRES_URL = os.getenv("DATABASE_URL")
POSTGRES_SCHEMA = os.getenv("DATABASE_SCHEMA")


def _postgres_url_or_skip() -> str:
    if not POSTGRES_URL or not POSTGRES_URL.startswith("postgresql"):
        pytest.skip("PostgreSQL integration tests require a PostgreSQL DATABASE_URL.")
    return POSTGRES_URL


@pytest.fixture()
def postgres_session_factory() -> Generator[sessionmaker, None, None]:
    database_url = _postgres_url_or_skip()
    schema_name = f"codex_intake_{uuid4().hex[:12]}"
    admin_engine = create_engine(database_url, future=True)
    engine = create_engine_from_url(database_url, schema_name)

    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))

    Base.metadata.create_all(bind=engine)

    try:
        yield sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        admin_engine.dispose()


@pytest.fixture()
def postgres_db_session(postgres_session_factory: sessionmaker) -> Generator[Session, None, None]:
    session = postgres_session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def postgres_client(postgres_session_factory: sessionmaker) -> Generator[TestClient, None, None]:
    def override_get_session():
        session = postgres_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_db] = override_get_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture()
def postgres_seeded_assessment(postgres_db_session: Session) -> dict[str, str]:
    assessment = SarAssessment(
        id=str(uuid4()),
        technology_name="Copilot",
        vendor_name="Microsoft",
        product_name="Microsoft 365 Copilot",
    )
    triage_version = add_questionnaire_version(
        postgres_db_session,
        questionnaire_type=QuestionnaireType.TRIAGE.value,
        version="triage-v1",
        is_active=True,
    )
    postgres_db_session.add(assessment)
    postgres_db_session.commit()
    return {"assessment_id": assessment.id, "triage_version_id": triage_version.id}


def _seed_intake_and_triage_dataset(session: Session, assessment_id: str, triage_version_id: str) -> dict[str, object]:
    intake_version = add_questionnaire_version(
        session,
        questionnaire_type="intake",
        version="intake-v1",
        is_active=True,
    )

    section_counts = [
        ("general", 6),
        ("hosting_data", 6),
        ("solution", 6),
        ("operations", 6),
        ("security_access", 6),
        ("findings", 7),
    ]

    intake_questions = []
    for section_code, count in section_counts:
        for index in range(1, count + 1):
            question, options = add_question_with_options(
                session,
                intake_version.id,
                risk_domain="Operations",
                question_code=f"{section_code.upper()}-{index:03d}",
                section_code=section_code,
                question_order=index,
                prompt=f"{section_code} question {index}",
                options=[("No", RiskLevel.LOW, 0.0, "Low signal"), ("Yes", RiskLevel.HIGH, 3.0, "High signal")],
            )
            intake_questions.append((question, options))

    add_question_with_options(
        session,
        intake_version.id,
        risk_domain="Operations",
        question_code="HIDDEN-INTAKE-001",
        section_code="general",
        question_order=99,
        is_visible=False,
    )

    triage_questions = []
    for index in range(1, 9):
        question, options = add_question_with_options(
            session,
            triage_version_id,
            risk_domain="Security",
            question_code=f"TRIAGE-{index:03d}",
            section_code="security_access",
            question_order=index,
            prompt=f"triage question {index}",
            options=[("No", RiskLevel.LOW, 0.0, "Low signal"), ("Yes", RiskLevel.HIGH, 3.0, "High signal")],
        )
        triage_questions.append((question, options))

    add_question_with_options(
        session,
        triage_version_id,
        risk_domain="Security",
        question_code="TRIAGE-HIDDEN-001",
        section_code="security_access",
        question_order=99,
        is_visible=False,
    )

    first_intake_question, first_intake_options = intake_questions[0]
    session.add(
        AssessmentResponse(
            assessment_id=assessment_id,
            question_definition_id=first_intake_question.id,
            selected_option_id=first_intake_options[1].id,
            answer_value=None,
        )
    )

    first_triage_question, first_triage_options = triage_questions[0]
    session.add(
        AssessmentResponse(
            assessment_id=assessment_id,
            question_definition_id=first_triage_question.id,
            selected_option_id=first_triage_options[1].id,
            answer_value=None,
        )
    )
    session.commit()

    return {
        "intake_version_id": intake_version.id,
        "intake_questions": intake_questions,
        "triage_questions": triage_questions,
    }


def test_get_intake_returns_37_visible_intake_questions_8_visible_triage_questions_and_section_ordering(
    postgres_client,
    postgres_db_session,
    postgres_seeded_assessment,
):
    seeded = _seed_intake_and_triage_dataset(
        postgres_db_session,
        assessment_id=postgres_seeded_assessment["assessment_id"],
        triage_version_id=postgres_seeded_assessment["triage_version_id"],
    )

    response = postgres_client.get(f"/api/v1/assessments/{postgres_seeded_assessment['assessment_id']}/intake")

    assert response.status_code == 200
    payload = response.json()
    assert sum(len(section["questions"]) for section in payload["sections"]) == 37
    assert len(payload["triage"]) == 8
    assert [section["code"] for section in payload["sections"]] == [
        "general",
        "hosting_data",
        "solution",
        "operations",
        "security_access",
        "findings",
    ]
    assert payload["sections"][0]["questions"][0]["questionCode"] == seeded["intake_questions"][0][0].question_code
    assert payload["triage"][0]["questionCode"] == seeded["triage_questions"][0][0].question_code


def test_get_intake_resolves_selected_option_labels(postgres_client, postgres_db_session, postgres_seeded_assessment):
    _seed_intake_and_triage_dataset(
        postgres_db_session,
        assessment_id=postgres_seeded_assessment["assessment_id"],
        triage_version_id=postgres_seeded_assessment["triage_version_id"],
    )

    response = postgres_client.get(f"/api/v1/assessments/{postgres_seeded_assessment['assessment_id']}/intake")

    assert response.status_code == 200
    payload = response.json()
    assert payload["sections"][0]["questions"][0]["answer"] == "Yes"
    assert payload["triage"][0]["answer"] == "Yes"


def test_patch_create_update_and_explicit_null_clearing(postgres_client, postgres_db_session, postgres_seeded_assessment):
    question, options = add_question_with_options(
        postgres_db_session,
        postgres_seeded_assessment["triage_version_id"],
        risk_domain="Security",
        question_code="TRIAGE-NEW-001",
        section_code="security_access",
        question_order=10,
        options=[("No", RiskLevel.LOW, 0.0, "Low signal"), ("Yes", RiskLevel.HIGH, 3.0, "High signal")],
    )

    created = postgres_client.patch(
        f"/api/v1/assessments/{postgres_seeded_assessment['assessment_id']}/questions/{question.id}",
        json={"selectedOptionId": options[1].id, "answerValue": "Yes"},
    )
    assert created.status_code == 200
    assert created.json() == {
        "questionId": question.id,
        "selectedOptionId": options[1].id,
        "answerValue": "Yes",
    }

    updated = postgres_client.patch(
        f"/api/v1/assessments/{postgres_seeded_assessment['assessment_id']}/questions/{question.id}",
        json={"answerValue": "Updated"},
    )
    assert updated.status_code == 200
    assert updated.json() == {
        "questionId": question.id,
        "selectedOptionId": options[1].id,
        "answerValue": "Updated",
    }

    cleared = postgres_client.patch(
        f"/api/v1/assessments/{postgres_seeded_assessment['assessment_id']}/questions/{question.id}",
        json={"selectedOptionId": None, "answerValue": None},
    )
    assert cleared.status_code == 200
    assert cleared.json() == {
        "questionId": question.id,
        "selectedOptionId": None,
        "answerValue": None,
    }


def test_unique_response_constraint_is_enforced_in_postgres(postgres_db_session, postgres_seeded_assessment):
    question, options = add_question_with_options(
        postgres_db_session,
        postgres_seeded_assessment["triage_version_id"],
        risk_domain="Security",
        options=[("Selected", RiskLevel.HIGH, 3.0, "High signal")],
    )
    postgres_db_session.add(
        AssessmentResponse(
            assessment_id=postgres_seeded_assessment["assessment_id"],
            question_definition_id=question.id,
            selected_option_id=options[0].id,
        )
    )
    postgres_db_session.commit()

    postgres_db_session.add(
        AssessmentResponse(
            assessment_id=postgres_seeded_assessment["assessment_id"],
            question_definition_id=question.id,
            selected_option_id=options[0].id,
        )
    )

    with pytest.raises(IntegrityError):
        postgres_db_session.commit()

    postgres_db_session.rollback()


def test_real_configured_questionnaire_schema_matches_orm_contract() -> None:
    database_url = _postgres_url_or_skip()
    schema_name = POSTGRES_SCHEMA
    if not schema_name:
        pytest.skip("PostgreSQL integration tests require DATABASE_SCHEMA to inspect a configured schema.")
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        if "question_definitions" not in inspector.get_table_names(schema=schema_name):
            pytest.skip(f"Schema {schema_name} does not contain question_definitions.")
        if "assessment_responses" not in inspector.get_table_names(schema=schema_name):
            pytest.skip(f"Schema {schema_name} does not contain assessment_responses.")

        question_definition_columns = {
            column["name"]: column for column in inspector.get_columns("question_definitions", schema=schema_name)
        }
        assessment_response_columns = {
            column["name"]: column for column in inspector.get_columns("assessment_responses", schema=schema_name)
        }

        expected_question_definition = {
            "question_code": ("VARCHAR", 255, False),
            "section_code": ("VARCHAR", 64, True),
            "question_order": ("INTEGER", None, True),
            "risk_domain": ("VARCHAR", 128, False),
            "is_visible": ("BOOLEAN", None, False),
            "is_required": ("BOOLEAN", None, False),
        }
        for column_name, (type_name, length, nullable) in expected_question_definition.items():
            assert column_name in question_definition_columns
            reflected = question_definition_columns[column_name]
            assert reflected["type"].__class__.__name__.upper().startswith(type_name)
            if length is not None:
                assert getattr(reflected["type"], "length", None) == length
            assert reflected["nullable"] is nullable

        for column_name in ["assessment_id", "question_definition_id", "selected_option_id", "answer_value"]:
            assert column_name in assessment_response_columns

        unique_constraints = inspector.get_unique_constraints("assessment_responses", schema=schema_name)
        assert any(
            constraint["name"] == "uq_assessment_responses_assessment_question"
            and constraint["column_names"] == ["assessment_id", "question_definition_id"]
            for constraint in unique_constraints
        )
    finally:
        engine.dispose()
