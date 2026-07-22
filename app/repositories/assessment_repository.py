from __future__ import annotations

from collections import defaultdict
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import AssessmentResponse, QuestionDefinition, QuestionOption, QuestionnaireVersion, SarAssessment
from app.models.dto import TriagedQuestionLoadResult, TriagedQuestionResponse
from app.models.intake import (
    IntakeHeaderRecord,
    IntakeOverviewRecord,
    IntakeQuestionRecord,
    IntakeSectionRecord,
    IntakeTriageQuestionRecord,
)
from app.models.enums import QuestionnaireType, RiskLevel

VENDOR_REPUTATION_DOMAIN = "Vendor Reputation"
INTAKE_QUESTIONNAIRE_TYPE = "intake"


class AssessmentRepository:
    async def get_assessment(self, session: AsyncSession, assessment_id: UUID | str) -> SarAssessment | None:
        return await session.get(SarAssessment, self._coerce_uuid(assessment_id))

    async def get_question(self, session: AsyncSession, question_id: UUID | str) -> QuestionDefinition | None:
        return await session.get(QuestionDefinition, self._coerce_uuid(question_id))

    async def get_question_option(
        self,
        session: AsyncSession,
        question_id: UUID | str,
        option_id: UUID | str,
    ) -> QuestionOption | None:
        return (
            await session.execute(
                select(QuestionOption).where(
                    QuestionOption.id == self._coerce_uuid(option_id),
                    QuestionOption.question_definition_id == self._coerce_uuid(question_id),
                )
            )
        ).scalars().first()

    async def get_question_option_by_label(
        self,
        session: AsyncSession,
        question_id: UUID | str,
        option_label: str,
    ) -> QuestionOption | None:
        return (
            await session.execute(
                select(QuestionOption)
                .where(
                    QuestionOption.question_definition_id == self._coerce_uuid(question_id),
                    QuestionOption.label == option_label,
                )
                .order_by(QuestionOption.display_order.asc(), QuestionOption.id.asc())
            )
        ).scalars().first()

    async def load_intake_overview(
        self,
        session: AsyncSession,
        assessment_id: UUID | str,
    ) -> IntakeOverviewRecord | None:
        assessment = await self.get_assessment(session, assessment_id)
        if assessment is None:
            return None

        intake_version = await self._get_active_questionnaire_version(session, INTAKE_QUESTIONNAIRE_TYPE)
        triage_version = await self._get_active_questionnaire_version(session, QuestionnaireType.TRIAGE.value)

        intake_questions = await self._load_visible_questions(
            session=session,
            questionnaire_version_id=intake_version.id if intake_version else None,
            order_by_section=True,
        )
        triage_questions = await self._load_visible_questions(
            session=session,
            questionnaire_version_id=triage_version.id if triage_version else None,
            order_by_section=False,
        )

        all_question_ids = [question.id for question in intake_questions]
        all_question_ids.extend(question.id for question in triage_questions)
        responses_by_question_id = await self._load_responses_by_question(session, assessment_id, all_question_ids)
        options_by_question_id, option_by_id = await self._load_options(session, all_question_ids)

        intake_question_records = [
            self._build_intake_question_record(
                question=question,
                response=responses_by_question_id.get(question.id),
                options=options_by_question_id.get(question.id, []),
                option_by_id=option_by_id,
            )
            for question in intake_questions
        ]
        triage_question_records = [
            self._build_triage_question_record(
                question=question,
                response=responses_by_question_id.get(question.id),
                options=options_by_question_id.get(question.id, []),
                option_by_id=option_by_id,
            )
            for question in triage_questions
        ]

        return IntakeOverviewRecord(
            assessment_id=assessment.id,
            header=IntakeHeaderRecord(
                technology_name=assessment.technology_name,
                source_system=None,
                questionnaire_version=intake_version.version if intake_version else None,
            ),
            sections=self._group_intake_sections(intake_question_records),
            triage=triage_question_records,
        )

    async def load_active_triage_question_responses(
        self,
        session: AsyncSession,
        assessment_id: UUID | str,
    ) -> TriagedQuestionLoadResult:
        version = await self._get_active_questionnaire_version(session, QuestionnaireType.TRIAGE.value)

        if version is None:
            return TriagedQuestionLoadResult(question_responses=[], required_triage_question_count=0)

        questions = await self._load_visible_questions(
            session=session,
            questionnaire_version_id=version.id,
            order_by_section=False,
            exclude_vendor_reputation=True,
        )

        if not questions:
            return TriagedQuestionLoadResult(question_responses=[], required_triage_question_count=0)

        question_ids = [question.id for question in questions]
        question_by_id = {question.id: question for question in questions}

        responses = list((await self._load_responses_by_question(session, assessment_id, question_ids)).values())

        if not responses:
            return TriagedQuestionLoadResult(
                question_responses=[],
                required_triage_question_count=sum(1 for question in questions if question.is_required),
            )

        options_by_question, option_by_id = await self._load_options(session, question_ids)

        resolved_questions: list[TriagedQuestionResponse] = []
        unresolved_response_ids: list[str] = []
        used_answer_value_resolution = False

        for response in responses:
            question = question_by_id.get(response.question_definition_id)
            if question is None:
                continue

            question_options = options_by_question.get(question.id, [])
            selected_option = self._resolve_selected_option(
                response=response,
                options=question_options,
                option_by_id=option_by_id,
            )
            normalized_answer = self.normalize_answer_value(response.answer_value)
            resolved_from_answer_value = (
                selected_option is not None
                and response.selected_option_id is None
                and normalized_answer == selected_option.label
            )

            if selected_option is None:
                unresolved_response_ids.append(response.id)
                continue

            used_answer_value_resolution = used_answer_value_resolution or resolved_from_answer_value
            max_risk_weight = max((option.risk_weight or 0.0) for option in question_options)
            resolved_questions.append(
                TriagedQuestionResponse(
                    question_code=question.question_code,
                    question_id=question.id,
                    response_id=response.id,
                    question_text=question.prompt,
                    risk_domain=question.risk_domain or "",
                    is_required=question.is_required,
                    why_it_matters=question.why_it_matters,
                    selected_option_id=selected_option.id,
                    selected_option_label=selected_option.label,
                    risk_weight=selected_option.risk_weight or 0.0,
                    max_risk_weight=max_risk_weight,
                    risk_level=RiskLevel(selected_option.risk_band),
                    risk_signal=selected_option.risk_signal or "",
                    confidence=0.8 if resolved_from_answer_value else 1.0,
                    resolved_from_answer_value=resolved_from_answer_value,
                )
            )

        return TriagedQuestionLoadResult(
            question_responses=resolved_questions,
            required_triage_question_count=sum(1 for question in questions if question.is_required),
            used_answer_value_resolution=used_answer_value_resolution,
            unresolved_response_ids=unresolved_response_ids,
        )

    async def _get_active_questionnaire_version(
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

    async def _load_visible_questions(
        self,
        *,
        session: AsyncSession,
        questionnaire_version_id: UUID | None,
        order_by_section: bool,
        exclude_vendor_reputation: bool = False,
    ) -> list[QuestionDefinition]:
        if questionnaire_version_id is None:
            return []

        statement = (
            select(QuestionDefinition)
            .where(
                QuestionDefinition.questionnaire_version_id == questionnaire_version_id,
                QuestionDefinition.is_visible.is_(True),
            )
            .order_by(QuestionDefinition.id.asc())
        )
        if exclude_vendor_reputation:
            statement = statement.where(QuestionDefinition.risk_domain != VENDOR_REPUTATION_DOMAIN)

        questions = (await session.execute(statement)).scalars().all()
        if order_by_section:
            return sorted(
                questions,
                key=lambda question: (
                    question.section_code or "",
                    question.question_order if question.question_order is not None else 0,
                    str(question.id),
                ),
            )
        return sorted(
            questions,
            key=lambda question: (
                question.question_order if question.question_order is not None else 0,
                str(question.id),
            ),
        )

    async def _load_responses_by_question(
        self,
        session: AsyncSession,
        assessment_id: UUID | str,
        question_ids: list[UUID],
    ) -> dict[UUID, AssessmentResponse]:
        if not question_ids:
            return {}

        responses = (
            await session.execute(
                select(AssessmentResponse)
                .where(
                    AssessmentResponse.assessment_id == self._coerce_uuid(assessment_id),
                    AssessmentResponse.question_definition_id.in_(question_ids),
                )
                .order_by(AssessmentResponse.created_at.asc(), AssessmentResponse.id.asc())
            )
        ).scalars().all()

        return {response.question_definition_id: response for response in responses}

    async def _load_options(
        self,
        session: AsyncSession,
        question_ids: list[UUID],
    ) -> tuple[dict[UUID, list[QuestionOption]], dict[UUID, QuestionOption]]:
        if not question_ids:
            return {}, {}

        options = (
            await session.execute(
                select(QuestionOption)
                .where(QuestionOption.question_definition_id.in_(question_ids))
                .order_by(QuestionOption.display_order.asc(), QuestionOption.id.asc())
            )
        ).scalars().all()

        option_by_id = {option.id: option for option in options}
        options_by_question: dict[UUID, list[QuestionOption]] = defaultdict(list)
        for option in options:
            options_by_question[option.question_definition_id].append(option)
        return options_by_question, option_by_id

    def _build_intake_question_record(
        self,
        *,
        question: QuestionDefinition,
        response: AssessmentResponse | None,
        options: list[QuestionOption],
        option_by_id: dict[UUID, QuestionOption],
    ) -> IntakeQuestionRecord:
        selected_option = self._resolve_selected_option(response=response, options=options, option_by_id=option_by_id)
        answer = self._resolve_answer(response=response, options=options, option_by_id=option_by_id)
        return IntakeQuestionRecord(
            question_id=question.id,
            question_code=question.question_code,
            label=question.prompt,
            answer=answer,
            response_type=question.response_type,
            required=question.is_required,
            risk_domain=question.risk_domain or "",
            section_code=question.section_code,
            response_id=response.id if response else None,
            selected_option_id=selected_option.id if selected_option else None,
            answer_value=self.normalize_answer_value(response.answer_value) if response else None,
        )

    def _build_triage_question_record(
        self,
        *,
        question: QuestionDefinition,
        response: AssessmentResponse | None,
        options: list[QuestionOption],
        option_by_id: dict[UUID, QuestionOption],
    ) -> IntakeTriageQuestionRecord:
        selected_option = self._resolve_selected_option(response=response, options=options, option_by_id=option_by_id)
        return IntakeTriageQuestionRecord(
            question_id=question.id,
            question_code=question.question_code,
            label=question.prompt,
            answer=self._resolve_answer(response=response, options=options, option_by_id=option_by_id),
            response_id=response.id if response else None,
            selected_option_id=selected_option.id if selected_option else None,
            answer_value=self.normalize_answer_value(response.answer_value) if response else None,
        )

    def _group_intake_sections(self, questions: list[IntakeQuestionRecord]) -> list[IntakeSectionRecord]:
        sections: list[IntakeSectionRecord] = []
        section_index_by_code: dict[str | None, int] = {}

        for question in questions:
            code = question.section_code
            if code not in section_index_by_code:
                section_index_by_code[code] = len(sections)
                sections.append(
                    IntakeSectionRecord(
                        code=code,
                        questions=[],
                    )
                )
            sections[section_index_by_code[code]].questions.append(question)

        return sections

    @staticmethod
    def _resolve_answer(
        *,
        response: AssessmentResponse | None,
        options: list[QuestionOption],
        option_by_id: dict[UUID, QuestionOption],
    ) -> str | None:
        if response is None:
            return None
        selected_option = AssessmentRepository._resolve_selected_option(
            response=response,
            options=options,
            option_by_id=option_by_id,
        )
        if selected_option is not None:
            return selected_option.label
        return AssessmentRepository.normalize_answer_value(response.answer_value)

    @staticmethod
    def _resolve_selected_option(
        *,
        response: AssessmentResponse | None,
        options: list[QuestionOption],
        option_by_id: dict[UUID, QuestionOption],
    ) -> QuestionOption | None:
        if response is None:
            return None
        if response.selected_option_id:
            selected_option = option_by_id.get(response.selected_option_id)
            if selected_option is not None:
                return selected_option
        normalized_answer = AssessmentRepository.normalize_answer_value(response.answer_value)
        if normalized_answer is None:
            return None
        return next((option for option in options if option.label == normalized_answer), None)

    @staticmethod
    def normalize_answer_value(answer_value: object | None) -> str | None:
        if answer_value is None:
            return None
        if isinstance(answer_value, str):
            return answer_value
        return json.dumps(answer_value, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _coerce_uuid(value: UUID | str) -> UUID:
        return value if isinstance(value, UUID) else UUID(value)
