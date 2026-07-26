from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.api.dependencies import get_session
from app.main import app
from app.models.database import DocumentClassificationReview, DocumentChecklistRun, SarAssessment
from app.models.enums import DocumentType
from app.repositories.document_repository import DocumentRepository
from app.services.document_checklist_service import DocumentChecklistService

pytestmark = pytest.mark.asyncio


async def test_classification_review_created(client, db_session, seeded_assessment):
    document = await upload_document(client, seeded_assessment["assessment_id"])

    response = await create_review(
        client,
        seeded_assessment["assessment_id"],
        document["document_id"],
        document_type=DocumentType.SOC2_TYPE_II.value,
        reason="Reviewer identified SOC 2.",
    )

    review = await db_session.get(DocumentClassificationReview, uuid.UUID(response.json()["review_id"]))
    assert response.status_code == 200
    assert response.json()["document_id"] == document["document_id"]
    assert response.json()["document_type"] == DocumentType.SOC2_TYPE_II.value
    assert response.json()["effective_document_type"] == DocumentType.SOC2_TYPE_II.value
    assert review is not None
    assert review.reason == "Reviewer identified SOC 2."


async def test_latest_review_becomes_effective_classification(client, db_session, seeded_assessment):
    document = await upload_document(client, seeded_assessment["assessment_id"])
    first = await create_review(
        client,
        seeded_assessment["assessment_id"],
        document["document_id"],
        document_type=DocumentType.SOC2_TYPE_II.value,
        reason="Initial classification.",
    )
    second = await create_review(
        client,
        seeded_assessment["assessment_id"],
        document["document_id"],
        document_type=DocumentType.ARCHITECTURE_DIAGRAM.value,
        reason="Latest classification.",
    )

    first_review = await db_session.get(DocumentClassificationReview, uuid.UUID(first.json()["review_id"]))
    second_review = await db_session.get(DocumentClassificationReview, uuid.UUID(second.json()["review_id"]))
    first_review.created_at = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    second_review.created_at = datetime(2026, 7, 20, 12, 1, tzinfo=timezone.utc)
    await db_session.commit()

    documents = await DocumentRepository().list_active_documents_by_assessment(
        db_session,
        seeded_assessment["assessment_id"],
    )

    assert documents[0].effective_document_type == DocumentType.ARCHITECTURE_DIAGRAM.value


async def test_previous_classification_reviews_remain_unchanged(client, db_session, seeded_assessment):
    document = await upload_document(client, seeded_assessment["assessment_id"])
    first = await create_review(
        client,
        seeded_assessment["assessment_id"],
        document["document_id"],
        document_type=DocumentType.SOC2_TYPE_II.value,
        reason="Initial review.",
    )
    await create_review(
        client,
        seeded_assessment["assessment_id"],
        document["document_id"],
        document_type=DocumentType.ISO_27001.value,
        reason="Second review.",
    )

    first_review = await db_session.get(DocumentClassificationReview, uuid.UUID(first.json()["review_id"]))
    review_count = await db_session.scalar(select(func.count()).select_from(DocumentClassificationReview))
    assert review_count == 2
    assert first_review.document_type == DocumentType.SOC2_TYPE_II.value
    assert first_review.reason == "Initial review."


async def test_invalid_document_type_rejected(client, seeded_assessment):
    document = await upload_document(client, seeded_assessment["assessment_id"])

    response = await create_review(
        client,
        seeded_assessment["assessment_id"],
        document["document_id"],
        document_type="Unclassified",
        reason="Invalid manual type.",
    )

    assert response.status_code == 422


async def test_missing_reason_rejected(client, seeded_assessment):
    document = await upload_document(client, seeded_assessment["assessment_id"])

    response = await client.post(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/documents/{document['document_id']}/classification-reviews",
        json={"document_type": DocumentType.SOC2_TYPE_II.value},
    )

    assert response.status_code == 422


async def test_soft_deleted_document_rejected(client, seeded_assessment):
    document = await upload_document(client, seeded_assessment["assessment_id"])
    await client.delete(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/documents/{document['document_id']}"
    )

    response = await create_review(
        client,
        seeded_assessment["assessment_id"],
        document["document_id"],
        document_type=DocumentType.SOC2_TYPE_II.value,
        reason="Deleted document.",
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Document not found."}


async def test_cross_assessment_document_rejected(client, db_session, seeded_assessment):
    other_assessment = SarAssessment(
        id=uuid.uuid4(),
        technology_name="Other",
        vendor_name="Other Vendor",
        product_name="Other Product",
    )
    db_session.add(other_assessment)
    await db_session.commit()
    other_document = await upload_document(client, other_assessment.id)

    response = await create_review(
        client,
        seeded_assessment["assessment_id"],
        other_document["document_id"],
        document_type=DocumentType.SOC2_TYPE_II.value,
        reason="Wrong assessment.",
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Document not found."}


async def test_classification_review_does_not_regenerate_checklist(client, db_session, seeded_assessment):
    document = await upload_document(client, seeded_assessment["assessment_id"], system_document_type="Unclassified")
    await DocumentChecklistService().generate_checklist_run(db_session, seeded_assessment["assessment_id"])
    await db_session.commit()

    response = await create_review(
        client,
        seeded_assessment["assessment_id"],
        document["document_id"],
        document_type=DocumentType.SOC2_TYPE_II.value,
        reason="Classify after checklist generation.",
    )
    checklist_response = await client.get(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/document-checklist"
    )
    run_count = await db_session.scalar(select(func.count()).select_from(DocumentChecklistRun))
    soc2_item = next(
        item for item in checklist_response.json()["items"] if item["document_type"] == DocumentType.SOC2_TYPE_II.value
    )

    assert response.status_code == 200
    assert run_count == 1
    assert soc2_item["detected_file_status"] == "missing"
    assert soc2_item["detected_document_id"] is None


async def test_classification_review_api_commits_once(session_factory, seeded_assessment):
    async with session_factory() as seed_session:
        document = await upload_document_with_session(seed_session, seeded_assessment["assessment_id"])

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
                response = await create_review(
                    test_client,
                    seeded_assessment["assessment_id"],
                    str(document["document_id"]),
                    document_type=DocumentType.SOC2_TYPE_II.value,
                    reason="Commit once.",
                )
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 200
    assert commit_calls == 1


async def upload_document(
    client,
    assessment_id: uuid.UUID,
    *,
    system_document_type: str = "Unclassified",
) -> dict[str, object]:
    response = await client.post(
        f"/api/v1/assessments/{assessment_id}/documents",
        data={"system_document_type": system_document_type},
        files={"file": (f"{uuid.uuid4()}.pdf", b"classification", "application/pdf")},
    )
    assert response.status_code == 200
    return response.json()


async def upload_document_with_session(session, assessment_id: uuid.UUID) -> dict[str, object]:
    async def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as test_client:
            return await upload_document(test_client, assessment_id)
    finally:
        app.dependency_overrides.clear()


async def create_review(
    client,
    assessment_id: uuid.UUID,
    document_id: str,
    *,
    document_type: str,
    reason: str,
):
    return await client.post(
        f"/api/v1/assessments/{assessment_id}/documents/{document_id}/classification-reviews",
        json={"document_type": document_type, "reason": reason},
    )
