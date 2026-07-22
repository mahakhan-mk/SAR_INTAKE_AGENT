from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

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


@pytest_asyncio.fixture()
async def session_factory(tmp_path) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_engine_from_url(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture()
async def db_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture()
async def seeded_assessment(db_session: AsyncSession) -> dict[str, uuid.UUID]:
    assessment = SarAssessment(
        id=uuid.uuid4(),
        technology_name="Copilot",
        vendor_name="Microsoft",
        product_name="Microsoft 365 Copilot",
    )
    version = QuestionnaireVersion(
        id=uuid.uuid4(),
        questionnaire_type=QuestionnaireType.TRIAGE.value,
        version="triage-v1",
        status="active",
    )
    db_session.add_all([assessment, version])
    await db_session.commit()
    return {"assessment_id": assessment.id, "questionnaire_version_id": version.id}


async def add_questionnaire_version(
    session: AsyncSession,
    *,
    questionnaire_type: str,
    version: str,
    is_active: bool = True,
) -> QuestionnaireVersion:
    questionnaire_version = QuestionnaireVersion(
        id=uuid4(),
        questionnaire_type=questionnaire_type,
        version=version,
        status="active" if is_active else "inactive",
    )
    session.add(questionnaire_version)
    await session.commit()
    return questionnaire_version


async def add_question_with_options(
    session: AsyncSession,
    questionnaire_version_id: uuid.UUID,
    *,
    risk_domain: str,
    question_text: str | None = None,
    why_it_matters: str = "Configuration-defined rationale.",
    is_visible: bool = True,
    is_required: bool = True,
    question_order: int | None = 1,
    response_type: str | None = None,
    options: list[tuple[str, RiskLevel, float, str]] | None = None,
) -> tuple[QuestionDefinition, list[QuestionOption]]:
    question = QuestionDefinition(
        id=uuid.uuid4(),
        questionnaire_version_id=questionnaire_version_id,
        question_code=f"question-{uuid.uuid4()}",
        question_text=question_text or f"{risk_domain} question",
        response_type=response_type or ("single_select" if options is None or options else "text"),
        risk_domain=risk_domain,
        is_required=is_required,
        section_code="triage",
        question_order=question_order,
        is_visible=is_visible,
    )
    question.why_it_matters = why_it_matters
    session.add(question)
    await session.flush()

    resolved_options = (
        [("Selected", RiskLevel.LOW, 0.0, "Configuration-defined signal.")]
        if options is None
        else options
    )
    option_models = [
        QuestionOption(
            id=uuid.uuid4(),
            question_id=question.id,
            option_code=f"option-{index}",
            option_label=label,
            risk_weight=risk_weight,
            display_order=index,
            risk_band=risk_level.value,
            why_it_matters=why_it_matters,
            risk_signal=risk_signal,
        )
        for index, (label, risk_level, risk_weight, risk_signal) in enumerate(resolved_options, start=1)
    ]
    session.add_all(option_models)
    await session.commit()
    return question, option_models


async def add_question_with_option(
    session: AsyncSession,
    questionnaire_version_id: uuid.UUID,
    *,
    risk_domain: str,
    risk_level: RiskLevel,
    risk_weight: float,
    question_text: str | None = None,
    label: str = "Selected",
    why_it_matters: str = "Configuration-defined rationale.",
    risk_signal: str = "Configuration-defined signal.",
    is_visible: bool = True,
    is_required: bool = True,
    question_order: int | None = 1,
) -> tuple[QuestionDefinition, QuestionOption]:
    question, options = await add_question_with_options(
        session,
        questionnaire_version_id,
        risk_domain=risk_domain,
        question_text=question_text,
        why_it_matters=why_it_matters,
        is_visible=is_visible,
        is_required=is_required,
        question_order=question_order,
        options=[(label, risk_level, risk_weight, risk_signal)],
    )
    return question, options[0]


async def add_response(
    session: AsyncSession,
    assessment_id: uuid.UUID,
    question: QuestionDefinition,
    option: QuestionOption | None = None,
    *,
    answer_value: dict[str, object] | None = None,
) -> AssessmentResponse:
    resolved_answer_value = answer_value
    if resolved_answer_value is None and option is not None:
        resolved_answer_value = option.option_label

    response = AssessmentResponse(
        id=uuid.uuid4(),
        assessment_id=assessment_id,
        question_id=question.id,
        answer_value=resolved_answer_value,
        response_status="answered",
    )
    response.selected_option_id = option.id if option else None
    session.add(response)
    await session.commit()
    return response


@pytest_asyncio.fixture()
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


@pytest_asyncio.fixture()
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_db] = override_get_session
    app.dependency_overrides[get_inherent_risk_scoring_policy] = PercentageInherentRiskScoringPolicy

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture()
async def seeded_completed_run(
    db_session: AsyncSession,
    seeded_assessment: dict[str, uuid.UUID],
) -> dict[str, uuid.UUID]:
    question, options = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Business Continuity",
        options=[
            ("Selected", RiskLevel.HIGH, 3.0, "High disruption exposure."),
            ("Maximum", RiskLevel.CRITICAL, 4.0, "Critical disruption exposure."),
        ],
    )
    selected_option = options[0]
    response = await add_response(db_session, seeded_assessment["assessment_id"], question, selected_option)
    generated_at = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    run = QuestionAnalysisRun(
        id=uuid.uuid4(),
        assessment_id=seeded_assessment["assessment_id"],
        status=AnalysisRunStatus.COMPLETED.value,
        scoring_rule_version="existing-config-v1",
        triage_score=3.0,
        inherent_score=75.0,
        inherent_risk_level=RiskLevel.HIGH.value,
        executive_summary_text="Stored summary.",
        executive_summary_model="gpt-5.5-test",
        executive_summary_prompt_version="v1",
        executive_summary_input_hash="hash-1",
        executive_summary_generated_at=generated_at,
    )
    db_session.add(run)
    await db_session.flush()
    db_session.add(
        QuestionRiskResult(
            id=uuid.uuid4(),
            analysis_run_id=run.id,
            response_id=response.id,
            risk_domain=question.risk_domain,
            risk_level=RiskLevel.HIGH.value,
            risk_score=selected_option.risk_weight,
            risk_impact=selected_option.why_it_matters,
            risk_signal=selected_option.risk_signal,
            explanation='Question "Business Continuity question" was answered with "Selected". This matters because Configuration-defined rationale. The selected response indicates High disruption exposure..',
            confidence=1.0,
            input_snapshot={
                "questionCode": question.question_code,
                "questionId": str(question.id),
                "questionText": question.question_text,
                "selectedOptionId": str(selected_option.id),
                "selectedOptionCode": selected_option.option_code,
                "selectedOptionLabel": selected_option.option_label,
                "selectedResponse": selected_option.option_label,
                "riskWeight": selected_option.risk_weight,
                "maxRiskWeight": max(option.risk_weight for option in options if option.risk_weight is not None),
                "whyItMatters": selected_option.why_it_matters,
                "riskSignal": selected_option.risk_signal,
                "riskBand": RiskLevel.HIGH.value,
                "scoringRuleVersion": "existing-config-v1",
            },
        )
    )
    await db_session.commit()
    return {"assessment_id": seeded_assessment["assessment_id"], "run_id": run.id}
