from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import DATABASE_SCHEMA_TOKEN, Settings
from app.domain.errors import BusinessPreconditionError, DocumentChecklistRunNotFoundError, sanitize_failure_summary
from app.messaging.contracts import validate_assessment_event_payload
from app.messaging.envelope import MessageEnvelope, create_message_envelope
from app.models.database import Base, OutboxMessage, WorkflowTask
from app.models.enums import DocumentChecklistRunStatus
from app.worker.handlers import AssessmentCommandHandlers, CommandExecutionResult
from app.worker.processor import CommandProcessor, _error_summary, _is_retryable


NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
WORKFLOW_ID = UUID("11111111-1111-4111-8111-111111111111")
TASK_ID = UUID("22222222-2222-4222-8222-222222222222")
ASSESSMENT_ID = UUID("33333333-3333-4333-8333-333333333333")
WORKFLOW_VERSION = 4


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


@dataclass(frozen=True)
class _Completeness:
    is_complete: bool


class _AssessmentRepository:
    def __init__(self, *, complete: bool = True, exists: bool = True, triage_unresolved: bool = False) -> None:
        self.complete = complete
        self.exists = exists
        self.triage_unresolved = triage_unresolved
        self.loaded_types: list[str] = []

    async def get_assessment(self, session, assessment_id):
        return SimpleNamespace(id=assessment_id) if self.exists else None

    async def load_required_response_completeness(self, session, assessment_id, questionnaire_type):
        self.loaded_types.append(questionnaire_type)
        return _Completeness(is_complete=self.complete)

    async def load_active_triage_question_responses(self, session, assessment_id):
        required_response = SimpleNamespace(is_required=True)
        return SimpleNamespace(
            question_responses=[required_response],
            required_triage_question_count=1,
            unresolved_response_ids=[uuid4()] if self.triage_unresolved else [],
        )


class _AnalysisRepository:
    def __init__(self, *, latest_run=True) -> None:
        self.latest_run = latest_run

    async def get_latest_usable_analysis_run(self, session, assessment_id):
        return SimpleNamespace(id=uuid4()) if self.latest_run else None


class _RiskService:
    def __init__(self, *, complete: bool = True, latest_run=True, triage_unresolved: bool = False) -> None:
        self.assessment_repository = _AssessmentRepository(
            complete=complete,
            triage_unresolved=triage_unresolved,
        )
        self.analysis_repository = _AnalysisRepository(latest_run=latest_run)
        self.created: list[bool] = []

    async def create_analysis_run(self, session, assessment_id, force: bool = False):
        self.created.append(force)
        return SimpleNamespace(analysisRunId=str(uuid4()))


class _ExecutiveSummaryService:
    async def generate(self, session, assessment_id, run_id, force: bool = False):
        return None


class _ChecklistRepository:
    def __init__(self, *, run_record=None, review=None) -> None:
        self.run_record = run_record
        self.review = review

    async def get_checklist_run_with_items(self, session, *, assessment_id, run_id):
        if self.run_record is None:
            return None
        if self.run_record.run.assessment_id != assessment_id or self.run_record.run.id != run_id:
            return None
        return self.run_record

    async def get_latest_checklist_run_with_items(self, session, assessment_id):
        return self.run_record

    async def get_item_review_for_run_items(self, session, *, assessment_id, review_id, item_ids):
        if self.review is None or self.review.id != review_id or self.review.source_item_id not in item_ids:
            return None
        return self.review


class _ChecklistService:
    def __init__(self, repository: _ChecklistRepository | None = None) -> None:
        self.checklist_repository = repository or _ChecklistRepository()
        self.generated = 0

    async def generate_checklist(self, session, assessment_id):
        self.generated += 1

    async def finalize_checklist(self, session, *, assessment_id, run_id):
        return SimpleNamespace(run=SimpleNamespace(status=DocumentChecklistRunStatus.COMPLETED.value))


class _ReportService:
    def __init__(self, *, checklist_record=None, analysis_run=True) -> None:
        self.context_service = SimpleNamespace(
            checklist_repository=_ChecklistRepository(run_record=checklist_record),
            analysis_repository=_AnalysisRepository(latest_run=analysis_run),
        )
        self.generated: list[bool] = []

    async def generate_report(self, session, *, assessment_id, source_workflow_version, regenerate=False):
        self.generated.append(regenerate)
        return SimpleNamespace(report_id=uuid4())

    async def finalize_successful_generation(self, session, report_id):
        return None

    async def compensate_failed_generation(self, session, report_id):
        return None


class _ReportRepository:
    async def mark_reports_stale(self, session, assessment_id, stale_at):
        return 0

    async def get_latest_report_for_assessment(self, session, assessment_id):
        return None


class _Registry:
    def __init__(self, command_type: str, handler) -> None:
        self.command_type = command_type
        self.handler = handler

    def resolve(self, message_type: str):
        assert message_type == self.command_type
        return self.handler


def _settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        database_schema="public",
        rabbitmq_url="amqp://guest:guest@localhost/",
        worker_instance_id="host-a:123:worker-a",
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


def _handlers(
    *,
    risk_service: _RiskService | None = None,
    checklist_service: _ChecklistService | None = None,
    report_service: _ReportService | None = None,
) -> AssessmentCommandHandlers:
    return AssessmentCommandHandlers(
        risk_service=risk_service or _RiskService(),
        executive_summary_service=_ExecutiveSummaryService(),
        checklist_service=checklist_service or _ChecklistService(),
        report_service=report_service or _ReportService(),
        report_repository=_ReportRepository(),
    )


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


def _checklist_record(*, status: str = DocumentChecklistRunStatus.COMPLETED.value):
    run_id = uuid4()
    item = SimpleNamespace(id=uuid4(), document_type="SOC 2 Type II")
    return SimpleNamespace(
        run=SimpleNamespace(id=run_id, assessment_id=ASSESSMENT_ID, status=status),
        items=[item],
    )


async def _insert_task(session_factory: async_sessionmaker[AsyncSession], command_type: str) -> None:
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
                    input_payload={},
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


@pytest.mark.parametrize(
    ("unsafe", "forbidden"),
    [
        ("Authorization: Bearer eyJ.secret.token", "eyJ.secret.token"),
        ("password=super-secret", "super-secret"),
        ("postgresql://user:pass@localhost/db", "user:pass"),
        ("amqp://guest:guest@rabbitmq/", "guest:guest"),
        ("https://example.test/file?sv=1&sig=secret", "sig=secret"),
        ("https://acct.blob.core.windows.net/container/blob?sig=secret", "blob.core.windows.net"),
        ("Traceback (most recent call last):\n  File \"x.py\", line 1\nboom", "Traceback"),
        ("document content: full customer questionnaire text", "full customer questionnaire text"),
        ("raw LLM response: hidden prompt and model output", "hidden prompt"),
    ],
)
def test_failure_sanitizer_redacts_sensitive_categories(unsafe: str, forbidden: str) -> None:
    sanitized = sanitize_failure_summary(unsafe)

    assert sanitized
    assert forbidden not in sanitized
    assert "\n" not in sanitized


def test_failure_sanitizer_is_non_empty_and_bounded() -> None:
    assert sanitize_failure_summary("") == "Operation failed."
    sanitized = sanitize_failure_summary("x" * 5000, max_length=100)
    assert len(sanitized) == 100


def test_failure_classification_and_payload_contract() -> None:
    assert _is_retryable(BusinessPreconditionError("missing mandatory data")) is False
    assert _is_retryable(ValueError("invalid command payload")) is False
    assert _is_retryable(SQLAlchemyError("database unavailable")) is True
    assert _is_retryable(TimeoutError("blob upload timed out")) is True

    payload = validate_assessment_event_payload(
        "assessment.report.failed",
        {
            "retryable": _is_retryable(TimeoutError("timeout")),
            "errorSummary": _error_summary(TimeoutError("timeout")),
        },
    )
    assert set(payload) == {"retryable", "errorSummary"}


@pytest.mark.asyncio
async def test_processor_records_checklist_failed_for_execution_failure(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    command_type = "assessment.checklist.generate"
    await _insert_task(session_factory, command_type)

    async def handler(session: AsyncSession, envelope: MessageEnvelope) -> CommandExecutionResult:
        raise TimeoutError("blob upload timed out password=secret")

    processor = CommandProcessor(session_factory, _settings(), _Registry(command_type, handler))

    assert await processor.process(_envelope(command_type)) is True

    async with session_factory() as session:
        outbox = (await session.execute(select(OutboxMessage))).scalar_one()
    assert outbox.message_type == "assessment.checklist.failed"
    assert outbox.payload["retryable"] is True
    assert set(outbox.payload) == {"retryable", "errorSummary"}
    assert "secret" not in outbox.payload["errorSummary"]


@pytest.mark.asyncio
async def test_calculate_rejects_missing_mandatory_responses() -> None:
    handlers = _handlers(risk_service=_RiskService(complete=False))

    with pytest.raises(BusinessPreconditionError):
        await handlers.calculate_risk(object(), _envelope("assessment.risk.calculate"))


@pytest.mark.asyncio
async def test_calculate_accepts_complete_authoritative_responses() -> None:
    risk_service = _RiskService(complete=True)
    handlers = _handlers(risk_service=risk_service)

    result = await handlers.calculate_risk(object(), _envelope("assessment.risk.calculate"))

    assert result.event_type == "assessment.risk.completed"
    assert risk_service.created == [False]


@pytest.mark.asyncio
async def test_recalculate_preserves_historical_runs_by_creating_new_forced_run() -> None:
    risk_service = _RiskService(complete=True)
    handlers = _handlers(risk_service=risk_service)

    result = await handlers.recalculate_risk(
        object(),
        _envelope("assessment.risk.recalculate", {"responseVersion": 1}),
    )

    assert result.event_type == "assessment.risk.completed"
    assert risk_service.created == [True]


@pytest.mark.asyncio
async def test_checklist_generate_rejects_absent_completed_risk_run() -> None:
    handlers = _handlers(risk_service=_RiskService(latest_run=False))

    with pytest.raises(BusinessPreconditionError):
        await handlers.generate_checklist(object(), _envelope("assessment.checklist.generate"))


@pytest.mark.asyncio
async def test_checklist_generate_succeeds_with_completed_risk_input() -> None:
    checklist_service = _ChecklistService()
    handlers = _handlers(checklist_service=checklist_service)

    result = await handlers.generate_checklist(object(), _envelope("assessment.checklist.generate"))

    assert result.event_type == "assessment.checklist.generated"
    assert checklist_service.generated == 1


@pytest.mark.asyncio
async def test_finalize_rejects_checklist_run_from_another_assessment() -> None:
    run_id = uuid4()
    handlers = _handlers(checklist_service=_ChecklistService(_ChecklistRepository(run_record=None)))

    with pytest.raises(DocumentChecklistRunNotFoundError):
        await handlers.finalize_checklist(
            object(),
            _envelope(
                "assessment.checklist.finalize",
                {"checklistRunId": str(run_id), "reviewId": str(uuid4())},
            ),
        )


@pytest.mark.asyncio
async def test_finalize_rejects_review_from_another_checklist_run() -> None:
    run_record = _checklist_record()
    review = SimpleNamespace(id=uuid4(), source_item_id=uuid4())
    handlers = _handlers(
        checklist_service=_ChecklistService(_ChecklistRepository(run_record=run_record, review=review))
    )

    with pytest.raises(BusinessPreconditionError):
        await handlers.finalize_checklist(
            object(),
            _envelope(
                "assessment.checklist.finalize",
                {"checklistRunId": str(run_record.run.id), "reviewId": str(review.id)},
            ),
        )


@pytest.mark.asyncio
async def test_report_generate_rejects_non_completed_checklist() -> None:
    handlers = _handlers(report_service=_ReportService(checklist_record=_checklist_record(status="draft")))

    with pytest.raises(BusinessPreconditionError):
        await handlers.generate_report(object(), _envelope("assessment.report.generate"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        DocumentChecklistRunStatus.COMPLETED.value,
        DocumentChecklistRunStatus.COMPLETED_WITH_LIMITATIONS.value,
    ],
)
async def test_report_generate_accepts_completed_checklist_statuses(status: str) -> None:
    report_service = _ReportService(checklist_record=_checklist_record(status=status))
    handlers = _handlers(report_service=report_service)

    result = await handlers.generate_report(object(), _envelope("assessment.report.generate"))

    assert result.event_type == "assessment.report.completed"
    assert report_service.generated == [False]
