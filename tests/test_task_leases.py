from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import DATABASE_SCHEMA_TOKEN, Settings
from app.messaging.envelope import create_message_envelope
from app.models.database import Base, OutboxMessage, ProcessedMessage, QuestionnaireVersion, WorkflowTask
from app.repositories.worker_messaging_repository import (
    TaskLeaseUnavailable,
    WorkflowTaskExecutionRepository,
)
from app.worker.processor import CommandProcessor, InfrastructureFailure


NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
WORKFLOW_ID = UUID("11111111-1111-4111-8111-111111111111")
TASK_ID = UUID("22222222-2222-4222-8222-222222222222")
ASSESSMENT_ID = UUID("33333333-3333-4333-8333-333333333333")
COMMAND_TYPE = "assessment.risk.calculate"
WORKFLOW_VERSION = 4
PAYLOAD: dict[str, object] = {}


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


def _settings(
    *,
    worker_instance_id: str = "host-a:123:worker-a",
    command_lease_seconds: int = 1,
    command_lease_heartbeat_seconds: float = 0.05,
) -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        database_schema="public",
        rabbitmq_url="amqp://guest:guest@localhost/",
        worker_instance_id=worker_instance_id,
        worker_actor_id="assessment-worker",
        consumer_name="assessment-worker",
        command_prefetch_count=1,
        command_retry_limit=3,
        command_lease_seconds=command_lease_seconds,
        command_lease_heartbeat_seconds=command_lease_heartbeat_seconds,
        rabbitmq_retry_delay_milliseconds=30000,
        outbox_batch_size=25,
        outbox_max_publish_attempts=10,
        outbox_poll_interval_seconds=1.0,
        outbox_publish_timeout_seconds=15.0,
        shutdown_grace_seconds=30.0,
        azure_blob_connection_string=None,
        azure_blob_container_name=None,
        azure_openai_endpoint=None,
        azure_openai_api_key=None,
        azure_openai_deployment=None,
        azure_openai_timeout_seconds=30.0,
        azure_openai_api_version=None,
    )


def _normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


async def _insert_task(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    status: str = "pending",
    attempt_count: int = 0,
    max_attempts: int = 3,
    lease_owner: str | None = None,
    lease_expires_at: datetime | None = None,
    started_at: datetime | None = None,
    updated_at: datetime = NOW,
    input_payload: dict[str, object] | None = None,
    task_id: UUID = TASK_ID,
    workflow_id: UUID = WORKFLOW_ID,
    task_type: str = COMMAND_TYPE,
    expected_workflow_version: int = WORKFLOW_VERSION,
) -> UUID:
    async with session_factory() as session:
        async with session.begin():
            session.add(
                WorkflowTask(
                    id=task_id,
                    workflow_id=workflow_id,
                    task_type=task_type,
                    idempotency_key=f"idem-{uuid4()}",
                    status=status,
                    expected_workflow_version=expected_workflow_version,
                    attempt_count=attempt_count,
                    max_attempts=max_attempts,
                    input_payload=input_payload or dict(PAYLOAD),
                    lease_owner=lease_owner,
                    lease_expires_at=lease_expires_at,
                    error_summary=None,
                    queued_at=NOW,
                    started_at=started_at,
                    completed_at=None,
                    created_at=NOW,
                    updated_at=updated_at,
                )
            )
    return task_id


async def _get_task(
    session_factory: async_sessionmaker[AsyncSession],
    task_id: UUID = TASK_ID,
) -> WorkflowTask:
    async with session_factory() as session:
        result = await session.execute(
            select(WorkflowTask).where(WorkflowTask.id == task_id)
        )
        return result.scalar_one()


class _Registry:
    def __init__(self, handler) -> None:
        self._handler = handler

    def resolve(self, message_type: str):
        assert message_type == COMMAND_TYPE
        return self._handler


@pytest.mark.asyncio
async def test_successful_claim(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert_task(session_factory)
    repository = WorkflowTaskExecutionRepository()

    async with session_factory() as session:
        claimed = await repository.claim(
            session,
            task_id=TASK_ID,
            workflow_id=WORKFLOW_ID,
            task_type=COMMAND_TYPE,
            expected_workflow_version=WORKFLOW_VERSION,
            attempt=1,
            input_payload=dict(PAYLOAD),
            lease_owner="host-a:123:worker-a",
            lease_seconds=30,
        )
        await session.commit()

    stored = await _get_task(session_factory)
    assert claimed.status == "running"
    assert claimed.attempt_count == 1
    assert stored.status == "running"
    assert stored.attempt_count == 1
    assert stored.lease_owner == "host-a:123:worker-a"
    assert _normalize_datetime(stored.lease_expires_at) is not None
    assert _normalize_datetime(stored.started_at) is not None


@pytest.mark.asyncio
async def test_stale_attempt_rejection(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert_task(session_factory, attempt_count=2)
    repository = WorkflowTaskExecutionRepository()

    async with session_factory() as session:
        with pytest.raises(ValueError, match="stale attempt 2; expected attempt is 3"):
            await repository.claim(
                session,
                task_id=TASK_ID,
                workflow_id=WORKFLOW_ID,
                task_type=COMMAND_TYPE,
                expected_workflow_version=WORKFLOW_VERSION,
                attempt=2,
                input_payload=dict(PAYLOAD),
                lease_owner="host-a:123:worker-a",
                lease_seconds=30,
            )


@pytest.mark.asyncio
async def test_future_attempt_rejection(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert_task(session_factory, attempt_count=2, max_attempts=10)
    repository = WorkflowTaskExecutionRepository()

    async with session_factory() as session:
        with pytest.raises(ValueError, match="future attempt 4; expected attempt is 3"):
            await repository.claim(
                session,
                task_id=TASK_ID,
                workflow_id=WORKFLOW_ID,
                task_type=COMMAND_TYPE,
                expected_workflow_version=WORKFLOW_VERSION,
                attempt=4,
                input_payload=dict(PAYLOAD),
                lease_owner="host-a:123:worker-a",
                lease_seconds=30,
            )


@pytest.mark.asyncio
async def test_terminal_task_rejection(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert_task(session_factory, status="succeeded", attempt_count=1, started_at=NOW)
    repository = WorkflowTaskExecutionRepository()

    async with session_factory() as session:
        with pytest.raises(ValueError, match="cannot be claimed from terminal status succeeded"):
            await repository.claim(
                session,
                task_id=TASK_ID,
                workflow_id=WORKFLOW_ID,
                task_type=COMMAND_TYPE,
                expected_workflow_version=WORKFLOW_VERSION,
                attempt=2,
                input_payload=dict(PAYLOAD),
                lease_owner="host-a:123:worker-a",
                lease_seconds=30,
            )


@pytest.mark.asyncio
async def test_active_foreign_lease_rejection(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert_task(
        session_factory,
        status="running",
        attempt_count=1,
        lease_owner="host-b:456:worker-b",
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=30),
        started_at=NOW,
    )
    repository = WorkflowTaskExecutionRepository()

    async with session_factory() as session:
        with pytest.raises(TaskLeaseUnavailable, match="is leased by host-b:456:worker-b"):
            await repository.claim(
                session,
                task_id=TASK_ID,
                workflow_id=WORKFLOW_ID,
                task_type=COMMAND_TYPE,
                expected_workflow_version=WORKFLOW_VERSION,
                attempt=1,
                input_payload=dict(PAYLOAD),
                lease_owner="host-a:123:worker-a",
                lease_seconds=30,
            )


@pytest.mark.asyncio
async def test_expired_lease_claim(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert_task(
        session_factory,
        status="running",
        attempt_count=1,
        lease_owner="host-b:456:worker-b",
        lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        started_at=NOW,
    )
    repository = WorkflowTaskExecutionRepository()

    async with session_factory() as session:
        claimed = await repository.claim(
            session,
            task_id=TASK_ID,
            workflow_id=WORKFLOW_ID,
            task_type=COMMAND_TYPE,
            expected_workflow_version=WORKFLOW_VERSION,
            attempt=1,
            input_payload=dict(PAYLOAD),
            lease_owner="host-a:123:worker-a",
            lease_seconds=30,
        )
        await session.commit()

    stored = await _get_task(session_factory)
    assert claimed.attempt_count == 1
    assert stored.status == "running"
    assert stored.attempt_count == 1
    assert stored.lease_owner == "host-a:123:worker-a"


@pytest.mark.asyncio
async def test_heartbeat_renewal(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert_task(
        session_factory,
        status="running",
        attempt_count=1,
        lease_owner="host-a:123:worker-a",
        lease_expires_at=NOW + timedelta(seconds=5),
        started_at=NOW,
    )
    repository = WorkflowTaskExecutionRepository()
    renew_started_at = datetime.now(UTC)

    async with session_factory() as session:
        renewed_until = await repository.renew_lease(
            session,
            task_id=TASK_ID,
            attempt=1,
            lease_owner="host-a:123:worker-a",
            lease_seconds=30,
        )
        await session.commit()

    stored = await _get_task(session_factory)
    assert _normalize_datetime(stored.lease_expires_at) == _normalize_datetime(renewed_until)
    assert _normalize_datetime(stored.lease_expires_at) > renew_started_at


@pytest.mark.asyncio
async def test_heartbeat_owner_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert_task(
        session_factory,
        status="running",
        attempt_count=1,
        lease_owner="host-b:456:worker-b",
        lease_expires_at=NOW + timedelta(seconds=30),
        started_at=NOW,
    )
    repository = WorkflowTaskExecutionRepository()

    async with session_factory() as session:
        with pytest.raises(TaskLeaseUnavailable, match="lease could not be renewed"):
            await repository.renew_lease(
                session,
                task_id=TASK_ID,
                attempt=1,
                lease_owner="host-a:123:worker-a",
                lease_seconds=30,
            )


@pytest.mark.asyncio
async def test_heartbeat_attempt_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert_task(
        session_factory,
        status="running",
        attempt_count=2,
        lease_owner="host-a:123:worker-a",
        lease_expires_at=NOW + timedelta(seconds=30),
        started_at=NOW,
    )
    repository = WorkflowTaskExecutionRepository()

    async with session_factory() as session:
        with pytest.raises(TaskLeaseUnavailable, match="lease could not be renewed"):
            await repository.renew_lease(
                session,
                task_id=TASK_ID,
                attempt=1,
                lease_owner="host-a:123:worker-a",
                lease_seconds=30,
            )


@pytest.mark.asyncio
async def test_lease_loss_prevents_final_commit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert_task(session_factory)
    settings = _settings()
    handler_started = asyncio.Event()
    handler_cancelled = asyncio.Event()

    async def handler(session: AsyncSession, envelope) -> SimpleNamespace:
        _ = envelope
        session.add(
            QuestionnaireVersion(
                id=uuid4(),
                questionnaire_type="risk",
                version=f"v-{uuid4()}",
                status="draft",
            )
        )
        handler_started.set()
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            handler_cancelled.set()
            raise
        return SimpleNamespace(
            event_type="assessment.risk.completed",
            payload={},
            committed=lambda: None,
            rolled_back=lambda: None,
        )

    processor = CommandProcessor(
        session_factory,
        settings,
        _Registry(handler),
    )
    envelope = create_message_envelope(
        message_type=COMMAND_TYPE,
        assessment_id=ASSESSMENT_ID,
        workflow_id=WORKFLOW_ID,
        task_id=TASK_ID,
        expected_workflow_version=WORKFLOW_VERSION,
        attempt=1,
        actor_id="orchestrator",
        payload=PAYLOAD,
        occurred_at=NOW,
    )

    async def steal_lease() -> None:
        await handler_started.wait()
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(WorkflowTask)
                    .where(WorkflowTask.id == TASK_ID)
                    .values(
                        lease_owner="host-b:456:worker-b",
                        lease_expires_at=datetime.now(UTC) + timedelta(seconds=30),
                    )
                )

    stealer = asyncio.create_task(steal_lease())
    with pytest.raises(InfrastructureFailure, match="lease lost"):
        await processor.process(envelope)
    await stealer

    task = await _get_task(session_factory)
    async with session_factory() as session:
        outbox_count = await session.scalar(select(func.count()).select_from(OutboxMessage))
        processed_count = await session.scalar(select(func.count()).select_from(ProcessedMessage))
        questionnaire_count = await session.scalar(
            select(func.count()).select_from(QuestionnaireVersion)
        )

    assert handler_cancelled.is_set()
    assert task.status == "running"
    assert task.attempt_count == 1
    assert task.lease_owner == "host-b:456:worker-b"
    assert outbox_count == 0
    assert processed_count == 0
    assert questionnaire_count == 0
