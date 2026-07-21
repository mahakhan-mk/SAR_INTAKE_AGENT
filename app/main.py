from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.v1.intake import router as intake_router
from app.api.v1.inherent_risk import router as inherent_risk_router
from app.database import init_db

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await init_db()
    yield


app = FastAPI(title="SAR Assessment Service", lifespan=lifespan)
register_exception_handlers(app)
app.include_router(intake_router)
app.include_router(inherent_risk_router)
