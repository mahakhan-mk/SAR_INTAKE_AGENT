from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.application.models import (
    InitialSarReportArchitecture,
    InitialSarReportAssessment,
    InitialSarReportBusinessContactDetails,
    InitialSarReportBusinessContinuity,
    InitialSarReportDataFlow,
    InitialSarReportDataHosted,
    InitialSarReportDocumentChecklist,
    InitialSarReportHosting,
    InitialSarReportContext,
    InitialSarReportRiskAssessment,
    InitialSarReportSolutionOverview,
    InitialSarReportThirdPartyMeasures,
    InitialSarReportVendorReputation,
)
from app.models.initial_sar_report_context import (
    INITIAL_SAR_REPORT_QUESTION_CODE_TO_FIELD_NAME,
)


class InitialSarReportContextAssembler:
    def to_dto(
        self,
        *,
        assessment: object,
        response_records: list[object] | None = None,
        analysis_snapshot: object | None = None,
        checklist_state: object | None = None,
        architecture_document: object | None = None,
        generated_at: datetime | None = None,
        questionnaire_version: str | None = None,
        source_system: str | None = None,
        vendor_reputation: object | None = None,
    ) -> InitialSarReportContext:
        section_values: dict[str, dict[str, object]] = {
            "businessContactDetails": {},
            "solutionOverview": {},
            "hosting": {},
            "dataHosted": {},
            "dataFlow": {},
            "businessContinuity": {},
            "thirdPartyMeasures": {},
        }

        for record in response_records or []:
            question_code = self._read_attr(record, "question_code", "questionCode")
            mapping_target = INITIAL_SAR_REPORT_QUESTION_CODE_TO_FIELD_NAME.get(question_code)
            if mapping_target is None:
                continue

            answer_value = self._coerce_answer_to_string(
                self._read_attr(record, "answer_value", "answerValue"),
            )
            if answer_value is None:
                continue

            section_name, field_name = mapping_target.split(".", 1)
            section_values[section_name][field_name] = answer_value

        risk_assessment = self._build_risk_assessment(analysis_snapshot)
        architecture = self._build_architecture(architecture_document)
        document_checklist = self._build_document_checklist(checklist_state)

        return InitialSarReportContext(
            assessmentId=self._coerce_uuid(self._read_attr(assessment, "id", "assessment_id", "assessmentId")),
            generatedAt=generated_at or datetime.now(timezone.utc),
            assessment=InitialSarReportAssessment(
                technologyName=self._read_attr(assessment, "technology_name", "technologyName"),
                vendorName=self._read_attr(assessment, "vendor_name", "vendorName"),
                productName=self._read_attr(assessment, "product_name", "productName"),
                requestedBy=self._read_attr(assessment, "requested_by", "requestedBy"),
                createdAt=self._read_attr(assessment, "created_at", "createdAt"),
                sourceSystem=source_system or self._read_attr(assessment, "source_system", "sourceSystem"),
                questionnaireVersion=questionnaire_version
                or self._read_attr(assessment, "questionnaire_version", "questionnaireVersion"),
            ),
            riskAssessment=risk_assessment,
            businessContactDetails=InitialSarReportBusinessContactDetails(**section_values["businessContactDetails"]),
            solutionOverview=InitialSarReportSolutionOverview(**section_values["solutionOverview"]),
            architecture=architecture,
            hosting=InitialSarReportHosting(**section_values["hosting"]),
            dataHosted=InitialSarReportDataHosted(**section_values["dataHosted"]),
            dataFlow=InitialSarReportDataFlow(**section_values["dataFlow"]),
            businessContinuity=InitialSarReportBusinessContinuity(**section_values["businessContinuity"]),
            thirdPartyMeasures=InitialSarReportThirdPartyMeasures(**section_values["thirdPartyMeasures"]),
            documentChecklist=document_checklist,
            vendorReputation=self._build_vendor_reputation(vendor_reputation),
            limitations=self._build_limitations(
                analysis_snapshot=analysis_snapshot,
                checklist_state=checklist_state,
                architecture_document=architecture_document,
                vendor_reputation=vendor_reputation,
            ),
        )

    def _build_risk_assessment(self, analysis_snapshot: object | None) -> InitialSarReportRiskAssessment:
        if analysis_snapshot is None:
            return InitialSarReportRiskAssessment(
                analysisRunId=None,
                inherentRiskLevel=None,
                executiveSummary=None,
                status=None,
                topRiskDrivers=[],
            )

        top_risk_drivers = self._derive_top_risk_drivers(analysis_snapshot)
        return InitialSarReportRiskAssessment(
            analysisRunId=self._read_attr(analysis_snapshot, "analysis_run_id", "analysisRunId"),
            inherentRiskLevel=self._enum_value(
                self._read_attr(analysis_snapshot, "inherent_risk_level", "inherentRiskLevel"),
            ),
            executiveSummary=self._read_attr(
                analysis_snapshot,
                "executive_summary_text",
                "executiveSummary",
                "executive_summary",
            ),
            status=self._enum_value(self._read_attr(analysis_snapshot, "status")),
            topRiskDrivers=top_risk_drivers,
        )

    def _build_architecture(self, architecture_document: object | None) -> InitialSarReportArchitecture:
        return InitialSarReportArchitecture(
            architectureDetails=None,
            documentId=(
                str(self._read_attr(architecture_document, "id", "document_id", "documentId"))
                if architecture_document is not None
                else None
            ),
            filename=(
                self._read_attr(architecture_document, "original_filename", "filename")
                if architecture_document is not None
                else None
            ),
            contentType=(
                self._read_attr(architecture_document, "content_type", "contentType")
                if architecture_document is not None
                else None
            ),
        )

    def _build_document_checklist(self, checklist_state: object | None) -> InitialSarReportDocumentChecklist:
        if checklist_state is None:
            return InitialSarReportDocumentChecklist(
                runId=None,
                summary=None,
                status=None,
                items=[],
                missingRequiredCount=None,
            )

        run = self._read_attr(checklist_state, "run")
        items = [self._build_checklist_item(item_state) for item_state in self._read_attr(checklist_state, "items") or []]
        return InitialSarReportDocumentChecklist(
            runId=self._read_attr(run, "id", "run_id", "runId"),
            summary=self._read_attr(run, "summary_text", "summary", "summaryText"),
            status=self._read_attr(run, "status"),
            items=items,
            missingRequiredCount=sum(
                1
                for item in items
                if item["effectiveVerdict"] == "Required"
                and item["detectedDocumentId"] is None
            ),
        )

    def _build_checklist_item(self, item_state: object) -> dict[str, Any]:
        item = self._read_attr(item_state, "item")
        return {
            "itemId": str(self._read_attr(item, "id", "item_id", "itemId")),
            "documentType": self._read_attr(item, "document_type", "documentType"),
            "baseVerdict": self._read_attr(item, "base_verdict", "baseVerdict"),
            "effectiveVerdict": self._read_attr(item_state, "effective_verdict", "effectiveVerdict"),
            "detectedFileStatus": self._read_attr(item_state, "detected_file_status", "detectedFileStatus"),
            "detectedDocumentId": self._stringify_uuid(
                self._read_attr(item_state, "detected_document_id", "detectedDocumentId"),
            ),
            "reviewerVerdict": self._read_attr(item_state, "reviewer_verdict", "reviewerVerdict"),
            "reviewerReason": self._read_attr(item_state, "reviewer_reason", "reviewerReason"),
        }


    def _build_vendor_reputation(self, snapshot: object | None) -> InitialSarReportVendorReputation | None:
        if snapshot is None:
            return None
        rows = []
        for row in self._read_attr(snapshot, "rows") or []:
            rows.append({
                "category": self._read_attr(row, "category"),
                "sentiment": self._read_attr(row, "sentiment"),
                "interpretation": self._read_attr(row, "ai_interpretation", "aiInterpretation"),
                "riskImpact": self._read_attr(row, "risk_impact", "riskImpact"),
                "confidence": self._read_attr(row, "confidence"),
                "sources": self._read_attr(row, "sources") or [],
            })
        summary = " ".join(
            str(row["interpretation"]).strip()
            for row in rows[:3]
            if row.get("interpretation")
        ) or None
        return InitialSarReportVendorReputation(
            status=self._read_attr(snapshot, "status"),
            summary=summary,
            rows=rows,
        )

    def _build_limitations(
        self,
        *,
        analysis_snapshot: object | None,
        checklist_state: object | None,
        architecture_document: object | None,
        vendor_reputation: object | None,
    ) -> list[str]:
        limitations: list[str] = []
        if analysis_snapshot is None:
            limitations.append("Risk assessment is unavailable.")
        if checklist_state is None:
            limitations.append("Document checklist is unavailable.")
        if architecture_document is None:
            limitations.append("Architecture document metadata is unavailable.")
        if vendor_reputation is None:
            limitations.append("Vendor reputation is unavailable.")
        return limitations

    def _derive_top_risk_drivers(self, analysis_snapshot: object) -> list[dict[str, str]]:
        prepared_drivers = self._read_attr(analysis_snapshot, "top_risk_drivers", "topRiskDrivers")
        if prepared_drivers is None:
            return []

        drivers: list[dict[str, str]] = []
        for driver in prepared_drivers:
            domain = self._read_attr(driver, "domain")
            level = self._enum_value(self._read_attr(driver, "level"))
            if domain is None or level is None:
                continue
            drivers.append({"domain": domain, "level": level})
        return drivers

    @staticmethod
    def _coerce_answer_to_string(value: object | None) -> str | None:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for key in ("optionLabel", "option_label", "selectedResponse", "value", "answer"):
                candidate = value.get(key)
                if isinstance(candidate, str):
                    return candidate
        return None

    @staticmethod
    def _read_attr(record: object | None, *names: str) -> Any:
        if record is None:
            return None
        for name in names:
            if hasattr(record, name):
                return getattr(record, name)
            if isinstance(record, dict) and name in record:
                return record[name]
        return None

    @staticmethod
    def _enum_value(value: object | None) -> str | None:
        if value is None:
            return None
        if hasattr(value, "value"):
            return str(value.value)
        return str(value)

    @staticmethod
    def _coerce_uuid(value: UUID | str | None) -> UUID:
        if isinstance(value, UUID):
            return value
        if value is None:
            raise ValueError("assessment id is required")
        return UUID(str(value))

    @staticmethod
    def _stringify_uuid(value: UUID | str | None) -> str | None:
        if value is None:
            return None
        return str(value)
