from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import DATABASE_SCHEMA_TOKEN, get_settings
from app.models.database import Base


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if database_url.startswith("sqlite:///"):
        return database_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if database_url.startswith("sqlite://"):
        return database_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    return database_url


def create_engine_from_url(database_url: str, database_schema: str | None = None) -> AsyncEngine:
    normalized_database_url = normalize_database_url(database_url)
    connect_args = {"check_same_thread": False} if normalized_database_url.startswith("sqlite") else {}
    schema_translate_map = {
        DATABASE_SCHEMA_TOKEN: None if normalized_database_url.startswith("sqlite") else database_schema,
    }
    return create_async_engine(
        normalized_database_url,
        future=True,
        connect_args=connect_args,
        execution_options={"schema_translate_map": schema_translate_map},
    )


settings = get_settings()
engine = create_engine_from_url(settings.database_url, settings.database_schema)
SessionLocal = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
