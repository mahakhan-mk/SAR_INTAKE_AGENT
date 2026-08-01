from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import DATABASE_SCHEMA_TOKEN, Settings
from app.messaging.consumer import AssessmentCommandConsumer
from app.messaging.envelope import MessageEnvelope, create_message_envelope
from app.models.database import (
    Base,
    OutboxMessage,
    ProcessedMessage,
    QuestionnaireVersion,
    WorkflowTask,
)
from app.worker.handlers import CommandExecutionResult
from app.worker.processor import (
    CommandAlreadyInFlight,
    CommandProcessor,
    NonRetryableCommandFailure,
)


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


def _settings(*, worker_instance_id: str = "host-a:123:worker-a") -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        database_schema="public",
        rabbitmq_url="amqp://guest:guest@localhost/",
        worker_instance_id=worker_instance_id,
        worker_actor_id="assessment-worker",
        consumer_name="assessment-worker",
        command_prefetch_count=1,
        command_retry_limit=3,
        command_lease_seconds=30,
        command_lease_heartbeat_seconds=5.0,
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


def _as_utc(value: datetime | None) -> datetime | None:
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
    task_id: UUID = TASK_ID,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            session.add(
                WorkflowTask(
                    id=task_id,
                    workflow_id=WORKFLOW_ID,
                    task_type=COMMAND_TYPE,
                    idempotency_key=f"idem-{uuid4()}",
                    status=status,
                    expected_workflow_version=WORKFLOW_VERSION,
                    attempt_count=attempt_count,
                    max_attempts=max_attempts,
                    input_payload=dict(PAYLOAD),
                    lease_owner=lease_owner,
                    lease_expires_at=lease_expires_at,
                    error_summary=None,
                    queued_at=NOW,
                    started_at=None,
                    completed_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )


async def _counts(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[int, int, int]:
    async with session_factory() as session:
        outbox_count = await session.scalar(select(func.count()).select_from(OutboxMessage))
        processed_count = await session.scalar(select(func.count()).select_from(ProcessedMessage))
        questionnaire_count = await session.scalar(
            select(func.count()).select_from(QuestionnaireVersion)
        )
        return int(outbox_count or 0), int(processed_count or 0), int(questionnaire_count or 0)


class _Registry:
    def __init__(self, handler) -> None:
        self._handler = handler

    def resolve(self, message_type: str):
        assert message_type == COMMAND_TYPE
        return self._handler


class _FakeMessage:
    def __init__(self, envelope: MessageEnvelope) -> None:
        self.body = envelope.model_dump_json(by_alias=True).encode("utf-8")
        self.routing_key = envelope.message_type
        self.headers: dict[str, object] = {}
        self.content_type = "application/json"
        self.message_id = str(envelope.message_id)
        self.correlation_id = str(envelope.workflow_id)
        self.type = envelope.message_type
        self.timestamp = envelope.occurred_at
        self.acked = 0
        self.rejected: list[bool] = []
        self.nacked: list[bool] = []

    async def ack(self) -> None:
        self.acked += 1

    async def reject(self, *, requeue: bool) -> None:
        self.rejected.append(requeue)

    async def nack(self, *, requeue: bool) -> None:
        self.nacked.append(requeue)


class _RecordingRetryExchange:
    def __init__(self) -> None:
        self.published = 0

    async def publish(self, *args, **kwargs) -> None:
        self.published += 1


class _FailingOutbox:
    async def add_result(self, *args, **kwargs):
        raise SQLAlchemyError("simulated outbox failure")


def _envelope(
    *,
    message_id: UUID | None = None,
    attempt: int = 1,
) -> MessageEnvelope:
    return create_message_envelope(
        message_id=message_id or uuid4(),
        message_type=COMMAND_TYPE,
        assessment_id=ASSESSMENT_ID,
        workflow_id=WORKFLOW_ID,
        task_id=TASK_ID,
        expected_workflow_version=WORKFLOW_VERSION,
        attempt=attempt,
        actor_id="orchestrator",
        payload=PAYLOAD,
        occurred_at=NOW,
    )


def _processor(
    session_factory: async_sessionmaker[AsyncSession],
    handler,
    *,
    worker_instance_id: str = "host-a:123:worker-a",
) -> CommandProcessor:
    return CommandProcessor(
        session_factory,
        _settings(worker_instance_id=worker_instance_id),
        _Registry(handler),
    )


@pytest.mark.asyncio
async def test_exact_duplicate_message_id_acks_without_rerun(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert_task(session_factory)
    calls = 0

    async def handler(session: AsyncSession, envelope: MessageEnvelope) -> CommandExecutionResult:
        nonlocal calls
        _ = envelope
        calls += 1
        session.add(
            QuestionnaireVersion(
                id=uuid4(),
                questionnaire_type="risk",
                version=f"v-{calls}",
                status="draft",
            )
        )
        return CommandExecutionResult("assessment.risk.completed", {})

    processor = _processor(session_factory, handler)
    consumer = AssessmentCommandConsumer(SimpleNamespace(), processor, _settings())
    envelope = _envelope(message_id=uuid4())

    first = _FakeMessage(envelope)
    second = _FakeMessage(envelope)

    await consumer._consume(first)
    await consumer._consume(second)

    outbox_count, processed_count, questionnaire_count = await _counts(session_factory)
    assert calls == 1
    assert first.acked == 1
    assert second.acked == 1
    assert second.rejected == []
    assert outbox_count == 1
    assert processed_count == 1
    assert questionnaire_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_status", ["succeeded", "failed"])
async def test_new_message_id_for_terminal_task_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
    terminal_status: str,
) -> None:
    await _insert_task(session_factory, status=terminal_status, attempt_count=1)
    calls = 0

    async def handler(session: AsyncSession, envelope: MessageEnvelope) -> CommandExecutionResult:
        nonlocal calls
        _ = session, envelope
        calls += 1
        return CommandExecutionResult("assessment.risk.completed", {})

    processor = _processor(session_factory, handler)
    consumer = AssessmentCommandConsumer(SimpleNamespace(), processor, _settings())
    message = _FakeMessage(_envelope(message_id=uuid4(), attempt=2))

    await consumer._consume(message)

    outbox_count, processed_count, questionnaire_count = await _counts(session_factory)
    assert calls == 0
    assert message.acked == 0
    assert message.rejected == [False]
    assert message.nacked == []
    assert outbox_count == 0
    assert processed_count == 0
    assert questionnaire_count == 0


@pytest.mark.asyncio
async def test_concurrent_duplicate_delivery_creates_one_result(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert_task(session_factory)
    calls = 0
    release = asyncio.Event()
    started = asyncio.Event()

    async def handler(session: AsyncSession, envelope: MessageEnvelope) -> CommandExecutionResult:
        nonlocal calls
        _ = envelope
        calls += 1
        session.add(
            QuestionnaireVersion(
                id=uuid4(),
                questionnaire_type="risk",
                version=f"v-{calls}",
                status="draft",
            )
        )
        started.set()
        await release.wait()
        return CommandExecutionResult("assessment.risk.completed", {})

    processor = _processor(session_factory, handler)
    envelope = _envelope(message_id=uuid4())

    first_task = asyncio.create_task(processor.process(envelope))
    await started.wait()
    second_task = asyncio.create_task(processor.process(envelope))
    await asyncio.sleep(0.05)
    release.set()

    first_result = await first_task
    second_exception: Exception | None = None
    try:
        await second_task
    except Exception as exc:  # noqa: BLE001
        second_exception = exc

    outbox_count, processed_count, questionnaire_count = await _counts(session_factory)
    assert first_result is True
    assert isinstance(second_exception, CommandAlreadyInFlight)
    assert calls == 1
    assert outbox_count == 1
    assert processed_count == 1
    assert questionnaire_count == 1


@pytest.mark.asyncio
async def test_active_lease_duplicate_delivery_is_acked_without_retry_or_task_mutation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    lease_expires_at = datetime.now(UTC) + timedelta(seconds=30)
    await _insert_task(
        session_factory,
        status="running",
        attempt_count=1,
        lease_owner="host-b:456:worker-b",
        lease_expires_at=lease_expires_at,
    )
    calls = 0

    async def handler(session: AsyncSession, envelope: MessageEnvelope) -> CommandExecutionResult:
        nonlocal calls
        _ = session, envelope
        calls += 1
        return CommandExecutionResult("assessment.risk.completed", {})

    retry_exchange = _RecordingRetryExchange()
    processor = _processor(session_factory, handler)
    consumer = AssessmentCommandConsumer(SimpleNamespace(), processor, _settings())
    consumer._retry_exchange = retry_exchange
    message = _FakeMessage(_envelope(message_id=uuid4(), attempt=1))

    await consumer._consume(message)

    async with session_factory() as session:
        task = (
            await session.execute(select(WorkflowTask).where(WorkflowTask.id == TASK_ID))
        ).scalar_one()
    outbox_count, processed_count, questionnaire_count = await _counts(session_factory)
    assert calls == 0
    assert message.acked == 1
    assert message.rejected == []
    assert message.nacked == []
    assert retry_exchange.published == 0
    assert task.status == "running"
    assert task.attempt_count == 1
    assert task.lease_owner == "host-b:456:worker-b"
    assert _as_utc(task.lease_expires_at) == lease_expires_at
    assert outbox_count == 0
    assert processed_count == 0
    assert questionnaire_count == 0


@pytest.mark.asyncio
async def test_post_claim_infrastructure_failure_acks_and_leaves_running_for_reconciliation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert_task(session_factory)

    async def handler(session: AsyncSession, envelope: MessageEnvelope) -> CommandExecutionResult:
        _ = envelope
        session.add(
            QuestionnaireVersion(
                id=uuid4(),
                questionnaire_type="risk",
                version="rolled-back",
                status="draft",
            )
        )
        return CommandExecutionResult("assessment.risk.completed", {})

    retry_exchange = _RecordingRetryExchange()
    processor = _processor(session_factory, handler)
    processor._outbox = _FailingOutbox()
    consumer = AssessmentCommandConsumer(SimpleNamespace(), processor, _settings())
    consumer._retry_exchange = retry_exchange
    message = _FakeMessage(_envelope(message_id=uuid4(), attempt=1))

    await consumer._consume(message)

    async with session_factory() as session:
        task = (
            await session.execute(select(WorkflowTask).where(WorkflowTask.id == TASK_ID))
        ).scalar_one()
    outbox_count, processed_count, questionnaire_count = await _counts(session_factory)
    assert message.acked == 1
    assert message.rejected == []
    assert message.nacked == []
    assert retry_exchange.published == 0
    assert task.status == "running"
    assert task.attempt_count == 1
    assert task.lease_owner == _settings().worker_instance_id
    assert task.lease_expires_at is not None
    assert outbox_count == 0
    assert processed_count == 0
    assert questionnaire_count == 0


@pytest.mark.asyncio
async def test_duplicate_command_creates_one_outbox_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert_task(session_factory)
    calls = 0
    message_id = uuid4()

    async def handler(session: AsyncSession, envelope: MessageEnvelope) -> CommandExecutionResult:
        nonlocal calls
        _ = envelope
        calls += 1
        session.add(
            QuestionnaireVersion(
                id=uuid4(),
                questionnaire_type="risk",
                version=f"v-{calls}",
                status="draft",
            )
        )
        return CommandExecutionResult("assessment.risk.completed", {})

    processor = _processor(session_factory, handler)

    assert await processor.process(_envelope(message_id=message_id)) is True
    assert await processor.process(_envelope(message_id=message_id)) is False

    outbox_count, processed_count, questionnaire_count = await _counts(session_factory)
    assert calls == 1
    assert outbox_count == 1
    assert processed_count == 1
    assert questionnaire_count == 1


@pytest.mark.asyncio
async def test_retry_attempt_with_correct_new_message_id_is_accepted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert_task(session_factory, status="retry", attempt_count=1)
    calls = 0

    async def handler(session: AsyncSession, envelope: MessageEnvelope) -> CommandExecutionResult:
        nonlocal calls
        calls += 1
        session.add(
            QuestionnaireVersion(
                id=uuid4(),
                questionnaire_type="risk",
                version=f"v-{calls}",
                status="draft",
            )
        )
        return CommandExecutionResult("assessment.risk.completed", {})

    processor = _processor(session_factory, handler)

    assert await processor.process(_envelope(message_id=uuid4(), attempt=2)) is True

    outbox_count, processed_count, questionnaire_count = await _counts(session_factory)
    async with session_factory() as session:
        task = (
            await session.execute(select(WorkflowTask).where(WorkflowTask.id == TASK_ID))
        ).scalar_one()
    assert calls == 1
    assert task.status == "succeeded"
    assert task.attempt_count == 2
    assert outbox_count == 1
    assert processed_count == 1
    assert questionnaire_count == 1


@pytest.mark.asyncio
async def test_stale_retry_attempt_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert_task(session_factory, status="retry", attempt_count=1)
    calls = 0

    async def handler(session: AsyncSession, envelope: MessageEnvelope) -> CommandExecutionResult:
        nonlocal calls
        _ = session, envelope
        calls += 1
        return CommandExecutionResult("assessment.risk.completed", {})

    processor = _processor(session_factory, handler)

    with pytest.raises(NonRetryableCommandFailure, match="stale attempt 1; expected attempt is 2"):
        await processor.process(_envelope(message_id=uuid4(), attempt=1))

    outbox_count, processed_count, questionnaire_count = await _counts(session_factory)
    assert calls == 0
    assert outbox_count == 0
    assert processed_count == 0
    assert questionnaire_count == 0
