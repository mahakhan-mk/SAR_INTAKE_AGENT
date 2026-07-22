from __future__ import annotations

from datetime import datetime, timezone
import json
import uuid
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import QuestionAnalysisRun, QuestionRiskResult
from app.models.dto import ComputedQuestionRisk, StoredAnalysisSnapshot
from app.models.enums import AnalysisRunStatus, ExecutiveSummaryStatus, RiskLevel

SUCCESSFUL_RUN_STATUSES = (
    AnalysisRunStatus.COMPLETED.value,
    AnalysisRunStatus.COMPLETED_WITH_LIMITATIONS.value,
)


class AnalysisRepository:
    async def get_latest_completed_snapshot(
        self,
        session: AsyncSession,
        assessment_id: uuid.UUID,
    ) -> StoredAnalysisSnapshot | None:
        run = (
            await session.execute(
            select(QuestionAnalysisRun)
            .where(
                QuestionAnalysisRun.assessment_id == self._coerce_uuid(assessment_id),
                QuestionAnalysisRun.status.in_(SUCCESSFUL_RUN_STATUSES),
            )
            .order_by(QuestionAnalysisRun.created_at.desc(), QuestionAnalysisRun.id.desc())
            )
        ).scalars().first()

        if run is None:
            return None

        return await self._build_snapshot(session, run)

    async def get_analysis_run_for_assessment(
        self,
        session: AsyncSession,
        assessment_id: uuid.UUID,
        analysis_run_id: uuid.UUID,
    ) -> QuestionAnalysisRun | None:
        return (
            await session.execute(
                select(QuestionAnalysisRun).where(
                    QuestionAnalysisRun.id == self._coerce_uuid(analysis_run_id),
                    QuestionAnalysisRun.assessment_id == self._coerce_uuid(assessment_id),
                )
            )
        ).scalars().first()

    async def get_snapshot_for_run(
        self,
        session: AsyncSession,
        run: QuestionAnalysisRun,
    ) -> StoredAnalysisSnapshot:
        return await self._build_snapshot(session, run)

    async def _build_snapshot(
        self,
        session: AsyncSession,
        run: QuestionAnalysisRun,
    ) -> StoredAnalysisSnapshot:
        results = (
            await session.execute(
            select(QuestionRiskResult)
            .where(QuestionRiskResult.analysis_run_id == run.id)
            .order_by(QuestionRiskResult.created_at.asc(), QuestionRiskResult.id.asc())
            )
        ).scalars().all()

        summary_status = ExecutiveSummaryStatus.NOT_GENERATED
        if run.executive_summary_text and run.executive_summary_generated_at:
            summary_status = (
                ExecutiveSummaryStatus.FALLBACK
                if run.executive_summary_model == "fallback"
                else ExecutiveSummaryStatus.GENERATED
            )

        return StoredAnalysisSnapshot(
            analysis_run_id=run.id,
            status=AnalysisRunStatus(run.status),
            triage_score=run.triage_score,
            inherent_score=run.inherent_score,
            inherent_risk_level=RiskLevel(run.inherent_risk_level or RiskLevel.NOT_ASSESSED.value),
            executive_summary_status=summary_status,
            executive_summary_text=run.executive_summary_text,
            executive_summary_model=run.executive_summary_model,
            executive_summary_prompt_version=run.executive_summary_prompt_version,
            executive_summary_input_hash=run.executive_summary_input_hash,
            executive_summary_generated_at=run.executive_summary_generated_at,
            error_summary=run.error_summary,
            question_results=[
                ComputedQuestionRisk(
                    question_code=self._extract_str(result.input_snapshot, "questionCode"),
                    response_id=result.response_id,
                    question_definition_id=self._extract_uuid(result.input_snapshot, "questionId"),
                    selected_option_id=self._extract_uuid(result.input_snapshot, "selectedOptionId"),
                    selected_option_label=self._extract_selected_response(result.input_snapshot),
                    question_text=self._extract_str(result.input_snapshot, "questionText"),
                    risk_domain=result.risk_domain or "",
                    risk_level=RiskLevel(result.risk_level),
                    risk_weight=self._extract_float(result.input_snapshot, "riskWeight", result.risk_score),
                    max_risk_weight=self._extract_float(result.input_snapshot, "maxRiskWeight", result.risk_score),
                    why_it_matters=self._extract_str(result.input_snapshot, "whyItMatters", result.risk_impact),
                    risk_signal=result.risk_signal or self._extract_str(result.input_snapshot, "riskSignal"),
                    explanation=result.explanation,
                    confidence=float(result.confidence or 0.0),
                    input_snapshot=self._coerce_snapshot(result.input_snapshot),
                )
                for result in results
            ],
        )

    async def create_analysis_run(
        self,
        session: AsyncSession,
        assessment_id: uuid.UUID,
        status: AnalysisRunStatus,
        scoring_rule_version: str,
        triage_score: float | None,
        inherent_score: float | None,
        inherent_risk_level: RiskLevel,
        intake_score: float | None = None,
        error_summary: str | None = None,
    ) -> QuestionAnalysisRun:
        now = datetime.now(timezone.utc)
        run = QuestionAnalysisRun(
            assessment_id=self._coerce_uuid(assessment_id),
            status=status.value,
            scoring_rule_version=scoring_rule_version,
            intake_score=intake_score,
            triage_score=triage_score,
            inherent_score=inherent_score,
            inherent_risk_level=inherent_risk_level.value,
            error_summary=error_summary,
            started_at=now,
            completed_at=now,
            created_at=now,
        )
        session.add(run)
        await session.flush()
        return run

    async def get_analysis_run(
        self,
        session: AsyncSession,
        analysis_run_id: uuid.UUID,
    ) -> QuestionAnalysisRun | None:
        return await session.get(QuestionAnalysisRun, self._coerce_uuid(analysis_run_id))

    async def update_executive_summary(
        self,
        session: AsyncSession,
        analysis_run_id: uuid.UUID,
        *,
        summary_text: str,
        summary_status: ExecutiveSummaryStatus,
        summary_model: str,
        prompt_version: str,
        input_hash: str,
        generated_at: datetime,
        error_summary: str | None,
    ) -> QuestionAnalysisRun:
        run = await self.get_analysis_run(session, analysis_run_id)
        if run is None:
            raise LookupError(f"Analysis run {analysis_run_id} was not found.")

        run.executive_summary_text = summary_text
        run.executive_summary_model = summary_model
        run.executive_summary_prompt_version = prompt_version
        run.executive_summary_input_hash = input_hash
        run.executive_summary_generated_at = generated_at
        if summary_status == ExecutiveSummaryStatus.FALLBACK:
            run.status = AnalysisRunStatus.COMPLETED_WITH_LIMITATIONS.value
            run.error_summary = error_summary
        else:
            if run.status != AnalysisRunStatus.COMPLETED_WITH_LIMITATIONS.value:
                run.status = AnalysisRunStatus.COMPLETED.value
            run.error_summary = None

        await session.flush()
        return run

    @staticmethod
    def _coerce_uuid(value: UUID | str) -> UUID:
        return value if isinstance(value, UUID) else UUID(value)

    @staticmethod
    def _extract_selected_response(input_snapshot: object | None) -> str:
        snapshot = AnalysisRepository._coerce_snapshot(input_snapshot)
        value = snapshot.get("selectedOptionLabel")
        if isinstance(value, str):
            return value
        value = snapshot.get("selectedResponse")
        return value if isinstance(value, str) else ""

    @staticmethod
    def _coerce_snapshot(input_snapshot: object | None) -> dict[str, object]:
        if isinstance(input_snapshot, dict):
            return input_snapshot
        if isinstance(input_snapshot, str):
            try:
                parsed = json.loads(input_snapshot)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    @staticmethod
    def _extract_str(input_snapshot: object | None, key: str, fallback: object | None = None) -> str:
        snapshot = AnalysisRepository._coerce_snapshot(input_snapshot)
        value = snapshot.get(key, fallback)
        return value if isinstance(value, str) else ""

    @staticmethod
    def _extract_uuid(input_snapshot: object | None, key: str) -> uuid.UUID | None:
        value = AnalysisRepository._extract_str(input_snapshot, key)
        if not value:
            return None
        try:
            return uuid.UUID(value)
        except ValueError:
            return None

    @staticmethod
    def _extract_float(input_snapshot: object | None, key: str, fallback: object | None = None) -> float:
        snapshot = AnalysisRepository._coerce_snapshot(input_snapshot)
        value = snapshot.get(key, fallback)
        if value is None:
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    async def upsert_question_risk_results(
        self,
        session: AsyncSession,
        analysis_run_id: uuid.UUID,
        question_results: list[ComputedQuestionRisk],
    ) -> None:
        if not question_results:
            return

        response_ids = [result.response_id for result in question_results]
        existing_results = (
            await session.execute(
            select(QuestionRiskResult).where(
                QuestionRiskResult.analysis_run_id == analysis_run_id,
                QuestionRiskResult.response_id.in_(response_ids),
            )
            )
        ).scalars().all()
        existing_by_response_id = {result.response_id: result for result in existing_results}

        for result in question_results:
            existing = existing_by_response_id.get(result.response_id)
            if existing is None:
                session.add(
                    QuestionRiskResult(
                        analysis_run_id=analysis_run_id,
                        response_id=result.response_id,
                        risk_domain=result.risk_domain,
                        risk_score=result.risk_weight,
                        risk_level=result.risk_level.value,
                        risk_impact=result.why_it_matters,
                        risk_signal=result.risk_signal,
                        explanation=result.explanation,
                        confidence=result.confidence,
                        input_snapshot=result.input_snapshot,
                    )
                )
                continue

            existing.risk_domain = result.risk_domain
            existing.risk_score = result.risk_weight
            existing.risk_level = result.risk_level.value
            existing.risk_impact = result.why_it_matters
            existing.risk_signal = result.risk_signal
            existing.explanation = result.explanation
            existing.confidence = result.confidence
            existing.input_snapshot = result.input_snapshot

        await session.flush()
