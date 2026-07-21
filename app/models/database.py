from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import DATABASE_SCHEMA_TOKEN


def new_uuid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    metadata = MetaData(schema=DATABASE_SCHEMA_TOKEN)


class SarAssessment(Base):
    __tablename__ = "sar_assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    technology_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vendor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuestionnaireVersion(Base):
    __tablename__ = "questionnaire_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    questionnaire_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuestionDefinition(Base):
    __tablename__ = "question_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    questionnaire_version_id: Mapped[str] = mapped_column(
        ForeignKey("questionnaire_versions.id"),
        nullable=False,
        index=True,
    )
    question_code: Mapped[str] = mapped_column(String(255), nullable=False)
    section_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    why_it_matters: Mapped[str] = mapped_column(Text, nullable=False)
    risk_domain: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    question_order: Mapped[int | None] = mapped_column(Integer, nullable=True)


class QuestionOption(Base):
    __tablename__ = "question_options"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    question_definition_id: Mapped[str] = mapped_column(
        ForeignKey("question_definitions.id"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    risk_weight: Mapped[float] = mapped_column(Float, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    risk_band: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    risk_signal: Mapped[str] = mapped_column(Text, nullable=False)


class AssessmentResponse(Base):
    __tablename__ = "assessment_responses"
    __table_args__ = (
        UniqueConstraint(
            "assessment_id",
            "question_definition_id",
            name="uq_assessment_responses_assessment_question",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("sar_assessments.id"), nullable=False, index=True)
    question_definition_id: Mapped[str] = mapped_column(
        ForeignKey("question_definitions.id"),
        nullable=False,
        index=True,
    )
    selected_option_id: Mapped[str | None] = mapped_column(ForeignKey("question_options.id"), nullable=True)
    answer_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuestionAnalysisRun(Base):
    __tablename__ = "question_analysis_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("sar_assessments.id"), nullable=False, index=True)
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

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    analysis_run_id: Mapped[str] = mapped_column(
        ForeignKey("question_analysis_runs.id"),
        nullable=False,
        index=True,
    )
    response_id: Mapped[str] = mapped_column(ForeignKey("assessment_responses.id"), nullable=False, index=True)
    question_definition_id: Mapped[str] = mapped_column(
        ForeignKey("question_definitions.id"),
        nullable=False,
        index=True,
    )
    selected_option_id: Mapped[str | None] = mapped_column(ForeignKey("question_options.id"), nullable=True)
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
