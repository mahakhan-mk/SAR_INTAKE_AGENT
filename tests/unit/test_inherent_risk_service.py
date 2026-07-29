from __future__ import annotations

import builtins
import uuid

import pytest
from sqlalchemy import select

from app.assemblers.inherent_risk_assembler import InherentRiskAssembler
from app.application.models import ComputedQuestionRisk, TopRiskDriverState
from app.config import DATABASE_SCHEMA_TOKEN, PercentageInherentRiskScoringPolicy
from app.domain.errors import AssessmentNotFoundError
from app.models.database import QuestionAnalysisRun, QuestionRiskResult
from app.models.enums import AnalysisRunStatus, ExecutiveSummaryStatus, RiskLevel
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.assessment_repository import AssessmentRepository
from app.services.inherent_risk_service import InherentRiskExecutionService, InherentRiskQueryService
from tests.conftest import add_question_with_option, add_question_with_options, add_response

pytestmark = pytest.mark.asyncio


def build_execution_service() -> InherentRiskExecutionService:
    return InherentRiskExecutionService(
        assessment_repository=AssessmentRepository(),
        analysis_repository=AnalysisRepository(),
        scoring_policy=PercentageInherentRiskScoringPolicy(),
    )


def build_query_service() -> InherentRiskQueryService:
    return InherentRiskQueryService(
        assessment_repository=AssessmentRepository(),
        analysis_repository=AnalysisRepository(),
        assembler=InherentRiskAssembler(),
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


def build_question_result(risk_domain: str, risk_level: RiskLevel, risk_weight: float) -> ComputedQuestionRisk:
    token = uuid.uuid4()
    return ComputedQuestionRisk(
        question_code=f"Q-{risk_domain}-{risk_level.value}-{risk_weight}",
        response_id=token,
        question_definition_id=token,
        selected_option_id=token,
        selected_option_label="Selected",
        question_text=f"Question for {risk_domain}",
        risk_domain=risk_domain,
        risk_level=risk_level,
        risk_weight=risk_weight,
        max_risk_weight=max(risk_weight, 4.0),
        why_it_matters="Why it matters.",
        risk_signal="Risk signal.",
        explanation="Explanation.",
        confidence=1.0,
        input_snapshot={},
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
    service = build_query_service()

    with pytest.raises(AssessmentNotFoundError):
        await service.get_inherent_risk_screen(db_session, uuid.uuid4())


async def test_assessment_with_no_responses_returns_not_assessed(db_session, seeded_assessment):
    service = build_query_service()

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
    execution_service = build_execution_service()
    query_service = build_query_service()

    await execution_service.create_analysis_run(db_session, seeded_assessment["assessment_id"])
    dto = await query_service.get_inherent_risk_screen(db_session, seeded_assessment["assessment_id"])
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

    service = build_execution_service()
    run_dto = await service.create_analysis_run(db_session, seeded_assessment["assessment_id"])
    run = await db_session.get(QuestionAnalysisRun, uuid.UUID(run_dto.analysisRunId))

    assert run_dto.status == AnalysisRunStatus.COMPLETED
    assert run is not None
    assert run.error_summary is None


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

    service = build_execution_service()
    run_dto = await service.create_analysis_run(db_session, seeded_assessment["assessment_id"])
    run = await db_session.get(QuestionAnalysisRun, uuid.UUID(run_dto.analysisRunId))

    assert run_dto.status == AnalysisRunStatus.COMPLETED_WITH_LIMITATIONS
    assert run is not None
    assert run.error_summary is None


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

    execution_service = build_execution_service()
    query_service = build_query_service()
    await execution_service.create_analysis_run(db_session, seeded_assessment["assessment_id"])
    dto = await query_service.get_inherent_risk_screen(db_session, seeded_assessment["assessment_id"])

    assert dto.inherentRisk.highRiskQuestionCount == 2


async def test_derive_top_risk_drivers_returns_empty_when_no_high_or_critical_results():
    service = build_query_service()

    drivers = service.derive_top_risk_drivers(
        [
            build_question_result("domain-low", RiskLevel.LOW, 1.0),
            build_question_result("domain-medium", RiskLevel.MEDIUM, 2.0),
        ]
    )

    assert drivers == []


async def test_derive_top_risk_drivers_returns_one_driver_for_one_eligible_domain():
    service = build_query_service()

    drivers = service.derive_top_risk_drivers(
        [build_question_result("domain-eligible", RiskLevel.HIGH, 3.0)]
    )

    assert [(driver.domain, driver.level) for driver in drivers] == [
        ("domain-eligible", RiskLevel.HIGH),
    ]


async def test_derive_top_risk_drivers_uses_all_eligible_domains_with_deterministic_ordering():
    service = build_query_service()

    drivers = service.derive_top_risk_drivers(
        [
            build_question_result("domain-gamma", RiskLevel.HIGH, 3.4),
            build_question_result("domain-alpha", RiskLevel.HIGH, 3.8),
            build_question_result("domain-alpha", RiskLevel.CRITICAL, 4.5),
            build_question_result("domain-delta", RiskLevel.CRITICAL, 3.2),
            build_question_result("domain-beta", RiskLevel.HIGH, 3.4),
            build_question_result("domain-epsilon", RiskLevel.HIGH, 3.7),
            build_question_result("domain-epsilon", RiskLevel.HIGH, 3.9),
            build_question_result("domain-low", RiskLevel.LOW, 4.0),
            build_question_result("domain-medium", RiskLevel.MEDIUM, 2.0),
        ]
    )

    assert [(driver.domain, driver.level) for driver in drivers] == [
        ("domain-alpha", RiskLevel.CRITICAL),
        ("domain-delta", RiskLevel.CRITICAL),
        ("domain-epsilon", RiskLevel.HIGH),
        ("domain-beta", RiskLevel.HIGH),
        ("domain-gamma", RiskLevel.HIGH),
    ]


async def test_get_inherent_risk_screen_uses_public_top_risk_driver_deriver(
    db_session,
    seeded_assessment,
    monkeypatch,
):
    question, option = await add_question_with_option(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="domain-source",
        risk_level=RiskLevel.HIGH,
        risk_weight=3.0,
    )
    await add_response(db_session, seeded_assessment["assessment_id"], question, option)
    execution_service = build_execution_service()
    service = build_query_service()
    captured: dict[str, object] = {}

    def fake_derive_top_risk_drivers(question_results):
        captured["question_results"] = question_results
        return [TopRiskDriverState(domain="domain-from-public-method", level=RiskLevel.CRITICAL)]

    monkeypatch.setattr(service, "derive_top_risk_drivers", fake_derive_top_risk_drivers)

    await execution_service.create_analysis_run(db_session, seeded_assessment["assessment_id"])
    dto = await service.get_inherent_risk_screen(db_session, seeded_assessment["assessment_id"])

    assert len(captured["question_results"]) == 1
    assert [{"domain": driver.domain, "level": driver.level} for driver in dto.topRiskDrivers] == [
        {"domain": "domain-from-public-method", "level": RiskLevel.CRITICAL},
    ]


async def test_get_inherent_risk_screen_exposes_complete_top_risk_driver_list(db_session, seeded_assessment):
    items = [
        ("domain-gamma", RiskLevel.HIGH, 3.4),
        ("domain-alpha", RiskLevel.CRITICAL, 4.5),
        ("domain-delta", RiskLevel.CRITICAL, 3.2),
        ("domain-beta", RiskLevel.HIGH, 3.4),
        ("domain-epsilon", RiskLevel.HIGH, 3.9),
        ("domain-low", RiskLevel.LOW, 1.0),
        ("domain-medium", RiskLevel.MEDIUM, 2.0),
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

    execution_service = build_execution_service()
    query_service = build_query_service()
    await execution_service.create_analysis_run(db_session, seeded_assessment["assessment_id"])
    dto = await query_service.get_inherent_risk_screen(db_session, seeded_assessment["assessment_id"])

    assert [{"domain": driver.domain, "level": driver.level} for driver in dto.topRiskDrivers] == [
        {"domain": "domain-alpha", "level": RiskLevel.CRITICAL},
        {"domain": "domain-delta", "level": RiskLevel.CRITICAL},
        {"domain": "domain-epsilon", "level": RiskLevel.HIGH},
        {"domain": "domain-beta", "level": RiskLevel.HIGH},
        {"domain": "domain-gamma", "level": RiskLevel.HIGH},
    ]


async def test_answer_value_json_path_sets_full_confidence(db_session, seeded_assessment):
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

    service = build_execution_service()
    run_dto = await service.create_analysis_run(db_session, seeded_assessment["assessment_id"])
    stored_result = (
        await db_session.execute(
            select(QuestionRiskResult).where(
                QuestionRiskResult.analysis_run_id == uuid.UUID(run_dto.analysisRunId)
            )
        )
    ).scalars().one()

    assert stored_result.confidence == 1.0


async def test_unresolvable_answer_value_json_creates_limitation(db_session, seeded_assessment):
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
        answer_value={"selectedResponse": "Unknown option"},
    )

    service = build_execution_service()
    run_dto = await service.create_analysis_run(db_session, seeded_assessment["assessment_id"])
    stored_results = (
        await db_session.execute(
            select(QuestionRiskResult).where(
                QuestionRiskResult.analysis_run_id == uuid.UUID(run_dto.analysisRunId)
            )
        )
    ).scalars().all()

    assert run_dto.status == AnalysisRunStatus.COMPLETED_WITH_LIMITATIONS
    assert stored_results == []


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
    service = build_execution_service()

    run_dto = await service.create_analysis_run(db_session, seeded_assessment["assessment_id"])
    stored_result = (
        await db_session.execute(
            select(QuestionRiskResult).where(
                QuestionRiskResult.analysis_run_id == uuid.UUID(run_dto.analysisRunId)
            )
        )
    ).scalars().one()

    assert stored_result.risk_impact == "Stored why-it-matters text."
    assert stored_result.risk_signal == "Stored risk signal text."
    assert "Stored why-it-matters text." in stored_result.explanation
    assert "Stored risk signal text." in stored_result.explanation


async def test_existing_completed_run_is_returned_correctly(db_session, seeded_completed_run):
    service = build_query_service()

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
    execution_service = build_execution_service()
    query_service = build_query_service()

    first_run = await execution_service.create_analysis_run(db_session, seeded_assessment["assessment_id"])
    first_row = await db_session.get(QuestionAnalysisRun, uuid.UUID(first_run.analysisRunId))
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

    second_run = await execution_service.create_analysis_run(db_session, seeded_assessment["assessment_id"])
    run_rows = (
        await db_session.execute(
            select(QuestionAnalysisRun).where(
                QuestionAnalysisRun.assessment_id == seeded_assessment["assessment_id"]
            )
        )
    ).scalars().all()

    assert len(run_rows) == 2
    assert (await db_session.get(QuestionAnalysisRun, uuid.UUID(first_run.analysisRunId))).inherent_score == first_score

    dto = await query_service.get_inherent_risk_screen(db_session, seeded_assessment["assessment_id"])
    assert dto.analysisRunId == uuid.UUID(second_run.analysisRunId)
    assert dto.inherentRisk.level == RiskLevel.HIGH


async def test_failed_run_is_not_selected_as_latest_completed_run(db_session, seeded_completed_run):
    db_session.add(
        QuestionAnalysisRun(
            id=uuid.uuid4(),
            assessment_id=seeded_completed_run["assessment_id"],
            status=AnalysisRunStatus.FAILED.value,
            scoring_rule_version="existing-config-v1",
            inherent_risk_level=RiskLevel.NOT_ASSESSED.value,
        )
    )
    await db_session.commit()

    service = build_query_service()
    dto = await service.get_inherent_risk_screen(db_session, seeded_completed_run["assessment_id"])

    assert dto.analysisRunId == seeded_completed_run["run_id"]
    assert dto.status == AnalysisRunStatus.COMPLETED


async def test_create_analysis_run_service_does_not_commit_or_rollback(db_session, seeded_assessment, monkeypatch):
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
    service = build_execution_service()
    commit_calls = 0
    rollback_calls = 0
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

    run_dto = await service.create_analysis_run(db_session, seeded_assessment["assessment_id"])
    run = await db_session.get(QuestionAnalysisRun, uuid.UUID(run_dto.analysisRunId))

    assert run is not None
    assert commit_calls == 0
    assert rollback_calls == 0


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
    service = build_execution_service()

    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.startswith("app.llm"):
            raise AssertionError("LLM import should not occur in inherent risk flow.")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    await service.create_analysis_run(db_session, seeded_assessment["assessment_id"])
