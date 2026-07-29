from __future__ import annotations

import os
import socket
from uuid import uuid4
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from dotenv import load_dotenv

from app.models.enums import RiskLevel

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
DATABASE_SCHEMA_ENV_VAR = "DATABASE_SCHEMA"
DATABASE_SCHEMA_TOKEN = "app_schema"


class SettingsError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    database_schema: str
    rabbitmq_url: str
    worker_instance_id: str
    worker_actor_id: str
    consumer_name: str
    command_prefetch_count: int
    command_retry_limit: int
    command_lease_seconds: int
    rabbitmq_retry_delay_milliseconds: int
    outbox_batch_size: int
    outbox_max_publish_attempts: int
    outbox_poll_interval_seconds: float
    outbox_publish_timeout_seconds: float
    shutdown_grace_seconds: float
    azure_blob_connection_string: str | None
    azure_blob_container_name: str | None
    azure_openai_endpoint: str | None
    azure_openai_api_key: str | None
    azure_openai_deployment: str | None
    azure_openai_timeout_seconds: float
    azure_openai_api_version: str | None


def get_settings() -> Settings:
    load_dotenv(dotenv_path=ENV_FILE, override=False)
    database_url = _required_env("DATABASE_URL")
    database_schema = _required_env(DATABASE_SCHEMA_ENV_VAR)
    rabbitmq_url = _required_env("RABBITMQ_URL")
    return Settings(
        database_url=database_url,
        database_schema=database_schema,
        rabbitmq_url=rabbitmq_url,
        worker_instance_id=os.getenv("WORKER_INSTANCE_ID") or _default_worker_instance_id(),
        worker_actor_id=os.getenv("WORKER_ACTOR_ID", "assessment-worker"),
        consumer_name=os.getenv("ASSESSMENT_CONSUMER_NAME", "assessment-worker"),
        command_prefetch_count=_positive_int("ASSESSMENT_COMMAND_PREFETCH", 1),
        command_retry_limit=_non_negative_int("ASSESSMENT_COMMAND_RETRY_LIMIT", 3),
        command_lease_seconds=_positive_int("ASSESSMENT_COMMAND_LEASE_SECONDS", 1800),
        rabbitmq_retry_delay_milliseconds=_positive_int("RABBITMQ_RETRY_DELAY_MS", 30000),
        outbox_batch_size=_positive_int("OUTBOX_BATCH_SIZE", 25),
        outbox_max_publish_attempts=_positive_int("OUTBOX_MAX_PUBLISH_ATTEMPTS", 10),
        outbox_poll_interval_seconds=_positive_float("OUTBOX_POLL_INTERVAL_SECONDS", 1.0),
        outbox_publish_timeout_seconds=_positive_float("OUTBOX_PUBLISH_TIMEOUT_SECONDS", 15.0),
        shutdown_grace_seconds=_positive_float("SHUTDOWN_GRACE_SECONDS", 30.0),
        azure_blob_connection_string=os.getenv("AZURE_BLOB_CONNECTION_STRING"),
        azure_blob_container_name=os.getenv("AZURE_BLOB_CONTAINER_NAME"),
        azure_openai_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        azure_openai_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
        azure_openai_timeout_seconds=_positive_float("AZURE_OPENAI_TIMEOUT_SECONDS", 30.0),
        azure_openai_api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    )


def _default_worker_instance_id() -> str:
    hostname = socket.gethostname().strip() or "unknown-host"
    return f"assessment-worker-{hostname}-{os.getpid()}-{uuid4().hex[:12]}"


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SettingsError(f"{name} is required and must be non-blank")
    return value


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise SettingsError(f"{name} must be an integer") from exc
    if value < 1:
        raise SettingsError(f"{name} must be greater than zero")
    return value


def _non_negative_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise SettingsError(f"{name} must be an integer") from exc
    if value < 0:
        raise SettingsError(f"{name} must be non-negative")
    return value


def _positive_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise SettingsError(f"{name} must be numeric") from exc
    if value <= 0:
        raise SettingsError(f"{name} must be greater than zero")
    return value


class InherentRiskScoringPolicy(Protocol):
    version: str

    def determine_level(self, score_percentage: float | None) -> RiskLevel | None:
        ...


@dataclass(frozen=True)
class PercentageInherentRiskScoringPolicy:
    version: str = "inherent-risk-v1-percentage"

    def determine_level(self, score_percentage: float | None) -> RiskLevel | None:
        if score_percentage is None:
            return None
        if score_percentage < 25.0:
            return RiskLevel.LOW
        if score_percentage < 50.0:
            return RiskLevel.MEDIUM
        if score_percentage < 75.0:
            return RiskLevel.HIGH
        return RiskLevel.CRITICAL


DEFAULT_INHERENT_RISK_SCORING_POLICY = PercentageInherentRiskScoringPolicy()
