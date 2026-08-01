from __future__ import annotations

import asyncio
import logging

try:
    import aio_pika
except ModuleNotFoundError:  # pragma: no cover
    aio_pika = None
from pydantic import ValidationError

from app.config import Settings
from app.messaging.contracts import ASSESSMENT_COMMAND_TYPES, SAR_RETRY_EXCHANGE_NAME
from app.messaging.envelope import MessageEnvelope
from app.messaging.topology import (
    ASSESSMENT_DOCUMENTS_QUEUE_NAME,
    ASSESSMENT_WORKFLOW_QUEUE_NAME,
)
from app.worker.processor import (
    CommandAlreadyInFlight,
    CommandProcessor,
    InfrastructureFailure,
    NonRetryableCommandFailure,
    PostClaimInfrastructureFailure,
    PreClaimInfrastructureFailure,
)

logger = logging.getLogger(__name__)
_RETRY_HEADER = "x-assessment-worker-retry-count"


class AssessmentCommandConsumer:
    def __init__(
        self,
        connection: aio_pika.RobustConnection,
        processor: CommandProcessor,
        settings: Settings,
    ) -> None:
        self._connection = connection
        self._processor = processor
        self._settings = settings
        self._execution_gate = asyncio.Semaphore(1)
        self._channels: list[aio_pika.abc.AbstractChannel] = []
        self._consumers: list[tuple[aio_pika.abc.AbstractQueue, str]] = []
        self._retry_exchange: aio_pika.abc.AbstractExchange | None = None

    async def start(self) -> None:
        if aio_pika is None:
            raise RuntimeError("aio-pika is required to start the command consumer")
        if self._channels:
            return
        await self._start_queue(ASSESSMENT_WORKFLOW_QUEUE_NAME)
        await self._start_queue(ASSESSMENT_DOCUMENTS_QUEUE_NAME)

    async def close(self) -> None:
        for queue, tag in reversed(self._consumers):
            try:
                await queue.cancel(tag)
            except Exception:
                logger.exception("consumer_cancel_failed tag=%s", tag)
        self._consumers.clear()
        for channel in reversed(self._channels):
            try:
                await channel.close()
            except Exception:
                logger.exception("consumer_channel_close_failed")
        self._channels.clear()
        self._retry_exchange = None

    async def _start_queue(self, queue_name: str) -> None:
        channel = await self._connection.channel()
        await channel.set_qos(prefetch_count=self._settings.command_prefetch_count)
        if self._retry_exchange is None:
            self._retry_exchange = await channel.get_exchange(
                SAR_RETRY_EXCHANGE_NAME,
                ensure=True,
            )
        queue = await channel.get_queue(queue_name, ensure=True)
        tag = await queue.consume(self._consume)
        self._channels.append(channel)
        self._consumers.append((queue, tag))

    async def _consume(self, message: aio_pika.IncomingMessage) -> None:
        routing_key = message.routing_key
        try:
            envelope = MessageEnvelope.model_validate_json(message.body)
        except (ValidationError, ValueError, TypeError):
            logger.exception("invalid_command_envelope routing_key=%s", routing_key)
            await message.reject(requeue=False)
            return

        if (
            routing_key not in ASSESSMENT_COMMAND_TYPES
            or envelope.message_type != routing_key
            or envelope.schema_version != 1
        ):
            logger.error(
                "command_routing_mismatch routing_key=%s message_type=%s schema=%s",
                routing_key,
                envelope.message_type,
                envelope.schema_version,
            )
            await message.reject(requeue=False)
            return

        try:
            async with self._execution_gate:
                await self._processor.process(envelope)
        except CommandAlreadyInFlight:
            logger.info(
                "command_already_in_flight_acked message_id=%s assessment_id=%s "
                "workflow_id=%s task_id=%s attempt=%s command=%s",
                envelope.message_id,
                envelope.assessment_id,
                envelope.workflow_id,
                envelope.task_id,
                envelope.attempt,
                envelope.message_type,
            )
            await message.ack()
            return
        except NonRetryableCommandFailure as exc:
            logger.error(
                "command_rejected message_id=%s assessment_id=%s workflow_id=%s "
                "task_id=%s attempt=%s command=%s error=%s",
                envelope.message_id,
                envelope.assessment_id,
                envelope.workflow_id,
                envelope.task_id,
                envelope.attempt,
                envelope.message_type,
                exc,
            )
            await message.reject(requeue=False)
            return
        except PreClaimInfrastructureFailure:
            logger.exception(
                "command_pre_claim_infrastructure_failure message_id=%s assessment_id=%s "
                "workflow_id=%s task_id=%s attempt=%s command=%s",
                envelope.message_id,
                envelope.assessment_id,
                envelope.workflow_id,
                envelope.task_id,
                envelope.attempt,
                envelope.message_type,
            )
            await self._retry_or_dead_letter(message, envelope)
            return
        except PostClaimInfrastructureFailure:
            logger.exception(
                "command_post_claim_infrastructure_failure_acked message_id=%s "
                "assessment_id=%s workflow_id=%s task_id=%s attempt=%s command=%s",
                envelope.message_id,
                envelope.assessment_id,
                envelope.workflow_id,
                envelope.task_id,
                envelope.attempt,
                envelope.message_type,
            )
            await message.ack()
            return
        except InfrastructureFailure:
            logger.exception(
                "command_unclassified_infrastructure_failure message_id=%s assessment_id=%s "
                "workflow_id=%s task_id=%s attempt=%s command=%s",
                envelope.message_id,
                envelope.assessment_id,
                envelope.workflow_id,
                envelope.task_id,
                envelope.attempt,
                envelope.message_type,
            )
            await self._retry_or_dead_letter(message, envelope)
            return
        except Exception:
            logger.exception(
                "command_consumer_failure message_id=%s assessment_id=%s workflow_id=%s "
                "task_id=%s attempt=%s command=%s",
                envelope.message_id,
                envelope.assessment_id,
                envelope.workflow_id,
                envelope.task_id,
                envelope.attempt,
                envelope.message_type,
            )
            await self._retry_or_dead_letter(message, envelope)
            return
        logger.info(
            "command_processed message_id=%s assessment_id=%s workflow_id=%s "
            "task_id=%s attempt=%s command=%s",
            envelope.message_id,
            envelope.assessment_id,
            envelope.workflow_id,
            envelope.task_id,
            envelope.attempt,
            envelope.message_type,
        )
        await message.ack()

    async def _retry_or_dead_letter(
        self,
        message: aio_pika.IncomingMessage,
        envelope: MessageEnvelope,
    ) -> None:
        retries = _retry_count(message)
        if retries >= self._settings.command_retry_limit:
            logger.error(
                "command_transport_retry_exhausted message_id=%s assessment_id=%s "
                "workflow_id=%s task_id=%s attempt=%s command=%s retries=%s",
                envelope.message_id,
                envelope.assessment_id,
                envelope.workflow_id,
                envelope.task_id,
                envelope.attempt,
                envelope.message_type,
                retries,
            )
            await message.reject(requeue=False)
            return
        try:
            exchange = await self._retry_exchange_for_publish()
            headers = dict(message.headers or {})
            headers[_RETRY_HEADER] = retries + 1
            await asyncio.wait_for(
                exchange.publish(
                    aio_pika.Message(
                        body=bytes(message.body),
                        content_type=message.content_type or "application/json",
                        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                        message_id=message.message_id,
                        correlation_id=message.correlation_id,
                        type=message.type,
                        timestamp=message.timestamp,
                        headers=headers,
                    ),
                    routing_key=message.routing_key,
                ),
                timeout=10.0,
            )
        except Exception:
            logger.exception(
                "command_retry_publish_failed message_id=%s assessment_id=%s "
                "workflow_id=%s task_id=%s attempt=%s command=%s",
                envelope.message_id,
                envelope.assessment_id,
                envelope.workflow_id,
                envelope.task_id,
                envelope.attempt,
                envelope.message_type,
            )
            await message.reject(requeue=False)
            return
        logger.warning(
            "command_transport_retry_scheduled message_id=%s assessment_id=%s "
            "workflow_id=%s task_id=%s attempt=%s command=%s transport_retry=%s",
            envelope.message_id,
            envelope.assessment_id,
            envelope.workflow_id,
            envelope.task_id,
            envelope.attempt,
            envelope.message_type,
            retries + 1,
        )
        await message.ack()

    async def _retry_exchange_for_publish(self) -> aio_pika.abc.AbstractExchange:
        if self._retry_exchange is not None:
            return self._retry_exchange
        if not self._channels:
            raise RuntimeError("consumer retry exchange is unavailable")
        self._retry_exchange = await self._channels[0].get_exchange(
            SAR_RETRY_EXCHANGE_NAME,
            ensure=True,
        )
        return self._retry_exchange


def _retry_count(message: aio_pika.IncomingMessage) -> int:
    raw = (message.headers or {}).get(_RETRY_HEADER, 0)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0
