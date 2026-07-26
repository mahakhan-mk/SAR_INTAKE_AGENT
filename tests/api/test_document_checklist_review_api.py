from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.api.dependencies import get_session
from app.main import app
from app.models.database import AssessmentDocument, DocumentChecklistItem, DocumentChecklistItemReview, SarAssessment
from app.models.enums import ChecklistVerdict, DocumentType
from app.services.document_checklist_service import DocumentChecklistService

pytestmark = pytest.mark.asyncio


async def test_review_endpoint_creates_append_only_review(client, db_session, seeded_assessment):
    item = await create_run_item(client, seeded_assessment["assessment_id"], DocumentType.ISO_27001)

    first = await client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/document-checklist/items/{item['item_id']}/reviews",
        json={"reviewer_verdict": "Recommended", "reason": "Certification is available under NDA."},
    )
    second = await client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/document-checklist/items/{item['item_id']}/reviews",
        json={"reviewer_verdict": "N/A", "reason": "Reviewer accepted compensating evidence."},
    )

    review_count = await db_session.scalar(select(func.count()).select_from(DocumentChecklistItemReview))
    assert first.status_code == 200
    assert second.status_code == 200
    assert review_count == 2
    assert second.json()["effective_verdict"] == ChecklistVerdict.NOT_APPLICABLE.value
    assert second.json()["reviewer_reason"] == "Reviewer accepted compensating evidence."


async def test_review_endpoint_null_verdict_clears_override(client, seeded_assessment):
    item = await create_run_item(client, seeded_assessment["assessment_id"], DocumentType.ARCHITECTURE_DIAGRAM)
    await client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/document-checklist/items/{item['item_id']}/reviews",
        json={"reviewer_verdict": "N/A", "reason": "Diagram is not needed."},
    )

    response = await client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/document-checklist/items/{item['item_id']}/reviews",
        json={"reviewer_verdict": None, "reason": "Clear override."},
    )

    assert response.status_code == 200
    assert response.json()["base_verdict"] == ChecklistVerdict.REQUIRED.value
    assert response.json()["effective_verdict"] == ChecklistVerdict.REQUIRED.value
    assert response.json()["reviewer_verdict"] is None
    assert response.json()["reviewer_reason"] == "Clear override."


async def test_review_endpoint_rejects_non_null_verdict_without_reason(client, seeded_assessment):
    item = await create_run_item(client, seeded_assessment["assessment_id"], DocumentType.SOC2_TYPE_II)

    response = await client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/document-checklist/items/{item['item_id']}/reviews",
        json={"reviewer_verdict": "Recommended"},
    )

    assert response.status_code == 422
    assert "reason is required" in str(response.json())


async def test_review_endpoint_rejects_item_from_another_assessment(client, db_session, seeded_assessment):
    other_assessment = SarAssessment(
        id=uuid.uuid4(),
        technology_name="Other",
        vendor_name="Other Vendor",
        product_name="Other Product",
    )
    db_session.add(other_assessment)
    await db_session.commit()
    other_item = await create_run_item(client, other_assessment.id, DocumentType.SOC2_TYPE_II)

    response = await client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/document-checklist/items/{other_item['item_id']}/reviews",
        json={"reviewer_verdict": "Recommended", "reason": "Wrong assessment."},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Document checklist item not found."}


async def test_review_endpoint_unknown_assessment_or_item_returns_404(client, seeded_assessment):
    item = await create_run_item(client, seeded_assessment["assessment_id"], DocumentType.SOC2_TYPE_II)

    unknown_assessment_response = await client.post(
        f"/api/v1/assessments/{uuid.uuid4()}/document-checklist/items/{item['item_id']}/reviews",
        json={"reviewer_verdict": "Recommended", "reason": "Unknown assessment."},
    )
    unknown_item_response = await client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/document-checklist/items/{uuid.uuid4()}/reviews",
        json={"reviewer_verdict": "Recommended", "reason": "Unknown item."},
    )

    assert unknown_assessment_response.status_code == 404
    assert unknown_assessment_response.json() == {"detail": "Document checklist item not found."}
    assert unknown_item_response.status_code == 404
    assert unknown_item_response.json() == {"detail": "Document checklist item not found."}


async def test_review_endpoint_preserves_base_verdict_and_detected_file_status(client, db_session, seeded_assessment):
    document = AssessmentDocument(
        id=uuid.uuid4(),
        assessment_id=seeded_assessment["assessment_id"],
        original_filename="soc2.pdf",
        content_type="application/pdf",
        file_size_bytes=128,
        sha256=f"sha-{uuid.uuid4()}",
        storage_container="sar-documents",
        storage_key=f"{seeded_assessment['assessment_id']}/soc2.pdf",
        upload_source="sar_request",
        system_document_type=DocumentType.SOC2_TYPE_II.value,
        document_metadata={},
    )
    db_session.add(document)
    await db_session.commit()
    item = await create_run_item(client, seeded_assessment["assessment_id"], DocumentType.SOC2_TYPE_II)
    item_model = await db_session.get(DocumentChecklistItem, uuid.UUID(item["item_id"]))

    response = await client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/document-checklist/items/{item['item_id']}/reviews",
        json={"reviewer_verdict": "Required", "reason": "Reviewer wants explicit evidence."},
    )

    await db_session.refresh(item_model)
    assert response.status_code == 200
    assert response.json()["base_verdict"] == ChecklistVerdict.NOT_APPLICABLE.value
    assert response.json()["effective_verdict"] == ChecklistVerdict.REQUIRED.value
    assert response.json()["detected_file_status"] == "uploaded"
    assert response.json()["detected_document_id"] == str(document.id)
    assert item_model.base_verdict == ChecklistVerdict.NOT_APPLICABLE.value


async def test_review_endpoint_commits_once(session_factory, seeded_assessment):
    async with session_factory() as seed_session:
        run = await DocumentChecklistService().generate_checklist_run(seed_session, seeded_assessment["assessment_id"])
        item_id = run.items[0].item.id
        await seed_session.commit()

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
                    f"/api/v1/assessments/{seeded_assessment['assessment_id']}/document-checklist/items/{item_id}/reviews",
                    json={"reviewer_verdict": "Recommended", "reason": "Reviewer accepted certification."},
                )
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 200
    assert commit_calls == 1


async def create_run_item(client, assessment_id: uuid.UUID, document_type: DocumentType) -> dict[str, object]:
    response = await client.post(f"/api/v1/assessments/{assessment_id}/document-checklist/runs")
    assert response.status_code == 200
    return next(item for item in response.json()["items"] if item["document_type"] == document_type.value)
