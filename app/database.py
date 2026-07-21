from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import DATABASE_SCHEMA_TOKEN, get_settings
from app.models.database import Base


def create_engine_from_url(database_url: str, database_schema: str | None = None):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    schema_translate_map = {
        DATABASE_SCHEMA_TOKEN: None if database_url.startswith("sqlite") else database_schema,
    }
    return create_engine(
        database_url,
        future=True,
        connect_args=connect_args,
        execution_options={"schema_translate_map": schema_translate_map},
    )


settings = get_settings()
engine = create_engine_from_url(settings.database_url, settings.database_schema)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
