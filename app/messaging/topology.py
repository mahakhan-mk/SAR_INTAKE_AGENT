from __future__ import annotations

try:
    import aio_pika
except ModuleNotFoundError:  # pragma: no cover
    aio_pika = None

from app.messaging.contracts import (
    ASSESSMENT_DOCUMENT_COMMANDS,
    ASSESSMENT_WORKFLOW_COMMANDS,
    SAR_COMMANDS_EXCHANGE_NAME,
    SAR_DLX_EXCHANGE_NAME,
    SAR_EVENTS_EXCHANGE_NAME,
    SAR_RETRY_EXCHANGE_NAME,
)

ASSESSMENT_WORKFLOW_QUEUE_NAME = "assessment.workflow.q"
ASSESSMENT_WORKFLOW_RETRY_QUEUE_NAME = "assessment.workflow.retry.q"
ASSESSMENT_WORKFLOW_DLQ_NAME = "assessment.workflow.dlq"
ASSESSMENT_WORKFLOW_DLQ_ROUTING_KEY = "assessment.workflow.dlq"
ASSESSMENT_DOCUMENTS_QUEUE_NAME = "assessment.documents.q"
ASSESSMENT_DOCUMENTS_RETRY_QUEUE_NAME = "assessment.documents.retry.q"
ASSESSMENT_DOCUMENTS_DLQ_NAME = "assessment.documents.dlq"
ASSESSMENT_DOCUMENTS_DLQ_ROUTING_KEY = "assessment.documents.dlq"


async def declare_topology(
    connection: aio_pika.RobustConnection,
    *,
    retry_delay_milliseconds: int = 30_000,
) -> None:
    if aio_pika is None:
        raise RuntimeError("aio-pika is required to declare RabbitMQ topology")
    channel = await connection.channel()
    try:
        commands = await channel.declare_exchange(
            SAR_COMMANDS_EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
        )
        await channel.declare_exchange(
            SAR_EVENTS_EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
        )
        retry = await channel.declare_exchange(
            SAR_RETRY_EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
        )
        dlx = await channel.declare_exchange(
            SAR_DLX_EXCHANGE_NAME, aio_pika.ExchangeType.DIRECT, durable=True
        )
        await _declare_group(
            channel,
            commands=commands,
            retry=retry,
            dlx=dlx,
            queue_name=ASSESSMENT_WORKFLOW_QUEUE_NAME,
            retry_queue_name=ASSESSMENT_WORKFLOW_RETRY_QUEUE_NAME,
            dlq_name=ASSESSMENT_WORKFLOW_DLQ_NAME,
            dlq_routing_key=ASSESSMENT_WORKFLOW_DLQ_ROUTING_KEY,
            routing_keys=ASSESSMENT_WORKFLOW_COMMANDS,
            retry_delay_milliseconds=retry_delay_milliseconds,
        )
        await _declare_group(
            channel,
            commands=commands,
            retry=retry,
            dlx=dlx,
            queue_name=ASSESSMENT_DOCUMENTS_QUEUE_NAME,
            retry_queue_name=ASSESSMENT_DOCUMENTS_RETRY_QUEUE_NAME,
            dlq_name=ASSESSMENT_DOCUMENTS_DLQ_NAME,
            dlq_routing_key=ASSESSMENT_DOCUMENTS_DLQ_ROUTING_KEY,
            routing_keys=ASSESSMENT_DOCUMENT_COMMANDS,
            retry_delay_milliseconds=retry_delay_milliseconds,
        )
    finally:
        await channel.close()


async def _declare_group(
    channel: aio_pika.abc.AbstractChannel,
    *,
    commands: aio_pika.abc.AbstractExchange,
    retry: aio_pika.abc.AbstractExchange,
    dlx: aio_pika.abc.AbstractExchange,
    queue_name: str,
    retry_queue_name: str,
    dlq_name: str,
    dlq_routing_key: str,
    routing_keys: tuple[str, ...],
    retry_delay_milliseconds: int,
) -> None:
    queue = await channel.declare_queue(
        queue_name,
        durable=True,
        arguments={
            "x-dead-letter-exchange": SAR_DLX_EXCHANGE_NAME,
            "x-dead-letter-routing-key": dlq_routing_key,
        },
    )
    retry_queue = await channel.declare_queue(
        retry_queue_name,
        durable=True,
        arguments={
            "x-message-ttl": retry_delay_milliseconds,
            "x-dead-letter-exchange": SAR_COMMANDS_EXCHANGE_NAME,
        },
    )
    dlq = await channel.declare_queue(dlq_name, durable=True)
    for routing_key in routing_keys:
        await queue.bind(commands, routing_key=routing_key)
        await retry_queue.bind(retry, routing_key=routing_key)
    await dlq.bind(dlx, routing_key=dlq_routing_key)
