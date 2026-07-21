from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from app.models.enums import RiskLevel

DATABASE_SCHEMA_TOKEN = "configured_database_schema"


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./sar_assessment.db")
    database_schema: str = os.getenv("DATABASE_SCHEMA", "kpmg_sar")
    azure_openai_endpoint: str | None = os.getenv("AZURE_OPENAI_ENDPOINT")
    azure_openai_api_key: str | None = os.getenv("AZURE_OPENAI_API_KEY")
    azure_openai_deployment: str | None = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    azure_openai_timeout_seconds: float = float(os.getenv("AZURE_OPENAI_TIMEOUT_SECONDS", "30"))
    azure_openai_api_version: str | None = os.getenv("AZURE_OPENAI_API_VERSION")


def get_settings() -> Settings:
    return Settings()


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
