from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import uuid

import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from app.api.dependencies import get_session
from app.api.router import api_router
from app.api.v1.document_checklist import get_document_checklist_service
from app.main import app
from app.models.database import AssessmentDocument, DocumentChecklistRun
from app.models.enums import ChecklistVerdict, DocumentType
from app.repositories.document_checklist_repository import DocumentChecklistRepository
from app.repositories.vendor_certification_repository import vendor_reputation_hitl_reviews, vendor_reputation_jobs
from app.services.document_checklist_service import DocumentChecklistService

pytestmark = pytest.mark.asyncio

BASE_TIME = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)


async def test_post_creates_and_returns_new_run(client, db_session, seeded_assessment):
    await add_document(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        filename="soc2.pdf",
        system_document_type=DocumentType.SOC2_TYPE_II.value,
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/document-checklist/runs"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["assessment_id"] == str(seeded_assessment["assessment_id"])
    assert payload["status"] == "draft"
    assert payload["summary_text"] is None
    assert payload["summary_status"] == "failed"
    assert payload["limitations"] == []
    assert [item["item_order"] for item in payload["items"]] == [1, 2, 3]
    assert [item["document_type"] for item in payload["items"]] == [
        DocumentType.SOC2_TYPE_II.value,
        DocumentType.ISO_27001.value,
        DocumentType.ARCHITECTURE_DIAGRAM.value,
    ]
    assert payload["items"][0]["detected_file_status"] == "uploaded"
    assert payload["items"][0]["detected_document_id"] is not None
    assert await db_session.get(DocumentChecklistRun, uuid.UUID(payload["run_id"])) is not None


async def test_get_returns_latest_run(client, db_session, seeded_assessment):
    first_response = await client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/document-checklist/runs"
    )
    second_response = await client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/document-checklist/runs"
    )

    response = await client.get(f"/api/v1/assessments/{seeded_assessment['assessment_id']}/document-checklist")

    assert response.status_code == 200
    assert first_response.json()["run_id"] != second_response.json()["run_id"]
    assert response.json()["run_id"] == second_response.json()["run_id"]
    assert [item["item_order"] for item in response.json()["items"]] == [1, 2, 3]


async def test_get_returns_404_when_absent(client, seeded_assessment):
    response = await client.get(f"/api/v1/assessments/{seeded_assessment['assessment_id']}/document-checklist")

    assert response.status_code == 404
    assert response.json() == {"detail": "Document checklist run not found."}


async def test_get_effective_verdict_uses_latest_review_and_null_clears_override(client, db_session, seeded_assessment):
    post_response = await client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/document-checklist/runs"
    )
    run_id = post_response.json()["run_id"]
    repository = DocumentChecklistRepository()
    older = await repository.append_checklist_verdict_review(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        document_type=DocumentType.ISO_27001,
        reviewer_verdict=ChecklistVerdict.RECOMMENDED,
        reason="Use current certification.",
    )
    ignored_null = await repository.append_checklist_verdict_review(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        document_type=DocumentType.ISO_27001,
        reviewer_verdict=None,
        reason="No override.",
    )
    older.created_at = BASE_TIME
    ignored_null.created_at = BASE_TIME + timedelta(minutes=1)
    await db_session.commit()

    response = await client.get(f"/api/v1/assessments/{seeded_assessment['assessment_id']}/document-checklist")

    assert response.status_code == 200
    assert response.json()["run_id"] == run_id
    iso_item = _item_by_type(response.json(), DocumentType.ISO_27001)
    assert iso_item["base_verdict"] == ChecklistVerdict.REQUIRED.value
    assert iso_item["effective_verdict"] == ChecklistVerdict.REQUIRED.value
    assert iso_item["reviewer_verdict"] is None
    assert iso_item["reviewer_reason"] == "No override."


async def test_vendor_reputation_does_not_mark_file_uploaded(client, db_session, seeded_assessment):
    await add_vendor_certification(
        db_session,
        assessment_id=seeded_assessment["assessment_id"],
        soc2_auto_status="Available",
        iso27001_auto_status="Missing",
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/document-checklist/runs"
    )

    assert response.status_code == 200
    soc2_item = _item_by_type(response.json(), DocumentType.SOC2_TYPE_II)
    assert soc2_item["detected_file_status"] == "missing"
    assert soc2_item["detected_document_id"] is None
    assert soc2_item["base_verdict"] == ChecklistVerdict.RECOMMENDED.value
    assert soc2_item["vendor_certification_automatic_status"] == "Available"
    assert soc2_item["vendor_certification_analyst_status"] is None
    assert soc2_item["vendor_certification_effective_status"] == "Available"


async def test_post_commits_once(session_factory, seeded_assessment):
    commit_calls = 0

    async with session_factory() as session:
        original_commit = session.commit

        async def commit_spy():
            nonlocal commit_calls
            commit_calls += 1
            await original_commit()

        session.commit = commit_spy

        async def override_get_session():
            yield session

        app.dependency_overrides[get_session] = override_get_session
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as test_client:
                response = await test_client.post(
                    f"/api/v1/assessments/{seeded_assessment['assessment_id']}/document-checklist/runs"
                )
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 200
    assert commit_calls == 1


async def test_get_does_not_commit_or_regenerate(session_factory, seeded_assessment):
    async with session_factory() as seed_session:
        await DocumentChecklistService().generate_checklist(seed_session, seeded_assessment["assessment_id"])
        await seed_session.commit()

    commit_calls = 0
    generate_calls = 0

    class GuardedService(DocumentChecklistService):
        async def generate_checklist(self, session, assessment_id):
            nonlocal generate_calls
            generate_calls += 1
            raise AssertionError("GET must not regenerate a checklist.")

    async with session_factory() as session:
        async def commit_spy():
            nonlocal commit_calls
            commit_calls += 1
            raise AssertionError("GET must not commit.")

        session.commit = commit_spy

        async def override_get_session():
            yield session

        app.dependency_overrides[get_session] = override_get_session
        app.dependency_overrides[get_document_checklist_service] = lambda: GuardedService()
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as test_client:
                response = await test_client.get(
                    f"/api/v1/assessments/{seeded_assessment['assessment_id']}/document-checklist"
                )
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 200
    assert commit_calls == 0
    assert generate_calls == 0


async def test_existing_api_routes_remain_unchanged():
    route_signature_list = [(route.path, tuple(sorted(route.methods))) for route in _api_routes()]
    route_signatures = set(route_signature_list)

    assert ("/api/v1/assessments/{assessment_id}/intake", ("GET",)) in route_signatures
    assert (
        "/api/v1/assessments/{assessment_id}/questions/{question_id}",
        ("PATCH",),
    ) in route_signatures
    assert ("/api/v1/assessments/{assessment_id}/inherent-risk", ("GET",)) in route_signatures
    assert ("/api/v1/assessments/{assessment_id}/analysis-runs", ("POST",)) in route_signatures
    assert ("/api/v1/assessments/{assessment_id}/ai-analysis", ("GET",)) in route_signatures
    assert all(count == 1 for count in Counter(route_signature_list).values())


async def add_document(
    session,
    *,
    assessment_id: uuid.UUID,
    filename: str,
    system_document_type: str,
) -> AssessmentDocument:
    document = AssessmentDocument(
        id=uuid.uuid4(),
        assessment_id=assessment_id,
        original_filename=filename,
        content_type="application/pdf",
        file_size_bytes=128,
        sha256=f"sha-{uuid.uuid4()}",
        storage_container="sar-documents",
        storage_key=f"{assessment_id}/{filename}",
        upload_source="sar_request",
        system_document_type=system_document_type,
        created_at=BASE_TIME,
        document_metadata={},
    )
    session.add(document)
    await session.flush()
    return document


async def add_vendor_certification(
    session,
    *,
    assessment_id: uuid.UUID,
    soc2_auto_status: str,
    iso27001_auto_status: str,
) -> None:
    job_id = uuid.uuid4()
    await session.execute(
        vendor_reputation_jobs.insert(),
        [
            {
                "id": job_id,
                "assessment_id": assessment_id,
                "vendor_name": "Vendor",
                "product_name": "Product",
                "pipeline_profile": "vendor_reputation_default",
                "status": "review_submitted",
                "requires_analyst_review": True,
                "created_at": BASE_TIME,
                "updated_at": BASE_TIME,
                "limitations": [],
                "metadata": {},
            }
        ],
    )
    await session.execute(
        vendor_reputation_hitl_reviews.insert(),
        [
            {
                "id": uuid.uuid4(),
                "job_id": job_id,
                "trust_center_scraped_char_count": 0,
                "soc2_auto_status": soc2_auto_status,
                "soc2_reviewer_status": None,
                "iso27001_auto_status": iso27001_auto_status,
                "iso27001_reviewer_status": None,
                "review_status": "pending",
                "limitations": [],
                "metadata": {},
                "created_at": BASE_TIME,
                "updated_at": BASE_TIME,
            }
        ],
    )


def _item_by_type(payload: dict[str, object], document_type: DocumentType) -> dict[str, object]:
    return next(item for item in payload["items"] if item["document_type"] == document_type.value)


def _api_routes() -> list[APIRoute]:
    flattened: list[APIRoute] = []
    for route in api_router.routes:
        if isinstance(route, APIRoute):
            flattened.append(route)
            continue
        nested_router = getattr(route, "original_router", None)
        if nested_router is not None:
            flattened.extend(
                nested_route for nested_route in nested_router.routes if isinstance(nested_route, APIRoute)
            )
    return flattened
