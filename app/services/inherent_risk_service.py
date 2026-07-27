from __future__ import annotations

from collections import defaultdict
from typing import Sequence
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AssessmentNotFoundError
from app.assemblers.inherent_risk_assembler import InherentRiskAssembler
from app.config import InherentRiskScoringPolicy
from app.models.dto import (
    AnalysisRunCreateResponseDTO,
    ComputedQuestionRisk,
    InherentRiskScreenState,
    StoredAnalysisSnapshot,
    TopRiskDriverState,
    TriagedQuestionLoadResult,
)
from app.models.enums import AnalysisRunStatus, ExecutiveSummaryStatus, RiskLevel
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.assessment_repository import AssessmentRepository

NO_RESPONSES_LIMITATION = "No answered triage responses were available for scoring."
MISSING_RESPONSES_LIMITATION = "One or more triage questions are unanswered; scoring used the available responses only."
UNRESOLVED_LIMITATION = "One or more stored responses could not be resolved to a configured triage option."


class InherentRiskService:
    def __init__(
        self,
        assessment_repository: AssessmentRepository,
        analysis_repository: AnalysisRepository,
        assembler: InherentRiskAssembler,
        scoring_policy: InherentRiskScoringPolicy,
    ) -> None:
        self.assessment_repository = assessment_repository
        self.analysis_repository = analysis_repository
        self.assembler = assembler
        self.scoring_policy = scoring_policy

    async def get_inherent_risk_screen(self, session: AsyncSession, assessment_id: uuid.UUID):
        assessment = await self.assessment_repository.get_assessment(session, assessment_id)
        if assessment is None:
            raise AssessmentNotFoundError()

        snapshot = await self.analysis_repository.get_latest_completed_snapshot(session, assessment_id)
        if snapshot is None:
            snapshot = await self._create_and_persist_analysis(
                session=session,
                assessment_id=assessment_id,
                persist_empty_run=False,
            )

        if snapshot is None:
            return self.assembler.to_dto(self._not_assessed_state(assessment_id, analysis_run_id=None))

        return self.assembler.to_dto(self._build_state_from_snapshot(assessment_id, snapshot))

    async def create_analysis_run(
        self,
        session: AsyncSession,
        assessment_id: uuid.UUID,
        force: bool = False,
    ) -> AnalysisRunCreateResponseDTO:
        del force

        assessment = await self.assessment_repository.get_assessment(session, assessment_id)
        if assessment is None:
            raise AssessmentNotFoundError()

        snapshot = await self._create_and_persist_analysis(
            session=session,
            assessment_id=assessment_id,
            persist_empty_run=True,
        )

        if snapshot is None:
            return AnalysisRunCreateResponseDTO(
                analysisRunId="",
                status=AnalysisRunStatus.COMPLETED_WITH_LIMITATIONS,
            )

        return AnalysisRunCreateResponseDTO(
            analysisRunId=str(snapshot.analysis_run_id),
            status=snapshot.status,
        )

    def _build_state_from_snapshot(
        self,
        assessment_id: uuid.UUID,
        snapshot: StoredAnalysisSnapshot,
    ) -> InherentRiskScreenState:
        high_risk_count = sum(
            1
            for result in snapshot.question_results
            if result.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
        )
        return InherentRiskScreenState(
            assessment_id=assessment_id,
            analysis_run_id=snapshot.analysis_run_id,
            status=snapshot.status,
            inherent_risk_level=snapshot.inherent_risk_level,
            high_risk_question_count=high_risk_count,
            top_risk_drivers=self._derive_top_risk_drivers(snapshot.question_results),
            executive_summary_status=snapshot.executive_summary_status,
            executive_summary_text=snapshot.executive_summary_text,
            executive_summary_generated_at=snapshot.executive_summary_generated_at,
        )

    def _not_assessed_state(
        self,
        assessment_id: uuid.UUID,
        analysis_run_id: uuid.UUID | None,
    ) -> InherentRiskScreenState:
        return InherentRiskScreenState(
            assessment_id=assessment_id,
            analysis_run_id=analysis_run_id,
            status=AnalysisRunStatus.COMPLETED_WITH_LIMITATIONS,
            inherent_risk_level=RiskLevel.NOT_ASSESSED,
            high_risk_question_count=0,
            top_risk_drivers=[],
            executive_summary_status=ExecutiveSummaryStatus.NOT_GENERATED,
            executive_summary_text=None,
            executive_summary_generated_at=None,
        )

    async def _create_and_persist_analysis(
        self,
        session: AsyncSession,
        assessment_id: uuid.UUID,
        persist_empty_run: bool,
    ) -> StoredAnalysisSnapshot | None:
        triage_payload = await self.assessment_repository.load_active_triage_question_responses(
            session,
            assessment_id,
        )
        if not triage_payload.question_responses and not persist_empty_run:
            return None

        question_results = self._build_question_results(triage_payload)
        triage_score = sum(result.risk_weight for result in question_results) if question_results else 0.0
        inherent_score = self._calculate_score_percentage(question_results)
        overall_level = (
            RiskLevel.NOT_ASSESSED
            if not question_results
            else self.scoring_policy.determine_level(inherent_score) or RiskLevel.NOT_ASSESSED
        )

        limitations = self._build_limitations(triage_payload)
        if not question_results:
            limitations.insert(0, NO_RESPONSES_LIMITATION)

        status = (
            AnalysisRunStatus.COMPLETED_WITH_LIMITATIONS
            if limitations or not question_results
            else AnalysisRunStatus.COMPLETED
        )
        run = await self.analysis_repository.create_analysis_run(
            session=session,
            assessment_id=assessment_id,
            status=status,
            scoring_rule_version=self.scoring_policy.version,
            triage_score=triage_score,
            inherent_score=inherent_score,
            inherent_risk_level=overall_level,
        )
        await self.analysis_repository.upsert_question_risk_results(session, run.id, question_results)

        return StoredAnalysisSnapshot(
            analysis_run_id=run.id,
            status=status,
            triage_score=triage_score,
            inherent_score=inherent_score,
            inherent_risk_level=overall_level,
            executive_summary_status=ExecutiveSummaryStatus.NOT_GENERATED,
            executive_summary_text=None,
            executive_summary_model=None,
            executive_summary_prompt_version=None,
            executive_summary_input_hash=None,
            executive_summary_generated_at=None,
            error_summary=None,
            question_results=question_results,
        )

    def _build_question_results(
        self,
        triage_payload: TriagedQuestionLoadResult,
    ) -> list[ComputedQuestionRisk]:
        question_results: list[ComputedQuestionRisk] = []
        for response in triage_payload.question_responses:
            explanation = (
                f'Question "{response.question_text}" was answered with "{response.selected_option_label}". '
                f"This matters because {response.why_it_matters} "
                f"The selected response indicates {response.risk_signal}."
            )
            input_snapshot = {
                "questionCode": response.question_code,
                "questionId": str(response.question_id),
                "questionText": response.question_text,
                "selectedOptionId": str(response.selected_option_id),
                "selectedOptionCode": response.selected_option_code,
                "selectedOptionLabel": response.selected_option_label,
                "selectedResponse": response.selected_option_label,
                "riskWeight": response.risk_weight,
                "maxRiskWeight": response.max_risk_weight,
                "whyItMatters": response.why_it_matters,
                "riskSignal": response.risk_signal,
                "riskBand": response.risk_level.value,
                "scoringRuleVersion": self.scoring_policy.version,
            }
            question_results.append(
                ComputedQuestionRisk(
                    question_code=response.question_code,
                    response_id=response.response_id,
                    question_definition_id=response.question_id,
                    selected_option_id=response.selected_option_id,
                    selected_option_label=response.selected_option_label,
                    question_text=response.question_text,
                    risk_domain=response.risk_domain,
                    risk_level=response.risk_level,
                    risk_weight=response.risk_weight,
                    max_risk_weight=response.max_risk_weight,
                    why_it_matters=response.why_it_matters,
                    risk_signal=response.risk_signal,
                    explanation=explanation,
                    confidence=response.confidence,
                    input_snapshot=input_snapshot,
                )
            )
        return question_results

    def _calculate_score_percentage(self, question_results: Sequence[ComputedQuestionRisk]) -> float | None:
        if not question_results:
            return None
        total_score = sum(result.risk_weight for result in question_results)
        max_score = sum(result.max_risk_weight for result in question_results)
        if max_score <= 0:
            return None
        return (total_score / max_score) * 100.0

    def _build_limitations(self, triage_payload: TriagedQuestionLoadResult) -> list[str]:
        limitations: list[str] = []
        answered_required_question_count = len(
            {response.question_id for response in triage_payload.question_responses if response.is_required}
        )
        if triage_payload.required_triage_question_count > answered_required_question_count:
            limitations.append(MISSING_RESPONSES_LIMITATION)
        if triage_payload.unresolved_response_ids:
            limitations.append(UNRESOLVED_LIMITATION)
        return limitations

    def _derive_top_risk_drivers(
        self,
        question_results: Sequence[ComputedQuestionRisk],
    ) -> list[TopRiskDriverState]:
        grouped: dict[str, list[ComputedQuestionRisk]] = defaultdict(list)
        for result in question_results:
            if result.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
                grouped[result.risk_domain].append(result)

        ranked_domains: list[tuple[int, float, str, RiskLevel]] = []
        for domain, domain_results in grouped.items():
            highest_level = max((result.risk_level for result in domain_results), key=lambda level: level.rank)
            highest_weight = max(result.risk_weight for result in domain_results)
            ranked_domains.append((highest_level.rank, highest_weight, domain, highest_level))

        ranked_domains.sort(key=lambda item: (-item[0], -item[1], item[2]))
        return [
            TopRiskDriverState(domain=domain, level=level)
            for _, _, domain, level in ranked_domains[:3]
        ]
