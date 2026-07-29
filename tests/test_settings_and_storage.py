from __future__ import annotations

import os
from uuid import uuid4

import pytest

from app.config import SettingsError, get_settings
from app.services.initial_sar_report_storage import build_initial_sar_report_storage_key


def test_settings_require_database_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.delenv("DATABASE_SCHEMA", raising=False)
    monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")
    monkeypatch.setattr("app.config.load_dotenv", lambda *args, **kwargs: None)
    with pytest.raises(SettingsError):
        get_settings()


def test_report_storage_key_is_assessment_scoped() -> None:
    assessment_id = uuid4()
    report_id = uuid4()
    key = build_initial_sar_report_storage_key(
        assessment_id=assessment_id,
        report_id=report_id,
        filename="Initial SAR Report.docx",
    )
    assert key.startswith(f"assessments/{assessment_id}/reports/{report_id}/")
    assert "local-dev" not in key
