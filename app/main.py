from __future__ import annotations

import asyncio
import logging
import signal

from app.composition import build_application
from app.config import get_settings
from app.database import DatabaseRuntime
from app.messaging.rabbitmq import create_rabbitmq_connection
from app.messaging.topology import declare_topology

logger = logging.getLogger(__name__)


async def run_worker() -> None:
    settings = get_settings()
    _configure_logging()
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown_event.set)
        except NotImplementedError:
            pass

    database = DatabaseRuntime.create(settings)
    connection = await create_rabbitmq_connection(settings.rabbitmq_url)
    components = None
    publisher_task: asyncio.Task[None] | None = None
    shutdown_waiter: asyncio.Task[bool] | None = None
    try:
        await declare_topology(
            connection,
            retry_delay_milliseconds=settings.rabbitmq_retry_delay_milliseconds,
        )
        components = build_application(
            settings=settings,
            database=database,
            rabbitmq_connection=connection,
        )
        await components.consumer.start()
        publisher_task = asyncio.create_task(
            components.outbox_publisher.run(shutdown_event),
            name="assessment-outbox-publisher",
        )
        shutdown_waiter = asyncio.create_task(
            shutdown_event.wait(),
            name="assessment-shutdown-waiter",
        )
        logger.info(
            "assessment_worker_started instance=%s consumer=%s",
            settings.worker_instance_id,
            settings.consumer_name,
        )
        done, _ = await asyncio.wait(
            {publisher_task, shutdown_waiter},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if publisher_task in done:
            exception = publisher_task.exception()
            if exception is not None:
                raise exception
            logger.error("outbox_publisher_stopped_unexpectedly")
            raise RuntimeError("outbox publisher stopped unexpectedly")
    finally:
        shutdown_event.set()
        if shutdown_waiter is not None and not shutdown_waiter.done():
            shutdown_waiter.cancel()
            await asyncio.gather(shutdown_waiter, return_exceptions=True)
        if components is not None:
            try:
                await components.consumer.close()
            except Exception:
                logger.exception("assessment_consumer_close_failed")
        if publisher_task is not None:
            try:
                await asyncio.wait_for(
                    publisher_task,
                    timeout=settings.shutdown_grace_seconds,
                )
            except TimeoutError:
                publisher_task.cancel()
                await asyncio.gather(publisher_task, return_exceptions=True)
            except Exception:
                logger.exception("assessment_outbox_publisher_close_failed")
        try:
            await connection.close()
        except Exception:
            logger.exception("assessment_rabbitmq_close_failed")
        try:
            await database.close()
        except Exception:
            logger.exception("assessment_database_close_failed")
        logger.info("assessment_worker_stopped")


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


if __name__ == "__main__":
    asyncio.run(run_worker())
