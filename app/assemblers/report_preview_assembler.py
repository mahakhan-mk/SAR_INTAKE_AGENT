from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import ConfigDict

from app.models.report_preview import (
    REPORT_PREVIEW_QUESTION_CODE_TO_FIELD_NAME,
    ReportPreviewArchitectureDTO,
    ReportPreviewAssessmentDTO,
    ReportPreviewBusinessContactDetailsDTO,
    ReportPreviewBusinessContinuityDTO,
    ReportPreviewDataFlowDTO,
    ReportPreviewDataHostedDTO,
    ReportPreviewDocumentChecklistDTO,
    ReportPreviewHostingDTO,
    ReportPreviewResponseDTO,
    ReportPreviewRiskAssessmentDTO,
    ReportPreviewSolutionOverviewDTO,
    ReportPreviewThirdPartyMeasuresDTO,
)


class _ExtendedRiskAssessmentDTO(ReportPreviewRiskAssessmentDTO):
    model_config = ConfigDict(extra="allow")


class _ExtendedArchitectureDTO(ReportPreviewArchitectureDTO):
    model_config = ConfigDict(extra="allow")


class _ExtendedDocumentChecklistDTO(ReportPreviewDocumentChecklistDTO):
    model_config = ConfigDict(extra="allow")


class ReportPreviewAssembler:
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
    ) -> ReportPreviewResponseDTO:
        business_contact_details = ReportPreviewBusinessContactDetailsDTO()
        solution_overview = ReportPreviewSolutionOverviewDTO()
        hosting = ReportPreviewHostingDTO()
        data_hosted = ReportPreviewDataHostedDTO()
        data_flow = ReportPreviewDataFlowDTO()
        business_continuity = ReportPreviewBusinessContinuityDTO()
        third_party_measures = ReportPreviewThirdPartyMeasuresDTO()

        section_dtos: dict[str, object] = {
            "businessContactDetails": business_contact_details,
            "solutionOverview": solution_overview,
            "hosting": hosting,
            "dataHosted": data_hosted,
            "dataFlow": data_flow,
            "businessContinuity": business_continuity,
            "thirdPartyMeasures": third_party_measures,
        }

        for record in response_records or []:
            question_code = self._read_attr(record, "question_code", "questionCode")
            mapping_target = REPORT_PREVIEW_QUESTION_CODE_TO_FIELD_NAME.get(question_code)
            if mapping_target is None:
                continue

            answer_value = self._coerce_answer_to_string(
                self._read_attr(record, "answer_value", "answerValue"),
            )
            if answer_value is None:
                continue

            section_name, field_name = mapping_target.split(".", 1)
            setattr(section_dtos[section_name], field_name, answer_value)

        risk_assessment = self._build_risk_assessment(analysis_snapshot)
        architecture = self._build_architecture(architecture_document)
        document_checklist = self._build_document_checklist(checklist_state)

        return ReportPreviewResponseDTO.model_construct(
            assessmentId=self._coerce_uuid(self._read_attr(assessment, "id", "assessment_id", "assessmentId")),
            generatedAt=generated_at or datetime.now(timezone.utc),
            assessment=ReportPreviewAssessmentDTO(
                technologyName=self._read_attr(assessment, "technology_name", "technologyName"),
                sourceSystem=source_system or self._read_attr(assessment, "source_system", "sourceSystem"),
                questionnaireVersion=questionnaire_version
                or self._read_attr(assessment, "questionnaire_version", "questionnaireVersion"),
            ),
            riskAssessment=risk_assessment,
            businessContactDetails=business_contact_details,
            solutionOverview=solution_overview,
            architecture=architecture,
            hosting=hosting,
            dataHosted=data_hosted,
            dataFlow=data_flow,
            businessContinuity=business_continuity,
            thirdPartyMeasures=third_party_measures,
            documentChecklist=document_checklist,
            vendorReputation=None,
            limitations=self._build_limitations(
                analysis_snapshot=analysis_snapshot,
                checklist_state=checklist_state,
                architecture_document=architecture_document,
            ),
        )

    def _build_risk_assessment(self, analysis_snapshot: object | None) -> _ExtendedRiskAssessmentDTO:
        if analysis_snapshot is None:
            return _ExtendedRiskAssessmentDTO(
                inherentRiskLevel=None,
                executiveSummary=None,
                status=None,
                topRiskDrivers=[],
            )

        top_risk_drivers = self._derive_top_risk_drivers(analysis_snapshot)
        return _ExtendedRiskAssessmentDTO(
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

    def _build_architecture(self, architecture_document: object | None) -> _ExtendedArchitectureDTO:
        return _ExtendedArchitectureDTO(
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

    def _build_document_checklist(self, checklist_state: object | None) -> _ExtendedDocumentChecklistDTO:
        if checklist_state is None:
            return _ExtendedDocumentChecklistDTO(
                summary=None,
                status=None,
                items=[],
                missingRequiredCount=None,
            )

        run = self._read_attr(checklist_state, "run")
        items = [self._build_checklist_item(item_state) for item_state in self._read_attr(checklist_state, "items") or []]
        return _ExtendedDocumentChecklistDTO(
            summary=self._read_attr(run, "summary_text", "summary", "summaryText"),
            status=self._read_attr(run, "status"),
            items=items,
            missingRequiredCount=sum(1 for item in items if item["effectiveVerdict"] == "Required"),
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

    def _build_limitations(
        self,
        *,
        analysis_snapshot: object | None,
        checklist_state: object | None,
        architecture_document: object | None,
    ) -> list[str]:
        limitations: list[str] = []
        if analysis_snapshot is None:
            limitations.append("Risk assessment is unavailable.")
        if checklist_state is None:
            limitations.append("Document checklist is unavailable.")
        if architecture_document is None:
            limitations.append("Architecture document metadata is unavailable.")
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
