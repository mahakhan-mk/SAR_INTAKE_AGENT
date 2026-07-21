from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.dependencies import get_inherent_risk_scoring_policy, get_session
from app.config import PercentageInherentRiskScoringPolicy
from app.database import create_engine_from_url
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
async def seeded_assessment(db_session: AsyncSession) -> dict[str, str]:
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
    await db_session.commit()
    return {"assessment_id": assessment.id, "questionnaire_version_id": version.id}


async def add_question_with_options(
    session: AsyncSession,
    questionnaire_version_id: str,
    *,
    risk_domain: str,
    prompt: str | None = None,
    why_it_matters: str = "Configuration-defined rationale.",
    is_required: bool = True,
    options: list[tuple[str, RiskLevel, float, str]] | None = None,
) -> tuple[QuestionDefinition, list[QuestionOption]]:
    question = QuestionDefinition(
        id=str(uuid4()),
        questionnaire_version_id=questionnaire_version_id,
        prompt=prompt or f"{risk_domain} question",
        why_it_matters=why_it_matters,
        risk_domain=risk_domain,
        is_required=is_required,
        display_order=1,
    )
    session.add(question)
    await session.flush()

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
    await session.commit()
    return question, option_models


async def add_question_with_option(
    session: AsyncSession,
    questionnaire_version_id: str,
    *,
    risk_domain: str,
    risk_level: RiskLevel,
    risk_weight: float,
    prompt: str | None = None,
    label: str = "Selected",
    why_it_matters: str = "Configuration-defined rationale.",
    risk_signal: str = "Configuration-defined signal.",
    is_required: bool = True,
) -> tuple[QuestionDefinition, QuestionOption]:
    question, options = await add_question_with_options(
        session,
        questionnaire_version_id,
        risk_domain=risk_domain,
        prompt=prompt,
        why_it_matters=why_it_matters,
        is_required=is_required,
        options=[(label, risk_level, risk_weight, risk_signal)],
    )
    return question, options[0]


async def add_response(
    session: AsyncSession,
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
    app.dependency_overrides[get_inherent_risk_scoring_policy] = PercentageInherentRiskScoringPolicy

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture()
async def seeded_completed_run(db_session: AsyncSession, seeded_assessment: dict[str, str]) -> dict[str, str]:
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
    await db_session.flush()
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
            input_snapshot='{"questionCode":"' + question.id + '","selectedResponse":"Selected","riskBand":"high","scoringRuleVersion":"existing-config-v1"}',
        )
    )
    await db_session.commit()
    return {"assessment_id": seeded_assessment["assessment_id"], "run_id": run.id}
