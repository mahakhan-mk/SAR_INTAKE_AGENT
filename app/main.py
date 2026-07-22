from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.router import api_router
from app.database import init_db


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await init_db()
    yield


app = FastAPI(title="SAR Assessment Service", lifespan=lifespan)
register_exception_handlers(app)
app.include_router(api_router)
