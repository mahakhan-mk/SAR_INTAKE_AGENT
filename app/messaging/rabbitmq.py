from __future__ import annotations

try:
    import aio_pika
except ModuleNotFoundError:  # pragma: no cover
    aio_pika = None


async def create_rabbitmq_connection(url: str) -> aio_pika.RobustConnection:
    if aio_pika is None:
        raise RuntimeError("aio-pika is required to start the Assessment Worker")
    return await aio_pika.connect_robust(url)
