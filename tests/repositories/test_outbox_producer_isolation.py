from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import DATABASE_SCHEMA_TOKEN
from app.models.database import Base, OutboxMessage
from app.repositories.worker_messaging_repository import ASSESSMENT_WORKER_PRODUCER, WorkerOutboxRepository


ASSESSMENT_ID = UUID("11111111-1111-4111-8111-111111111111")
WORKFLOW_ID = UUID("22222222-2222-4222-8222-222222222222")
TASK_ID = UUID("33333333-3333-4333-8333-333333333333")
NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        execution_options={"schema_translate_map": {DATABASE_SCHEMA_TOKEN: None}},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _insert_outbox_row(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    producer_component: str = ASSESSMENT_WORKER_PRODUCER,
    status: str = "pending",
    locked_by: str | None = None,
    lease_expires_at: datetime | None = None,
    available_at: datetime = NOW - timedelta(seconds=1),
) -> UUID:
    message_id = uuid4()
    async with session_factory() as session:
        async with session.begin():
            session.add(
                OutboxMessage(
                    message_id=message_id,
                    producer_component=producer_component,
                    exchange_name="sar.events",
                    message_type="assessment.risk.completed",
                    schema_version=1,
                    assessment_id=ASSESSMENT_ID,
                    workflow_id=WORKFLOW_ID,
                    task_id=TASK_ID,
                    causation_id=None,
                    expected_workflow_version=4,
                    message_attempt=1,
                    actor_id="assessment-worker",
                    payload={},
                    status=status,
                    locked_by=locked_by,
                    lease_expires_at=lease_expires_at,
                    publish_attempt_count=0,
                    available_at=available_at,
                    published_at=None,
                    last_error=None,
                    created_at=NOW - timedelta(minutes=1),
                )
            )
    return message_id


async def _get_outbox_row(
    session_factory: async_sessionmaker[AsyncSession],
    message_id: UUID,
) -> OutboxMessage:
    async with session_factory() as session:
        return (
            await session.execute(select(OutboxMessage).where(OutboxMessage.message_id == message_id))
        ).scalar_one()


@pytest.mark.asyncio
async def test_assessment_publisher_claims_assessment_worker_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    message_id = await _insert_outbox_row(session_factory)
    repository = WorkerOutboxRepository()

    async with session_factory() as session:
        claimed = await repository.claim_publishable(
            session,
            limit=10,
            locked_by="publisher-a",
            lease_duration=timedelta(seconds=30),
            now=NOW,
        )
        await session.commit()

    assert ASSESSMENT_WORKER_PRODUCER == "assessment-worker"
    assert [record.message_id for record in claimed] == [message_id]
    assert claimed[0].producer_component == "assessment-worker"


@pytest.mark.asyncio
@pytest.mark.parametrize("producer_component", ["api-gateway", "orchestrator_agent", "worker_service"])
async def test_assessment_publisher_does_not_claim_foreign_producer_row(
    session_factory: async_sessionmaker[AsyncSession],
    producer_component: str,
) -> None:
    message_id = await _insert_outbox_row(session_factory, producer_component=producer_component)
    repository = WorkerOutboxRepository()

    async with session_factory() as session:
        claimed = await repository.claim_publishable(
            session,
            limit=10,
            locked_by="publisher-a",
            lease_duration=timedelta(seconds=30),
            now=NOW,
        )
        await session.commit()

    stored = await _get_outbox_row(session_factory, message_id)
    assert claimed == []
    assert stored.status == "pending"
    assert stored.locked_by is None
    assert stored.lease_expires_at is None


@pytest.mark.asyncio
async def test_mixed_producer_batch_returns_only_assessment_rows_and_leaves_foreign_pending(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    assessment_ids = [
        await _insert_outbox_row(session_factory),
        await _insert_outbox_row(session_factory),
    ]
    foreign_ids = [
        await _insert_outbox_row(session_factory, producer_component="api-gateway"),
        await _insert_outbox_row(session_factory, producer_component="orchestrator_agent"),
        await _insert_outbox_row(session_factory, producer_component="worker_service"),
    ]
    repository = WorkerOutboxRepository()

    async with session_factory() as session:
        claimed = await repository.claim_publishable(
            session,
            limit=10,
            locked_by="publisher-a",
            lease_duration=timedelta(seconds=30),
            now=NOW,
        )
        await session.commit()

    assert {record.message_id for record in claimed} == set(assessment_ids)
    assert {record.producer_component for record in claimed} == {"assessment-worker"}
    for message_id in foreign_ids:
        stored = await _get_outbox_row(session_factory, message_id)
        assert stored.status == "pending"
        assert stored.locked_by is None
        assert stored.lease_expires_at is None


@pytest.mark.asyncio
async def test_producer_predicate_is_applied_inside_locked_claim_query(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert_outbox_row(session_factory)
    statements: list[str] = []
    bind = session_factory.kw["bind"]

    def capture_sql(conn, cursor, statement, parameters, context, executemany):
        _ = conn, cursor, parameters, context, executemany
        statements.append(" ".join(statement.lower().split()))

    event.listen(bind.sync_engine, "before_cursor_execute", capture_sql)
    try:
        async with session_factory() as session:
            await WorkerOutboxRepository().claim_publishable(
                session,
                limit=10,
                locked_by="publisher-a",
                lease_duration=timedelta(seconds=30),
                now=NOW,
            )
    finally:
        event.remove(bind.sync_engine, "before_cursor_execute", capture_sql)

    claim_update = next(
        statement
        for statement in statements
        if "update" in statement and "outbox_messages" in statement
    )
    assert "producer_component" in claim_update
    assert " in (select " in claim_update
    assert "message_id" in claim_update


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["published", "failed"])
async def test_assessment_publisher_cannot_mutate_foreign_rows(
    session_factory: async_sessionmaker[AsyncSession],
    mutation: str,
) -> None:
    message_id = await _insert_outbox_row(
        session_factory,
        producer_component="api-gateway",
        status="processing",
        locked_by="publisher-a",
        lease_expires_at=NOW + timedelta(seconds=30),
    )
    repository = WorkerOutboxRepository()

    async with session_factory() as session:
        with pytest.raises(LookupError):
            if mutation == "published":
                await repository.mark_published(
                    session,
                    message_id=message_id,
                    locked_by="publisher-a",
                )
            else:
                await repository.mark_publish_failed(
                    session,
                    message_id=message_id,
                    locked_by="publisher-a",
                    current_attempt_count=0,
                    max_attempts=3,
                    error=RuntimeError("publish failed"),
                )
        await session.rollback()

    stored = await _get_outbox_row(session_factory, message_id)
    assert stored.producer_component == "api-gateway"
    assert stored.status == "processing"
    assert stored.locked_by == "publisher-a"
    assert stored.lease_expires_at is not None
    assert stored.publish_attempt_count == 0
    assert stored.published_at is None
    assert stored.last_error is None


@pytest.mark.asyncio
async def test_multiple_assessment_publisher_replicas_remain_lease_safe(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    message_id = await _insert_outbox_row(session_factory)
    repository = WorkerOutboxRepository()

    async with session_factory() as session:
        first_claim = await repository.claim_publishable(
            session,
            limit=10,
            locked_by="publisher-a",
            lease_duration=timedelta(seconds=30),
            now=NOW,
        )
        await session.commit()

    async with session_factory() as session:
        second_claim = await repository.claim_publishable(
            session,
            limit=10,
            locked_by="publisher-b",
            lease_duration=timedelta(seconds=30),
            now=NOW,
        )
        await session.commit()

    stored = await _get_outbox_row(session_factory, message_id)
    assert [record.message_id for record in first_claim] == [message_id]
    assert second_claim == []
    assert stored.status == "processing"
    assert stored.locked_by == "publisher-a"
