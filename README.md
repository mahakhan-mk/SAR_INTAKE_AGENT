# SAR Assessment Service

## Current Scope

The current FastAPI application exposes the inherent-risk workflow for SAR assessments:

- `GET /api/v1/assessments/{assessment_id}/inherent-risk`
- `POST /api/v1/assessments/{assessment_id}/analysis-runs`
- `POST /api/v1/assessments/{assessment_id}/inherent-risk/executive-summary`

`db.txt` is the schema source of truth. The maintained runtime target is PostgreSQL schema `kpmg_sar`.

## Runtime Prerequisites

- Python `3.12`
- PostgreSQL with tables and constraints aligned to [db.txt](/C:/Users/Lenovo/Documents/SAR_INTAKE_AGENT/db.txt)
- Environment variables:
  - `DATABASE_URL`
  - `DATABASE_SCHEMA` (defaults to `kpmg_sar`)
  - `AZURE_OPENAI_ENDPOINT`
  - `AZURE_OPENAI_API_KEY`
  - `AZURE_OPENAI_DEPLOYMENT`
  - `AZURE_OPENAI_API_VERSION`
  - `AZURE_OPENAI_TIMEOUT_SECONDS` (optional, defaults to `30`)

The executive-summary flow also depends on the metadata columns added by [migrations/20260721_add_question_analysis_run_executive_summary_metadata.py](/C:/Users/Lenovo/Documents/SAR_INTAKE_AGENT/migrations/20260721_add_question_analysis_run_executive_summary_metadata.py). Apply the base PostgreSQL schema from `db.txt` first, then run that migration for databases created before July 21, 2026.

`app.database.init_db()` creates mapped tables, but it is not the authoritative schema-management path for PostgreSQL because `db.txt` includes the canonical schema, constraints, and trigger definitions.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Set the required environment variables in `.env`, then start the API:

```powershell
uvicorn app.main:app --reload
```

## Testing

Run the automated test suite with:

```powershell
pytest
```

The current tests cover:

- inherent-risk API responses
- deterministic analysis-run scoring and persistence
- executive-summary generation, caching, and fallback behavior
