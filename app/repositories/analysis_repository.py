from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timezone
import json
import uuid
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_analysis import AIAnalysisQuestionRowRecord, AIAnalysisRunRecord, AIAnalysisViewRecord
from app.models.database import (
    AssessmentResponse,
    QuestionAnalysisRun,
    QuestionDefinition,
    QuestionOption,
    QuestionRiskResult,
    QuestionnaireVersion,
    SarAssessment,
)
from app.application.models import ComputedQuestionRisk, StoredAnalysisSnapshot
from app.models.enums import AnalysisRunStatus, ExecutiveSummaryStatus, QuestionnaireType, RiskLevel

SUCCESSFUL_RUN_STATUSES = (
    AnalysisRunStatus.COMPLETED.value,
    AnalysisRunStatus.COMPLETED_WITH_LIMITATIONS.value,
)


class AnalysisRepository:
    async def get_latest_usable_analysis_run(
        self,
        session: AsyncSession,
        assessment_id: uuid.UUID,
    ) -> QuestionAnalysisRun | None:
        return (
            await session.execute(
                select(QuestionAnalysisRun)
                .where(
                    QuestionAnalysisRun.assessment_id == self._coerce_uuid(assessment_id),
                    QuestionAnalysisRun.status.in_(SUCCESSFUL_RUN_STATUSES),
                )
                .order_by(
                    QuestionAnalysisRun.completed_at.desc().nullslast(),
                    QuestionAnalysisRun.created_at.desc(),
                    QuestionAnalysisRun.id.desc(),
                )
            )
        ).scalars().first()

    async def load_ai_analysis_view(
        self,
        session: AsyncSession,
        assessment_id: uuid.UUID,
    ) -> AIAnalysisViewRecord | None:
        normalized_assessment_id = self._coerce_uuid(assessment_id)
        assessment = await session.get(SarAssessment, normalized_assessment_id)
        if assessment is None:
            return None

        latest_run = await self.get_latest_usable_analysis_run(session, normalized_assessment_id)

        version = (
            await session.execute(
                select(QuestionnaireVersion)
                .where(
                    QuestionnaireVersion.questionnaire_type == QuestionnaireType.TRIAGE.value,
                    QuestionnaireVersion.status == "active",
                )
                .order_by(QuestionnaireVersion.created_at.desc(), QuestionnaireVersion.id.desc())
            )
        ).scalars().first()

        if version is None:
            return AIAnalysisViewRecord(
                assessment_id=normalized_assessment_id,
                latest_run=self._to_ai_analysis_run_record(latest_run),
                questions=[],
            )

        questions = (
            await session.execute(
                select(QuestionDefinition)
                .where(
                    QuestionDefinition.questionnaire_version_id == version.id,
                    QuestionDefinition.is_visible.is_(True),
                )
                .order_by(QuestionDefinition.question_order.asc(), QuestionDefinition.id.asc())
            )
        ).scalars().all()

        if not questions:
            return AIAnalysisViewRecord(
                assessment_id=normalized_assessment_id,
                latest_run=self._to_ai_analysis_run_record(latest_run),
                questions=[],
            )

        question_ids = [question.id for question in questions]
        responses = (
            await session.execute(
                select(AssessmentResponse)
                .where(
                    AssessmentResponse.assessment_id == normalized_assessment_id,
                    AssessmentResponse.question_id.in_(question_ids),
                )
                .order_by(AssessmentResponse.created_at.asc(), AssessmentResponse.id.asc())
            )
        ).scalars().all()
        responses_by_question_id = {response.question_id: response for response in responses}

        options = (
            await session.execute(
                select(QuestionOption)
                .where(QuestionOption.question_id.in_(question_ids))
                .order_by(QuestionOption.display_order.asc(), QuestionOption.id.asc())
            )
        ).scalars().all()
        options_by_question_id: dict[uuid.UUID, list[QuestionOption]] = defaultdict(list)
        for option in options:
            options_by_question_id[option.question_id].append(option)

        results_by_response_id: dict[uuid.UUID, QuestionRiskResult] = {}
        if latest_run is not None:
            results = (
                await session.execute(
                    select(QuestionRiskResult)
                    .where(QuestionRiskResult.analysis_run_id == latest_run.id)
                    .order_by(QuestionRiskResult.created_at.asc(), QuestionRiskResult.id.asc())
                )
            ).scalars().all()
            results_by_response_id = {result.response_id: result for result in results}

        rows: list[AIAnalysisQuestionRowRecord] = []
        for question in questions:
            response = responses_by_question_id.get(question.id)
            selected_option = (
                self._match_selected_option(
                    options_by_question_id.get(question.id, []),
                    self._extract_candidate_values(response.answer_value),
                )
                if response is not None
                else None
            )
            result = results_by_response_id.get(response.id) if response is not None else None

            rows.append(
                AIAnalysisQuestionRowRecord(
                    question_id=question.id,
                    question_number=question.question_code,
                    question_text=question.question_text,
                    domain=question.risk_domain,
                    response_id=response.id if response is not None else None,
                    selected_option_id=selected_option.id if selected_option is not None else None,
                    answer_value=response.answer_value if response is not None else None,
                    option_risk_band=selected_option.risk_band if selected_option is not None else None,
                    option_risk_weight=(
                        float(selected_option.risk_weight)
                        if selected_option is not None and selected_option.risk_weight is not None
                        else None
                    ),
                    option_why_it_matters=question.why_it_matters,
                    option_risk_signal=selected_option.risk_signal if selected_option is not None else None,
                    result_risk_level=result.risk_level if result is not None else None,
                    result_risk_score=(
                        float(result.risk_score) if result is not None and result.risk_score is not None else None
                    ),
                    result_risk_impact=result.risk_impact if result is not None else None,
                    result_explanation=result.explanation if result is not None else None,
                    result_confidence=(
                        float(result.confidence) if result is not None and result.confidence is not None else None
                    ),
                    reviewer_remarks=response.reviewer_remarks if response is not None else None,
                )
            )

        return AIAnalysisViewRecord(
            assessment_id=normalized_assessment_id,
            latest_run=self._to_ai_analysis_run_record(latest_run),
            questions=rows,
        )

    async def get_latest_completed_snapshot(
        self,
        session: AsyncSession,
        assessment_id: uuid.UUID,
    ) -> StoredAnalysisSnapshot | None:
        run = await self.get_latest_usable_analysis_run(session, assessment_id)

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
                    question_weight=self._extract_int(result.input_snapshot, "questionWeight"),
                    option_weight=self._extract_float(result.input_snapshot, "optionWeight"),
                    weighted_score=self._extract_float(
                        result.input_snapshot,
                        "weightedScore",
                        self._extract_float(result.input_snapshot, "riskWeight", result.risk_score),
                    ),
                    max_option_weight=self._extract_float(result.input_snapshot, "maxOptionWeight"),
                    max_weighted_score=self._extract_float(
                        result.input_snapshot,
                        "maxWeightedScore",
                        self._extract_float(result.input_snapshot, "maxRiskWeight", result.risk_score),
                    ),
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

    @staticmethod
    def _extract_int(input_snapshot: object | None, key: str, fallback: object | None = None) -> int | None:
        snapshot = AnalysisRepository._coerce_snapshot(input_snapshot)
        value = snapshot.get(key, fallback)
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_candidate_values(answer_value: object | None) -> list[str]:
        if isinstance(answer_value, str):
            return [answer_value] if answer_value else []

        if isinstance(answer_value, dict):
            values: list[str] = []
            for key in ("optionCode", "option_code", "selectedResponse", "optionLabel", "option_label", "value"):
                values.extend(AnalysisRepository._coerce_strings(answer_value.get(key)))
            return list(dict.fromkeys(values))

        if isinstance(answer_value, list):
            return [value for value in answer_value if isinstance(value, str) and value]

        return []

    @staticmethod
    def _coerce_strings(value: object) -> list[str]:
        if isinstance(value, str):
            return [value] if value else []
        if isinstance(value, Iterable) and not isinstance(value, (str, bytes, dict)):
            return [item for item in value if isinstance(item, str) and item]
        return []

    @staticmethod
    def _match_selected_option(options: list[QuestionOption], candidate_values: list[str]) -> QuestionOption | None:
        for candidate in candidate_values:
            for option in options:
                if option.option_code == candidate:
                    return option
            for option in options:
                if option.option_label == candidate:
                    return option
        return None

    @staticmethod
    def _to_ai_analysis_run_record(run: QuestionAnalysisRun | None) -> AIAnalysisRunRecord | None:
        if run is None:
            return None
        return AIAnalysisRunRecord(
            analysis_run_id=run.id,
            status=AnalysisRunStatus(run.status),
            created_at=run.created_at,
        )

    @staticmethod
    def _coerce_uuid(value: uuid.UUID | str) -> uuid.UUID:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(value)

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
                        risk_score=result.weighted_score,
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
            existing.risk_score = result.weighted_score
            existing.risk_level = result.risk_level.value
            existing.risk_impact = result.why_it_matters
            existing.risk_signal = result.risk_signal
            existing.explanation = result.explanation
            existing.confidence = result.confidence
            existing.input_snapshot = result.input_snapshot

        await session.flush()
