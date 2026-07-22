from __future__ import annotations

from datetime import datetime, timezone
import uuid

import pytest
from sqlalchemy import select

from app.api.dependencies import get_azure_executive_summary_client, get_executive_summary_prompt_loader
from app.llm.executive_summary import ExecutiveSummaryPromptLoader
from app.main import app
from app.models.database import QuestionAnalysisRun, QuestionnaireVersion, SarAssessment
from app.models.enums import AnalysisRunStatus, RiskLevel
from tests.conftest import add_question_with_options, add_response

pytestmark = pytest.mark.asyncio


class FakeAzureSummaryClient:
    def __init__(self, summary_text: str):
        self.summary_text = summary_text
        self.calls = 0
        self.model_name = "gpt-5.5-test"

    def generate_summary(self, prompt, payload):
        self.calls += 1
        return self.summary_text


async def test_get_endpoint_returns_404_for_missing_assessment(client):
    response = await client.get(f"/api/v1/assessments/{uuid.uuid4()}/inherent-risk")

    assert response.status_code == 404
    assert response.json() == {"detail": "Assessment not found."}


async def test_post_analysis_run_returns_404_for_missing_assessment(client):
    response = await client.post(f"/api/v1/assessments/{uuid.uuid4()}/analysis-runs", json={"force": False})

    assert response.status_code == 404
    assert response.json() == {"detail": "Assessment not found."}


async def test_post_analysis_run_persists_run(client, db_session, seeded_assessment):
    question, options = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Business Continuity",
        options=[
            ("Selected", RiskLevel.HIGH, 2.0, "High continuity signal."),
            ("Maximum", RiskLevel.CRITICAL, 4.0, "Maximum continuity signal."),
        ],
    )
    await add_response(db_session, seeded_assessment["assessment_id"], question, options[0])

    response = await client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/analysis-runs",
        json={"force": False},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    run = await db_session.get(QuestionAnalysisRun, uuid.UUID(response.json()["analysisRunId"]))
    assert run is not None
    assert run.scoring_rule_version == "inherent-risk-v1-percentage"
    assert run.triage_score == 2.0
    assert run.inherent_score == 50.0
    assert run.inherent_risk_level == "high"


async def test_post_executive_summary_persists_and_get_returns_saved_summary(
    client,
    db_session,
    seeded_assessment,
    executive_summary_prompt_path,
):
    fake_client = FakeAzureSummaryClient("Generated executive summary.")
    app.dependency_overrides[get_executive_summary_prompt_loader] = lambda: ExecutiveSummaryPromptLoader(
        executive_summary_prompt_path
    )
    app.dependency_overrides[get_azure_executive_summary_client] = lambda: fake_client

    question, options = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Business Continuity",
        why_it_matters="DB why-it-matters",
        options=[
            ("Selected", RiskLevel.HIGH, 2.0, "DB risk signal"),
            ("Maximum", RiskLevel.CRITICAL, 4.0, "Maximum continuity signal"),
        ],
    )
    await add_response(db_session, seeded_assessment["assessment_id"], question, options[0])

    run_response = await client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/analysis-runs",
        json={"force": False},
    )
    analysis_run_id = run_response.json()["analysisRunId"]

    summary_response = await client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/analysis-runs/{analysis_run_id}/executive-summary",
        json={"force": False},
    )

    assert summary_response.status_code == 200
    assert summary_response.json()["assessmentId"] == str(seeded_assessment["assessment_id"])
    assert summary_response.json()["analysisRunId"] == analysis_run_id
    assert summary_response.json()["executiveSummary"]["text"] == "Generated executive summary."
    assert summary_response.json()["executiveSummary"]["status"] == "generated"
    assert fake_client.calls == 1

    get_response = await client.get(f"/api/v1/assessments/{seeded_assessment['assessment_id']}/inherent-risk")

    assert get_response.status_code == 200
    assert get_response.json()["executiveSummary"]["text"] == "Generated executive summary."
    assert get_response.json()["executiveSummary"]["status"] == "generated"

    app.dependency_overrides.pop(get_executive_summary_prompt_loader, None)
    app.dependency_overrides.pop(get_azure_executive_summary_client, None)


async def test_post_executive_summary_returns_404_for_wrong_assessment_run_pair(
    client,
    db_session,
    seeded_assessment,
    executive_summary_prompt_path,
):
    fake_client = FakeAzureSummaryClient("Generated executive summary.")
    app.dependency_overrides[get_executive_summary_prompt_loader] = lambda: ExecutiveSummaryPromptLoader(
        executive_summary_prompt_path
    )
    app.dependency_overrides[get_azure_executive_summary_client] = lambda: fake_client

    question, options = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        options=[("Selected", RiskLevel.HIGH, 2.0, "High security signal.")],
    )
    await add_response(db_session, seeded_assessment["assessment_id"], question, options[0])

    run_response = await client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/analysis-runs",
        json={"force": False},
    )
    analysis_run_id = run_response.json()["analysisRunId"]

    other_assessment = SarAssessment(
        id=uuid.uuid4(),
        technology_name="Another Tech",
        vendor_name="Another Vendor",
        product_name="Another Product",
    )
    other_version = QuestionnaireVersion(
        id=uuid.uuid4(),
        questionnaire_type="triage",
        version="triage-v2",
        status="active",
    )
    db_session.add_all([other_assessment, other_version])
    await db_session.commit()

    response = await client.post(
        f"/api/v1/assessments/{other_assessment.id}/analysis-runs/{analysis_run_id}/executive-summary",
        json={"force": False},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Analysis run not found."}
    assert fake_client.calls == 0

    app.dependency_overrides.pop(get_executive_summary_prompt_loader, None)
    app.dependency_overrides.pop(get_azure_executive_summary_client, None)


@pytest.mark.parametrize("status", ["queued", "running", AnalysisRunStatus.FAILED.value])
async def test_post_executive_summary_returns_409_for_invalid_run_status(
    client,
    db_session,
    seeded_assessment,
    executive_summary_prompt_path,
    status,
):
    fake_client = FakeAzureSummaryClient("Generated executive summary.")
    app.dependency_overrides[get_executive_summary_prompt_loader] = lambda: ExecutiveSummaryPromptLoader(
        executive_summary_prompt_path
    )
    app.dependency_overrides[get_azure_executive_summary_client] = lambda: fake_client

    run = QuestionAnalysisRun(
        id=uuid.uuid4(),
        assessment_id=seeded_assessment["assessment_id"],
        status=status,
        scoring_rule_version="inherent-risk-v1-percentage",
        inherent_risk_level=RiskLevel.NOT_ASSESSED.value,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(run)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/analysis-runs/{run.id}/executive-summary",
        json={"force": False},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": f"Analysis run status '{status}' does not allow executive summary generation."
    }
    assert fake_client.calls == 0

    app.dependency_overrides.pop(get_executive_summary_prompt_loader, None)
    app.dependency_overrides.pop(get_azure_executive_summary_client, None)


async def test_post_executive_summary_allows_completed_with_limitations(
    client,
    seeded_assessment,
    executive_summary_prompt_path,
):
    fake_client = FakeAzureSummaryClient("Generated executive summary.")
    app.dependency_overrides[get_executive_summary_prompt_loader] = lambda: ExecutiveSummaryPromptLoader(
        executive_summary_prompt_path
    )
    app.dependency_overrides[get_azure_executive_summary_client] = lambda: fake_client

    run_response = await client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/analysis-runs",
        json={"force": False},
    )

    assert run_response.status_code == 200
    assert run_response.json()["status"] == AnalysisRunStatus.COMPLETED_WITH_LIMITATIONS

    summary_response = await client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/analysis-runs/{run_response.json()['analysisRunId']}/executive-summary",
        json={"force": False},
    )

    assert summary_response.status_code == 200
    assert summary_response.json()["executiveSummary"]["text"] == "Generated executive summary."
    assert fake_client.calls == 1

    app.dependency_overrides.pop(get_executive_summary_prompt_loader, None)
    app.dependency_overrides.pop(get_azure_executive_summary_client, None)


async def test_post_executive_summary_updates_only_requested_run(
    client,
    db_session,
    seeded_assessment,
    executive_summary_prompt_path,
):
    fake_client = FakeAzureSummaryClient("Generated executive summary.")
    app.dependency_overrides[get_executive_summary_prompt_loader] = lambda: ExecutiveSummaryPromptLoader(
        executive_summary_prompt_path
    )
    app.dependency_overrides[get_azure_executive_summary_client] = lambda: fake_client

    question, options = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Business Continuity",
        options=[
            ("Selected", RiskLevel.HIGH, 2.0, "High continuity signal."),
            ("Maximum", RiskLevel.CRITICAL, 4.0, "Maximum continuity signal."),
        ],
    )
    await add_response(db_session, seeded_assessment["assessment_id"], question, options[0])

    first_run_response = await client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/analysis-runs",
        json={"force": False},
    )
    second_run_response = await client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/analysis-runs",
        json={"force": False},
    )

    target_run_id = second_run_response.json()["analysisRunId"]
    response = await client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/analysis-runs/{target_run_id}/executive-summary",
        json={"force": False},
    )

    assert response.status_code == 200

    first_run = await db_session.get(QuestionAnalysisRun, uuid.UUID(first_run_response.json()["analysisRunId"]))
    second_run = await db_session.get(QuestionAnalysisRun, uuid.UUID(target_run_id))

    assert first_run is not None
    assert first_run.executive_summary_text is None
    assert first_run.executive_summary_generated_at is None
    assert second_run is not None
    assert second_run.executive_summary_text == "Generated executive summary."
    assert second_run.executive_summary_generated_at is not None

    app.dependency_overrides.pop(get_executive_summary_prompt_loader, None)
    app.dependency_overrides.pop(get_azure_executive_summary_client, None)


async def test_get_endpoint_returns_controlled_not_assessed_response(client, seeded_assessment):
    response = await client.get(f"/api/v1/assessments/{seeded_assessment['assessment_id']}/inherent-risk")

    assert response.status_code == 200
    assert response.json() == {
        "assessmentId": str(seeded_assessment["assessment_id"]),
        "analysisRunId": None,
        "status": "completed_with_limitations",
        "inherentRisk": {
            "level": "not_assessed",
            "label": "Not Assessed",
            "highRiskQuestionCount": 0,
            "sourceText": "Derived from SAR triage questions.",
        },
        "topRiskDrivers": [],
        "executiveSummary": {
            "text": None,
            "status": "not_generated",
            "generatedAt": None,
        },
        "links": {
            "aiAnalysis": f"/api/v1/assessments/{seeded_assessment['assessment_id']}/ai-analysis",
            "reportPreview": f"/api/v1/assessments/{seeded_assessment['assessment_id']}/report-preview",
        },
    }


async def test_get_returns_latest_successful_run_when_failed_run_exists(client, db_session, seeded_assessment):
    question, options = await add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        options=[
            ("Selected", RiskLevel.HIGH, 2.0, "High security signal."),
            ("Maximum", RiskLevel.CRITICAL, 4.0, "Maximum security signal."),
        ],
    )
    await add_response(db_session, seeded_assessment["assessment_id"], question, options[0])

    created = (
        await client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/analysis-runs",
        json={"force": False},
        )
    ).json()

    db_session.add(
        QuestionAnalysisRun(
            id=uuid.uuid4(),
            assessment_id=seeded_assessment["assessment_id"],
            status=AnalysisRunStatus.FAILED.value,
            scoring_rule_version="inherent-risk-v1-percentage",
            inherent_risk_level=RiskLevel.NOT_ASSESSED.value,
        )
    )
    await db_session.commit()

    response = await client.get(f"/api/v1/assessments/{seeded_assessment['assessment_id']}/inherent-risk")

    assert response.status_code == 200
    assert response.json()["analysisRunId"] == created["analysisRunId"]
