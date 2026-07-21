from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import get_inherent_risk_scoring_policy, get_session
from app.config import PercentageInherentRiskScoringPolicy
from app.database import create_engine_from_url, get_db
from app.main import app
from app.models.database import (
    AssessmentResponse,
    Base,
    QuestionAnalysisRun,
    QuestionDefinition,
    QuestionOption,
    QuestionnaireVersion,
    QuestionRiskResult,
    SarAssessment,
)
from app.models.enums import AnalysisRunStatus, QuestionnaireType, RiskLevel


@pytest.fixture()
def session_factory(tmp_path) -> sessionmaker:
    engine = create_engine_from_url(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@pytest.fixture()
def db_session(session_factory: sessionmaker) -> Generator[Session, None, None]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def seeded_assessment(db_session: Session) -> dict[str, str]:
    assessment = SarAssessment(
        id=str(uuid4()),
        technology_name="Copilot",
        vendor_name="Microsoft",
        product_name="Microsoft 365 Copilot",
    )
    version = QuestionnaireVersion(
        id=str(uuid4()),
        questionnaire_type=QuestionnaireType.TRIAGE.value,
        version="triage-v1",
        is_active=True,
    )
    db_session.add_all([assessment, version])
    db_session.commit()
    return {"assessment_id": assessment.id, "questionnaire_version_id": version.id}


def add_questionnaire_version(
    session: Session,
    *,
    questionnaire_type: str,
    version: str,
    is_active: bool = True,
) -> QuestionnaireVersion:
    questionnaire_version = QuestionnaireVersion(
        id=str(uuid4()),
        questionnaire_type=questionnaire_type,
        version=version,
        is_active=is_active,
    )
    session.add(questionnaire_version)
    session.commit()
    return questionnaire_version


def add_question_with_options(
    session: Session,
    questionnaire_version_id: str,
    *,
    risk_domain: str,
    question_code: str | None = None,
    section_code: str | None = "general",
    prompt: str | None = None,
    why_it_matters: str = "Configuration-defined rationale.",
    is_visible: bool = True,
    is_required: bool = True,
    question_order: int | None = 1,
    options: list[tuple[str, RiskLevel, float, str]] | None = None,
) -> tuple[QuestionDefinition, list[QuestionOption]]:
    question = QuestionDefinition(
        id=str(uuid4()),
        questionnaire_version_id=questionnaire_version_id,
        question_code=question_code or f"Q-{uuid4().hex[:8]}",
        section_code=section_code,
        prompt=prompt or f"{risk_domain} question",
        why_it_matters=why_it_matters,
        risk_domain=risk_domain,
        is_visible=is_visible,
        is_required=is_required,
        question_order=question_order,
    )
    session.add(question)
    session.flush()

    resolved_options = options or [("Selected", RiskLevel.LOW, 0.0, "Configuration-defined signal.")]
    option_models = [
        QuestionOption(
            id=str(uuid4()),
            question_definition_id=question.id,
            label=label,
            risk_weight=risk_weight,
            display_order=index,
            risk_band=risk_level.value,
            risk_signal=risk_signal,
        )
        for index, (label, risk_level, risk_weight, risk_signal) in enumerate(resolved_options, start=1)
    ]
    session.add_all(option_models)
    session.commit()
    return question, option_models


def add_question_with_option(
    session: Session,
    questionnaire_version_id: str,
    *,
    risk_domain: str,
    risk_level: RiskLevel,
    risk_weight: float,
    question_code: str | None = None,
    section_code: str | None = "general",
    prompt: str | None = None,
    label: str = "Selected",
    why_it_matters: str = "Configuration-defined rationale.",
    risk_signal: str = "Configuration-defined signal.",
    is_visible: bool = True,
    is_required: bool = True,
    question_order: int | None = 1,
) -> tuple[QuestionDefinition, QuestionOption]:
    question, options = add_question_with_options(
        session,
        questionnaire_version_id,
        risk_domain=risk_domain,
        question_code=question_code,
        section_code=section_code,
        prompt=prompt,
        why_it_matters=why_it_matters,
        is_visible=is_visible,
        is_required=is_required,
        question_order=question_order,
        options=[(label, risk_level, risk_weight, risk_signal)],
    )
    return question, options[0]


def add_response(
    session: Session,
    assessment_id: str,
    question: QuestionDefinition,
    option: QuestionOption | None = None,
    *,
    answer_value: str | None = None,
) -> AssessmentResponse:
    response = AssessmentResponse(
        id=str(uuid4()),
        assessment_id=assessment_id,
        question_definition_id=question.id,
        selected_option_id=option.id if option else None,
        answer_value=answer_value,
    )
    session.add(response)
    session.commit()
    return response


@pytest.fixture()
def executive_summary_prompt_path(tmp_path: Path) -> Path:
    prompt_path = tmp_path / "executive_summary.yaml"
    prompt_path.write_text(
        "\n".join(
            [
                "id: executive-summary",
                "version: v1",
                "system: You explain the provided deterministic risk assessment.",
                'user_template: "Summarize this deterministic SAR assessment input as JSON only:\\n{input_json}"',
            ]
        ),
        encoding="utf-8",
    )
    return prompt_path


@pytest.fixture()
def client(session_factory: sessionmaker) -> Generator[TestClient, None, None]:
    def override_get_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_db] = override_get_session
    app.dependency_overrides[get_inherent_risk_scoring_policy] = PercentageInherentRiskScoringPolicy

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture()
def seeded_completed_run(db_session: Session, seeded_assessment: dict[str, str]) -> dict[str, str]:
    question, options = add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Business Continuity",
        options=[
            ("Selected", RiskLevel.HIGH, 3.0, "High disruption exposure."),
            ("Maximum", RiskLevel.CRITICAL, 4.0, "Critical disruption exposure."),
        ],
    )
    selected_option = options[0]
    response = add_response(db_session, seeded_assessment["assessment_id"], question, selected_option)
    generated_at = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    run = QuestionAnalysisRun(
        id=str(uuid4()),
        assessment_id=seeded_assessment["assessment_id"],
        status=AnalysisRunStatus.COMPLETED.value,
        scoring_config_version="existing-config-v1",
        triage_score=3.0,
        inherent_score=75.0,
        inherent_risk_level=RiskLevel.HIGH.value,
        overall_risk_level=RiskLevel.HIGH.value,
        executive_summary_text="Stored summary.",
        executive_summary_model="gpt-5.5-test",
        executive_summary_prompt_version="v1",
        executive_summary_input_hash="hash-1",
        executive_summary_generated_at=generated_at,
        source_text="Derived from SAR triage questions.",
    )
    db_session.add(run)
    db_session.flush()
    db_session.add(
        QuestionRiskResult(
            id=str(uuid4()),
            analysis_run_id=run.id,
            response_id=response.id,
            question_definition_id=question.id,
            selected_option_id=selected_option.id,
            question_text=question.prompt,
            risk_domain=question.risk_domain,
            risk_level=RiskLevel.HIGH.value,
            risk_weight=selected_option.risk_weight,
            why_it_matters=question.why_it_matters,
            risk_signal=selected_option.risk_signal,
            ai_explanation='Question "Business Continuity question" was answered with "Selected". This matters because Configuration-defined rationale. The selected response indicates High disruption exposure..',
            ai_confidence=1.0,
            input_snapshot='{"questionCode":"' + question.question_code + '","selectedResponse":"Selected","riskBand":"high","scoringRuleVersion":"existing-config-v1"}',
        )
    )
    db_session.commit()
    return {"assessment_id": seeded_assessment["assessment_id"], "run_id": run.id}
