from __future__ import annotations

import builtins
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.errors import AssessmentNotFoundError
from app.assemblers.inherent_risk_assembler import InherentRiskAssembler
from app.config import DATABASE_SCHEMA_TOKEN, PercentageInherentRiskScoringPolicy
from app.models.database import QuestionAnalysisRun, QuestionRiskResult
from app.models.enums import AnalysisRunStatus, ExecutiveSummaryStatus, RiskLevel
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.assessment_repository import AssessmentRepository
from app.services.inherent_risk_service import InherentRiskService
from tests.conftest import add_question_with_option, add_question_with_options, add_response

pytestmark = pytest.mark.asyncio


def build_service() -> InherentRiskService:
    return InherentRiskService(
        assessment_repository=AssessmentRepository(),
        analysis_repository=AnalysisRepository(),
        assembler=InherentRiskAssembler(),
        scoring_policy=PercentageInherentRiskScoringPolicy(),
    )


def seed_boundary_question(db_session, seeded_assessment, selected_weight: float, selected_level: RiskLevel):
    return add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Boundary",
        options=[
            ("Selected", selected_level, selected_weight, "Boundary risk signal."),
            ("Maximum", RiskLevel.CRITICAL, 4.0, "Maximum risk signal."),
        ],
    )


async def test_database_schema_is_applied(monkeypatch):
    captured: dict[str, object] = {}

    def fake_create_engine(*args, **kwargs):
        captured["execution_options"] = kwargs.get("execution_options")
        return object()

    monkeypatch.setattr("app.database.create_async_engine", fake_create_engine)

    from app.database import create_engine_from_url

    create_engine_from_url("postgresql://example", "custom_schema")

    execution_options = captured["execution_options"]
    assert execution_options["schema_translate_map"][DATABASE_SCHEMA_TOKEN] == "custom_schema"


async def test_assessment_not_found(db_session):
    service = build_service()

    with pytest.raises(AssessmentNotFoundError):
        await service.get_inherent_risk_screen(db_session, str(uuid4()))


async def test_assessment_with_no_responses_returns_not_assessed(db_session, seeded_assessment):
    service = build_service()

    dto = await service.get_inherent_risk_screen(db_session, seeded_assessment["assessment_id"])

    assert dto.analysisRunId is None
    assert dto.status == AnalysisRunStatus.COMPLETED_WITH_LIMITATIONS
    assert dto.inherentRisk.level == RiskLevel.NOT_ASSESSED


@pytest.mark.parametrize(
    ("selected_weight", "selected_level", "expected_level"),
    [
        (0.0, RiskLevel.LOW, RiskLevel.LOW),
        (1.0, RiskLevel.MEDIUM, RiskLevel.MEDIUM),
        (2.0, RiskLevel.HIGH, RiskLevel.HIGH),
        (3.0, RiskLevel.CRITICAL, RiskLevel.CRITICAL),
    ],
)
async def test_percentage_scoring_exact_boundaries(
    db_session,
    seeded_assessment,
    selected_weight,
    selected_level,
    expected_level,
):
    question, options = await seed_boundary_question(db_session, seeded_assessment, selected_weight, selected_level)
    await add_response(db_session, seeded_assessment["assessment_id"], question, options[0])
    service = build_service()

    dto = await service.get_inherent_risk_screen(db_session, seeded_assessment["assessment_id"])
    snapshot = await AnalysisRepository().get_latest_completed_snapshot(db_session, seeded_assessment["assessment_id"])

    assert dto.status == AnalysisRunStatus.COMPLETED
    assert dto.inherentRisk.level == expected_level
    assert snapshot is not None
    assert snapshot.inherent_score == pytest.approx((selected_weight / 4.0) * 100.0)
    assert snapshot.triage_score == selected_weight


async def test_optional_unanswered_questions_do_not_create_limitations(db_session, seeded_assessment):
    answered_question, answered_options = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        is_required=True,
        options=[
            ("Selected", RiskLevel.HIGH, 3.0, "High security signal."),
            ("Maximum", RiskLevel.CRITICAL, 4.0, "Maximum security signal."),
        ],
    )
    await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Privacy",
        is_required=False,
        options=[
            ("Selected", RiskLevel.MEDIUM, 2.0, "Medium privacy signal."),
            ("Maximum", RiskLevel.CRITICAL, 4.0, "Maximum privacy signal."),
        ],
    )
    await add_response(db_session, seeded_assessment["assessment_id"], answered_question, answered_options[0])

    service = build_service()
    run_dto = await service.create_analysis_run(db_session, seeded_assessment["assessment_id"])
    run = await db_session.get(QuestionAnalysisRun, run_dto.analysisRunId)

    assert run_dto.status == AnalysisRunStatus.COMPLETED
    assert run is not None
    assert run.limitation_summary is None


async def test_required_unanswered_questions_do_create_limitations(db_session, seeded_assessment):
    answered_question, answered_options = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        is_required=True,
        options=[
            ("Selected", RiskLevel.HIGH, 3.0, "High security signal."),
            ("Maximum", RiskLevel.CRITICAL, 4.0, "Maximum security signal."),
        ],
    )
    await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Privacy",
        is_required=True,
        options=[
            ("Selected", RiskLevel.MEDIUM, 2.0, "Medium privacy signal."),
            ("Maximum", RiskLevel.CRITICAL, 4.0, "Maximum privacy signal."),
        ],
    )
    await add_response(db_session, seeded_assessment["assessment_id"], answered_question, answered_options[0])

    service = build_service()
    run_dto = await service.create_analysis_run(db_session, seeded_assessment["assessment_id"])
    run = await db_session.get(QuestionAnalysisRun, run_dto.analysisRunId)

    assert run_dto.status == AnalysisRunStatus.COMPLETED_WITH_LIMITATIONS
    assert run is not None
    assert "unanswered" in (run.limitation_summary or "")


async def test_high_risk_question_count_counts_high_and_critical_only(db_session, seeded_assessment):
    items = [
        ("Business Continuity", RiskLevel.HIGH, 3.0),
        ("Security", RiskLevel.CRITICAL, 4.0),
        ("Privacy", RiskLevel.MEDIUM, 2.0),
    ]
    for domain, level, weight in items:
        question, option = await add_question_with_option(
            db_session,
            seeded_assessment["questionnaire_version_id"],
            risk_domain=domain,
            risk_level=level,
            risk_weight=weight,
        )
        await add_response(db_session, seeded_assessment["assessment_id"], question, option)

    service = build_service()
    dto = await service.get_inherent_risk_screen(db_session, seeded_assessment["assessment_id"])

    assert dto.inherentRisk.highRiskQuestionCount == 2


async def test_top_risk_drivers_are_limited_and_deterministic(db_session, seeded_assessment):
    items = [
        ("Operations", RiskLevel.HIGH, 3.0),
        ("Business Continuity", RiskLevel.CRITICAL, 4.0),
        ("Security", RiskLevel.HIGH, 3.5),
        ("Privacy", RiskLevel.MEDIUM, 2.0),
        ("Vendor Reputation", RiskLevel.CRITICAL, 4.0),
    ]
    for domain, level, weight in items:
        question, option = await add_question_with_option(
            db_session,
            seeded_assessment["questionnaire_version_id"],
            risk_domain=domain,
            risk_level=level,
            risk_weight=weight,
        )
        await add_response(db_session, seeded_assessment["assessment_id"], question, option)

    service = build_service()
    dto = await service.get_inherent_risk_screen(db_session, seeded_assessment["assessment_id"])

    assert [driver.model_dump() for driver in dto.topRiskDrivers] == [
        {"domain": "Business Continuity", "level": RiskLevel.CRITICAL},
        {"domain": "Security", "level": RiskLevel.HIGH},
        {"domain": "Operations", "level": RiskLevel.HIGH},
    ]


async def test_selected_option_id_path_sets_full_confidence(db_session, seeded_assessment):
    question, options = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        options=[
            ("Exact", RiskLevel.HIGH, 3.0, "High security signal."),
            ("Maximum", RiskLevel.CRITICAL, 4.0, "Maximum security signal."),
        ],
    )
    await add_response(db_session, seeded_assessment["assessment_id"], question, options[0])

    service = build_service()
    run_dto = await service.create_analysis_run(db_session, seeded_assessment["assessment_id"])
    stored_result = (
        await db_session.execute(
            select(QuestionRiskResult).where(QuestionRiskResult.analysis_run_id == run_dto.analysisRunId)
        )
    ).scalars().one()

    assert stored_result.ai_confidence == 1.0


async def test_answer_value_fallback_path_sets_lower_confidence(db_session, seeded_assessment):
    question, options = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        options=[
            ("Fallback", RiskLevel.HIGH, 3.0, "High security signal."),
            ("Maximum", RiskLevel.CRITICAL, 4.0, "Maximum security signal."),
        ],
    )
    await add_response(
        db_session,
        seeded_assessment["assessment_id"],
        question,
        option=None,
        answer_value=options[0].label,
    )

    service = build_service()
    run_dto = await service.create_analysis_run(db_session, seeded_assessment["assessment_id"])
    stored_result = (
        await db_session.execute(
            select(QuestionRiskResult).where(QuestionRiskResult.analysis_run_id == run_dto.analysisRunId)
        )
    ).scalars().one()

    assert run_dto.status == AnalysisRunStatus.COMPLETED_WITH_LIMITATIONS
    assert stored_result.ai_confidence == 0.8


async def test_db_configuration_fields_are_read_and_explanation_uses_db_values(db_session, seeded_assessment):
    question, options = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        why_it_matters="Stored why-it-matters text.",
        options=[
            ("Selected", RiskLevel.HIGH, 3.0, "Stored risk signal text."),
            ("Maximum", RiskLevel.CRITICAL, 4.0, "Maximum security signal."),
        ],
    )
    await add_response(db_session, seeded_assessment["assessment_id"], question, options[0])
    service = build_service()

    run_dto = await service.create_analysis_run(db_session, seeded_assessment["assessment_id"])
    stored_result = (
        await db_session.execute(
            select(QuestionRiskResult).where(QuestionRiskResult.analysis_run_id == run_dto.analysisRunId)
        )
    ).scalars().one()

    assert stored_result.why_it_matters == "Stored why-it-matters text."
    assert stored_result.risk_signal == "Stored risk signal text."
    assert "Stored why-it-matters text." in (stored_result.ai_explanation or "")
    assert "Stored risk signal text." in (stored_result.ai_explanation or "")


async def test_existing_completed_run_is_returned_correctly(db_session, seeded_completed_run):
    service = build_service()

    dto = await service.get_inherent_risk_screen(db_session, seeded_completed_run["assessment_id"])

    assert dto.analysisRunId == seeded_completed_run["run_id"]
    assert dto.executiveSummary.text == "Stored summary."
    assert dto.executiveSummary.status == ExecutiveSummaryStatus.GENERATED


async def test_previous_runs_remain_unchanged_and_latest_successful_run_is_selected(db_session, seeded_assessment):
    question, options = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        options=[
            ("Selected", RiskLevel.MEDIUM, 1.0, "Medium security signal."),
            ("Maximum", RiskLevel.CRITICAL, 4.0, "Maximum security signal."),
        ],
    )
    await add_response(db_session, seeded_assessment["assessment_id"], question, options[0])
    service = build_service()

    first_run = await service.create_analysis_run(db_session, seeded_assessment["assessment_id"])
    first_row = await db_session.get(QuestionAnalysisRun, first_run.analysisRunId)
    assert first_row is not None
    first_score = first_row.inherent_score

    question_two, options_two = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Business Continuity",
        options=[
            ("Selected", RiskLevel.CRITICAL, 4.0, "Critical continuity signal."),
            ("Maximum", RiskLevel.CRITICAL, 4.0, "Critical continuity signal."),
        ],
    )
    await add_response(db_session, seeded_assessment["assessment_id"], question_two, options_two[0])

    second_run = await service.create_analysis_run(db_session, seeded_assessment["assessment_id"])
    run_rows = (
        await db_session.execute(
            select(QuestionAnalysisRun).where(
                QuestionAnalysisRun.assessment_id == seeded_assessment["assessment_id"]
            )
        )
    ).scalars().all()

    assert len(run_rows) == 2
    assert (await db_session.get(QuestionAnalysisRun, first_run.analysisRunId)).inherent_score == first_score

    dto = await service.get_inherent_risk_screen(db_session, seeded_assessment["assessment_id"])
    assert dto.analysisRunId == second_run.analysisRunId
    assert dto.inherentRisk.level == RiskLevel.HIGH


async def test_failed_run_is_not_selected_as_latest_completed_run(db_session, seeded_completed_run):
    db_session.add(
        QuestionAnalysisRun(
            id=str(uuid4()),
            assessment_id=seeded_completed_run["assessment_id"],
            status=AnalysisRunStatus.FAILED.value,
            scoring_config_version="existing-config-v1",
            overall_risk_level=RiskLevel.NOT_ASSESSED.value,
            source_text="Derived from SAR triage questions.",
        )
    )
    await db_session.commit()

    service = build_service()
    dto = await service.get_inherent_risk_screen(db_session, seeded_completed_run["assessment_id"])

    assert dto.analysisRunId == seeded_completed_run["run_id"]
    assert dto.status == AnalysisRunStatus.COMPLETED


async def test_no_llm_client_is_called(db_session, seeded_assessment, monkeypatch):
    question, options = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        options=[
            ("Selected", RiskLevel.HIGH, 3.0, "High security signal."),
            ("Maximum", RiskLevel.CRITICAL, 4.0, "Maximum security signal."),
        ],
    )
    await add_response(db_session, seeded_assessment["assessment_id"], question, options[0])
    service = build_service()

    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.startswith("app.llm"):
            raise AssertionError("LLM import should not occur in inherent risk flow.")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    await service.create_analysis_run(db_session, seeded_assessment["assessment_id"])
