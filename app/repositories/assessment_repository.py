from __future__ import annotations

from collections import defaultdict
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import AssessmentResponse, QuestionDefinition, QuestionOption, QuestionnaireVersion, SarAssessment
from app.models.dto import TriagedQuestionLoadResult, TriagedQuestionResponse
from app.models.enums import QuestionnaireType, RiskLevel

VENDOR_REPUTATION_DOMAIN = "Vendor Reputation"


class AssessmentRepository:
    async def get_assessment(self, session: AsyncSession, assessment_id: uuid.UUID) -> SarAssessment | None:
        return await session.get(SarAssessment, assessment_id)

    async def load_active_triage_question_responses(
        self,
        session: AsyncSession,
        assessment_id: uuid.UUID,
    ) -> TriagedQuestionLoadResult:
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
            return TriagedQuestionLoadResult(question_responses=[], required_triage_question_count=0)

        questions = (
            await session.execute(
                select(QuestionDefinition)
                .where(
                    QuestionDefinition.questionnaire_version_id == version.id,
                    QuestionDefinition.risk_domain != VENDOR_REPUTATION_DOMAIN,
                )
                .order_by(QuestionDefinition.question_order.asc(), QuestionDefinition.id.asc())
            )
        ).scalars().all()

        if not questions:
            return TriagedQuestionLoadResult(question_responses=[], required_triage_question_count=0)

        question_ids = [question.id for question in questions]
        question_by_id = {question.id: question for question in questions}

        responses = (
            await session.execute(
                select(AssessmentResponse)
                .where(
                    AssessmentResponse.assessment_id == assessment_id,
                    AssessmentResponse.question_id.in_(question_ids),
                )
                .order_by(AssessmentResponse.created_at.asc(), AssessmentResponse.id.asc())
            )
        ).scalars().all()

        if not responses:
            return TriagedQuestionLoadResult(
                question_responses=[],
                required_triage_question_count=sum(1 for question in questions if question.is_required),
            )

        options = (
            await session.execute(
                select(QuestionOption)
                .where(QuestionOption.question_id.in_(question_ids))
                .order_by(QuestionOption.display_order.asc(), QuestionOption.id.asc())
            )
        ).scalars().all()

        options_by_question: dict[uuid.UUID, list[QuestionOption]] = defaultdict(list)
        for option in options:
            options_by_question[option.question_id].append(option)

        resolved_questions: list[TriagedQuestionResponse] = []
        unresolved_response_ids: list[uuid.UUID] = []

        for response in responses:
            question = question_by_id.get(response.question_id)
            if question is None:
                continue

            selected_response = self._extract_selected_response(response.answer_value)
            if selected_response is None:
                unresolved_response_ids.append(response.id)
                continue

            selected_option = next(
                (
                    option
                    for option in options_by_question[question.id]
                    if option.option_label == selected_response
                ),
                None,
            )

            if selected_option is None:
                unresolved_response_ids.append(response.id)
                continue

            max_risk_weight = max(option.risk_weight for option in options_by_question[question.id])
            resolved_questions.append(
                TriagedQuestionResponse(
                    question_code=question.question_code,
                    question_id=question.id,
                    response_id=response.id,
                    question_text=question.question_text,
                    risk_domain=question.risk_domain,
                    is_required=question.is_required,
                    why_it_matters=selected_option.why_it_matters,
                    selected_option_label=selected_option.option_label,
                    risk_weight=selected_option.risk_weight,
                    max_risk_weight=max_risk_weight,
                    risk_level=RiskLevel(selected_option.risk_band),
                    risk_signal=selected_option.risk_signal,
                    confidence=1.0,
                )
            )

        return TriagedQuestionLoadResult(
            question_responses=resolved_questions,
            required_triage_question_count=sum(1 for question in questions if question.is_required),
            unresolved_response_ids=unresolved_response_ids,
        )

    @staticmethod
    def _extract_selected_response(answer_value: dict[str, object] | None) -> str | None:
        if not isinstance(answer_value, dict):
            return None
        value = answer_value.get("selectedResponse")
        return value if isinstance(value, str) else None
