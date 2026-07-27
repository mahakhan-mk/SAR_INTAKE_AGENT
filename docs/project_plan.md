## Current Implementation Snapshot

The codebase currently implements the inherent-risk workflow, executive-summary workflow, and Document Checklist workflow around shared assessment persistence.

Implemented files:

- `app/api/v1/inherent_risk.py`
- `app/api/v1/document_checklist.py`
- `app/api/v1/documents.py`
- `app/services/inherent_risk_service.py`
- `app/services/executive_summary_service.py`
- `app/services/document_checklist_service.py`
- `app/services/document_service.py`
- `app/services/document_storage.py`
- `app/repositories/assessment_repository.py`
- `app/repositories/analysis_repository.py`
- `app/repositories/document_repository.py`
- `app/repositories/document_checklist_repository.py`
- `app/repositories/vendor_certification_repository.py`
- `app/assemblers/inherent_risk_assembler.py`
- `app/assemblers/document_checklist_assembler.py`
- `app/models/database.py`
- `app/models/document_checklist.py`
- `app/models/dto.py`
- `app/models/enums.py`
- focused API and service tests

Implemented endpoints:

- `GET /api/v1/assessments/{assessment_id}/inherent-risk`
- `POST /api/v1/assessments/{assessment_id}/analysis-runs`
- `POST /api/v1/assessments/{assessment_id}/analysis-runs/{analysis_run_id}/executive-summary`
- `POST /api/v1/assessments/{assessment_id}/document-checklist/runs`
- `GET /api/v1/assessments/{assessment_id}/document-checklist`
- `POST /api/v1/assessments/{assessment_id}/document-checklist/items/{item_id}/reviews`
- `POST /api/v1/assessments/{assessment_id}/documents`
- `GET /api/v1/assessments/{assessment_id}/documents`
- `DELETE /api/v1/assessments/{assessment_id}/documents/{document_id}`
- `POST /api/v1/assessments/{assessment_id}/documents/{document_id}/classification-reviews`

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
- Document Checklist uses `assessment_documents`, `document_classification_reviews`, `document_checklist_runs`, `document_checklist_items`, and `document_checklist_item_reviews`.
- Checklist generation always creates one immutable run with exactly three ordered items: SOC 2 Type II, ISO 27001, and Architecture Diagram.
- Document uploads persist metadata and SHA-256 only; file bytes are stored through the checklist-specific test storage abstraction until Blob Storage is implemented.
- Vendor Reputation HITL certification data is read-only and can affect checklist verdicts without marking files as uploaded.
- Checklist AI summary generation uses `app/prompts/document_checklist_summary.yaml`; failures preserve the run and items and store failed summary metadata.
