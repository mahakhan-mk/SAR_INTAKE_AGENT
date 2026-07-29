from __future__ import annotations

from app.config import DATABASE_SCHEMA_TOKEN
from app.models.database import Base, InitialSarReport, OutboxMessage, WorkflowTask


def test_report_table_uses_explicit_singular_override() -> None:
    assert InitialSarReport.__tablename__ == "initial_sar_report"
    table_names = {table.name for table in Base.metadata.tables.values()}
    assert "assessment_reports" not in table_names
    assert "initial_sar_reports" not in table_names


def test_platform_models_use_schema_token_and_required_constraints() -> None:
    assert InitialSarReport.__table__.schema == DATABASE_SCHEMA_TOKEN
    assert WorkflowTask.__table__.schema == DATABASE_SCHEMA_TOKEN
    assert OutboxMessage.__table__.schema == DATABASE_SCHEMA_TOKEN
    workflow_constraint_names = {
        constraint.name for constraint in WorkflowTask.__table__.constraints
    }
    outbox_constraint_names = {
        constraint.name for constraint in OutboxMessage.__table__.constraints
    }
    assert "workflow_tasks_lease_pair_check" in workflow_constraint_names
    assert "workflow_tasks_running_lease_check" in workflow_constraint_names
    assert "outbox_messages_status_check" in outbox_constraint_names
