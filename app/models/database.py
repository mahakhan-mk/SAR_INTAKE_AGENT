from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    JSON,
    Index,
    Integer,
    JSON,
    MetaData,
    Numeric,
    String,
    Text,
    Uuid,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.config import DATABASE_SCHEMA_TOKEN


class UUIDType(TypeDecorator):
    impl = PostgreSQLUUID(as_uuid=True)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PostgreSQLUUID(as_uuid=True))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            value = uuid.UUID(value)
        if dialect.name == "postgresql":
            return value
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None or isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(value)


UUID_TYPE = UUIDType()
JSONB_TYPE = JSON().with_variant(JSONB(), "postgresql")


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    metadata = MetaData(schema=DATABASE_SCHEMA_TOKEN)


class SarAssessment(Base):
    __tablename__ = "sar_assessments"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=new_uuid)
    technology_name: Mapped[str] = mapped_column(Text, nullable=False)
    vendor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="received")
    requested_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QuestionnaireVersion(Base):
    __tablename__ = "questionnaire_versions"
    __table_args__ = (UniqueConstraint("questionnaire_type", "version", name="uq_questionnaire_versions_type_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=new_uuid)
    questionnaire_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @is_active.setter
    def is_active(self, value: bool) -> None:
        self.status = "active" if value else "inactive"


class QuestionDefinition(Base):
    __tablename__ = "question_definitions"
    __table_args__ = (
        UniqueConstraint("questionnaire_version_id", "question_code", name="uq_question_definitions_version_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=new_uuid)
    questionnaire_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("questionnaire_versions.id"),
        nullable=False,
        index=True,
    )
    question_code: Mapped[str] = mapped_column(String(128), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    response_type: Mapped[str] = mapped_column(String(64), nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    section_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    question_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_domain: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class QuestionOption(Base):
    __tablename__ = "question_options"
    __table_args__ = (
        UniqueConstraint("question_id", "option_code", name="uq_question_options_question_code"),
        UniqueConstraint("question_id", "display_order", name="uq_question_options_question_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=new_uuid)
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("question_definitions.id"),
        nullable=False,
        index=True,
    )
    option_code: Mapped[str] = mapped_column(String(128), nullable=False)
    option_label: Mapped[str] = mapped_column(String(255), nullable=False)
    risk_weight: Mapped[float | None] = mapped_column(Numeric(asdecimal=False), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_band: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    why_it_matters: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_signal: Mapped[str | None] = mapped_column(Text, nullable=True)


class AssessmentResponse(Base):
    __tablename__ = "assessment_responses"
    __table_args__ = (
        UniqueConstraint("assessment_id", "question_id", name="uq_assessment_responses_assessment_question"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=new_uuid)
    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("sar_assessments.id"), nullable=False, index=True)
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("question_definitions.id"),
        nullable=False,
        index=True,
    )
    answer_value: Mapped[object | None] = mapped_column(JSONB_TYPE, nullable=True)
    response_status: Mapped[str] = mapped_column(String(64), nullable=False, default="answered")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewer_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)


class QuestionAnalysisRun(Base):
    __tablename__ = "question_analysis_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=new_uuid)
    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("sar_assessments.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_deployment: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    scoring_rule_version: Mapped[str] = mapped_column(String(128), nullable=False)
    intake_score: Mapped[float | None] = mapped_column(Numeric(asdecimal=False), nullable=True)
    triage_score: Mapped[float | None] = mapped_column(Numeric(asdecimal=False), nullable=True)
    inherent_score: Mapped[float | None] = mapped_column(Numeric(asdecimal=False), nullable=True)
    inherent_risk_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    executive_summary_text: Mapped[str | None] = mapped_column("executive_summary", Text, nullable=True)
    executive_summary_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    executive_summary_prompt_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    executive_summary_input_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    executive_summary_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuestionRiskResult(Base):
    __tablename__ = "question_risk_results"
    __table_args__ = (UniqueConstraint("analysis_run_id", "response_id", name="uq_question_risk_results_run_response"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=new_uuid)
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("question_analysis_runs.id"),
        nullable=False,
        index=True,
    )
    response_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("assessment_responses.id"), nullable=False, index=True)
    risk_domain: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    risk_score: Mapped[float | None] = mapped_column(Numeric(asdecimal=False), nullable=True)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    risk_impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(asdecimal=False), nullable=True)
    input_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB_TYPE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    risk_signal: Mapped[str | None] = mapped_column(Text, nullable=True)


Index("idx_question_definitions_version", QuestionDefinition.questionnaire_version_id)
Index("idx_question_options_question", QuestionOption.question_id)
Index("idx_assessment_responses_assessment", AssessmentResponse.assessment_id)
Index("idx_assessment_responses_question", AssessmentResponse.question_id)
Index("idx_question_analysis_runs_assessment", QuestionAnalysisRun.assessment_id)
Index("idx_question_analysis_runs_status", QuestionAnalysisRun.status)
Index("idx_question_risk_results_analysis_run", QuestionRiskResult.analysis_run_id)
Index("idx_question_risk_results_response", QuestionRiskResult.response_id)
