from __future__ import annotations

import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.errors import (
    AnalysisRunNotFoundError,
    AnalysisRunStatusConflictError,
    AssessmentNotFoundError,
    DocumentChecklistRunNotFoundError,
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

        session = self._session_factory()
        execution_result: CommandExecutionResult | None = None
        committed = False
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

                task = await self._tasks.claim(
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
                if task.status in {"succeeded", "failed", "cancelled"}:
                    await self._processed.mark_processed(
                        session,
                        consumer_name=self._settings.consumer_name,
                        message_id=envelope.message_id,
                    )
                    return False

                try:
                    async with session.begin_nested():
                        execution_result = await handler(session, envelope)
                except SQLAlchemyError:
                    raise
                except Exception as exc:
                    await self._record_handled_failure(session, envelope, exc)
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
                    execution_result = None
                else:
                    await self._tasks.mark_succeeded(
                        session,
                        task_id=envelope.task_id,
                        attempt=envelope.attempt,
                        lease_owner=self._settings.worker_instance_id,
                    )
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

            committed = True
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


def _is_retryable(exc: Exception) -> bool:
    return not isinstance(
        exc,
        (
            AssessmentNotFoundError,
            AnalysisRunNotFoundError,
            AnalysisRunStatusConflictError,
            DocumentChecklistRunNotFoundError,
            LookupError,
            ValueError,
        ),
    )


def _error_summary(exc: Exception) -> str:
    text = str(exc).strip() or type(exc).__name__
    return f"{type(exc).__name__}: {text}"[:2000]
