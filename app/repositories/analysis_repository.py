from __future__ import annotations

from datetime import datetime, timezone
import json
import uuid

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
                QuestionAnalysisRun.assessment_id == assessment_id,
                QuestionAnalysisRun.status.in_(SUCCESSFUL_RUN_STATUSES),
            )
            .order_by(QuestionAnalysisRun.created_at.desc(), QuestionAnalysisRun.id.desc())
            )
        ).scalars().first()

        if run is None:
            return None

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
                    question_code=self._extract_question_code(result.input_snapshot),
                    response_id=result.response_id,
                    question_definition_id=result.question_definition_id,
                    selected_option_id=result.selected_option_id,
                    selected_option_label=self._extract_selected_response(result.input_snapshot),
                    question_text=result.question_text,
                    risk_domain=result.risk_domain,
                    risk_level=RiskLevel(result.risk_level),
                    risk_weight=result.risk_weight,
                    max_risk_weight=result.risk_weight,
                    why_it_matters=result.why_it_matters,
                    risk_signal=result.risk_signal,
                    explanation=result.ai_explanation or "",
                    confidence=result.ai_confidence or 0.0,
                    input_snapshot=result.input_snapshot or "",
                )
                for result in results
            ],
        )

    async def create_analysis_run(
        self,
        session: AsyncSession,
        assessment_id: uuid.UUID,
        status: AnalysisRunStatus,
        scoring_config_version: str,
        triage_score: float | None,
        inherent_score: float | None,
        inherent_risk_level: RiskLevel,
        error_summary: str | None = None,
    ) -> QuestionAnalysisRun:
        run = QuestionAnalysisRun(
            assessment_id=assessment_id,
            status=status.value,
            scoring_config_version=scoring_config_version,
            triage_score=triage_score,
            inherent_score=inherent_score,
            inherent_risk_level=inherent_risk_level.value,
            error_summary=error_summary,
            created_at=datetime.now(timezone.utc),
        )
        session.add(run)
        await session.flush()
        return run

    async def get_analysis_run(
        self,
        session: AsyncSession,
        analysis_run_id: uuid.UUID,
    ) -> QuestionAnalysisRun | None:
        return await session.get(QuestionAnalysisRun, analysis_run_id)

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
    def _extract_selected_response(input_snapshot: str | None) -> str:
        if not input_snapshot:
            return ""
        try:
            snapshot = json.loads(input_snapshot)
        except json.JSONDecodeError:
            return ""
        value = snapshot.get("selectedResponse")
        return value if isinstance(value, str) else ""

    @staticmethod
    def _extract_question_code(input_snapshot: str | None) -> str:
        if not input_snapshot:
            return ""
        try:
            snapshot = json.loads(input_snapshot)
        except json.JSONDecodeError:
            return ""
        value = snapshot.get("questionCode")
        return value if isinstance(value, str) else ""

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
                        question_definition_id=result.question_definition_id,
                        selected_option_id=result.selected_option_id,
                        question_text=result.question_text,
                        risk_domain=result.risk_domain,
                        risk_level=result.risk_level.value,
                        risk_weight=result.risk_weight,
                        why_it_matters=result.why_it_matters,
                        risk_signal=result.risk_signal,
                        ai_explanation=result.explanation,
                        ai_confidence=result.confidence,
                        input_snapshot=result.input_snapshot,
                    )
                )
                continue

            existing.question_definition_id = result.question_definition_id
            existing.selected_option_id = result.selected_option_id
            existing.question_text = result.question_text
            existing.risk_domain = result.risk_domain
            existing.risk_level = result.risk_level.value
            existing.risk_weight = result.risk_weight
            existing.why_it_matters = result.why_it_matters
            existing.risk_signal = result.risk_signal
            existing.ai_explanation = result.explanation
            existing.ai_confidence = result.confidence
            existing.input_snapshot = result.input_snapshot

        await session.flush()
