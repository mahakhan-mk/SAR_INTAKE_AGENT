from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.errors import (
    AnalysisRunNotFoundError,
    AnalysisRunStatusConflictError,
    AssessmentNotFoundError,
    BusinessPreconditionError,
    DocumentChecklistRunNotFoundError,
    TransientDependencyError,
    sanitize_failure_summary,
)
from app.messaging.contracts import COMMAND_FAILURE_EVENT
from app.messaging.envelope import MessageEnvelope
from app.repositories.worker_messaging_repository import (
    ProcessedMessageRepository,
    TaskLeaseUnavailable,
    WorkerOutboxRepository,
    WorkflowTaskExecutionRepository,
)
from app.worker.handlers import CommandExecutionResult
from app.worker.registry import CommandRegistry

logger = logging.getLogger(__name__)


class InfrastructureFailure(RuntimeError):
    pass


class NonRetryableCommandFailure(RuntimeError):
    pass


@dataclass(slots=True)
class _LeaseExecution:
    stop_event: asyncio.Event
    lost_event: asyncio.Event
    handler_task: asyncio.Task[CommandExecutionResult] | None = None
    lost_reason: str | None = None

    def mark_lost(self, reason: str) -> None:
        if self.lost_event.is_set():
            return
        self.lost_reason = reason
        self.lost_event.set()
        if self.handler_task is not None and not self.handler_task.done():
            self.handler_task.cancel()


class CommandProcessor:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        registry: CommandRegistry,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._registry = registry
        self._processed = ProcessedMessageRepository()
        self._tasks = WorkflowTaskExecutionRepository()
        self._outbox = WorkerOutboxRepository()

    async def process(self, envelope: MessageEnvelope) -> bool:
        if envelope.task_id is None:
            raise NonRetryableCommandFailure("assessment command requires taskId")
        if envelope.expected_workflow_version is None:
            raise NonRetryableCommandFailure(
                "assessment command requires expectedWorkflowVersion"
            )

        try:
            handler = self._registry.resolve(envelope.message_type)
        except LookupError as exc:
            raise NonRetryableCommandFailure(str(exc)) from exc

        try:
            claimed = await self._claim_task(envelope)
        except TaskLeaseUnavailable as exc:
            raise InfrastructureFailure(str(exc)) from exc
        except SQLAlchemyError as exc:
            raise InfrastructureFailure(str(exc)) from exc
        except (LookupError, ValueError) as exc:
            raise NonRetryableCommandFailure(str(exc)) from exc
        if not claimed:
            return False

        lease_execution = _LeaseExecution(
            stop_event=asyncio.Event(),
            lost_event=asyncio.Event(),
        )
        heartbeat_task = asyncio.create_task(
            self._renew_lease_until_stopped(envelope, lease_execution),
            name=f"task-lease-heartbeat-{envelope.task_id}",
        )

        session = self._session_factory()
        execution_result: CommandExecutionResult | None = None
        committed = False
        try:
            try:
                async with session.begin():
                    self._raise_if_lease_lost(envelope, lease_execution)
                    execution_result = await self._execute_handler(
                        handler,
                        session,
                        envelope,
                        lease_execution,
                    )
                    self._raise_if_lease_lost(envelope, lease_execution)
                    lease_execution.stop_event.set()
                    await self._outbox.add_result(
                        session,
                        event_type=execution_result.event_type,
                        assessment_id=envelope.assessment_id,
                        workflow_id=envelope.workflow_id,
                        task_id=envelope.task_id,
                        causation_id=envelope.message_id,
                        expected_workflow_version=envelope.expected_workflow_version,
                        attempt=envelope.attempt,
                        actor_id=self._settings.worker_actor_id,
                        payload=execution_result.payload,
                    )
                    await self._processed.mark_processed(
                        session,
                        consumer_name=self._settings.consumer_name,
                        message_id=envelope.message_id,
                    )
                    await self._tasks.mark_succeeded(
                        session,
                        task_id=envelope.task_id,
                        attempt=envelope.attempt,
                        lease_owner=self._settings.worker_instance_id,
                    )
            except SQLAlchemyError:
                raise
            except TaskLeaseUnavailable:
                raise
            except Exception as exc:
                self._raise_if_lease_lost(envelope, lease_execution)
                execution_result = None
                lease_execution.stop_event.set()
                async with session.begin():
                    self._raise_if_lease_lost(envelope, lease_execution)
                    await self._record_handled_failure(session, envelope, exc)
                    await self._tasks.renew_lease(
                        session,
                        task_id=envelope.task_id,
                        attempt=envelope.attempt,
                        lease_owner=self._settings.worker_instance_id,
                        lease_seconds=self._settings.command_lease_seconds,
                    )
                    self._raise_if_lease_lost(envelope, lease_execution)
                logger.exception(
                    "command_execution_failed message_id=%s assessment_id=%s "
                    "workflow_id=%s task_id=%s command=%s attempt=%s retryable=%s",
                    envelope.message_id,
                    envelope.assessment_id,
                    envelope.workflow_id,
                    envelope.task_id,
                    envelope.message_type,
                    envelope.attempt,
                    _is_retryable(exc),
                )

            committed = True
            await self._stop_heartbeat(lease_execution, heartbeat_task)
            if execution_result is not None:
                await execution_result.committed()
            return True
        except TaskLeaseUnavailable as exc:
            raise InfrastructureFailure(str(exc)) from exc
        except SQLAlchemyError as exc:
            raise InfrastructureFailure(str(exc)) from exc
        except (LookupError, ValueError) as exc:
            raise NonRetryableCommandFailure(str(exc)) from exc
        finally:
            await self._stop_heartbeat(lease_execution, heartbeat_task)
            if execution_result is not None and not committed:
                await execution_result.rolled_back()
            await session.close()

    async def _record_handled_failure(
        self,
        session: AsyncSession,
        envelope: MessageEnvelope,
        exc: Exception,
    ) -> None:
        await self._outbox.add_result(
            session,
            event_type=COMMAND_FAILURE_EVENT[envelope.message_type],
            assessment_id=envelope.assessment_id,
            workflow_id=envelope.workflow_id,
            task_id=envelope.task_id,
            causation_id=envelope.message_id,
            expected_workflow_version=envelope.expected_workflow_version,
            attempt=envelope.attempt,
            actor_id=self._settings.worker_actor_id,
            payload={
                "retryable": _is_retryable(exc),
                "errorSummary": _error_summary(exc),
            },
        )
        await self._processed.mark_processed(
            session,
            consumer_name=self._settings.consumer_name,
            message_id=envelope.message_id,
        )

    async def _claim_task(self, envelope: MessageEnvelope) -> bool:
        session = self._session_factory()
        try:
            async with session.begin():
                if await self._processed.is_processed(
                    session,
                    consumer_name=self._settings.consumer_name,
                    message_id=envelope.message_id,
                ):
                    logger.info(
                        "duplicate_command_ignored message_id=%s assessment_id=%s "
                        "workflow_id=%s task_id=%s attempt=%s",
                        envelope.message_id,
                        envelope.assessment_id,
                        envelope.workflow_id,
                        envelope.task_id,
                        envelope.attempt,
                    )
                    return False

                await self._tasks.claim(
                    session,
                    task_id=envelope.task_id,
                    workflow_id=envelope.workflow_id,
                    task_type=envelope.message_type,
                    expected_workflow_version=envelope.expected_workflow_version,
                    attempt=envelope.attempt,
                    input_payload=dict(envelope.payload),
                    lease_owner=self._settings.worker_instance_id,
                    lease_seconds=self._settings.command_lease_seconds,
                )
            return True
        finally:
            await session.close()

    async def _execute_handler(
        self,
        handler,
        session: AsyncSession,
        envelope: MessageEnvelope,
        lease_execution: _LeaseExecution,
    ) -> CommandExecutionResult:
        task = asyncio.create_task(handler(session, envelope))
        lease_execution.handler_task = task
        try:
            return await task
        except asyncio.CancelledError as exc:
            self._raise_if_lease_lost(envelope, lease_execution)
            raise exc
        finally:
            if lease_execution.handler_task is task:
                lease_execution.handler_task = None

    async def _renew_lease_until_stopped(
        self,
        envelope: MessageEnvelope,
        lease_execution: _LeaseExecution,
    ) -> None:
        while not lease_execution.stop_event.is_set() and not lease_execution.lost_event.is_set():
            try:
                await asyncio.wait_for(
                    lease_execution.stop_event.wait(),
                    timeout=self._settings.command_lease_heartbeat_seconds,
                )
                return
            except TimeoutError:
                pass

            session = self._session_factory()
            try:
                async with session.begin():
                    await self._tasks.renew_lease(
                        session,
                        task_id=envelope.task_id,
                        attempt=envelope.attempt,
                        lease_owner=self._settings.worker_instance_id,
                        lease_seconds=self._settings.command_lease_seconds,
                    )
            except TaskLeaseUnavailable as exc:
                logger.warning(
                    "task_lease_lost message_id=%s workflow_id=%s task_id=%s attempt=%s",
                    envelope.message_id,
                    envelope.workflow_id,
                    envelope.task_id,
                    envelope.attempt,
                )
                lease_execution.mark_lost(str(exc))
                return
            except SQLAlchemyError as exc:
                logger.exception(
                    "task_lease_renewal_failed message_id=%s workflow_id=%s task_id=%s attempt=%s",
                    envelope.message_id,
                    envelope.workflow_id,
                    envelope.task_id,
                    envelope.attempt,
                )
                lease_execution.mark_lost(str(exc))
                return
            finally:
                await session.close()

    @staticmethod
    def _raise_if_lease_lost(
        envelope: MessageEnvelope,
        lease_execution: _LeaseExecution,
    ) -> None:
        if not lease_execution.lost_event.is_set():
            return
        reason = lease_execution.lost_reason or "lease lost during execution"
        raise TaskLeaseUnavailable(
            f"task {envelope.task_id} lease lost for attempt {envelope.attempt}: {reason}"
        )

    @staticmethod
    async def _stop_heartbeat(
        lease_execution: _LeaseExecution,
        heartbeat_task: asyncio.Task[None],
    ) -> None:
        lease_execution.stop_event.set()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass


def _is_retryable(exc: Exception) -> bool:
    return not isinstance(
        exc,
        (
            AssessmentNotFoundError,
            AnalysisRunNotFoundError,
            AnalysisRunStatusConflictError,
            DocumentChecklistRunNotFoundError,
            BusinessPreconditionError,
            LookupError,
            ValueError,
        ),
    )


def _error_summary(exc: Exception) -> str:
    if not isinstance(
        exc,
        (
            AssessmentNotFoundError,
            AnalysisRunNotFoundError,
            AnalysisRunStatusConflictError,
            DocumentChecklistRunNotFoundError,
            BusinessPreconditionError,
            LookupError,
            ValueError,
        ),
    ):
        return sanitize_failure_summary(
            _fallback_failure_summary(exc),
            fallback="Assessment command processing failed.",
        )
    return sanitize_failure_summary(
        exc,
        fallback=_fallback_failure_summary(exc),
    )


def _fallback_failure_summary(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "Operation timed out while processing the assessment command."
    if isinstance(exc, TransientDependencyError):
        return "Temporary external dependency failure while processing the assessment command."
    if isinstance(exc, BusinessPreconditionError | ValueError):
        return "Command business precondition was not satisfied."
    if isinstance(exc, SQLAlchemyError):
        return "Database operation failed while processing the assessment command."
    return "Assessment command processing failed."
