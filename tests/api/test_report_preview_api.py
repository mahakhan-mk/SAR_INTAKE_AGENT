from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_session
from app.main import app
from tests.unit.test_report_preview_service import TEST_ARCHITECTURE_DOCUMENT_ID, seed_report_preview_inputs

pytestmark = pytest.mark.asyncio


async def test_get_report_preview_returns_complete_preview_response(client, db_session, seeded_assessment):
    await seed_report_preview_inputs(db_session, seeded_assessment)

    response = await client.get(f"/api/v1/assessments/{seeded_assessment['assessment_id']}/report-preview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["assessmentId"] == str(seeded_assessment["assessment_id"])
    assert payload["assessment"]["technologyName"] == "Copilot"
    assert payload["assessment"]["questionnaireVersion"] == "intake-v2"
    assert payload["riskAssessment"]["status"] == "completed_with_limitations"
    assert payload["documentChecklist"]["missingRequiredCount"] == 2
    assert payload["architecture"] == {
        "architectureDetails": None,
        "documentId": str(TEST_ARCHITECTURE_DOCUMENT_ID),
        "filename": "architecture.pdf",
        "contentType": "application/pdf",
    }


async def test_get_report_preview_returns_partial_response_when_optional_inputs_are_missing(client, seeded_assessment):
    response = await client.get(f"/api/v1/assessments/{seeded_assessment['assessment_id']}/report-preview")

    assert response.status_code == 200
    assert response.json() == {
        "assessmentId": str(seeded_assessment["assessment_id"]),
        "generatedAt": response.json()["generatedAt"],
        "assessment": {
            "technologyName": "Copilot",
            "sourceSystem": None,
            "questionnaireVersion": None,
        },
        "riskAssessment": {
            "inherentRiskLevel": None,
            "executiveSummary": None,
            "status": None,
            "topRiskDrivers": [],
        },
        "businessContactDetails": {
            "businessUnit": None,
            "sponsorBusinessOwner": None,
        },
        "solutionOverview": {
            "launchDate": None,
            "businessFunctionSolutionOverview": None,
        },
        "architecture": {
            "architectureDetails": None,
            "documentId": None,
            "filename": None,
            "contentType": None,
        },
        "hosting": {
            "hostingModel": None,
            "hostedBy": None,
            "accessedBy": None,
        },
        "dataHosted": {
            "dataResidency": None,
            "confidentiality": None,
            "integrity": None,
        },
        "dataFlow": {
            "dataFlow": None,
        },
        "businessContinuity": {
            "businessContinuityRating": None,
            "rpoRto": None,
            "backupAndRestore": None,
        },
        "thirdPartyMeasures": {
            "thirdPartyAssessment": None,
            "sla": None,
        },
        "documentChecklist": {
            "summary": None,
            "status": None,
            "items": [],
            "missingRequiredCount": None,
        },
        "vendorReputation": None,
        "limitations": [
            "Risk assessment is unavailable.",
            "Document checklist is unavailable.",
            "Architecture document metadata is unavailable.",
            "Vendor reputation is unavailable.",
        ],
    }


async def test_get_report_preview_returns_404_for_unknown_assessment(client):
    response = await client.get(f"/api/v1/assessments/{uuid.uuid4()}/report-preview")

    assert response.status_code == 404
    assert response.json() == {"detail": "Assessment not found."}


async def test_get_report_preview_does_not_commit(session_factory, seeded_assessment):
    async with session_factory() as seed_session:
        await seed_report_preview_inputs(seed_session, seeded_assessment)

    commit_calls = 0
    async with session_factory() as session:
        async def commit_spy():
            nonlocal commit_calls
            commit_calls += 1
            raise AssertionError("GET must not commit.")

        session.commit = commit_spy

        async def override_get_session():
            yield session

        app.dependency_overrides[get_session] = override_get_session
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as test_client:
                response = await test_client.get(
                    f"/api/v1/assessments/{seeded_assessment['assessment_id']}/report-preview"
                )
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 200
    assert commit_calls == 0


async def test_get_report_preview_architecture_metadata_exposes_only_safe_fields(client, db_session, seeded_assessment):
    await seed_report_preview_inputs(db_session, seeded_assessment)

    response = await client.get(f"/api/v1/assessments/{seeded_assessment['assessment_id']}/report-preview")

    assert response.status_code == 200
    architecture = response.json()["architecture"]
    assert set(architecture.keys()) == {"architectureDetails", "documentId", "filename", "contentType"}
