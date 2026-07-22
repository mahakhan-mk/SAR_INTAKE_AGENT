from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    JSON,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    Uuid,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB

from app.config import DATABASE_SCHEMA_TOKEN


UUID_TYPE = Uuid(as_uuid=True)
JSON_VALUE_TYPE = JSON(none_as_null=False).with_variant(JSONB(none_as_null=False), "postgresql")


def new_uuid() -> UUID:
    return uuid4()


class Base(DeclarativeBase):
    metadata = MetaData(schema=DATABASE_SCHEMA_TOKEN)


class SarAssessment(Base):
    __tablename__ = "sar_assessments"

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=new_uuid)
    technology_name: Mapped[str] = mapped_column(Text, nullable=False)
    vendor_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    requested_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QuestionnaireVersion(Base):
    __tablename__ = "questionnaire_versions"

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=new_uuid)
    questionnaire_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @is_active.setter
    def is_active(self, value: bool) -> None:
        self.status = "active" if value else "inactive"


class QuestionDefinition(Base):
    __tablename__ = "question_definitions"

    __allow_unmapped__ = True

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=new_uuid)
    questionnaire_version_id: Mapped[UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("questionnaire_versions.id"),
        nullable=False,
        index=True,
    )
    question_code: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column("question_text", Text, nullable=False)
    response_type: Mapped[str] = mapped_column(Text, nullable=False, default="single_select")
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    section_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    question_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_domain: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    @property
    def why_it_matters(self) -> str:
        return getattr(self, "_why_it_matters", "Configuration-defined rationale.")

    @why_it_matters.setter
    def why_it_matters(self, value: str) -> None:
        self._why_it_matters = value


class QuestionOption(Base):
    __tablename__ = "question_options"

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=new_uuid)
    question_definition_id: Mapped[UUID] = mapped_column(
        "question_id",
        UUID_TYPE,
        ForeignKey("question_definitions.id"),
        nullable=False,
        index=True,
    )
    option_code: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column("option_label", Text, nullable=False)
    risk_weight: Mapped[float | None] = mapped_column(Numeric(asdecimal=False), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    risk_band: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    why_it_matters: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_signal: Mapped[str | None] = mapped_column(Text, nullable=True)


class AssessmentResponse(Base):
    __tablename__ = "assessment_responses"
    __allow_unmapped__ = True
    _selected_option_registry: dict[UUID, UUID | None] = {}
    __table_args__ = (
        UniqueConstraint(
            "assessment_id",
            "question_id",
            name="uq_assessment_responses_assessment_question",
        ),
    )

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=new_uuid)
    assessment_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("sar_assessments.id"), nullable=False, index=True)
    question_definition_id: Mapped[UUID] = mapped_column(
        "question_id",
        UUID_TYPE,
        ForeignKey("question_definitions.id"),
        nullable=False,
        index=True,
    )
    answer_value: Mapped[Any | None] = mapped_column(JSON_VALUE_TYPE, nullable=True)
    response_status: Mapped[str] = mapped_column(Text, nullable=False, default="answered")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    reviewer_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def selected_option_id(self) -> UUID | None:
        if hasattr(self, "_selected_option_id"):
            return self._selected_option_id
        return self._selected_option_registry.get(self.id)

    @selected_option_id.setter
    def selected_option_id(self, value: UUID | None) -> None:
        self._selected_option_id = value
        self._selected_option_registry[self.id] = value


class QuestionAnalysisRun(Base):
    __tablename__ = "question_analysis_runs"

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=new_uuid)
    assessment_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("sar_assessments.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scoring_config_version: Mapped[str] = mapped_column(String(128), nullable=False)
    triage_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    inherent_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    inherent_risk_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    overall_risk_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    executive_summary_text: Mapped[str | None] = mapped_column("executive_summary", Text, nullable=True)
    executive_summary_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    executive_summary_prompt_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    executive_summary_input_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    executive_summary_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_text: Mapped[str] = mapped_column(Text, nullable=False, default="Derived from SAR triage questions.")
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    limitation_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuestionRiskResult(Base):
    __tablename__ = "question_risk_results"
    __table_args__ = (UniqueConstraint("analysis_run_id", "response_id", name="uq_question_risk_results_run_response"),)

    id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True, default=new_uuid)
    analysis_run_id: Mapped[UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("question_analysis_runs.id"),
        nullable=False,
        index=True,
    )
    response_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("assessment_responses.id"), nullable=False, index=True)
    question_definition_id: Mapped[UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("question_definitions.id"),
        nullable=False,
        index=True,
    )
    selected_option_id: Mapped[UUID | None] = mapped_column(UUID_TYPE, nullable=True)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    risk_domain: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    risk_weight: Mapped[float] = mapped_column(Float, nullable=False)
    why_it_matters: Mapped[str] = mapped_column(Text, nullable=False)
    risk_signal: Mapped[str] = mapped_column(Text, nullable=False)
    ai_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    input_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


Index("ix_question_definitions_version_order", QuestionDefinition.questionnaire_version_id, QuestionDefinition.question_order)
Index("ix_question_options_question_order", QuestionOption.question_definition_id, QuestionOption.display_order)
Index("ix_assessment_responses_assessment_question", AssessmentResponse.assessment_id, AssessmentResponse.question_definition_id)
Index("ix_question_analysis_runs_assessment_created", QuestionAnalysisRun.assessment_id, QuestionAnalysisRun.created_at)
Index("ix_question_risk_results_run_domain", QuestionRiskResult.analysis_run_id, QuestionRiskResult.risk_domain)
