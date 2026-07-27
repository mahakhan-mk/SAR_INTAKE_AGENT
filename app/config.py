from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from dotenv import load_dotenv

from app.models.enums import RiskLevel

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"

DATABASE_SCHEMA_ENV_VAR = "DATABASE_SCHEMA"
DATABASE_SCHEMA_TOKEN = "configured_database_schema"


@dataclass(frozen=True)
class Settings:
    database_url: str
    database_schema: str | None
    azure_openai_endpoint: str | None
    azure_openai_api_key: str | None
    azure_openai_deployment: str | None
    azure_openai_timeout_seconds: float
    azure_openai_api_version: str | None


def get_settings() -> Settings:
    load_dotenv(dotenv_path=ENV_FILE, override=False)
    return Settings(
        database_url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./sar_assessment.db"),
        database_schema=os.getenv(DATABASE_SCHEMA_ENV_VAR),
        azure_openai_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        azure_openai_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
        azure_openai_timeout_seconds=float(os.getenv("AZURE_OPENAI_TIMEOUT_SECONDS", "30")),
        azure_openai_api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    )


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
