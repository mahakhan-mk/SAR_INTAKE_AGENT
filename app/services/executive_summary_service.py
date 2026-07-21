from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.api.errors import AssessmentNotFoundError
from app.llm.client import (
    AzureExecutiveSummaryClient,
    AzureSummaryRequestError,
    AzureSummaryTimeoutError,
    InvalidSummaryOutputError,
)
from app.llm.executive_summary import ExecutiveSummaryPromptLoader
from app.models.dto import (
    ExecutiveSummaryGenerateEnvelopeDTO,
    ExecutiveSummaryGenerateResponseDTO,
    StoredAnalysisSnapshot,
)
from app.models.enums import AnalysisRunStatus, ExecutiveSummaryStatus, RiskLevel
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.assessment_repository import AssessmentRepository
from app.services.inherent_risk_service import InherentRiskService


class ExecutiveSummaryService:
    def __init__(
        self,
        assessment_repository: AssessmentRepository,
        analysis_repository: AnalysisRepository,
        inherent_risk_service: InherentRiskService,
        prompt_loader: ExecutiveSummaryPromptLoader,
        llm_client: AzureExecutiveSummaryClient,
    ) -> None:
        self.assessment_repository = assessment_repository
        self.analysis_repository = analysis_repository
        self.inherent_risk_service = inherent_risk_service
        self.prompt_loader = prompt_loader
        self.llm_client = llm_client

    def generate(
        self,
        session: Session,
        assessment_id: str,
        force: bool = False,
    ) -> ExecutiveSummaryGenerateResponseDTO:
        assessment = self.assessment_repository.get_assessment(session, assessment_id)
        if assessment is None:
            raise AssessmentNotFoundError()

        snapshot = self.analysis_repository.get_latest_completed_snapshot(session, assessment_id)
        if snapshot is None:
            self.inherent_risk_service.create_analysis_run(session, assessment_id, force=False)
            snapshot = self.analysis_repository.get_latest_completed_snapshot(session, assessment_id)

        if snapshot is None:
            raise RuntimeError("A completed inherent-risk analysis run is required before generating the executive summary.")

        input_payload = self._build_input_payload(assessment, snapshot)
        input_hash = self._build_input_hash(input_payload)

        if (
            snapshot.executive_summary_text
            and snapshot.executive_summary_generated_at
            and snapshot.executive_summary_input_hash == input_hash
            and not force
        ):
            return self._build_response(
                assessment_id=assessment_id,
                analysis_run_id=snapshot.analysis_run_id,
                text=snapshot.executive_summary_text,
                status=snapshot.executive_summary_status,
                generated_at=snapshot.executive_summary_generated_at,
            )

        prompt = self.prompt_loader.load()
        generated_at = datetime.now(timezone.utc)

        try:
            summary_text = self.llm_client.generate_summary(prompt, input_payload)
            run = self.analysis_repository.update_executive_summary(
                session=session,
                analysis_run_id=snapshot.analysis_run_id,
                summary_text=summary_text,
                summary_status=ExecutiveSummaryStatus.GENERATED,
                summary_model=self.llm_client.model_name,
                prompt_version=prompt.version,
                input_hash=input_hash,
                generated_at=generated_at,
                error_summary=None,
            )
            session.commit()
            return self._build_response(
                assessment_id=assessment_id,
                analysis_run_id=run.id,
                text=summary_text,
                status=ExecutiveSummaryStatus.GENERATED,
                generated_at=generated_at,
            )
        except (AzureSummaryTimeoutError, AzureSummaryRequestError, InvalidSummaryOutputError) as exc:
            session.rollback()
            fallback_text = self._build_fallback_summary(assessment, snapshot)
            run = self.analysis_repository.update_executive_summary(
                session=session,
                analysis_run_id=snapshot.analysis_run_id,
                summary_text=fallback_text,
                summary_status=ExecutiveSummaryStatus.FALLBACK,
                summary_model="fallback",
                prompt_version=prompt.version,
                input_hash=input_hash,
                generated_at=generated_at,
                error_summary=str(exc),
            )
            session.commit()
            return self._build_response(
                assessment_id=assessment_id,
                analysis_run_id=run.id,
                text=fallback_text,
                status=ExecutiveSummaryStatus.FALLBACK,
                generated_at=generated_at,
            )

    def _build_input_payload(self, assessment, snapshot: StoredAnalysisSnapshot) -> dict[str, object]:
        high_risk_results = [
            result
            for result in snapshot.question_results
            if result.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
        ]
        top_risk_drivers = [
            {"domain": driver["domain"], "level": driver["level"]}
            for driver in self._derive_top_risk_drivers(snapshot)
        ]
        material_questions = high_risk_results or self._top_material_questions(snapshot)

        return {
            "technologyName": assessment.technology_name,
            "vendorName": getattr(assessment, "vendor_name", None),
            "productName": getattr(assessment, "product_name", None),
            "inherentRiskLevel": snapshot.overall_risk_level.value,
            "highRiskQuestionCount": len(high_risk_results),
            "topRiskDrivers": top_risk_drivers,
            "materialQuestions": [
                {
                    "questionText": result.question_text,
                    "selectedResponse": result.selected_option_label,
                    "whyItMatters": result.why_it_matters,
                    "riskSignal": result.risk_signal,
                }
                for result in material_questions
            ],
            "materialLimitations": snapshot.limitation_summary,
        }

    @staticmethod
    def _build_input_hash(payload: dict[str, object]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _build_fallback_summary(self, assessment, snapshot: StoredAnalysisSnapshot) -> str:
        display_name = (
            getattr(assessment, "product_name", None)
            or getattr(assessment, "technology_name", None)
            or "the assessed solution"
        )
        top_risk_drivers = self._derive_top_risk_drivers(snapshot)
        if top_risk_drivers:
            drivers_text = ", ".join(driver["domain"] for driver in top_risk_drivers)
            driver_sentence = f" The top risk drivers are {drivers_text}."
        else:
            driver_sentence = ""

        high_risk_count = sum(
            1
            for result in snapshot.question_results
            if result.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
        )
        limitations_text = f" Limitations: {snapshot.limitation_summary}." if snapshot.limitation_summary else ""

        return (
            f"{display_name} is currently assessed as {snapshot.overall_risk_level.label} inherent risk "
            f"based on SAR triage responses. {high_risk_count} high-risk triage responses were identified."
            f"{driver_sentence}{limitations_text}"
        )

    def _derive_top_risk_drivers(self, snapshot: StoredAnalysisSnapshot) -> list[dict[str, str]]:
        grouped: dict[str, list] = {}
        for result in snapshot.question_results:
            if result.risk_level not in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
                continue
            grouped.setdefault(result.risk_domain, []).append(result)

        ranked: list[tuple[int, float, str, RiskLevel]] = []
        for domain, results in grouped.items():
            highest_level = max((result.risk_level for result in results), key=lambda level: level.rank)
            highest_weight = max(result.risk_weight for result in results)
            ranked.append((highest_level.rank, highest_weight, domain, highest_level))

        ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
        return [
            {"domain": domain, "level": level.value}
            for _, _, domain, level in ranked[:3]
        ]

    @staticmethod
    def _top_material_questions(snapshot: StoredAnalysisSnapshot):
        return sorted(
            snapshot.question_results,
            key=lambda result: (-result.risk_level.rank, -result.risk_weight, result.question_text),
        )[:3]

    @staticmethod
    def _build_response(
        *,
        assessment_id: str,
        analysis_run_id: str,
        text: str,
        status: ExecutiveSummaryStatus,
        generated_at: datetime,
    ) -> ExecutiveSummaryGenerateResponseDTO:
        return ExecutiveSummaryGenerateResponseDTO(
            assessmentId=assessment_id,
            analysisRunId=analysis_run_id,
            executiveSummary=ExecutiveSummaryGenerateEnvelopeDTO(
                text=text,
                status=status,
                generatedAt=generated_at,
            ),
        )
