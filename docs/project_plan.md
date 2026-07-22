## Current Implementation Snapshot

The codebase currently implements the inherent-risk and executive-summary workflow around shared analysis-run persistence.

Implemented files:

- `app/api/v1/inherent_risk.py`
- `app/services/inherent_risk_service.py`
- `app/services/executive_summary_service.py`
- `app/repositories/assessment_repository.py`
- `app/repositories/analysis_repository.py`
- `app/assemblers/inherent_risk_assembler.py`
- `app/models/database.py`
- `app/models/dto.py`
- `app/models/enums.py`
- focused API and service tests

Implemented endpoints:

- `GET /api/v1/assessments/{assessment_id}/inherent-risk`
- `POST /api/v1/assessments/{assessment_id}/analysis-runs`
- `POST /api/v1/assessments/{assessment_id}/inherent-risk/executive-summary`

Implemented scoring rule:

- scoring rule version: `inherent-risk-v1-percentage`
- `total_score = sum(selected option risk_weight)`
- `max_score = sum(max option risk_weight for each resolved answered triage question)`
- `score_percentage = total_score / max_score * 100`
- overall mapping:
  - `low`: `0 <= percentage < 25`
  - `medium`: `25 <= percentage < 50`
  - `high`: `50 <= percentage < 75`
  - `critical`: `75 <= percentage <= 100`

Current schema notes:

- `db.txt` is the PostgreSQL source of truth.
- `risk_domain` comes from `question_definitions`.
- `is_required` is implemented on `question_definitions` and is used for limitation detection.
- hidden questions and non-scoreable response types are excluded before scoring.
- `question_risk_results.input_snapshot` is the persistence contract for downstream reads and executive-summary generation.
