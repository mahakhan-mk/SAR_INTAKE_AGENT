from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.messaging.contracts import SAR_EVENTS_EXCHANGE_NAME, validate_assessment_event_payload
from app.models.database import OutboxMessage, ProcessedMessage, WorkflowTask


@dataclass(frozen=True, slots=True)
class ClaimedTask:
    id: UUID
    workflow_id: UUID
    task_type: str
    expected_workflow_version: int
    attempt_count: int
    max_attempts: int
    input_payload: dict[str, Any]
    status: str
    lease_owner: str | None
    lease_expires_at: datetime | None


class TaskLeaseUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OutboxMessageRecord:
    message_id: UUID
    producer_component: str
    exchange_name: str
    message_type: str
    schema_version: int
    assessment_id: UUID
    workflow_id: UUID
    task_id: UUID | None
    causation_id: UUID | None
    expected_workflow_version: int | None
    message_attempt: int
    actor_id: str
    payload: dict[str, Any]
    status: str
    locked_by: str | None
    lease_expires_at: datetime | None
    publish_attempt_count: int
    available_at: datetime
    published_at: datetime | None
    last_error: str | None
    created_at: datetime


class ProcessedMessageRepository:
    async def is_processed(
        self,
        session: AsyncSession,
        *,
        consumer_name: str,
        message_id: UUID,
    ) -> bool:
        result = await session.execute(
            select(ProcessedMessage.message_id).where(
                ProcessedMessage.consumer_name == consumer_name,
                ProcessedMessage.message_id == message_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def mark_processed(
        self,
        session: AsyncSession,
        *,
        consumer_name: str,
        message_id: UUID,
    ) -> None:
        await session.execute(
            insert(ProcessedMessage)
            .values(
                consumer_name=consumer_name,
                message_id=message_id,
                processed_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(
                index_elements=[
                    ProcessedMessage.consumer_name,
                    ProcessedMessage.message_id,
                ]
            )
        )


class WorkflowTaskExecutionRepository:
    async def claim(
        self,
        session: AsyncSession,
        *,
        task_id: UUID,
        workflow_id: UUID,
        task_type: str,
        expected_workflow_version: int,
        attempt: int,
        input_payload: dict[str, Any],
        lease_owner: str,
        lease_seconds: int,
    ) -> ClaimedTask:
        task = await self._get_for_update(session, task_id)
        self._validate_command_match(
            task,
            workflow_id=workflow_id,
            task_type=task_type,
            expected_workflow_version=expected_workflow_version,
            input_payload=input_payload,
        )

        if task.status in {"succeeded", "failed", "cancelled"}:
            return _claimed(task)
        if attempt < 1 or attempt > task.max_attempts:
            raise ValueError(f"attempt {attempt} is outside task retry policy")

        now = datetime.now(UTC)
        if task.status == "running":
            if task.attempt_count != attempt:
                relation = "stale" if attempt < task.attempt_count else "future"
                raise ValueError(
                    f"{relation} attempt {attempt}; current attempt is {task.attempt_count}"
                )
            lease_is_active = (
                task.lease_expires_at is not None
                and task.lease_expires_at > now
                and task.lease_owner != lease_owner
            )
            if lease_is_active:
                raise TaskLeaseUnavailable(
                    f"task {task.id} is leased by {task.lease_owner} until "
                    f"{task.lease_expires_at.isoformat()}"
                )
        elif task.status in {"queued", "retry", "pending"}:
            expected_attempt = task.attempt_count + 1
            if attempt != expected_attempt:
                relation = "stale" if attempt < expected_attempt else "future"
                raise ValueError(
                    f"{relation} attempt {attempt}; expected attempt is {expected_attempt}"
                )
        else:
            raise ValueError(f"task {task.id} cannot be claimed from status {task.status}")

        task.status = "running"
        task.attempt_count = attempt
        task.lease_owner = lease_owner
        task.lease_expires_at = now + timedelta(seconds=lease_seconds)
        task.started_at = task.started_at or now
        task.updated_at = now
        await session.flush()
        return _claimed(task)

    async def lock_running_execution(
        self,
        session: AsyncSession,
        *,
        task_id: UUID,
        attempt: int,
        lease_owner: str,
    ) -> ClaimedTask:
        task = await self._get_for_update(session, task_id)
        if task.status in {"succeeded", "failed", "cancelled"}:
            return _claimed(task)
        if task.status != "running":
            raise ValueError(
                f"task {task.id} must be running before execution; current status is {task.status}"
            )
        if task.attempt_count != attempt:
            raise ValueError(
                f"task {task.id} attempt changed from {attempt} to {task.attempt_count}"
            )
        if task.lease_owner != lease_owner:
            raise TaskLeaseUnavailable(
                f"task {task.id} lease owner changed to {task.lease_owner}"
            )
        return _claimed(task)

    async def mark_succeeded(
        self,
        session: AsyncSession,
        *,
        task_id: UUID,
        attempt: int,
        lease_owner: str,
    ) -> None:
        now = datetime.now(UTC)
        result = await session.execute(
            update(WorkflowTask)
            .where(
                WorkflowTask.id == task_id,
                WorkflowTask.status == "running",
                WorkflowTask.attempt_count == attempt,
                WorkflowTask.lease_owner == lease_owner,
            )
            .values(
                status="succeeded",
                completed_at=now,
                updated_at=now,
                lease_owner=None,
                lease_expires_at=None,
                error_summary=None,
            )
        )
        if result.rowcount != 1:
            raise ValueError(f"task {task_id} changed before success could be recorded")

    @staticmethod
    async def _get_for_update(session: AsyncSession, task_id: UUID) -> WorkflowTask:
        task = (
            await session.execute(
                select(WorkflowTask)
                .where(WorkflowTask.id == task_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if task is None:
            raise LookupError(f"workflow task {task_id} was not found")
        return task

    @staticmethod
    def _validate_command_match(
        task: WorkflowTask,
        *,
        workflow_id: UUID,
        task_type: str,
        expected_workflow_version: int,
        input_payload: dict[str, Any],
    ) -> None:
        mismatches: list[str] = []
        if task.workflow_id != workflow_id:
            mismatches.append("workflowId")
        if task.task_type != task_type:
            mismatches.append("messageType")
        if task.expected_workflow_version != expected_workflow_version:
            mismatches.append("expectedWorkflowVersion")
        if dict(task.input_payload or {}) != input_payload:
            mismatches.append("payload")
        if mismatches:
            raise ValueError("command does not match workflow task: " + ", ".join(mismatches))


class WorkerOutboxRepository:
    async def add_result(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        assessment_id: UUID,
        workflow_id: UUID,
        task_id: UUID,
        causation_id: UUID,
        expected_workflow_version: int,
        attempt: int,
        actor_id: str,
        payload: dict[str, Any],
    ) -> UUID:
        normalized_payload = validate_assessment_event_payload(event_type, payload)
        message_id = uuid4()
        session.add(
            OutboxMessage(
                message_id=message_id,
                producer_component="assessment_worker",
                exchange_name=SAR_EVENTS_EXCHANGE_NAME,
                message_type=event_type,
                schema_version=1,
                assessment_id=assessment_id,
                workflow_id=workflow_id,
                task_id=task_id,
                causation_id=causation_id,
                expected_workflow_version=expected_workflow_version,
                message_attempt=attempt,
                actor_id=actor_id,
                payload=normalized_payload,
                status="pending",
                locked_by=None,
                lease_expires_at=None,
                publish_attempt_count=0,
                available_at=datetime.now(UTC),
                published_at=None,
                last_error=None,
                created_at=datetime.now(UTC),
            )
        )
        await session.flush()
        return message_id

    async def claim_publishable(
        self,
        session: AsyncSession,
        *,
        limit: int,
        locked_by: str,
        lease_duration: timedelta,
        now: datetime | None = None,
    ) -> list[OutboxMessageRecord]:
        if limit < 1:
            raise ValueError("limit must be greater than or equal to 1")
        owner = _required(locked_by, "locked_by")
        if lease_duration.total_seconds() <= 0:
            raise ValueError("lease_duration must be greater than 0")
        reference_time = now or datetime.now(UTC)
        candidate_ids = (
            select(OutboxMessage.message_id)
            .where(
                or_(
                    and_(
                        OutboxMessage.status == "pending",
                        OutboxMessage.available_at <= reference_time,
                    ),
                    and_(
                        OutboxMessage.status == "processing",
                        OutboxMessage.lease_expires_at.is_not(None),
                        OutboxMessage.lease_expires_at <= reference_time,
                    ),
                )
            )
            .order_by(
                OutboxMessage.available_at,
                OutboxMessage.created_at,
                OutboxMessage.message_id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await session.execute(
            update(OutboxMessage)
            .where(OutboxMessage.message_id.in_(candidate_ids))
            .values(
                status="processing",
                locked_by=owner,
                lease_expires_at=reference_time + lease_duration,
            )
            .returning(*OutboxMessage.__table__.c)
        )
        return [_outbox_record(row._mapping) for row in result.all()]

    async def mark_published(
        self,
        session: AsyncSession,
        *,
        message_id: UUID,
        locked_by: str,
    ) -> None:
        owner = _required(locked_by, "locked_by")
        result = await session.execute(
            update(OutboxMessage)
            .where(
                OutboxMessage.message_id == message_id,
                OutboxMessage.status == "processing",
                OutboxMessage.locked_by == owner,
            )
            .values(
                status="published",
                published_at=datetime.now(UTC),
                locked_by=None,
                lease_expires_at=None,
                publish_attempt_count=OutboxMessage.publish_attempt_count + 1,
                last_error=None,
            )
        )
        if result.rowcount != 1:
            raise LookupError(f"outbox row changed for {message_id}")

    async def mark_publish_failed(
        self,
        session: AsyncSession,
        *,
        message_id: UUID,
        locked_by: str,
        current_attempt_count: int,
        max_attempts: int,
        error: Exception,
    ) -> None:
        next_attempt = current_attempt_count + 1
        terminal = next_attempt >= max_attempts
        delay = min(300, 2 * (2 ** max(0, next_attempt - 1)))
        owner = _required(locked_by, "locked_by")
        now = datetime.now(UTC)
        result = await session.execute(
            update(OutboxMessage)
            .where(
                OutboxMessage.message_id == message_id,
                OutboxMessage.status == "processing",
                OutboxMessage.locked_by == owner,
            )
            .values(
                status="failed" if terminal else "pending",
                locked_by=None,
                lease_expires_at=None,
                publish_attempt_count=next_attempt,
                available_at=(
                    now
                    if terminal
                    else now + timedelta(seconds=delay)
                ),
                last_error=f"{type(error).__name__}: {error}"[:2000],
            )
        )
        if result.rowcount != 1:
            raise LookupError(f"outbox row changed for {message_id}")


def _claimed(task: WorkflowTask) -> ClaimedTask:
    return ClaimedTask(
        id=task.id,
        workflow_id=task.workflow_id,
        task_type=task.task_type,
        expected_workflow_version=task.expected_workflow_version,
        attempt_count=task.attempt_count,
        max_attempts=task.max_attempts,
        input_payload=dict(task.input_payload or {}),
        status=task.status,
        lease_owner=task.lease_owner,
        lease_expires_at=task.lease_expires_at,
    )


def _outbox_record(mapping: Any) -> OutboxMessageRecord:
    return OutboxMessageRecord(
        message_id=mapping["message_id"],
        producer_component=mapping["producer_component"],
        exchange_name=mapping["exchange_name"],
        message_type=mapping["message_type"],
        schema_version=mapping["schema_version"],
        assessment_id=mapping["assessment_id"],
        workflow_id=mapping["workflow_id"],
        task_id=mapping["task_id"],
        causation_id=mapping["causation_id"],
        expected_workflow_version=mapping["expected_workflow_version"],
        message_attempt=mapping["message_attempt"],
        actor_id=mapping["actor_id"],
        payload=dict(mapping["payload"] or {}),
        status=mapping["status"],
        locked_by=mapping["locked_by"],
        lease_expires_at=mapping["lease_expires_at"],
        publish_attempt_count=mapping["publish_attempt_count"],
        available_at=mapping["available_at"],
        published_at=mapping["published_at"],
        last_error=mapping["last_error"],
        created_at=mapping["created_at"],
    )


def _required(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be a non-blank string")
    return normalized
