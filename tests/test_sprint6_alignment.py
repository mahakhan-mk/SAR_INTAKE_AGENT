from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.messaging.consumer as consumer_module
from app.config import DATABASE_SCHEMA_TOKEN, Settings
from app.domain.errors import BusinessPreconditionError
from app.messaging.consumer import AssessmentCommandConsumer, _RETRY_HEADER
from app.messaging.contracts import (
    ASSESSMENT_COMMAND_TYPES,
    ASSESSMENT_DOCUMENT_COMMANDS,
    ASSESSMENT_EVENT_PAYLOAD_FIELDS,
    ASSESSMENT_WORKER_EVENT_TYPES,
    ASSESSMENT_WORKFLOW_COMMANDS,
    COMMAND_FAILURE_EVENT,
    SAR_COMMANDS_EXCHANGE_NAME,
    SAR_DLX_EXCHANGE_NAME,
    SAR_EVENTS_EXCHANGE_NAME,
    SAR_RETRY_EXCHANGE_NAME,
)
from app.messaging.envelope import MessageEnvelope, create_message_envelope
from app.messaging.topology import ASSESSMENT_DOCUMENTS_QUEUE_NAME, ASSESSMENT_WORKFLOW_QUEUE_NAME
from app.models.database import Base, OutboxMessage, ProcessedMessage, QuestionnaireVersion, WorkflowTask
from app.repositories.worker_messaging_repository import ASSESSMENT_WORKER_PRODUCER
from app.services.initial_sar_report_generation_service import InitialSarReportGenerationService
from app.services.initial_sar_report_renderer import RenderedInitialSarReport
from app.services.initial_sar_report_storage import StoredInitialSarReport
from app.worker.handlers import CommandExecutionResult
from app.worker.processor import CommandProcessor, InfrastructureFailure, NonRetryableCommandFailure


NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
WORKFLOW_ID = UUID("11111111-1111-4111-8111-111111111111")
TASK_ID = UUID("22222222-2222-4222-8222-222222222222")
ASSESSMENT_ID = UUID("33333333-3333-4333-8333-333333333333")
WORKFLOW_VERSION = 4


SUCCESS_CASES = (
    ("assessment.risk.calculate", {}, "assessment.risk.completed", {}),
    ("assessment.risk.recalculate", {"responseVersion": 7}, "assessment.risk.completed", {}),
    ("assessment.checklist.generate", {}, "assessment.checklist.generated", {}),
    (
        "assessment.checklist.finalize",
        {
            "checklistRunId": "44444444-4444-4444-8444-444444444444",
            "reviewId": "55555555-5555-4555-8555-555555555555",
        },
        "assessment.checklist.completed",
        {"regenerate": True},
    ),
    ("assessment.report.generate", {}, "assessment.report.completed", {}),
    ("assessment.report.regenerate", {}, "assessment.report.completed", {}),
)


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


def _settings(*, retry_limit: int = 3) -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        database_schema="public",
        rabbitmq_url="amqp://guest:guest@localhost/",
        worker_instance_id="host-a:123:worker-a",
        worker_actor_id="assessment-worker",
        consumer_name="assessment-worker",
        command_prefetch_count=1,
        command_retry_limit=retry_limit,
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


class _Registry:
    def __init__(self, command_type: str, handler) -> None:
        self.command_type = command_type
        self.handler = handler

    def resolve(self, message_type: str):
        assert message_type == self.command_type
        return self.handler


class _ProcessorStub:
    def __init__(self, result=None, exc: Exception | None = None) -> None:
        self.result = result
        self.exc = exc
        self.calls: list[MessageEnvelope] = []

    async def process(self, envelope: MessageEnvelope):
        self.calls.append(envelope)
        if self.exc is not None:
            raise self.exc
        return self.result


class _FakeIncomingMessage:
    def __init__(
        self,
        envelope: MessageEnvelope,
        *,
        routing_key: str | None = None,
        headers: dict[str, object] | None = None,
        channel=None,
    ) -> None:
        self.body = envelope.model_dump_json(by_alias=True).encode("utf-8")
        self.routing_key = routing_key or envelope.message_type
        self.headers = headers or {}
        self.content_type = "application/json"
        self.message_id = str(envelope.message_id)
        self.correlation_id = str(envelope.workflow_id)
        self.type = envelope.message_type
        self.timestamp = envelope.occurred_at
        self.channel = channel
        self.acked = 0
        self.rejected: list[bool] = []
        self.nacked: list[bool] = []

    async def ack(self) -> None:
        self.acked += 1

    async def reject(self, *, requeue: bool) -> None:
        self.rejected.append(requeue)

    async def nack(self, *, requeue: bool) -> None:
        self.nacked.append(requeue)


@dataclass
class _FakePublishedMessage:
    body: bytes
    content_type: str
    delivery_mode: object
    message_id: str
    correlation_id: str
    type: str
    timestamp: datetime
    headers: dict[str, object]


class _FakeRetryExchange:
    def __init__(self) -> None:
        self.published: list[tuple[_FakePublishedMessage, str]] = []

    async def publish(self, message: _FakePublishedMessage, *, routing_key: str) -> None:
        self.published.append((message, routing_key))


class _FakeChannel:
    def __init__(self) -> None:
        self.exchange = _FakeRetryExchange()
        self.requested_exchange: str | None = None

    async def get_exchange(self, name: str, *, ensure: bool):
        self.requested_exchange = name
        assert ensure is True
        return self.exchange


def _envelope(command_type: str, payload: dict[str, object] | None = None) -> MessageEnvelope:
    return create_message_envelope(
        message_type=command_type,
        assessment_id=ASSESSMENT_ID,
        workflow_id=WORKFLOW_ID,
        task_id=TASK_ID,
        expected_workflow_version=WORKFLOW_VERSION,
        attempt=1,
        actor_id="orchestrator",
        payload=payload or {},
        occurred_at=NOW,
    )


async def _insert_task(
    session_factory: async_sessionmaker[AsyncSession],
    command_type: str,
    payload: dict[str, object],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            session.add(
                WorkflowTask(
                    id=TASK_ID,
                    workflow_id=WORKFLOW_ID,
                    task_type=command_type,
                    idempotency_key=f"idem-{uuid4()}",
                    status="pending",
                    expected_workflow_version=WORKFLOW_VERSION,
                    attempt_count=0,
                    max_attempts=3,
                    input_payload=dict(payload),
                    lease_owner=None,
                    lease_expires_at=None,
                    error_summary=None,
                    queued_at=NOW,
                    started_at=None,
                    completed_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )


async def _table_count(session_factory: async_sessionmaker[AsyncSession], model) -> int:
    async with session_factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


def _processor(session_factory, command_type: str, handler) -> CommandProcessor:
    return CommandProcessor(session_factory, _settings(), _Registry(command_type, handler))


@pytest.mark.asyncio
@pytest.mark.parametrize(("command_type", "payload", "event_type", "event_payload"), SUCCESS_CASES)
async def test_processor_success_for_each_command_emits_exact_outbox_envelope(
    session_factory: async_sessionmaker[AsyncSession],
    command_type: str,
    payload: dict[str, object],
    event_type: str,
    event_payload: dict[str, object],
) -> None:
    await _insert_task(session_factory, command_type, payload)
    envelope = _envelope(command_type, payload)

    async def handler(session: AsyncSession, received: MessageEnvelope) -> CommandExecutionResult:
        assert received == envelope
        session.add(
            QuestionnaireVersion(
                id=uuid4(),
                questionnaire_type=f"domain-{command_type}",
                version=str(uuid4()),
                status="draft",
            )
        )
        return CommandExecutionResult(event_type, event_payload)

    assert await _processor(session_factory, command_type, handler).process(envelope) is True

    async with session_factory() as session:
        task = (await session.execute(select(WorkflowTask))).scalar_one()
        outbox = (await session.execute(select(OutboxMessage))).scalar_one()
        processed = (await session.execute(select(ProcessedMessage))).scalar_one()

    assert task.status == "succeeded"
    assert task.attempt_count == 1
    assert task.lease_owner is None
    assert task.lease_expires_at is None
    assert outbox.producer_component == ASSESSMENT_WORKER_PRODUCER
    assert outbox.exchange_name == SAR_EVENTS_EXCHANGE_NAME
    assert outbox.message_type == event_type
    assert set(outbox.payload) == set(ASSESSMENT_EVENT_PAYLOAD_FIELDS[event_type])
    assert outbox.payload == event_payload
    assert outbox.assessment_id == ASSESSMENT_ID
    assert outbox.workflow_id == WORKFLOW_ID
    assert outbox.task_id == TASK_ID
    assert outbox.causation_id == envelope.message_id
    assert outbox.expected_workflow_version == WORKFLOW_VERSION
    assert outbox.message_attempt == envelope.attempt
    assert outbox.actor_id == _settings().worker_actor_id
    assert outbox.status == "pending"
    assert processed.consumer_name == _settings().consumer_name
    assert processed.message_id == envelope.message_id


@pytest.mark.asyncio
async def test_processor_can_emit_checklist_incomplete_without_failure_payload(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    command_type = "assessment.checklist.finalize"
    payload = {
        "checklistRunId": "44444444-4444-4444-8444-444444444444",
        "reviewId": "55555555-5555-4555-8555-555555555555",
    }
    await _insert_task(session_factory, command_type, payload)

    async def handler(session: AsyncSession, envelope: MessageEnvelope) -> CommandExecutionResult:
        return CommandExecutionResult("assessment.checklist.incomplete", {})

    assert await _processor(session_factory, command_type, handler).process(_envelope(command_type, payload)) is True

    async with session_factory() as session:
        outbox = (await session.execute(select(OutboxMessage))).scalar_one()
    assert outbox.message_type == "assessment.checklist.incomplete"
    assert outbox.payload == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command_type", "payload"),
    [
        ("assessment.risk.calculate", {}),
        ("assessment.checklist.generate", {}),
        ("assessment.report.generate", {}),
    ],
)
async def test_processor_failure_events_for_risk_checklist_and_report(
    session_factory: async_sessionmaker[AsyncSession],
    command_type: str,
    payload: dict[str, object],
) -> None:
    await _insert_task(session_factory, command_type, payload)

    async def handler(session: AsyncSession, envelope: MessageEnvelope) -> CommandExecutionResult:
        raise BusinessPreconditionError("Required input was not available.")

    assert await _processor(session_factory, command_type, handler).process(_envelope(command_type, payload)) is True

    async with session_factory() as session:
        task = (await session.execute(select(WorkflowTask))).scalar_one()
        outbox = (await session.execute(select(OutboxMessage))).scalar_one()
        processed = (await session.execute(select(ProcessedMessage))).scalar_one()
    assert task.status == "running"
    assert outbox.message_type == COMMAND_FAILURE_EVENT[command_type]
    assert set(outbox.payload) == {"retryable", "errorSummary"}
    assert outbox.payload["retryable"] is False
    assert outbox.causation_id == processed.message_id


class _FailingTasks:
    def __init__(self, delegate) -> None:
        self.delegate = delegate

    async def claim(self, *args, **kwargs):
        return await self.delegate.claim(*args, **kwargs)

    async def renew_lease(self, *args, **kwargs):
        return await self.delegate.renew_lease(*args, **kwargs)

    async def mark_succeeded(self, *args, **kwargs):
        raise SQLAlchemyError("simulated task update failure")


class _FailingOutbox:
    async def add_result(self, *args, **kwargs):
        raise SQLAlchemyError("simulated outbox insertion failure")


class _FailingProcessed:
    def __init__(self, delegate) -> None:
        self.delegate = delegate

    async def is_processed(self, *args, **kwargs):
        return await self.delegate.is_processed(*args, **kwargs)

    async def mark_processed(self, *args, **kwargs):
        raise SQLAlchemyError("simulated processed_messages insertion failure")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_point", ["task_update", "outbox_insert", "processed_insert"])
async def test_success_transaction_rolls_back_when_atomic_boundary_write_fails(
    session_factory: async_sessionmaker[AsyncSession],
    failure_point: str,
) -> None:
    command_type = "assessment.risk.calculate"
    await _insert_task(session_factory, command_type, {})

    async def handler(session: AsyncSession, envelope: MessageEnvelope) -> CommandExecutionResult:
        session.add(
            QuestionnaireVersion(
                id=uuid4(),
                questionnaire_type="domain-result",
                version=str(uuid4()),
                status="draft",
            )
        )
        return CommandExecutionResult("assessment.risk.completed", {})

    processor = _processor(session_factory, command_type, handler)
    if failure_point == "task_update":
        processor._tasks = _FailingTasks(processor._tasks)
    elif failure_point == "outbox_insert":
        processor._outbox = _FailingOutbox()
    else:
        processor._processed = _FailingProcessed(processor._processed)

    with pytest.raises(InfrastructureFailure):
        await processor.process(_envelope(command_type))

    async with session_factory() as session:
        task = (await session.execute(select(WorkflowTask))).scalar_one()
    assert task.status == "running"
    assert task.attempt_count == 1
    assert await _table_count(session_factory, QuestionnaireVersion) == 0
    assert await _table_count(session_factory, OutboxMessage) == 0
    assert await _table_count(session_factory, ProcessedMessage) == 0


@pytest.mark.asyncio
async def test_consumer_acks_only_after_processor_commit_callback(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    command_type = "assessment.risk.calculate"
    await _insert_task(session_factory, command_type, {})
    message = _FakeIncomingMessage(_envelope(command_type))
    committed_callback_seen = False

    async def handler(session: AsyncSession, envelope: MessageEnvelope) -> CommandExecutionResult:
        session.add(
            QuestionnaireVersion(
                id=uuid4(),
                questionnaire_type="ack-order",
                version=str(uuid4()),
                status="draft",
            )
        )

        def committed() -> None:
            nonlocal committed_callback_seen
            committed_callback_seen = True
            assert message.acked == 0

        return CommandExecutionResult("assessment.risk.completed", {}, on_commit=committed)

    consumer = AssessmentCommandConsumer(
        SimpleNamespace(),
        _processor(session_factory, command_type, handler),
        _settings(),
    )

    await consumer._consume(message)

    assert committed_callback_seen is True
    assert message.acked == 1
    assert await _table_count(session_factory, OutboxMessage) == 1
    assert await _table_count(session_factory, ProcessedMessage) == 1


@pytest.mark.asyncio
async def test_consumer_permanent_failure_rejects_without_requeue() -> None:
    envelope = _envelope("assessment.risk.calculate")
    message = _FakeIncomingMessage(envelope)
    consumer = AssessmentCommandConsumer(
        SimpleNamespace(),
        _ProcessorStub(exc=NonRetryableCommandFailure("terminal task")),
        _settings(),
    )

    await consumer._consume(message)

    assert message.acked == 0
    assert message.rejected == [False]
    assert message.nacked == []


@pytest.mark.asyncio
async def test_consumer_transient_failure_publishes_to_retry_exchange(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        consumer_module,
        "aio_pika",
        SimpleNamespace(
            Message=_FakePublishedMessage,
            DeliveryMode=SimpleNamespace(PERSISTENT="persistent"),
        ),
    )
    envelope = _envelope("assessment.report.generate")
    channel = _FakeChannel()
    message = _FakeIncomingMessage(envelope, channel=channel)
    consumer = AssessmentCommandConsumer(
        SimpleNamespace(),
        _ProcessorStub(exc=InfrastructureFailure("temporary database outage")),
        _settings(),
    )

    await consumer._consume(message)

    assert channel.requested_exchange == SAR_RETRY_EXCHANGE_NAME
    published, routing_key = channel.exchange.published[0]
    assert routing_key == envelope.message_type
    assert published.body == message.body
    assert published.headers[_RETRY_HEADER] == 1
    assert message.acked == 1
    assert message.rejected == []
    assert message.nacked == []


@pytest.mark.asyncio
async def test_consumer_transient_failure_dead_letters_after_retry_limit() -> None:
    envelope = _envelope("assessment.report.generate")
    settings = _settings(retry_limit=2)
    message = _FakeIncomingMessage(envelope, headers={_RETRY_HEADER: 2})
    consumer = AssessmentCommandConsumer(
        SimpleNamespace(),
        _ProcessorStub(exc=InfrastructureFailure("temporary database outage")),
        settings,
    )

    await consumer._consume(message)

    assert message.acked == 0
    assert message.rejected == [False]
    assert message.nacked == []


@pytest.mark.asyncio
async def test_report_blob_is_compensated_when_report_transaction_fails() -> None:
    deleted: list[tuple[str, str]] = []

    class _ContextService:
        async def build_context(self, session, assessment_id):
            return SimpleNamespace(assessmentId=assessment_id, architecture=None, limitations=[])

    class _Renderer:
        def render(self, preview, *, architecture_image_bytes=None):
            return RenderedInitialSarReport(
                bytes=b"docx",
                original_filename="report.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                file_size_bytes=4,
                sha256="hash",
            )

    class _Storage:
        async def store_report(self, **kwargs):
            return StoredInitialSarReport(storage_container="reports", storage_key="secret/key.docx")

        async def delete_report(self, storage_container: str, storage_key: str):
            deleted.append((storage_container, storage_key))

    class _Repository:
        async def get_next_report_version(self, session, assessment_id):
            return 1

        async def create_completed_report(self, *args, **kwargs):
            raise SQLAlchemyError("simulated persistence failure")

    service = InitialSarReportGenerationService(
        context_service=_ContextService(),
        renderer=_Renderer(),
        storage=_Storage(),
        repository=_Repository(),
        document_repository=SimpleNamespace(),
    )
    session = SimpleNamespace(info={})

    with pytest.raises(SQLAlchemyError):
        await service.generate_report(
            session,
            assessment_id=ASSESSMENT_ID,
            source_workflow_version=WORKFLOW_VERSION,
        )

    assert deleted == [("reports", "secret/key.docx")]
    assert session.info == {}


def test_worker_contract_constants_match_orchestrator_wire_expectations() -> None:
    assert ASSESSMENT_COMMAND_TYPES == (
        "assessment.risk.calculate",
        "assessment.risk.recalculate",
        "assessment.checklist.generate",
        "assessment.checklist.finalize",
        "assessment.report.generate",
        "assessment.report.regenerate",
    )
    assert ASSESSMENT_WORKER_EVENT_TYPES == (
        "assessment.risk.completed",
        "assessment.risk.failed",
        "assessment.checklist.generated",
        "assessment.checklist.completed",
        "assessment.checklist.incomplete",
        "assessment.checklist.failed",
        "assessment.report.completed",
        "assessment.report.failed",
    )
    assert ASSESSMENT_WORKFLOW_COMMANDS == ASSESSMENT_COMMAND_TYPES[:4]
    assert ASSESSMENT_DOCUMENT_COMMANDS == ASSESSMENT_COMMAND_TYPES[4:]
    assert SAR_COMMANDS_EXCHANGE_NAME == "sar.commands"
    assert SAR_EVENTS_EXCHANGE_NAME == "sar.events"
    assert SAR_RETRY_EXCHANGE_NAME == "sar.retry"
    assert SAR_DLX_EXCHANGE_NAME == "sar.dlx"
    assert ASSESSMENT_WORKFLOW_QUEUE_NAME == "assessment.workflow.q"
    assert ASSESSMENT_DOCUMENTS_QUEUE_NAME == "assessment.documents.q"
