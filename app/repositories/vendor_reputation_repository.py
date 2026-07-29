from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import VendorReputationJob, VendorReputationRow


@dataclass(frozen=True, slots=True)
class VendorReputationSnapshot:
    status: str
    rows: list[VendorReputationRow]


class VendorReputationReadRepository:
    async def get_latest_snapshot(
        self,
        session: AsyncSession,
        assessment_id: UUID,
    ) -> VendorReputationSnapshot | None:
        job = (
            await session.execute(
                select(VendorReputationJob)
                .where(VendorReputationJob.assessment_id == assessment_id)
                .order_by(VendorReputationJob.created_at.desc(), VendorReputationJob.id.desc())
            )
        ).scalars().first()
        if job is None:
            return None
        rows = (
            await session.execute(
                select(VendorReputationRow)
                .where(VendorReputationRow.job_id == job.id)
                .order_by(VendorReputationRow.row_order.asc(), VendorReputationRow.id.asc())
            )
        ).scalars().all()
        return VendorReputationSnapshot(status=job.status, rows=list(rows))
