from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import AssessmentResponse, QuestionDefinition, QuestionOption, QuestionnaireVersion, SarAssessment
from app.models.dto import TriagedQuestionLoadResult, TriagedQuestionResponse
from app.models.enums import QuestionnaireType, RiskLevel

SCORABLE_RESPONSE_TYPES = ("single_select", "multi_select")


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
                    QuestionDefinition.is_visible.is_(True),
                    QuestionDefinition.response_type.in_(SCORABLE_RESPONSE_TYPES),
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

            if response.response_status != "answered":
                continue

            candidate_values = self._extract_candidate_values(response.answer_value)
            if not candidate_values:
                unresolved_response_ids.append(response.id)
                continue

            selected_option = self._match_selected_option(options_by_question[question.id], candidate_values)

            if selected_option is None:
                unresolved_response_ids.append(response.id)
                continue

            if selected_option.risk_weight is None or selected_option.risk_band is None:
                unresolved_response_ids.append(response.id)
                continue

            weighted_options = [option for option in options_by_question[question.id] if option.risk_weight is not None]
            if not weighted_options:
                unresolved_response_ids.append(response.id)
                continue

            max_risk_weight = max(float(option.risk_weight) for option in weighted_options)
            resolved_questions.append(
                TriagedQuestionResponse(
                    question_code=question.question_code,
                    question_id=question.id,
                    response_id=response.id,
                    selected_option_id=selected_option.id,
                    selected_option_code=selected_option.option_code,
                    question_text=question.question_text,
                    risk_domain=question.risk_domain or "",
                    is_required=question.is_required,
                    why_it_matters=selected_option.why_it_matters or "",
                    selected_option_label=selected_option.option_label,
                    risk_weight=float(selected_option.risk_weight),
                    max_risk_weight=max_risk_weight,
                    risk_level=RiskLevel(selected_option.risk_band),
                    risk_signal=selected_option.risk_signal or "",
                    confidence=1.0,
                )
            )

        return TriagedQuestionLoadResult(
            question_responses=resolved_questions,
            required_triage_question_count=sum(1 for question in questions if question.is_required),
            unresolved_response_ids=unresolved_response_ids,
        )

    @staticmethod
    def _extract_candidate_values(answer_value: object | None) -> list[str]:
        if isinstance(answer_value, str):
            return [answer_value] if answer_value else []

        if isinstance(answer_value, dict):
            values: list[str] = []
            for key in ("optionCode", "option_code", "selectedResponse", "optionLabel", "option_label", "value"):
                values.extend(AssessmentRepository._coerce_strings(answer_value.get(key)))
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
