from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.config import DATABASE_SCHEMA_TOKEN
from app.database import create_engine_from_url
from app.models.database import Base, DocumentChecklistRun, SarAssessment
from app.repositories.vendor_certification_repository import vendor_reputation_jobs


def _render_sql(statement, schema_translate_map: dict[str, str | None]) -> str:
    compiled = statement.compile(
        dialect=postgresql.dialect(),
        schema_translate_map=schema_translate_map,
        compile_kwargs={"render_schema_translate": True},
    )
    return compiled.preparer._render_schema_translates(compiled.string, compiled.schema_translate_map)


def test_all_metadata_tables_share_the_configured_schema_token():
    assert {table.schema for table in Base.metadata.tables.values()} == {DATABASE_SCHEMA_TOKEN}


def test_compiled_sql_uses_database_schema_for_all_table_paths():
    engine = create_engine_from_url("postgresql://user:password@host:5432/database", "tenant_runtime_schema")
    schema_translate_map = engine.sync_engine.get_execution_options()["schema_translate_map"]

    sar_assessment_sql = _render_sql(select(SarAssessment), schema_translate_map)
    checklist_run_sql = _render_sql(select(DocumentChecklistRun), schema_translate_map)
    vendor_job_sql = _render_sql(select(vendor_reputation_jobs), schema_translate_map)

    assert "tenant_runtime_schema.sar_assessments" in sar_assessment_sql
    assert "tenant_runtime_schema.document_checklist_runs" in checklist_run_sql
    assert "tenant_runtime_schema.vendor_reputation_jobs" in vendor_job_sql
    assert DATABASE_SCHEMA_TOKEN not in sar_assessment_sql
    assert DATABASE_SCHEMA_TOKEN not in checklist_run_sql
    assert DATABASE_SCHEMA_TOKEN not in vendor_job_sql
    assert "kpmg_sar" not in sar_assessment_sql
    assert "kpmg_sar" not in checklist_run_sql
    assert "kpmg_sar" not in vendor_job_sql
