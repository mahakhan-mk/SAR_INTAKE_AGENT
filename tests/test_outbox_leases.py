from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import DATABASE_SCHEMA_TOKEN
from app.messaging.outbox_publisher import OutboxPublisher
from app.models.database import Base, OutboxMessage
from app.repositories.worker_messaging_repository import OutboxMessageRecord, WorkerOutboxRepository


ASSESSMENT_ID = UUID("11111111-1111-4111-8111-111111111111")
WORKFLOW_ID = UUID("22222222-2222-4222-8222-222222222222")
TASK_ID = UUID("33333333-3333-4333-8333-333333333333")
NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        execution_options={
            "schema_translate_map": {
                DATABASE_SCHEMA_TOKEN: None,
            }
        },
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    try:
        yield factory
    finally:
        await engine.dispose()


async def _insert_outbox_row(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    status: str = "pending",
    locked_by: str | None = None,
    lease_expires_at: datetime | None = None,
    available_at: datetime = NOW - timedelta(seconds=1),
    publish_attempt_count: int = 0,
) -> UUID:
    message_id = uuid4()
    async with session_factory() as session:
        async with session.begin():
            session.add(
                OutboxMessage(
                    message_id=message_id,
                    producer_component="assessment_worker",
                    exchange_name="sar.events",
                    message_type="assessment.completed",
                    schema_version=1,
                    assessment_id=ASSESSMENT_ID,
                    workflow_id=WORKFLOW_ID,
                    task_id=TASK_ID,
                    causation_id=None,
                    expected_workflow_version=4,
                    message_attempt=1,
                    actor_id="assessment-worker",
                    payload={"ok": True},
                    status=status,
                    locked_by=locked_by,
                    lease_expires_at=lease_expires_at,
                    publish_attempt_count=publish_attempt_count,
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
        result = await session.execute(
            select(OutboxMessage).where(OutboxMessage.message_id == message_id)
        )
        return result.scalar_one()


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        outbox_batch_size=10,
        outbox_max_publish_attempts=8,
        outbox_poll_interval_seconds=1.0,
        outbox_publish_timeout_seconds=15.0,
    )


def _normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


class _CommitAwareSession:
    def __init__(self, store: "_PublisherStore") -> None:
        self._store = store

    async def commit(self) -> None:
        self._store.claim_committed = True

    async def rollback(self) -> None:
        pass

    async def close(self) -> None:
        pass


class _PublisherStore:
    def __init__(self, record: OutboxMessageRecord) -> None:
        self.record = record
        self.claim_committed = False
        self.published: list[UUID] = []


class _FakePublisherRepository:
    async def claim_publishable(
        self,
        session: _CommitAwareSession,
        *,
        limit: int,
        locked_by: str,
        lease_duration: timedelta,
        now: datetime | None = None,
    ) -> list[OutboxMessageRecord]:
        _ = limit
        reference_time = now or NOW
        return [
            replace(
                session._store.record,
                status="processing",
                locked_by=locked_by,
                lease_expires_at=reference_time + lease_duration,
            )
        ]

    async def mark_published(
        self,
        session: _CommitAwareSession,
        *,
        message_id: UUID,
        locked_by: str,
    ) -> None:
        _ = session, message_id, locked_by

    async def mark_publish_failed(
        self,
        session: _CommitAwareSession,
        *,
        message_id: UUID,
        locked_by: str,
        current_attempt_count: int,
        max_attempts: int,
        error: Exception,
    ) -> None:
        raise AssertionError(
            f"mark_publish_failed should not be called: {message_id} {locked_by} "
            f"{current_attempt_count} {max_attempts} {error}"
        )


class _FakeExchange:
    def __init__(self, store: _PublisherStore) -> None:
        self._store = store

    async def publish(self, message, *, routing_key: str) -> None:
        assert self._store.claim_committed is True
        assert routing_key == message.type
        self._store.published.append(UUID(message.message_id))


class _FakeChannel:
    def __init__(self, store: _PublisherStore) -> None:
        self._store = store

    async def get_exchange(self, exchange_name: str, *, ensure: bool):
        assert exchange_name == "sar.events"
        assert ensure is True
        return _FakeExchange(self._store)

    async def close(self) -> None:
        pass


class _FakeConnection:
    def __init__(self, store: _PublisherStore) -> None:
        self._store = store

    async def channel(self, *, publisher_confirms: bool):
        assert publisher_confirms is True
        return _FakeChannel(self._store)


@pytest.mark.asyncio
async def test_pending_row_becomes_processing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    message_id = await _insert_outbox_row(session_factory)
    repository = WorkerOutboxRepository()

    async with session_factory() as session:
        records = await repository.claim_publishable(
            session,
            limit=1,
            locked_by="publisher-a",
            lease_duration=timedelta(seconds=30),
            now=NOW,
        )
        await session.commit()

    assert [record.message_id for record in records] == [message_id]
    stored = await _get_outbox_row(session_factory, message_id)
    assert stored.status == "processing"


@pytest.mark.asyncio
async def test_claim_sets_locked_by_and_lease_expires_at(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    message_id = await _insert_outbox_row(session_factory)
    repository = WorkerOutboxRepository()

    async with session_factory() as session:
        records = await repository.claim_publishable(
            session,
            limit=1,
            locked_by="publisher-a",
            lease_duration=timedelta(seconds=45),
            now=NOW,
        )
        await session.commit()

    assert len(records) == 1
    assert records[0].locked_by == "publisher-a"
    assert _normalize_datetime(records[0].lease_expires_at) == NOW + timedelta(seconds=45)
    stored = await _get_outbox_row(session_factory, message_id)
    assert stored.locked_by == "publisher-a"
    assert _normalize_datetime(stored.lease_expires_at) == NOW + timedelta(seconds=45)


@pytest.mark.asyncio
async def test_expired_processing_row_can_be_reclaimed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    message_id = await _insert_outbox_row(
        session_factory,
        status="processing",
        locked_by="publisher-a",
        lease_expires_at=NOW - timedelta(seconds=1),
    )
    repository = WorkerOutboxRepository()

    async with session_factory() as session:
        records = await repository.claim_publishable(
            session,
            limit=1,
            locked_by="publisher-b",
            lease_duration=timedelta(seconds=30),
            now=NOW,
        )
        await session.commit()

    assert [record.message_id for record in records] == [message_id]
    stored = await _get_outbox_row(session_factory, message_id)
    assert stored.status == "processing"
    assert stored.locked_by == "publisher-b"
    assert _normalize_datetime(stored.lease_expires_at) == NOW + timedelta(seconds=30)


@pytest.mark.asyncio
async def test_active_lease_cannot_be_reclaimed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    message_id = await _insert_outbox_row(
        session_factory,
        status="processing",
        locked_by="publisher-a",
        lease_expires_at=NOW + timedelta(seconds=1),
    )
    repository = WorkerOutboxRepository()

    async with session_factory() as session:
        records = await repository.claim_publishable(
            session,
            limit=1,
            locked_by="publisher-b",
            lease_duration=timedelta(seconds=30),
            now=NOW,
        )
        await session.commit()

    assert records == []
    stored = await _get_outbox_row(session_factory, message_id)
    assert stored.status == "processing"
    assert stored.locked_by == "publisher-a"
    assert _normalize_datetime(stored.lease_expires_at) == NOW + timedelta(seconds=1)


@pytest.mark.asyncio
async def test_wrong_publisher_owner_cannot_mark_published(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    message_id = await _insert_outbox_row(
        session_factory,
        status="processing",
        locked_by="publisher-b",
        lease_expires_at=NOW + timedelta(seconds=30),
    )
    repository = WorkerOutboxRepository()

    async with session_factory() as session:
        with pytest.raises(LookupError):
            await repository.mark_published(
                session,
                message_id=message_id,
                locked_by="publisher-a",
            )
        await session.rollback()

    stored = await _get_outbox_row(session_factory, message_id)
    assert stored.status == "processing"
    assert stored.locked_by == "publisher-b"


@pytest.mark.asyncio
async def test_wrong_publisher_owner_cannot_mark_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    message_id = await _insert_outbox_row(
        session_factory,
        status="processing",
        locked_by="publisher-b",
        lease_expires_at=NOW + timedelta(seconds=30),
    )
    repository = WorkerOutboxRepository()

    async with session_factory() as session:
        with pytest.raises(LookupError):
            await repository.mark_publish_failed(
                session,
                message_id=message_id,
                locked_by="publisher-a",
                current_attempt_count=0,
                max_attempts=8,
                error=RuntimeError("boom"),
            )
        await session.rollback()

    stored = await _get_outbox_row(session_factory, message_id)
    assert stored.status == "processing"
    assert stored.locked_by == "publisher-b"


@pytest.mark.asyncio
async def test_publish_happens_after_claim_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    record = OutboxMessageRecord(
        message_id=uuid4(),
        producer_component="assessment_worker",
        exchange_name="sar.events",
        message_type="assessment.completed",
        schema_version=1,
        assessment_id=ASSESSMENT_ID,
        workflow_id=WORKFLOW_ID,
        task_id=TASK_ID,
        causation_id=None,
        expected_workflow_version=4,
        message_attempt=1,
        actor_id="assessment-worker",
        payload={"ok": True},
        status="pending",
        locked_by=None,
        lease_expires_at=None,
        publish_attempt_count=0,
        available_at=NOW,
        published_at=None,
        last_error=None,
        created_at=NOW,
    )
    store = _PublisherStore(record)
    monkeypatch.setattr(
        "app.messaging.outbox_publisher.aio_pika",
        SimpleNamespace(
            Message=lambda **kwargs: SimpleNamespace(**kwargs),
            DeliveryMode=SimpleNamespace(PERSISTENT=2),
        ),
    )

    publisher = OutboxPublisher(
        lambda: _CommitAwareSession(store),
        _FakeConnection(store),
        _settings(),
        publisher_id="publisher-a",
    )
    publisher._repository = _FakePublisherRepository()

    published = await publisher._publish_batch()

    assert published == 1
    assert store.claim_committed is True
    assert store.published == [record.message_id]
