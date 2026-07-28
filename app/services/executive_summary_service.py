from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AnalysisRunNotFoundError, AnalysisRunStatusConflictError, AssessmentNotFoundError
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

    async def generate(
        self,
        session: AsyncSession,
        assessment_id: uuid.UUID,
        analysis_run_id: uuid.UUID,
        force: bool = False,
    ) -> ExecutiveSummaryGenerateResponseDTO:
        run = await self.analysis_repository.get_analysis_run_for_assessment(session, assessment_id, analysis_run_id)
        if run is None:
            raise AnalysisRunNotFoundError()

        if run.status not in {
            AnalysisRunStatus.COMPLETED.value,
            AnalysisRunStatus.COMPLETED_WITH_LIMITATIONS.value,
        }:
            raise AnalysisRunStatusConflictError(run.status)

        assessment = await self.assessment_repository.get_assessment(session, assessment_id)
        if assessment is None:
            raise AssessmentNotFoundError()

        snapshot = await self.analysis_repository.get_snapshot_for_run(session, run)

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
            run = await self.analysis_repository.update_executive_summary(
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
            return self._build_response(
                assessment_id=assessment_id,
                analysis_run_id=run.id,
                text=summary_text,
                status=ExecutiveSummaryStatus.GENERATED,
                generated_at=generated_at,
            )
        except (AzureSummaryTimeoutError, AzureSummaryRequestError, InvalidSummaryOutputError) as exc:
            fallback_text = self._build_fallback_summary(assessment, snapshot)
            run = await self.analysis_repository.update_executive_summary(
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
            return self._build_response(
                assessment_id=assessment_id,
                analysis_run_id=run.id,
                text=fallback_text,
                status=ExecutiveSummaryStatus.FALLBACK,
                generated_at=generated_at,
            )

    def _build_input_payload(self, assessment, snapshot: StoredAnalysisSnapshot) -> dict[str, object]:
        return {
            "technologyName": assessment.technology_name,
            "vendorName": getattr(assessment, "vendor_name", None),
            "productName": getattr(assessment, "product_name", None),
            "overallRisk": snapshot.inherent_risk_level.value,
            "topRiskDrivers": [
                {
                    "domain": driver.domain,
                    "level": driver.level.value,
                }
                for driver in self.inherent_risk_service.derive_top_risk_drivers(
                    snapshot.question_results
                )
            ],
            "materialLimitations": self._derive_material_limitations(snapshot),
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
        top_risk_drivers = self.inherent_risk_service.derive_top_risk_drivers(
            snapshot.question_results
        )
        if top_risk_drivers:
            drivers_text = ", ".join(driver.domain for driver in top_risk_drivers)
            driver_sentence = f" The top risk drivers are {drivers_text}."
        else:
            driver_sentence = ""

        high_risk_count = sum(
            1
            for result in snapshot.question_results
            if result.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
        )
        material_limitations = self._derive_material_limitations(snapshot)
        limitations_text = f" Limitations: {material_limitations}." if material_limitations else ""

        return (
            f"{display_name} is currently assessed as {snapshot.inherent_risk_level.label} inherent risk "
            f"based on SAR triage responses. {high_risk_count} high-risk triage responses were identified."
            f"{driver_sentence}{limitations_text}"
        )

    @staticmethod
    def _derive_material_limitations(snapshot: StoredAnalysisSnapshot) -> str | None:
        if snapshot.status == AnalysisRunStatus.FAILED:
            return snapshot.error_summary
        if snapshot.status != AnalysisRunStatus.COMPLETED_WITH_LIMITATIONS:
            return None
        if not snapshot.question_results:
            return "No answered triage responses were available for scoring."
        return "Scoring completed with limitations based on available triage responses."

    @staticmethod
    def _build_response(
        *,
        assessment_id: uuid.UUID,
        analysis_run_id: uuid.UUID,
        text: str,
        status: ExecutiveSummaryStatus,
        generated_at: datetime,
    ) -> ExecutiveSummaryGenerateResponseDTO:
        return ExecutiveSummaryGenerateResponseDTO(
            assessmentId=str(assessment_id),
            analysisRunId=str(analysis_run_id),
            executiveSummary=ExecutiveSummaryGenerateEnvelopeDTO(
                text=text,
                status=status,
                generatedAt=generated_at,
            ),
        )
