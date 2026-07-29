from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
import logging
from uuid import uuid4

try:
    import aio_pika
except ModuleNotFoundError:  # pragma: no cover
    aio_pika = None
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.messaging.contracts import SAR_EVENTS_EXCHANGE_NAME
from app.messaging.envelope import create_message_envelope
from app.repositories.worker_messaging_repository import OutboxMessageRecord, WorkerOutboxRepository

logger = logging.getLogger(__name__)


class OutboxPublisher:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        connection: object,
        settings: Settings,
        *,
        lease_duration_seconds: float = 60.0,
        publisher_id: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._connection = connection
        self._settings = settings
        self._repository = WorkerOutboxRepository()
        if lease_duration_seconds <= 0:
            raise ValueError("lease_duration_seconds must be greater than 0")
        self._lease_duration = timedelta(seconds=lease_duration_seconds)
        self._publisher_id = publisher_id or f"assessment-outbox-publisher-{uuid4()}"

    async def run(self, shutdown_event: asyncio.Event) -> None:
        if aio_pika is None:
            raise RuntimeError("aio-pika is required to run the outbox publisher")
        while not shutdown_event.is_set():
            await self._publish_batch()
            if shutdown_event.is_set():
                break
            try:
                await asyncio.wait_for(
                    shutdown_event.wait(),
                    timeout=self._settings.outbox_poll_interval_seconds,
                )
            except TimeoutError:
                continue

    async def _publish_batch(self) -> int:
        records = await self._claim_batch()
        if not records:
            return 0

        channel = None
        try:
            channel = await self._connection.channel(publisher_confirms=True)
            exchange = await channel.get_exchange(SAR_EVENTS_EXCHANGE_NAME, ensure=True)
            published = 0
            for record in records:
                try:
                    await asyncio.wait_for(
                        self._publish_record(exchange, record),
                        timeout=self._settings.outbox_publish_timeout_seconds,
                    )
                except Exception as exc:
                    logger.exception(
                        "outbox_publish_failed message_id=%s message_type=%s",
                        record.message_id,
                        record.message_type,
                    )
                    await self._mark_publish_failed(record, exc)
                    continue

                if await self._mark_published(record):
                    published += 1
            return published
        except Exception:
            logger.exception("outbox_batch_failed")
            return 0
        finally:
            if channel is not None:
                try:
                    await channel.close()
                except Exception:
                    logger.exception("outbox_channel_close_failed")

    async def _claim_batch(self) -> list[OutboxMessageRecord]:
        session = self._session_factory()
        try:
            records = await self._repository.claim_publishable(
                session,
                limit=self._settings.outbox_batch_size,
                locked_by=self._publisher_id,
                lease_duration=self._lease_duration,
            )
            await session.commit()
            return records
        except Exception:
            await session.rollback()
            logger.exception("outbox_claim_failed")
            return []
        finally:
            await session.close()

    async def _mark_published(self, record: OutboxMessageRecord) -> bool:
        session = self._session_factory()
        try:
            await self._repository.mark_published(
                session,
                message_id=record.message_id,
                locked_by=self._publisher_id,
            )
            await session.commit()
            return True
        except LookupError:
            await session.rollback()
            logger.warning(
                "outbox_publish_finalize_skipped message_id=%s reason=lease_lost",
                record.message_id,
            )
            return False
        except Exception:
            await session.rollback()
            logger.exception(
                "outbox_publish_finalize_failed message_id=%s",
                record.message_id,
            )
            return False
        finally:
            await session.close()

    async def _mark_publish_failed(
        self,
        record: OutboxMessageRecord,
        error: Exception,
    ) -> bool:
        session = self._session_factory()
        try:
            await self._repository.mark_publish_failed(
                session,
                message_id=record.message_id,
                locked_by=self._publisher_id,
                current_attempt_count=record.publish_attempt_count,
                max_attempts=self._settings.outbox_max_publish_attempts,
                error=error,
            )
            await session.commit()
            return True
        except LookupError:
            await session.rollback()
            logger.warning(
                "outbox_publish_failure_finalize_skipped "
                "message_id=%s reason=lease_lost",
                record.message_id,
            )
            return False
        except Exception:
            await session.rollback()
            logger.exception(
                "outbox_publish_failure_finalize_failed message_id=%s",
                record.message_id,
            )
            return False
        finally:
            await session.close()

    async def _publish_record(
        self,
        exchange: object,
        record: OutboxMessageRecord,
    ) -> None:
        if record.exchange_name != SAR_EVENTS_EXCHANGE_NAME:
            raise ValueError(
                f"Assessment Worker cannot publish outbox exchange {record.exchange_name}"
            )
        envelope = create_message_envelope(
            message_id=record.message_id,
            message_type=record.message_type,
            schema_version=record.schema_version,
            assessment_id=record.assessment_id,
            workflow_id=record.workflow_id,
            task_id=record.task_id,
            causation_id=record.causation_id,
            expected_workflow_version=record.expected_workflow_version,
            attempt=record.message_attempt,
            occurred_at=record.created_at,
            actor_id=record.actor_id,
            payload=dict(record.payload or {}),
        )
        body = json.dumps(
            envelope.model_dump(mode="json", by_alias=True),
            separators=(",", ":"),
        ).encode("utf-8")
        await exchange.publish(
            aio_pika.Message(
                body=body,
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                message_id=str(record.message_id),
                correlation_id=str(record.workflow_id),
                type=record.message_type,
                timestamp=datetime.now(UTC),
                headers={
                    "schema_version": record.schema_version,
                    "message_attempt": record.message_attempt,
                    "producer_component": record.producer_component,
                },
            ),
            routing_key=record.message_type,
        )
