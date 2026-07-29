from __future__ import annotations

from datetime import datetime, timezone
import base64
import hashlib
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID
from zipfile import ZipFile

from app.application.models import (
    ReportPreviewArchitecture as ReportPreviewArchitectureDTO,
    ReportPreviewAssessment as ReportPreviewAssessmentDTO,
    ReportPreviewBusinessContactDetails as ReportPreviewBusinessContactDetailsDTO,
    ReportPreviewBusinessContinuity as ReportPreviewBusinessContinuityDTO,
    ReportPreviewDataFlow as ReportPreviewDataFlowDTO,
    ReportPreviewDataHosted as ReportPreviewDataHostedDTO,
    ReportPreviewDocumentChecklist as ReportPreviewDocumentChecklistDTO,
    ReportPreviewHosting as ReportPreviewHostingDTO,
    ReportPreviewResult as ReportPreviewResponseDTO,
    ReportPreviewRiskAssessment as ReportPreviewRiskAssessmentDTO,
    ReportPreviewSolutionOverview as ReportPreviewSolutionOverviewDTO,
    ReportPreviewThirdPartyMeasures as ReportPreviewThirdPartyMeasuresDTO,
    ReportPreviewVendorReputation as ReportPreviewVendorReputationDTO,
)
from app.services.initial_sar_report_renderer import (
    DOCX_CONTENT_TYPE,
    InitialSarReportRenderer,
)


ONE_BY_ONE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Z0XQAAAAASUVORK5CYII="
)


def test_render_returns_docx_bytes_and_expected_metadata():
    renderer = InitialSarReportRenderer()
    preview = build_preview_dto()

    rendered = renderer.render(preview)

    assert rendered.original_filename == "initial-sar-report-00000000-0000-0000-0000-000000000001.docx"
    assert rendered.content_type == DOCX_CONTENT_TYPE
    assert rendered.file_size_bytes == len(rendered.bytes)
    assert rendered.sha256 == hashlib.sha256(rendered.bytes).hexdigest()

    document_xml = read_docx_entry(rendered.bytes, "word/document.xml")
    assert "{{" not in document_xml
    assert "{%" not in document_xml
    assert "Initial Security Assessment Report" in document_xml
    assert "Copilot" in document_xml
    assert "ServiceNow" not in document_xml
    assert "Security" in document_xml
    assert "Critical question" in document_xml
    assert "SOC 2 Type II" in document_xml
    assert "Uploaded as part of intake." in document_xml
    assert "Vendor review pending." in document_xml


def test_render_uses_template_defaults_for_missing_optional_fields():
    renderer = InitialSarReportRenderer()
    preview = build_preview_dto(
        technology_name=None,
        executive_summary=None,
        architecture_details=None,
        third_party_assessment=None,
        checklist_summary=None,
        vendor_reputation_summary=None,
        limitations=[],
    )
    object.__setattr__(preview, "vendorReputation", None)

    rendered = renderer.render(preview)

    document_xml = read_docx_entry(rendered.bytes, "word/document.xml")
    assert "{{" not in document_xml
    assert "{%" not in document_xml
    assert "Not provided" in document_xml
    assert "No executive summary is available." in document_xml
    assert "No architecture narrative was provided." in document_xml
    assert "No checklist summary is available." in document_xml
    assert "Vendor Reputation is not available." in document_xml
    assert "No limitations recorded." in document_xml


def test_render_embeds_architecture_image_when_image_bytes_are_provided():
    renderer = InitialSarReportRenderer()
    preview = build_preview_dto()

    rendered = renderer.render(preview, architecture_image_bytes=ONE_BY_ONE_PNG)

    document_xml = read_docx_entry(rendered.bytes, "word/document.xml")
    document_relationships_xml = read_docx_entry(rendered.bytes, "word/_rels/document.xml.rels")
    content_types_xml = read_docx_entry(rendered.bytes, "[Content_Types].xml")

    assert "__INLINE_IMAGE__" not in document_xml
    assert "Architecture Diagram" in document_xml
    assert "rId11" in document_relationships_xml
    assert "media/architecture_diagram.png" in document_relationships_xml
    assert 'Extension="png"' in content_types_xml
    with ZipFile(BytesIO(rendered.bytes)) as archive:
        assert archive.read("word/media/architecture_diagram.png") == ONE_BY_ONE_PNG


def read_docx_entry(docx_bytes: bytes, entry_name: str) -> str:
    with ZipFile(BytesIO(docx_bytes)) as archive:
        return archive.read(entry_name).decode("utf-8")


def build_preview_dto(
    *,
    technology_name: str | None = "Copilot",
    executive_summary: str | None = "Deterministic executive summary.",
    architecture_details: str | None = "Architecture narrative.",
    third_party_assessment: str | None = "SOC 2 Type II",
    checklist_summary: str | None = "Checklist summary text.",
    vendor_reputation_summary: str | None = "Vendor review pending.",
    limitations: list[str] | None = None,
) -> ReportPreviewResponseDTO:
    preview = ReportPreviewResponseDTO(
        assessmentId=UUID("00000000-0000-0000-0000-000000000001"),
        generatedAt=datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc),
        assessment=ReportPreviewAssessmentDTO(
            technologyName=technology_name,
            sourceSystem="ServiceNow",
            questionnaireVersion="2.0",
        ),
        riskAssessment=ReportPreviewRiskAssessmentDTO(
            inherentRiskLevel="high",
            executiveSummary=executive_summary,
        ),
        businessContactDetails=ReportPreviewBusinessContactDetailsDTO(
            businessUnit="Tax",
            sponsorBusinessOwner="Jane Smith",
        ),
        solutionOverview=ReportPreviewSolutionOverviewDTO(
            launchDate="2026-09-01",
            businessFunctionSolutionOverview="Supports analyst workflows.",
        ),
        architecture=ReportPreviewArchitectureDTO(
            architectureDetails=architecture_details,
        ),
        hosting=ReportPreviewHostingDTO(
            hostingModel="SaaS",
            hostedBy="Vendor",
            accessedBy="Internal users",
        ),
        dataHosted=ReportPreviewDataHostedDTO(
            dataResidency="United States",
            confidentiality="Confidential",
            integrity="High",
        ),
        dataFlow=ReportPreviewDataFlowDTO(
            dataFlow="Users submit data through the vendor portal.",
        ),
        businessContinuity=ReportPreviewBusinessContinuityDTO(
            businessContinuityRating="Tier 2",
            rpoRto="RPO 4 hours / RTO 8 hours",
            backupAndRestore="Vendor-managed backups",
        ),
        thirdPartyMeasures=ReportPreviewThirdPartyMeasuresDTO(
            thirdPartyAssessment=third_party_assessment,
            sla="24x7 support",
        ),
        documentChecklist=ReportPreviewDocumentChecklistDTO(summary=checklist_summary),
        vendorReputation=ReportPreviewVendorReputationDTO(summary=vendor_reputation_summary),
        limitations=limitations if limitations is not None else ["Architecture details were not provided."],
    )

    object.__setattr__(preview.riskAssessment, "analysisRunId", "analysis-run-1")
    object.__setattr__(preview.riskAssessment, "status", "completed")
    object.__setattr__(
        preview.riskAssessment,
        "topRiskDrivers",
        [
            {
                "domain": "Security",
                "level": "critical",
                "question": "Critical question",
                "response": "Yes",
                "reason": "Sensitive data is processed.",
            },
            {
                "domain": "Operations",
                "level": "high",
                "question": "High impact question",
                "response": "Vendor-managed",
                "reason": "Dependency on third-party uptime.",
            },
        ],
    )

    object.__setattr__(preview.architecture, "documentId", "architecture-doc-1")
    object.__setattr__(preview.architecture, "filename", "architecture.png")
    object.__setattr__(preview.architecture, "contentType", "image/png")

    object.__setattr__(preview.documentChecklist, "runId", "checklist-run-1")
    object.__setattr__(preview.documentChecklist, "status", "draft_with_limitations")
    object.__setattr__(preview.documentChecklist, "missingRequiredCount", 2)
    object.__setattr__(
        preview.documentChecklist,
        "items",
        [
            {
                "documentType": "SOC 2 Type II",
                "effectiveVerdict": "Required",
                "detectedFileStatus": "Uploaded",
                "filename": "soc2.pdf",
                "reviewerReason": "Uploaded as part of intake.",
            },
            {
                "documentType": "Architecture Diagram",
                "effectiveVerdict": "Recommended",
                "detectedFileStatus": "Missing",
                "filename": None,
                "reviewerReason": None,
            },
        ],
    )

    vendor_reputation = preview.vendorReputation or ReportPreviewVendorReputationDTO()
    object.__setattr__(vendor_reputation, "status", "available")
    object.__setattr__(vendor_reputation, "summary", vendor_reputation_summary)
    object.__setattr__(
        vendor_reputation,
        "rows",
        [
            SimpleNamespace(
                category="Trust center",
                sentiment="Neutral",
                interpretation="Public trust center was found.",
                riskImpact="Limited external evidence.",
                confidence="Medium",
                sources="Vendor website",
            )
        ],
    )
    object.__setattr__(preview, "vendorReputation", vendor_reputation)

    return preview
