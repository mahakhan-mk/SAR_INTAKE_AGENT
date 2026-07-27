from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    JSON,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
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


class AssessmentDocument(Base):
    __tablename__ = "assessment_documents"
    __table_args__ = (
        CheckConstraint("file_size_bytes > 0", name="assessment_documents_file_size_check"),
        CheckConstraint(
            "system_document_type IN ('SOC 2 Type II', 'ISO 27001', 'Architecture Diagram', 'Unclassified')",
            name="assessment_documents_system_type_check",
        ),
        CheckConstraint(
            "upload_source IN ('sar_request', 'checklist_row', 'checklist_unclassified')",
            name="assessment_documents_upload_source_check",
        ),
        UniqueConstraint("storage_container", "storage_key", name="assessment_documents_storage_key_unique"),
    )

    id: Mapped[uuid.UUID] = mapped_column("id", UUID_TYPE, primary_key=True, default=new_uuid)
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        "assessment_id",
        UUID_TYPE,
        ForeignKey("sar_assessments.id", ondelete="CASCADE"),
        nullable=False,
    )
    original_filename: Mapped[str] = mapped_column("original_filename", Text, nullable=False)
    content_type: Mapped[str] = mapped_column("content_type", Text, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column("file_size_bytes", BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column("sha256", Text, nullable=False)
    storage_container: Mapped[str] = mapped_column("storage_container", Text, nullable=False)
    storage_key: Mapped[str] = mapped_column("storage_key", Text, nullable=False)
    upload_source: Mapped[str] = mapped_column("upload_source", Text, nullable=False)
    system_document_type: Mapped[str] = mapped_column(
        "system_document_type",
        Text,
        nullable=False,
        server_default=text("'Unclassified'"),
    )
    uploaded_by: Mapped[str | None] = mapped_column("uploaded_by", Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column("deleted_at", DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[str | None] = mapped_column("deleted_by", Text, nullable=True)
    document_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        JSONB_TYPE,
        nullable=False,
        server_default=text("'{}'"),
    )


class DocumentChecklistRun(Base):
    __tablename__ = "document_checklist_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'draft_with_limitations', 'submitted', 'failed')",
            name="document_checklist_runs_status_check",
        ),
        CheckConstraint(
            "((status = 'submitted' AND submitted_at IS NOT NULL) OR status <> 'submitted')",
            name="document_checklist_runs_submission_check",
        ),
        CheckConstraint(
            "summary_status IN ('not_generated', 'generated', 'fallback', 'failed')",
            name="document_checklist_runs_summary_status_check",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column("id", UUID_TYPE, primary_key=True, default=new_uuid)
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        "assessment_id",
        UUID_TYPE,
        ForeignKey("sar_assessments.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column("status", Text, nullable=False, server_default=text("'draft'"))
    summary_text: Mapped[str | None] = mapped_column("summary_text", Text, nullable=True)
    summary_status: Mapped[str] = mapped_column(
        "summary_status",
        Text,
        nullable=False,
        server_default=text("'not_generated'"),
    )
    summary_model: Mapped[str | None] = mapped_column("summary_model", Text, nullable=True)
    summary_prompt_version: Mapped[str | None] = mapped_column("summary_prompt_version", Text, nullable=True)
    summary_input_hash: Mapped[str | None] = mapped_column("summary_input_hash", Text, nullable=True)
    summary_generated_at: Mapped[datetime | None] = mapped_column(
        "summary_generated_at",
        DateTime(timezone=True),
        nullable=True,
    )
    input_snapshot: Mapped[dict[str, object]] = mapped_column(
        "input_snapshot",
        JSONB_TYPE,
        nullable=False,
        server_default=text("'{}'"),
    )
    limitations: Mapped[list[object]] = mapped_column(
        "limitations",
        JSONB_TYPE,
        nullable=False,
        server_default=text("'[]'"),
    )
    error_summary: Mapped[str | None] = mapped_column("error_summary", Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime(timezone=True), server_default=func.now())
    submitted_at: Mapped[datetime | None] = mapped_column("submitted_at", DateTime(timezone=True), nullable=True)
    submitted_by: Mapped[str | None] = mapped_column("submitted_by", Text, nullable=True)


class DocumentClassificationReview(Base):
    __tablename__ = "document_classification_reviews"
    __table_args__ = (
        CheckConstraint(
            "document_type IN ('SOC 2 Type II', 'ISO 27001', 'Architecture Diagram')",
            name="document_classification_reviews_type_check",
        ),
        CheckConstraint("trim(reason) <> ''", name="document_classification_reviews_reason_check"),
    )

    id: Mapped[uuid.UUID] = mapped_column("id", UUID_TYPE, primary_key=True, default=new_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(
        "document_id",
        UUID_TYPE,
        ForeignKey("assessment_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_type: Mapped[str] = mapped_column("document_type", Text, nullable=False)
    reason: Mapped[str] = mapped_column("reason", Text, nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column("reviewed_by", Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime(timezone=True), server_default=func.now())


class DocumentChecklistItem(Base):
    __tablename__ = "document_checklist_items"
    __table_args__ = (
        CheckConstraint("item_order >= 1 AND item_order <= 3", name="document_checklist_items_order_check"),
        CheckConstraint(
            "document_type IN ('SOC 2 Type II', 'ISO 27001', 'Architecture Diagram')",
            name="document_checklist_items_type_check",
        ),
        CheckConstraint(
            "base_verdict IN ('Required', 'Recommended', 'N/A')",
            name="document_checklist_items_verdict_check",
        ),
        UniqueConstraint("checklist_run_id", "item_order", name="uq_document_checklist_items_run_order"),
        UniqueConstraint("checklist_run_id", "document_type", name="uq_document_checklist_items_run_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column("id", UUID_TYPE, primary_key=True, default=new_uuid)
    checklist_run_id: Mapped[uuid.UUID] = mapped_column(
        "checklist_run_id",
        UUID_TYPE,
        ForeignKey("document_checklist_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_type: Mapped[str] = mapped_column("document_type", Text, nullable=False)
    base_verdict: Mapped[str] = mapped_column("base_verdict", Text, nullable=False)
    item_order: Mapped[int] = mapped_column("item_order", SmallInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime(timezone=True), server_default=func.now())


class DocumentChecklistItemReview(Base):
    __tablename__ = "document_checklist_item_reviews"
    __table_args__ = (
        CheckConstraint(
            "document_type IN ('SOC 2 Type II', 'ISO 27001', 'Architecture Diagram')",
            name="document_checklist_item_reviews_type_check",
        ),
        CheckConstraint(
            "reviewer_verdict IS NULL OR reviewer_verdict IN ('Required', 'Recommended', 'N/A')",
            name="document_checklist_item_reviews_verdict_check",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column("id", UUID_TYPE, primary_key=True, default=new_uuid)
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        "assessment_id",
        UUID_TYPE,
        ForeignKey("sar_assessments.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_item_id: Mapped[uuid.UUID | None] = mapped_column(
        "source_item_id",
        UUID_TYPE,
        ForeignKey("document_checklist_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    document_type: Mapped[str] = mapped_column("document_type", Text, nullable=False)
    reviewer_verdict: Mapped[str | None] = mapped_column("reviewer_verdict", Text, nullable=True)
    reason: Mapped[str | None] = mapped_column("reason", Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column("reviewed_by", Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime(timezone=True), server_default=func.now())


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
Index(
    "idx_assessment_documents_active_type",
    AssessmentDocument.assessment_id,
    AssessmentDocument.system_document_type,
    postgresql_where=AssessmentDocument.deleted_at.is_(None),
    sqlite_where=AssessmentDocument.deleted_at.is_(None),
)
Index("idx_assessment_documents_assessment", AssessmentDocument.assessment_id, AssessmentDocument.created_at.desc())
Index(
    "uq_assessment_documents_active_hash",
    AssessmentDocument.assessment_id,
    AssessmentDocument.sha256,
    unique=True,
    postgresql_where=AssessmentDocument.deleted_at.is_(None),
    sqlite_where=AssessmentDocument.deleted_at.is_(None),
)
Index(
    "idx_document_checklist_runs_latest",
    DocumentChecklistRun.assessment_id,
    DocumentChecklistRun.created_at.desc(),
    DocumentChecklistRun.id.desc(),
)
Index(
    "idx_document_classification_reviews_latest",
    DocumentClassificationReview.document_id,
    DocumentClassificationReview.created_at.desc(),
    DocumentClassificationReview.id.desc(),
)
Index("idx_document_checklist_items_run", DocumentChecklistItem.checklist_run_id, DocumentChecklistItem.item_order)
Index(
    "idx_document_checklist_item_reviews_latest",
    DocumentChecklistItemReview.assessment_id,
    DocumentChecklistItemReview.document_type,
    DocumentChecklistItemReview.created_at.desc(),
    DocumentChecklistItemReview.id.desc(),
)
Index("idx_question_analysis_runs_assessment", QuestionAnalysisRun.assessment_id)
Index("idx_question_analysis_runs_status", QuestionAnalysisRun.status)
Index("idx_question_risk_results_analysis_run", QuestionRiskResult.analysis_run_id)
Index("idx_question_risk_results_response", QuestionRiskResult.response_id)
