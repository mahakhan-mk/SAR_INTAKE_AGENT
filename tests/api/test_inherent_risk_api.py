from __future__ import annotations

from uuid import uuid4

from app.api.dependencies import get_azure_executive_summary_client, get_executive_summary_prompt_loader
from app.llm.executive_summary import ExecutiveSummaryPromptLoader
from app.main import app
from app.models.database import QuestionAnalysisRun
from app.models.enums import AnalysisRunStatus, RiskLevel
from tests.conftest import add_question_with_options, add_response


class FakeAzureSummaryClient:
    def __init__(self, summary_text: str):
        self.summary_text = summary_text
        self.calls = 0
        self.model_name = "gpt-5.5-test"

    def generate_summary(self, prompt, payload):
        self.calls += 1
        return self.summary_text


def test_get_endpoint_returns_404_for_missing_assessment(client):
    response = client.get(f"/api/v1/assessments/{uuid4()}/inherent-risk")

    assert response.status_code == 404
    assert response.json() == {"detail": "Assessment not found."}


def test_post_analysis_run_returns_404_for_missing_assessment(client):
    response = client.post(f"/api/v1/assessments/{uuid4()}/analysis-runs", json={"force": False})

    assert response.status_code == 404
    assert response.json() == {"detail": "Assessment not found."}


def test_post_analysis_run_persists_run(client, db_session, seeded_assessment):
    question, options = add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Business Continuity",
        options=[
            ("Selected", RiskLevel.HIGH, 2.0, "High continuity signal."),
            ("Maximum", RiskLevel.CRITICAL, 4.0, "Maximum continuity signal."),
        ],
    )
    add_response(db_session, seeded_assessment["assessment_id"], question, options[0])

    response = client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/analysis-runs",
        json={"force": False},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    run = db_session.get(QuestionAnalysisRun, response.json()["analysisRunId"])
    assert run is not None
    assert run.scoring_config_version == "inherent-risk-v1-percentage"
    assert run.triage_score == 2.0
    assert run.inherent_score == 50.0
    assert run.inherent_risk_level == "high"


def test_post_executive_summary_persists_and_get_returns_saved_summary(
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

    question, options = add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Business Continuity",
        why_it_matters="DB why-it-matters",
        options=[
            ("Selected", RiskLevel.HIGH, 2.0, "DB risk signal"),
            ("Maximum", RiskLevel.CRITICAL, 4.0, "Maximum continuity signal"),
        ],
    )
    add_response(db_session, seeded_assessment["assessment_id"], question, options[0])

    summary_response = client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/inherent-risk/executive-summary",
        json={"force": False},
    )

    assert summary_response.status_code == 200
    assert summary_response.json()["assessmentId"] == seeded_assessment["assessment_id"]
    assert summary_response.json()["executiveSummary"]["text"] == "Generated executive summary."
    assert summary_response.json()["executiveSummary"]["status"] == "generated"
    assert fake_client.calls == 1

    get_response = client.get(f"/api/v1/assessments/{seeded_assessment['assessment_id']}/inherent-risk")

    assert get_response.status_code == 200
    assert get_response.json()["executiveSummary"]["text"] == "Generated executive summary."
    assert get_response.json()["executiveSummary"]["status"] == "generated"

    app.dependency_overrides.pop(get_executive_summary_prompt_loader, None)
    app.dependency_overrides.pop(get_azure_executive_summary_client, None)


def test_get_endpoint_returns_controlled_not_assessed_response(client, seeded_assessment):
    response = client.get(f"/api/v1/assessments/{seeded_assessment['assessment_id']}/inherent-risk")

    assert response.status_code == 200
    assert response.json() == {
        "assessmentId": seeded_assessment["assessment_id"],
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


def test_get_returns_latest_successful_run_when_failed_run_exists(client, db_session, seeded_assessment):
    question, options = add_question_with_options(
        db_session,
        seeded_assessment["questionnaire_version_id"],
        risk_domain="Security",
        options=[
            ("Selected", RiskLevel.HIGH, 2.0, "High security signal."),
            ("Maximum", RiskLevel.CRITICAL, 4.0, "Maximum security signal."),
        ],
    )
    add_response(db_session, seeded_assessment["assessment_id"], question, options[0])

    created = client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/analysis-runs",
        json={"force": False},
    ).json()

    db_session.add(
        QuestionAnalysisRun(
            id=str(uuid4()),
            assessment_id=seeded_assessment["assessment_id"],
            status=AnalysisRunStatus.FAILED.value,
            scoring_config_version="inherent-risk-v1-percentage",
            overall_risk_level=RiskLevel.NOT_ASSESSED.value,
            source_text="Derived from SAR triage questions.",
        )
    )
    db_session.commit()

    response = client.get(f"/api/v1/assessments/{seeded_assessment['assessment_id']}/inherent-risk")

    assert response.status_code == 200
    assert response.json()["analysisRunId"] == created["analysisRunId"]
