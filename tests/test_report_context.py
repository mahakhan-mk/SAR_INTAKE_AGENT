from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.assemblers.report_context_assembler import InitialSarReportContextAssembler
from app.services.initial_sar_report_renderer import InitialSarReportRenderer


def test_report_context_exposes_every_renderer_mapping_field() -> None:
    assessment_id = uuid4()
    analysis_id = uuid4()
    checklist_run_id = uuid4()
    architecture_id = uuid4()
    context = InitialSarReportContextAssembler().to_dto(
        assessment=SimpleNamespace(
            id=assessment_id,
            technology_name="Example Technology",
            vendor_name="Example Vendor",
            product_name="Example Product",
            requested_by="requester",
            created_at=datetime(2026, 7, 29, tzinfo=UTC),
        ),
        analysis_snapshot=SimpleNamespace(
            analysis_run_id=analysis_id,
            inherent_risk_level="High",
            executive_summary_text="Summary",
            status="completed",
            top_risk_drivers=[SimpleNamespace(domain="Data", level="High")],
        ),
        checklist_state=SimpleNamespace(
            run=SimpleNamespace(
                id=checklist_run_id,
                summary_text="Checklist summary",
                status="completed",
                limitations=[],
            ),
            items=[],
        ),
        architecture_document=SimpleNamespace(
            id=architecture_id,
            original_filename="architecture.png",
            content_type="image/png",
        ),
        vendor_reputation=SimpleNamespace(
            status="completed",
            rows=[
                SimpleNamespace(
                    category="Trust Center",
                    sentiment="Positive",
                    ai_interpretation="Published assurance material is available.",
                    risk_impact="Supports review.",
                    confidence="High",
                    sources=[],
                )
            ],
        ),
    )

    rendered_context = InitialSarReportRenderer()._build_context(context)

    assert rendered_context["vendor_name"] == "Example Vendor"
    assert rendered_context["product_name"] == "Example Product"
    assert rendered_context["requested_by"] == "requester"
    assert rendered_context["analysis_run_id"] == analysis_id
    assert rendered_context["checklist_run_id"] == checklist_run_id
    assert rendered_context["architecture_document_id"] == str(architecture_id)
    assert rendered_context["vendor_reputation_rows"][0]["interpretation"] == (
        "Published assurance material is available."
    )
