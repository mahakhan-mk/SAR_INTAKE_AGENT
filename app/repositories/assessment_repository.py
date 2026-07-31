from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
import uuid
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import AssessmentResponse, QuestionDefinition, QuestionOption, QuestionnaireVersion, SarAssessment
from app.application.models import TriagedQuestionLoadResult, TriagedQuestionResponse
from app.models.intake import (
    IntakeHeaderRecord,
    IntakeOverviewRecord,
    IntakeQuestionRecord,
    IntakeSectionRecord,
    IntakeTriageQuestionRecord,
)
from app.models.enums import QuestionnaireType, RiskLevel

SCORABLE_RESPONSE_TYPES = ("single_select", "multi_select")


@dataclass(frozen=True)
class AssessmentResponseProjectionRecord:
    question_code: str
    question_text: str
    questionnaire_type: str
    section_code: str | None
    question_order: int | None
    response_type: str
    answer_value: str | None
    selected_option_id: UUID | None
    selected_option_code: str | None
    selected_option_label: str | None
    reviewer_remarks: str | None


@dataclass(frozen=True)
class ResponseCompletenessRecord:
    questionnaire_type: str
    required_question_count: int
    answered_required_question_count: int
    unresolved_required_response_ids: list[UUID]

    @property
    def is_complete(self) -> bool:
        return (
            self.required_question_count == self.answered_required_question_count
            and not self.unresolved_required_response_ids
        )




@dataclass(frozen=True)
class RiskInputValidationIssue:
    reason_code: str
    questionnaire_type: str
    questionnaire_version_id: UUID | None = None
    question_id: UUID | None = None
    response_id: UUID | None = None


@dataclass(frozen=True)
class RiskInputValidationResult:
    intake_version_id: UUID | None
    triage_version_id: UUID | None
    issues: list[RiskInputValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.issues

    def summary(self) -> str:
        parts: list[str] = []
        for issue in self.issues:
            detail = issue.reason_code
            if issue.question_id is not None:
                detail += f":question={issue.question_id}"
            if issue.response_id is not None:
                detail += f":response={issue.response_id}"
            parts.append(detail)
        return "; ".join(parts)


class AssessmentRepository:
    async def get_assessment(self, session: AsyncSession, assessment_id: uuid.UUID) -> SarAssessment | None:
        return await session.get(SarAssessment, assessment_id)

    async def load_intake_overview(
        self,
        session: AsyncSession,
        assessment_id: UUID | str,
    ) -> IntakeOverviewRecord | None:
        assessment = await session.get(SarAssessment, self._coerce_uuid(assessment_id))
        if assessment is None:
            return None

        intake_version = await self._get_latest_active_questionnaire_version(session, "intake")
        triage_version = await self._get_latest_active_questionnaire_version(session, QuestionnaireType.TRIAGE.value)

        intake_questions = await self._load_visible_questions_for_version(
            session,
            intake_version.id if intake_version is not None else None,
        )
        triage_questions = await self._load_visible_questions_for_version(
            session,
            triage_version.id if triage_version is not None else None,
        )

        all_questions = intake_questions + triage_questions
        question_ids = [question.id for question in all_questions]
        responses_by_question = await self._load_responses_by_question(session, self._coerce_uuid(assessment_id), question_ids)
        options_by_question = await self._load_options_by_question(session, question_ids)

        sections_by_code: dict[str | None, list[IntakeQuestionRecord]] = defaultdict(list)
        for question in intake_questions:
            response = responses_by_question.get(question.id)
            answer, selected_option_id = self._resolve_answer(
                response.answer_value if response is not None else None,
                options_by_question.get(question.id, []),
            )
            sections_by_code[question.section_code].append(
                IntakeQuestionRecord(
                    question_id=question.id,
                    question_code=question.question_code,
                    label=question.question_text,
                    answer=answer,
                    response_type=question.response_type,
                    required=question.is_required,
                    risk_domain=question.risk_domain or "",
                    section_code=question.section_code,
                    response_id=response.id if response is not None else None,
                    selected_option_id=selected_option_id,
                    answer_value=answer,
                )
            )

        sections = [
            IntakeSectionRecord(code=section_code, questions=questions)
            for section_code, questions in sorted(
                sections_by_code.items(),
                key=lambda item: (item[0] is None, item[0] or ""),
            )
        ]

        triage = []
        for question in triage_questions:
            response = responses_by_question.get(question.id)
            answer, selected_option_id = self._resolve_answer(
                response.answer_value if response is not None else None,
                options_by_question.get(question.id, []),
            )
            triage.append(
                IntakeTriageQuestionRecord(
                    question_id=question.id,
                    question_code=question.question_code,
                    label=question.question_text,
                    answer=answer,
                    response_id=response.id if response is not None else None,
                    selected_option_id=selected_option_id,
                    answer_value=answer,
                )
            )

        return IntakeOverviewRecord(
            assessment_id=assessment.id,
            header=IntakeHeaderRecord(
                technology_name=assessment.technology_name,
                source_system=None,
                questionnaire_version=intake_version.version if intake_version is not None else None,
            ),
            sections=sections,
            triage=triage,
        )

    async def get_question(self, session: AsyncSession, question_id: UUID | str) -> QuestionDefinition | None:
        return await session.get(QuestionDefinition, self._coerce_uuid(question_id))

    async def get_question_option(
        self,
        session: AsyncSession,
        *,
        question_id: UUID | str,
        option_id: UUID | str,
    ) -> QuestionOption | None:
        return (
            await session.execute(
                select(QuestionOption).where(
                    QuestionOption.question_id == self._coerce_uuid(question_id),
                    QuestionOption.id == self._coerce_uuid(option_id),
                )
            )
        ).scalars().first()

    async def get_question_option_by_label(
        self,
        session: AsyncSession,
        *,
        question_id: UUID | str,
        option_label: str,
    ) -> QuestionOption | None:
        return (
            await session.execute(
                select(QuestionOption).where(
                    QuestionOption.question_id == self._coerce_uuid(question_id),
                    QuestionOption.option_label == option_label,
                )
            )
        ).scalars().first()

    async def list_visible_assessment_responses(
        self,
        session: AsyncSession,
        assessment_id: UUID | str,
    ) -> list[AssessmentResponseProjectionRecord]:
        rows = (
            await session.execute(
                select(AssessmentResponse, QuestionDefinition, QuestionnaireVersion)
                .join(QuestionDefinition, QuestionDefinition.id == AssessmentResponse.question_id)
                .join(QuestionnaireVersion, QuestionnaireVersion.id == QuestionDefinition.questionnaire_version_id)
                .where(
                    AssessmentResponse.assessment_id == self._coerce_uuid(assessment_id),
                    QuestionDefinition.is_visible.is_(True),
                )
                .order_by(
                    QuestionnaireVersion.questionnaire_type.asc(),
                    QuestionDefinition.question_order.asc().nullslast(),
                    QuestionDefinition.id.asc(),
                )
            )
        ).all()
        question_ids = [question.id for _, question, _ in rows]
        options_by_question = await self._load_options_by_question(session, question_ids)

        projections: list[AssessmentResponseProjectionRecord] = []
        for response, question, version in rows:
            selected_option = self._match_answer_to_option(
                options_by_question.get(question.id, []),
                response.answer_value,
            )
            projections.append(
                AssessmentResponseProjectionRecord(
                    question_code=question.question_code,
                    question_text=question.question_text,
                    questionnaire_type=version.questionnaire_type,
                    section_code=question.section_code,
                    question_order=question.question_order,
                    response_type=question.response_type,
                    answer_value=(
                        selected_option.option_label
                        if selected_option is not None
                        else self.normalize_answer_value(response.answer_value)
                    ),
                    selected_option_id=selected_option.id if selected_option is not None else None,
                    selected_option_code=selected_option.option_code if selected_option is not None else None,
                    selected_option_label=selected_option.option_label if selected_option is not None else None,
                    reviewer_remarks=response.reviewer_remarks,
                )
            )
        return projections

    @staticmethod
    def normalize_answer_value(answer_value: object | None) -> str | None:
        if isinstance(answer_value, str):
            return answer_value
        if isinstance(answer_value, dict):
            for key in ("optionLabel", "selectedResponse", "option_label", "value"):
                value = answer_value.get(key)
                if isinstance(value, str):
                    return value
            return None
        return None

    async def resolve_represented_questionnaire_version(
        self,
        session: AsyncSession,
        assessment_id: UUID | str,
        questionnaire_type: str,
    ) -> tuple[UUID | None, list[RiskInputValidationIssue]]:
        rows = (
            await session.execute(
                select(QuestionnaireVersion.id)
                .join(QuestionDefinition, QuestionDefinition.questionnaire_version_id == QuestionnaireVersion.id)
                .join(AssessmentResponse, AssessmentResponse.question_id == QuestionDefinition.id)
                .where(
                    AssessmentResponse.assessment_id == self._coerce_uuid(assessment_id),
                    QuestionnaireVersion.questionnaire_type == questionnaire_type,
                )
                .distinct()
            )
        ).scalars().all()
        version_ids = list(rows)
        if not version_ids:
            return None, [RiskInputValidationIssue(
                reason_code="QUESTIONNAIRE_VERSION_NOT_REPRESENTED",
                questionnaire_type=questionnaire_type,
            )]
        if len(version_ids) != 1:
            return None, [RiskInputValidationIssue(
                reason_code="MULTIPLE_QUESTIONNAIRE_VERSIONS_REPRESENTED",
                questionnaire_type=questionnaire_type,
            )]
        return version_ids[0], []

    async def validate_risk_inputs(
        self,
        session: AsyncSession,
        assessment_id: UUID | str,
    ) -> RiskInputValidationResult:
        assessment_uuid = self._coerce_uuid(assessment_id)
        issues: list[RiskInputValidationIssue] = []
        intake_version_id, intake_issues = await self.resolve_represented_questionnaire_version(
            session, assessment_uuid, "intake"
        )
        triage_version_id, triage_issues = await self.resolve_represented_questionnaire_version(
            session, assessment_uuid, QuestionnaireType.TRIAGE.value
        )
        issues.extend(intake_issues)
        issues.extend(triage_issues)

        for questionnaire_type, version_id in (
            ("intake", intake_version_id),
            (QuestionnaireType.TRIAGE.value, triage_version_id),
        ):
            if version_id is None:
                continue
            questions = (await session.execute(
                select(QuestionDefinition).where(
                    QuestionDefinition.questionnaire_version_id == version_id,
                    QuestionDefinition.is_visible.is_(True),
                    QuestionDefinition.is_required.is_(True),
                )
            )).scalars().all()
            responses = (await session.execute(
                select(AssessmentResponse).where(
                    AssessmentResponse.assessment_id == assessment_uuid,
                    AssessmentResponse.question_id.in_([q.id for q in questions]) if questions else False,
                )
            )).scalars().all() if questions else []
            response_by_question = {r.question_id: r for r in responses}
            options_by_question = await self._load_options_by_question(session, [q.id for q in questions])
            for question in questions:
                response = response_by_question.get(question.id)
                if response is None:
                    issues.append(RiskInputValidationIssue("REQUIRED_RESPONSE_MISSING", questionnaire_type, version_id, question.id))
                    continue
                if response.response_status != "answered":
                    issues.append(RiskInputValidationIssue("RESPONSE_NOT_ANSWERED", questionnaire_type, version_id, question.id, response.id))
                    continue
                if not self._answer_matches_type(question.response_type, response.answer_value):
                    issues.append(RiskInputValidationIssue("INVALID_ANSWER_VALUE", questionnaire_type, version_id, question.id, response.id))
                    continue
                if question.response_type == "single_select":
                    if self._match_answer_to_option(options_by_question.get(question.id, []), response.answer_value) is None:
                        issues.append(RiskInputValidationIssue("SELECTED_OPTION_NOT_RESOLVED", questionnaire_type, version_id, question.id, response.id))
                elif question.response_type == "multi_select":
                    issues.append(RiskInputValidationIssue("UNSUPPORTED_MULTI_SELECT_CONTRACT", questionnaire_type, version_id, question.id, response.id))

        return RiskInputValidationResult(intake_version_id, triage_version_id, issues)

    async def load_active_triage_question_responses(
        self,
        session: AsyncSession,
        assessment_id: uuid.UUID,
    ) -> TriagedQuestionLoadResult:
        version_id, version_issues = await self.resolve_represented_questionnaire_version(
            session, assessment_id, QuestionnaireType.TRIAGE.value
        )
        if version_id is None:
            return TriagedQuestionLoadResult([], 0, [], version_issues)

        questions = (await session.execute(
            select(QuestionDefinition).where(
                QuestionDefinition.questionnaire_version_id == version_id,
                QuestionDefinition.is_visible.is_(True),
                QuestionDefinition.question_weight.is_not(None),
            ).order_by(QuestionDefinition.question_order.asc(), QuestionDefinition.id.asc())
        )).scalars().all()
        if not questions:
            issue = RiskInputValidationIssue("NO_SCORABLE_TRIAGE_QUESTIONS", QuestionnaireType.TRIAGE.value, version_id)
            return TriagedQuestionLoadResult([], 0, [], [issue])

        question_ids = [q.id for q in questions]
        responses = (await session.execute(
            select(AssessmentResponse).where(
                AssessmentResponse.assessment_id == assessment_id,
                AssessmentResponse.question_id.in_(question_ids),
            )
        )).scalars().all()
        response_by_question = {r.question_id: r for r in responses}
        options_by_question = await self._load_options_by_question(session, question_ids)
        resolved: list[TriagedQuestionResponse] = []
        unresolved: list[uuid.UUID] = []
        issues: list[RiskInputValidationIssue] = []

        for question in questions:
            response = response_by_question.get(question.id)
            if response is None or response.response_status != "answered":
                issues.append(RiskInputValidationIssue("SCORABLE_RESPONSE_MISSING", QuestionnaireType.TRIAGE.value, version_id, question.id, response.id if response else None))
                continue
            if question.response_type == "multi_select":
                issues.append(RiskInputValidationIssue("UNSUPPORTED_MULTI_SELECT_CONTRACT", QuestionnaireType.TRIAGE.value, version_id, question.id, response.id))
                unresolved.append(response.id)
                continue
            if question.response_type != "single_select":
                issues.append(RiskInputValidationIssue("INVALID_ANSWER_VALUE", QuestionnaireType.TRIAGE.value, version_id, question.id, response.id))
                unresolved.append(response.id)
                continue
            selected = self._match_answer_to_option(options_by_question.get(question.id, []), response.answer_value)
            if selected is None:
                issues.append(RiskInputValidationIssue("SELECTED_OPTION_NOT_RESOLVED", QuestionnaireType.TRIAGE.value, version_id, question.id, response.id))
                unresolved.append(response.id)
                continue
            if selected.risk_weight is None:
                issues.append(RiskInputValidationIssue("OPTION_RISK_WEIGHT_MISSING", QuestionnaireType.TRIAGE.value, version_id, question.id, response.id))
                unresolved.append(response.id)
                continue
            if selected.risk_band is None:
                issues.append(RiskInputValidationIssue("OPTION_RISK_BAND_MISSING", QuestionnaireType.TRIAGE.value, version_id, question.id, response.id))
                unresolved.append(response.id)
                continue
            if selected.risk_band not in {"low", "medium", "high", "critical"}:
                issues.append(RiskInputValidationIssue("OPTION_RISK_BAND_INVALID", QuestionnaireType.TRIAGE.value, version_id, question.id, response.id))
                unresolved.append(response.id)
                continue
            weighted = [o for o in options_by_question.get(question.id, []) if o.risk_weight is not None]
            if not weighted:
                issues.append(RiskInputValidationIssue("OPTION_RISK_WEIGHT_MISSING", QuestionnaireType.TRIAGE.value, version_id, question.id, response.id))
                unresolved.append(response.id)
                continue
            qw = int(question.question_weight)
            ow = float(selected.risk_weight)
            max_ow = max(float(o.risk_weight) for o in weighted)
            resolved.append(TriagedQuestionResponse(
                question_code=question.question_code, question_id=question.id, response_id=response.id,
                selected_option_id=selected.id, selected_option_code=selected.option_code,
                question_text=question.question_text, risk_domain=question.risk_domain or "",
                is_required=question.is_required, why_it_matters=question.why_it_matters or "",
                selected_option_label=selected.option_label, question_weight=qw, option_weight=ow,
                weighted_score=qw * ow, max_option_weight=max_ow, max_weighted_score=qw * max_ow,
                risk_level=RiskLevel(selected.risk_band), risk_signal=selected.risk_signal or "", confidence=1.0,
            ))
        return TriagedQuestionLoadResult(resolved, len(questions), unresolved, issues)

    async def load_required_response_completeness(
        self,
        session: AsyncSession,
        assessment_id: UUID | str,
        questionnaire_type: str,
    ) -> ResponseCompletenessRecord:
        version_id, _ = await self.resolve_represented_questionnaire_version(session, assessment_id, questionnaire_type)
        if version_id is None:
            return ResponseCompletenessRecord(questionnaire_type, 1, 0, [])
        questions = (await session.execute(
            select(QuestionDefinition).where(
                QuestionDefinition.questionnaire_version_id == version_id,
                QuestionDefinition.is_visible.is_(True),
                QuestionDefinition.is_required.is_(True),
            )
        )).scalars().all()
        if not questions:
            return ResponseCompletenessRecord(questionnaire_type, 1, 0, [])
        responses = (await session.execute(
            select(AssessmentResponse).where(
                AssessmentResponse.assessment_id == self._coerce_uuid(assessment_id),
                AssessmentResponse.question_id.in_([q.id for q in questions]),
            )
        )).scalars().all()
        by_question = {r.question_id: r for r in responses}
        answered = 0
        unresolved: list[UUID] = []
        for question in questions:
            response = by_question.get(question.id)
            if response is None or response.response_status != "answered":
                continue
            if not self._answer_matches_type(question.response_type, response.answer_value):
                unresolved.append(response.id)
                continue
            answered += 1
        return ResponseCompletenessRecord(questionnaire_type, len(questions), answered, unresolved)

    @classmethod
    def _answer_matches_type(cls, response_type: str, value: object | None) -> bool:
        if response_type in {"text", "date"}:
            return isinstance(value, str) and bool(value.strip())
        if response_type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if response_type == "boolean":
            return isinstance(value, bool)
        if response_type == "single_select":
            return isinstance(value, (str, dict)) and bool(cls._extract_candidate_values(value))
        if response_type == "multi_select":
            return isinstance(value, list) and bool(value)
        return False

    @staticmethod
    def _extract_candidate_values(answer_value: object | None) -> list[str]:
        if isinstance(answer_value, str):
            return [answer_value] if answer_value else []

        if isinstance(answer_value, dict):
            values: list[str] = []
            for key in ("selectedOptionId", "optionCode", "option_code", "selectedResponse", "optionLabel", "option_label", "value"):
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

    async def _get_latest_active_questionnaire_version(
        self,
        session: AsyncSession,
        questionnaire_type: str,
    ) -> QuestionnaireVersion | None:
        return (
            await session.execute(
                select(QuestionnaireVersion)
                .where(
                    QuestionnaireVersion.questionnaire_type == questionnaire_type,
                    QuestionnaireVersion.status == "active",
                )
                .order_by(QuestionnaireVersion.created_at.desc(), QuestionnaireVersion.id.desc())
            )
        ).scalars().first()

    async def _load_visible_questions_for_version(
        self,
        session: AsyncSession,
        questionnaire_version_id: UUID | None,
    ) -> list[QuestionDefinition]:
        if questionnaire_version_id is None:
            return []
        questions = (
            await session.execute(
                select(QuestionDefinition)
                .where(
                    QuestionDefinition.questionnaire_version_id == questionnaire_version_id,
                    QuestionDefinition.is_visible.is_(True),
                )
            )
        ).scalars().all()
        return sorted(questions, key=self._question_sort_key)

    async def _load_responses_by_question(
        self,
        session: AsyncSession,
        assessment_id: UUID,
        question_ids: list[UUID],
    ) -> dict[UUID, AssessmentResponse]:
        if not question_ids:
            return {}
        responses = (
            await session.execute(
                select(AssessmentResponse)
                .where(
                    AssessmentResponse.assessment_id == assessment_id,
                    AssessmentResponse.question_id.in_(question_ids),
                )
                .order_by(AssessmentResponse.created_at.desc(), AssessmentResponse.id.desc())
            )
        ).scalars().all()
        return {response.question_id: response for response in reversed(responses)}

    async def _load_options_by_question(
        self,
        session: AsyncSession,
        question_ids: list[UUID],
    ) -> dict[UUID, list[QuestionOption]]:
        if not question_ids:
            return {}
        options = (
            await session.execute(
                select(QuestionOption)
                .where(QuestionOption.question_id.in_(question_ids))
                .order_by(QuestionOption.display_order.asc(), QuestionOption.id.asc())
            )
        ).scalars().all()
        options_by_question: dict[UUID, list[QuestionOption]] = defaultdict(list)
        for option in options:
            options_by_question[option.question_id].append(option)
        return options_by_question

    @classmethod
    def _resolve_answer(
        cls,
        answer_value: object | None,
        options: list[QuestionOption],
    ) -> tuple[str | None, UUID | None]:
        selected_option = cls._match_answer_to_option(options, answer_value)
        if selected_option is not None:
            return selected_option.option_label, selected_option.id
        return cls.normalize_answer_value(answer_value), None

    @staticmethod
    def _match_answer_to_option(
        options: list[QuestionOption],
        answer_value: object | None,
    ) -> QuestionOption | None:
        if isinstance(answer_value, dict):
            selected_option_id = answer_value.get("selectedOptionId")
            if isinstance(selected_option_id, str):
                try:
                    selected_option_uuid = UUID(selected_option_id)
                except ValueError:
                    selected_option_uuid = None
                if selected_option_uuid is not None:
                    for option in options:
                        if option.id == selected_option_uuid:
                            return option
            for key, attr in (("optionCode", "option_code"), ("optionLabel", "option_label")):
                candidate = answer_value.get(key)
                if isinstance(candidate, str):
                    for option in options:
                        if getattr(option, attr) == candidate:
                            return option

        if isinstance(answer_value, str):
            for option in options:
                if option.option_label == answer_value:
                    return option
                if option.option_code == answer_value:
                    return option
        return None

    @staticmethod
    def _question_sort_key(question: QuestionDefinition) -> tuple[int, int, UUID]:
        return (
            0 if question.question_order is not None else 1,
            question.question_order or 0,
            question.id,
        )

    @staticmethod
    def _coerce_uuid(value: UUID | str) -> UUID:
        return value if isinstance(value, UUID) else UUID(str(value))
