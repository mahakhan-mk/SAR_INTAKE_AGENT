# SAR Assessment Service

## Current Scope

The current FastAPI application exposes the inherent-risk workflow for SAR assessments:

- `GET /api/v1/assessments/{assessment_id}/inherent-risk`
- `POST /api/v1/assessments/{assessment_id}/analysis-runs`
- `POST /api/v1/assessments/{assessment_id}/analysis-runs/{analysis_run_id}/executive-summary`

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

This executive-summary API change did not require a new database migration. It uses the existing `question_analysis_runs` columns `executive_summary`, `executive_summary_generated_at`, `executive_summary_model`, `executive_summary_prompt_version`, and `executive_summary_input_hash`. For databases created before July 21, 2026, apply [migrations/20260721_add_question_analysis_run_executive_summary_metadata.py](/C:/Users/Lenovo/Documents/SAR_INTAKE_AGENT/migrations/20260721_add_question_analysis_run_executive_summary_metadata.py) after the base PostgreSQL schema from `db.txt`.

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
