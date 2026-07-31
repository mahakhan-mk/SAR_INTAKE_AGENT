from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import DATABASE_SCHEMA_TOKEN, DEFAULT_INHERENT_RISK_SCORING_POLICY
from app.models.database import (
    AssessmentResponse,
    Base,
    QuestionAnalysisRun,
    QuestionDefinition,
    QuestionOption,
    QuestionRiskResult,
    QuestionnaireVersion,
    SarAssessment,
)
from app.models.enums import AnalysisRunStatus, RiskLevel
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.assessment_repository import AssessmentRepository
from app.services.inherent_risk_service import InherentRiskExecutionService


@pytest_asyncio.fixture
async def session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        execution_options={"schema_translate_map": {DATABASE_SCHEMA_TOKEN: None}},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


def _question(
    version_id,
    *,
    code: str,
    order: int,
    weight: int | None,
    why_it_matters: str | None = None,
    visible: bool = True,
) -> QuestionDefinition:
    return QuestionDefinition(
        id=uuid4(),
        questionnaire_version_id=version_id,
        question_code=code,
        question_text=f"{code}?",
        response_type="single_select",
        is_required=True,
        section_code="triage",
        question_order=order,
        risk_domain="Domain",
        is_visible=visible,
        question_weight=weight,
        why_it_matters=why_it_matters,
    )


def _option(question_id, *, code: str, order: int, weight: int, band: RiskLevel) -> QuestionOption:
    return QuestionOption(
        id=uuid4(),
        question_id=question_id,
        option_code=code,
        option_label=code.title(),
        risk_weight=weight,
        display_order=order,
        risk_band=band.value,
        risk_signal=f"{code} signal",
    )


async def _seed_weighted_questions(session: AsyncSession):
    assessment = SarAssessment(id=uuid4(), technology_name="Weighted App")
    triage_version = QuestionnaireVersion(
        id=uuid4(),
        questionnaire_type="triage",
        version="1",
        status="active",
    )
    intake_version = QuestionnaireVersion(
        id=uuid4(),
        questionnaire_type="intake",
        version="1",
        status="active",
    )
    q_weight_5 = _question(
        triage_version.id,
        code="weight_5",
        order=1,
        weight=5,
        why_it_matters="Question-level reason.",
    )
    q_weight_2 = _question(triage_version.id, code="weight_2", order=2, weight=2)
    q_hidden = _question(triage_version.id, code="hidden_weighted", order=3, weight=1, visible=False)
    intake_question = _question(intake_version.id, code="intake_ignored", order=1, weight=5)
    session.add_all([assessment, triage_version, intake_version, q_weight_5, q_weight_2, q_hidden, intake_question])

    selected_5 = _option(q_weight_5.id, code="five", order=1, weight=5, band=RiskLevel.MEDIUM)
    max_10 = _option(q_weight_5.id, code="ten", order=2, weight=10, band=RiskLevel.HIGH)
    selected_3 = _option(q_weight_2.id, code="three", order=1, weight=3, band=RiskLevel.LOW)
    hidden_10 = _option(q_hidden.id, code="hidden_ten", order=1, weight=10, band=RiskLevel.HIGH)
    intake_10 = _option(intake_question.id, code="intake_ten", order=1, weight=10, band=RiskLevel.HIGH)
    session.add_all([selected_5, max_10, selected_3, hidden_10, intake_10])

    responses = [
        AssessmentResponse(
            id=uuid4(),
            assessment_id=assessment.id,
            question_id=q_weight_5.id,
            answer_value={"optionCode": selected_5.option_code},
            response_status="answered",
        ),
        AssessmentResponse(
            id=uuid4(),
            assessment_id=assessment.id,
            question_id=q_weight_2.id,
            answer_value={"optionCode": selected_3.option_code},
            response_status="answered",
        ),
        AssessmentResponse(
            id=uuid4(),
            assessment_id=assessment.id,
            question_id=q_hidden.id,
            answer_value={"optionCode": hidden_10.option_code},
            response_status="answered",
        ),
        AssessmentResponse(
            id=uuid4(),
            assessment_id=assessment.id,
            question_id=intake_question.id,
            answer_value={"optionCode": intake_10.option_code},
            response_status="answered",
        ),
    ]
    session.add_all(responses)
    return assessment.id


@pytest.mark.asyncio
async def test_inherent_risk_uses_weighted_formula_and_persists_snapshot_fields(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            assessment_id = await _seed_weighted_questions(session)

        service = InherentRiskExecutionService(
            assessment_repository=AssessmentRepository(),
            analysis_repository=AnalysisRepository(),
            scoring_policy=DEFAULT_INHERENT_RISK_SCORING_POLICY,
        )
        async with session.begin():
            result = await service.create_analysis_run(session, assessment_id)

        assert result.status == AnalysisRunStatus.COMPLETED

        run = (await session.execute(select(QuestionAnalysisRun))).scalar_one()
        assert run.triage_score == 41
        assert run.inherent_score == pytest.approx(float((Decimal("41") / Decimal("66")) * Decimal("100")))
        assert run.inherent_risk_level == RiskLevel.HIGH.value

        rows = (await session.execute(select(QuestionRiskResult))).scalars().all()
        snapshots_by_code = {row.input_snapshot["questionCode"]: row.input_snapshot for row in rows}
        scores_by_code = {row.input_snapshot["questionCode"]: row.risk_score for row in rows}

        assert set(scores_by_code) == {"weight_5", "weight_2", "hidden_weighted"}
        assert scores_by_code["weight_5"] == 25
        assert scores_by_code["weight_2"] == 6
        assert scores_by_code["hidden_weighted"] == 10
        assert snapshots_by_code["weight_5"]["questionWeight"] == 5
        assert snapshots_by_code["weight_5"]["optionWeight"] == 5
        assert snapshots_by_code["weight_5"]["weightedScore"] == 25
        assert snapshots_by_code["weight_5"]["maxOptionWeight"] == 10
        assert snapshots_by_code["weight_5"]["maxWeightedScore"] == 50
        assert snapshots_by_code["weight_5"]["rawScore"] == 41
        assert snapshots_by_code["weight_5"]["maximumPossibleScore"] == 66
        assert snapshots_by_code["weight_5"]["normalizedScore"] == pytest.approx(float(Decimal("41") / Decimal("66") * Decimal("100")))
        assert snapshots_by_code["weight_5"]["whyItMatters"] == "Question-level reason."
        assert snapshots_by_code["weight_5"]["riskBand"] == RiskLevel.MEDIUM.value
        assert snapshots_by_code["weight_5"]["riskSignal"] == "five signal"
        assert snapshots_by_code["weight_5"]["scoringRuleVersion"] == DEFAULT_INHERENT_RISK_SCORING_POLICY.version


def test_workbook_ratio_thresholds_and_never_critical() -> None:
    policy = DEFAULT_INHERENT_RISK_SCORING_POLICY
    low_boundary = Decimal("78") / Decimal("176") * Decimal("100")
    medium_boundary = Decimal("100") / Decimal("176") * Decimal("100")

    assert policy.determine_level(low_boundary) == RiskLevel.LOW
    assert policy.determine_level(low_boundary + Decimal("0.0000001")) == RiskLevel.MEDIUM
    assert policy.determine_level(medium_boundary) == RiskLevel.MEDIUM
    assert policy.determine_level(medium_boundary + Decimal("0.0000001")) == RiskLevel.HIGH
    assert policy.determine_level(Decimal("100")) == RiskLevel.HIGH


@pytest.mark.asyncio
async def test_missing_scoring_weights_are_unresolved(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            assessment = SarAssessment(id=uuid4(), technology_name="Unresolved App")
            version = QuestionnaireVersion(id=uuid4(), questionnaire_type="triage", version="1", status="active")
            missing_question_weight = _question(version.id, code="missing_question_weight", order=1, weight=None)
            missing_option_weight = _question(version.id, code="missing_option_weight", order=2, weight=3)
            option_without_question_weight = _option(
                missing_question_weight.id,
                code="has_weight",
                order=1,
                weight=2,
                band=RiskLevel.LOW,
            )
            option_without_weight = QuestionOption(
                id=uuid4(),
                question_id=missing_option_weight.id,
                option_code="missing_weight",
                option_label="Missing Weight",
                risk_weight=None,
                display_order=1,
                risk_band=RiskLevel.LOW.value,
                risk_signal="missing",
            )
            session.add_all(
                [
                    assessment,
                    version,
                    missing_question_weight,
                    missing_option_weight,
                    option_without_question_weight,
                    option_without_weight,
                    AssessmentResponse(
                        id=uuid4(),
                        assessment_id=assessment.id,
                        question_id=missing_question_weight.id,
                        answer_value={"optionCode": option_without_question_weight.option_code},
                        response_status="answered",
                    ),
                    AssessmentResponse(
                        id=uuid4(),
                        assessment_id=assessment.id,
                        question_id=missing_option_weight.id,
                        answer_value={"optionCode": option_without_weight.option_code},
                        response_status="answered",
                    ),
                ]
            )

        payload = await AssessmentRepository().load_active_triage_question_responses(session, assessment.id)

        assert payload.question_responses == []
        assert len(payload.unresolved_response_ids) == 2


@pytest.mark.asyncio
async def test_old_snapshots_remain_readable(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        async with session.begin():
            assessment = SarAssessment(id=uuid4(), technology_name="Legacy App")
            version = QuestionnaireVersion(id=uuid4(), questionnaire_type="triage", version="1", status="active")
            question = _question(version.id, code="legacy_question", order=1, weight=2)
            response = AssessmentResponse(
                id=uuid4(),
                assessment_id=assessment.id,
                question_id=question.id,
                answer_value={"optionCode": "legacy"},
                response_status="answered",
            )
            run = QuestionAnalysisRun(
                id=uuid4(),
                assessment_id=assessment.id,
                status=AnalysisRunStatus.COMPLETED.value,
                scoring_rule_version="legacy",
                triage_score=7,
                inherent_score=70,
                inherent_risk_level=RiskLevel.MEDIUM.value,
            )
            session.add_all([assessment, version, question, response, run])
            session.add(
                QuestionRiskResult(
                    id=uuid4(),
                    analysis_run_id=run.id,
                    response_id=response.id,
                    risk_domain="Domain",
                    risk_score=7,
                    risk_level=RiskLevel.MEDIUM.value,
                    risk_impact="legacy reason",
                    risk_signal="legacy signal",
                    explanation="legacy explanation",
                    confidence=1.0,
                    input_snapshot={
                        "questionCode": "legacy_question",
                        "questionId": str(question.id),
                        "selectedOptionId": str(uuid4()),
                        "selectedOptionLabel": "Legacy",
                        "questionText": "Legacy?",
                        "riskWeight": 7,
                        "maxRiskWeight": 10,
                        "whyItMatters": "legacy reason",
                        "riskSignal": "legacy signal",
                    },
                )
            )

        snapshot = await AnalysisRepository().get_latest_completed_snapshot(session, assessment.id)

        assert snapshot is not None
        assert len(snapshot.question_results) == 1
        result = snapshot.question_results[0]
        assert result.weighted_score == 7
        assert result.max_weighted_score == 10
        assert result.why_it_matters == "legacy reason"
