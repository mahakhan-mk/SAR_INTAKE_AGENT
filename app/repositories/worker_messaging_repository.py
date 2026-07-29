from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
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
    ) -> list[OutboxMessage]:
        now = datetime.now(UTC)
        records = (
            await session.execute(
                select(OutboxMessage)
                .where(
                    OutboxMessage.status == "pending",
                    OutboxMessage.available_at <= now,
                )
                .order_by(
                    OutboxMessage.available_at,
                    OutboxMessage.created_at,
                    OutboxMessage.message_id,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        return list(records)

    async def mark_published(
        self,
        session: AsyncSession,
        *,
        message_id: UUID,
    ) -> None:
        result = await session.execute(
            update(OutboxMessage)
            .where(
                OutboxMessage.message_id == message_id,
                OutboxMessage.status == "pending",
            )
            .values(
                status="published",
                published_at=datetime.now(UTC),
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
        current_attempt_count: int,
        max_attempts: int,
        error: Exception,
    ) -> None:
        next_attempt = current_attempt_count + 1
        terminal = next_attempt >= max_attempts
        delay = min(300, 2 * (2 ** max(0, next_attempt - 1)))
        result = await session.execute(
            update(OutboxMessage)
            .where(
                OutboxMessage.message_id == message_id,
                OutboxMessage.status == "pending",
            )
            .values(
                status="failed" if terminal else "pending",
                publish_attempt_count=next_attempt,
                available_at=(
                    datetime.now(UTC)
                    if terminal
                    else datetime.now(UTC) + timedelta(seconds=delay)
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
