from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Table, Text, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Base, JSONB_TYPE, UUID_TYPE, VendorReputationJob


vendor_reputation_jobs = VendorReputationJob.__table__

vendor_reputation_hitl_reviews = Table(
    "vendor_reputation_hitl_reviews",
    Base.metadata,
    Column("id", UUID_TYPE, primary_key=True),
    Column("job_id", UUID_TYPE, ForeignKey("vendor_reputation_jobs.id", ondelete="CASCADE"), nullable=False, unique=True),
    Column("trust_center_url", Text, nullable=True),
    Column("trust_center_final_url", Text, nullable=True),
    Column("trust_center_page_title", Text, nullable=True),
    Column("trust_center_extraction_status", Text, nullable=True),
    Column("trust_center_scraped_char_count", Integer, nullable=False),
    Column("soc2_auto_status", Text, nullable=False),
    Column("soc2_auto_evidence_text", Text, nullable=True),
    Column("soc2_auto_confidence", Text, nullable=True),
    Column("soc2_reviewer_status", Text, nullable=True),
    Column("iso27001_auto_status", Text, nullable=False),
    Column("iso27001_auto_evidence_text", Text, nullable=True),
    Column("iso27001_auto_confidence", Text, nullable=True),
    Column("iso27001_reviewer_status", Text, nullable=True),
    Column("reviewer_remarks", Text, nullable=True),
    Column("review_status", Text, nullable=False),
    Column("reviewed_by", Text, nullable=True),
    Column("reviewed_at", DateTime(timezone=True), nullable=True),
    Column("limitations", JSONB_TYPE, nullable=False),
    Column("metadata", JSONB_TYPE, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=True),
)


ELIGIBLE_VENDOR_REPUTATION_STATUSES = (
    "awaiting_hitl_review",
    "review_submitted",
    "completed",
    "completed_with_limitations",
)
VENDOR_CERTIFICATION_STATUSES = {"Available", "Under NDA", "Not Available", "Missing", "Unknown"}


@dataclass(frozen=True)
class VendorCertificationRecord:
    job_id: UUID
    hitl_review_id: UUID
    soc2_auto_status: str
    soc2_analyst_status: str | None
    soc2_status: str
    iso27001_auto_status: str
    iso27001_analyst_status: str | None
    iso27001_status: str


class VendorCertificationRepository:
    async def get_latest_eligible_hitl_review(
        self,
        session: AsyncSession,
        assessment_id: UUID | str,
    ) -> VendorCertificationRecord | None:
        row = (
            await session.execute(
                select(
                    vendor_reputation_jobs.c.id.label("job_id"),
                    vendor_reputation_hitl_reviews.c.id.label("hitl_review_id"),
                    vendor_reputation_hitl_reviews.c.soc2_auto_status,
                    vendor_reputation_hitl_reviews.c.soc2_reviewer_status,
                    vendor_reputation_hitl_reviews.c.iso27001_auto_status,
                    vendor_reputation_hitl_reviews.c.iso27001_reviewer_status,
                )
                .join(
                    vendor_reputation_hitl_reviews,
                    vendor_reputation_hitl_reviews.c.job_id == vendor_reputation_jobs.c.id,
                )
                .where(
                    vendor_reputation_jobs.c.assessment_id == self._coerce_uuid(assessment_id),
                    vendor_reputation_jobs.c.status.in_(ELIGIBLE_VENDOR_REPUTATION_STATUSES),
                )
                .order_by(
                    vendor_reputation_jobs.c.created_at.desc(),
                    vendor_reputation_jobs.c.id.desc(),
                    vendor_reputation_hitl_reviews.c.created_at.desc(),
                    vendor_reputation_hitl_reviews.c.id.desc(),
                )
            )
        ).mappings().first()
        if row is None:
            return None

        return VendorCertificationRecord(
            job_id=row["job_id"],
            hitl_review_id=row["hitl_review_id"],
            soc2_auto_status=row["soc2_auto_status"],
            soc2_analyst_status=row["soc2_reviewer_status"],
            soc2_status=self._effective_status(row["soc2_reviewer_status"], row["soc2_auto_status"]),
            iso27001_auto_status=row["iso27001_auto_status"],
            iso27001_analyst_status=row["iso27001_reviewer_status"],
            iso27001_status=self._effective_status(row["iso27001_reviewer_status"], row["iso27001_auto_status"]),
        )

    async def get_latest_certification_review_by_assessment(
        self,
        session: AsyncSession,
        assessment_id: UUID | str,
    ) -> VendorCertificationRecord | None:
        return await self.get_latest_eligible_hitl_review(session, assessment_id)

    @staticmethod
    def _effective_status(reviewer_status: str | None, auto_status: str) -> str:
        status = reviewer_status or auto_status
        if status not in VENDOR_CERTIFICATION_STATUSES:
            raise ValueError(f"Unsupported vendor certification status: {status}")
        return status

    @staticmethod
    def _coerce_uuid(value: UUID | str) -> UUID:
        return value if isinstance(value, UUID) else UUID(value)
