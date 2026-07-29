from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import DATABASE_SCHEMA_TOKEN, Settings


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return database_url


@dataclass(slots=True)
class DatabaseRuntime:
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]

    @classmethod
    def create(cls, settings: Settings) -> "DatabaseRuntime":
        engine = create_async_engine(
            normalize_database_url(settings.database_url),
            pool_pre_ping=True,
            execution_options={
                "schema_translate_map": {
                    DATABASE_SCHEMA_TOKEN: settings.database_schema,
                }
            },
        )
        return cls(
            engine=engine,
            session_factory=async_sessionmaker(
                bind=engine,
                autoflush=False,
                expire_on_commit=False,
            ),
        )

    async def close(self) -> None:
        await self.engine.dispose()
