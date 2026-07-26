from __future__ import annotations

import hashlib
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.api.dependencies import get_session
from app.main import app
from app.models.database import AssessmentDocument, DocumentChecklistRun, SarAssessment
from app.models.enums import DocumentType
from app.services.document_checklist_service import DocumentChecklistService

pytestmark = pytest.mark.asyncio


async def test_upload_persists_metadata_and_sha256(client, db_session, seeded_assessment):
    content = b"soc2 report"

    response = await upload_document(
        client,
        seeded_assessment["assessment_id"],
        filename="soc2.pdf",
        content=content,
        system_document_type=DocumentType.SOC2_TYPE_II.value,
    )

    assert response.status_code == 200
    payload = response.json()
    document = await db_session.get(AssessmentDocument, uuid.UUID(payload["document_id"]))
    assert document is not None
    assert payload["assessment_id"] == str(seeded_assessment["assessment_id"])
    assert payload["original_filename"] == "soc2.pdf"
    assert payload["content_type"] == "application/pdf"
    assert payload["file_size_bytes"] == len(content)
    assert payload["sha256"] == hashlib.sha256(content).hexdigest()
    assert payload["system_document_type"] == DocumentType.SOC2_TYPE_II.value
    assert document.storage_container == "sar-documents"
    assert document.storage_key


async def test_upload_rejects_duplicate_active_sha256(client, seeded_assessment):
    content = b"duplicate"
    first = await upload_document(client, seeded_assessment["assessment_id"], content=content)
    second = await upload_document(client, seeded_assessment["assessment_id"], content=content)

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json() == {"detail": "Duplicate active document content."}


async def test_upload_allows_same_sha256_after_prior_document_is_soft_deleted(client, seeded_assessment):
    content = b"same-after-delete"
    first = await upload_document(client, seeded_assessment["assessment_id"], content=content)
    await client.delete(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/documents/{first.json()['document_id']}"
    )

    second = await upload_document(client, seeded_assessment["assessment_id"], content=content)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["sha256"] == second.json()["sha256"]
    assert first.json()["document_id"] != second.json()["document_id"]


async def test_list_returns_active_documents_only(client, seeded_assessment):
    active = await upload_document(client, seeded_assessment["assessment_id"], filename="active.pdf", content=b"active")
    deleted = await upload_document(
        client,
        seeded_assessment["assessment_id"],
        filename="deleted.pdf",
        content=b"deleted",
    )
    await client.delete(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/documents/{deleted.json()['document_id']}"
    )

    response = await client.get(f"/api/v1/assessments/{seeded_assessment['assessment_id']}/documents")

    assert response.status_code == 200
    assert [document["document_id"] for document in response.json()["documents"]] == [active.json()["document_id"]]


async def test_delete_performs_soft_delete(client, db_session, seeded_assessment):
    uploaded = await upload_document(client, seeded_assessment["assessment_id"], content=b"delete-me")

    response = await client.delete(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/documents/{uploaded.json()['document_id']}",
        params={"deleted_by": "reviewer@example.com"},
    )

    document = await db_session.get(AssessmentDocument, uuid.UUID(uploaded.json()["document_id"]))
    assert response.status_code == 200
    assert response.json()["deleted_at"] is not None
    assert document is not None
    assert document.deleted_at is not None
    assert document.deleted_by == "reviewer@example.com"


async def test_cross_assessment_document_delete_is_rejected(client, db_session, seeded_assessment):
    other_assessment = SarAssessment(
        id=uuid.uuid4(),
        technology_name="Other",
        vendor_name="Other Vendor",
        product_name="Other Product",
    )
    db_session.add(other_assessment)
    await db_session.commit()
    uploaded = await upload_document(client, other_assessment.id, content=b"other")

    response = await client.delete(
        f"/api/v1/assessments/{seeded_assessment['assessment_id']}/documents/{uploaded.json()['document_id']}"
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Document not found."}


async def test_upload_does_not_regenerate_existing_checklist(client, db_session, seeded_assessment):
    await DocumentChecklistService().generate_checklist_run(db_session, seeded_assessment["assessment_id"])
    await db_session.commit()

    response = await upload_document(
        client,
        seeded_assessment["assessment_id"],
        filename="soc2.pdf",
        content=b"soc2 uploaded later",
        system_document_type=DocumentType.SOC2_TYPE_II.value,
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


async def test_upload_commits_once(session_factory, seeded_assessment):
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
                response = await upload_document(
                    test_client,
                    seeded_assessment["assessment_id"],
                    content=b"commit-once",
                )
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 200
    assert commit_calls == 1


async def upload_document(
    client,
    assessment_id: uuid.UUID,
    *,
    filename: str = "document.pdf",
    content: bytes = b"document",
    content_type: str = "application/pdf",
    system_document_type: str = "Unclassified",
):
    return await client.post(
        f"/api/v1/assessments/{assessment_id}/documents",
        data={"system_document_type": system_document_type},
        files={"file": (filename, content, content_type)},
    )
