# Architecture

## Current Implemented Scope

The current application surface is the inherent-risk workflow, executive-summary companion, and Document Checklist workflow:

- deterministic analysis-run creation
- inherent-risk read API
- executive-summary generation and persistence
- Document Checklist generation and read API
- document upload metadata, soft delete, and listing
- manual document classification reviews
- checklist reviewer/HITL verdict overrides
- read-only Vendor Reputation certification integration
- checklist AI summary generation

The FastAPI app mounts the v1 routers through [app/api/router.py](/C:/Users/Lenovo/Documents/SAR_INTAKE_AGENT/app/api/router.py). `db.txt` is the schema source of truth for PostgreSQL.

## Layer Responsibilities

- API routes validate request models and delegate to services.
- Repositories load and persist ORM entities without building response DTOs.
- Services own scoring, limitation handling, run creation, document metadata orchestration, checklist generation, and summary orchestration.
- Assemblers convert service read state into API DTOs.
- Repositories and services flush only for Document Checklist write paths; API routes own commit/rollback boundaries.

## High-Level Flow

```text
assessment
  -> assessment_responses
  -> AssessmentRepository.load_active_triage_question_responses()
  -> InherentRiskService
     -> question_analysis_runs
     -> question_risk_results
  -> InherentRiskAssembler
  -> API response
```

Executive-summary generation targets an explicit existing analysis run:

```text
question_analysis_runs + question_risk_results
  -> ExecutiveSummaryService._build_input_payload()
  -> AzureExecutiveSummaryClient
  -> same question_analysis_runs row executive_summary*
```

Document Checklist generation creates an immutable run:

```text
assessment_documents + latest document_classification_reviews
  + latest document_checklist_item_reviews
  + read-only Vendor Reputation HITL certification rows
  -> DocumentChecklistService
     -> document_checklist_runs
     -> exactly three document_checklist_items
     -> AzureExecutiveSummaryClient for checklist summary
  -> DocumentChecklistAssembler
  -> API response
```

Document upload, classification, and reviewer override flows are append-only or soft-delete only:

```text
multipart upload
  -> DocumentService validates filename/content type/size
  -> SHA-256 duplicate active check
  -> test storage abstraction stores bytes outside PostgreSQL
  -> assessment_documents metadata row

classification review
  -> active assessment_documents ownership check
  -> append document_classification_reviews row

checklist item review
  -> document_checklist_items ownership check through run.assessment_id
  -> append document_checklist_item_reviews row
```

## Triage Question Selection

`AssessmentRepository.load_active_triage_question_responses()` loads only the latest active triage questionnaire version and excludes questions that should not participate in scoring:

- `question_definitions.is_visible = true`
- `question_definitions.response_type in ('single_select', 'multi_select')`
- `assessment_responses.response_status = 'answered'`

Questions that are hidden, non-scoreable, unanswered, or unresolved against configured options never become `question_risk_results`.

## JSONB Answer Resolution

`assessment_responses.answer_value` is treated as JSONB in PostgreSQL and is parsed by `AssessmentRepository._extract_candidate_values()` in this order:

- raw string value
- object keys `optionCode`, `option_code`, `selectedResponse`, `optionLabel`, `option_label`, `value`
- list values containing strings

Option matching is `option_code` first and `option_label` second. If no configured `question_options` row can be resolved, the response is recorded as a limitation and excluded from scoring output.

## Deterministic Scoring Flow

The inherent-risk service never calls an LLM. It creates question results directly from configured triage options:

- `risk_weight`, `risk_band`, `why_it_matters`, and `risk_signal` come from `question_options`
- `risk_domain`, `question_text`, and `is_required` come from `question_definitions`
- `scoring_rule_version` is `inherent-risk-v1-percentage`

Per run:

- `triage_score = sum(selected option risk_weight)`
- `inherent_score = sum(selected risk_weight) / sum(max risk_weight per resolved question) * 100`
- score bands map to `low`, `medium`, `high`, `critical`
- no resolved questions returns `not_assessed`

Run status is:

- `completed` when all required scorable triage questions are resolved
- `completed_with_limitations` when required questions are unanswered, responses cannot be resolved, or no resolved triage responses exist
- `failed` only when persistence fails

`question_definitions.is_required` is implemented and is the field used for missing-response limitation detection.

## Persistence Model

Each successful deterministic run persists:

- one `question_analysis_runs` row
- zero or more `question_risk_results` rows, one per resolved answered triage response

`question_risk_results.input_snapshot` is the canonical persisted payload for question-level reconstruction. It includes:

- question identifiers and text
- selected option identifiers, code, and label
- selected response text
- `riskWeight` and `maxRiskWeight`
- `whyItMatters`, `riskSignal`, `riskBand`
- `scoringRuleVersion`

`AnalysisRepository.get_latest_completed_snapshot()` rebuilds `ComputedQuestionRisk` objects from `question_risk_results` plus `input_snapshot`, so the stored snapshot remains the source for downstream reads.

## Executive Summary Flow

`POST /api/v1/assessments/{assessment_id}/analysis-runs/{analysis_run_id}/executive-summary` targets a specific existing run. The service loads `question_analysis_runs` by both `assessment_id` and `id`.

The summary flow:

- accepts UUID path parameters `assessment_id` and `analysis_run_id`
- returns `404` when the assessment/run pair does not match a stored run
- returns `409` when the targeted run status is `queued`, `running`, or `failed`
- allows only `completed` and `completed_with_limitations`
- builds a deterministic input payload from assessment context, inherent-risk level, high-risk count, top risk drivers, material questions, and material limitations
- hashes that payload and reuses the stored summary when the hash matches and `force = false`
- loads the YAML prompt from `app/prompts/executive_summary.yaml`
- reuses the existing summary generation flow and calls Azure OpenAI only to explain the deterministic result
- stores summary text and summary metadata on the same `question_analysis_runs` row using `executive_summary`, `executive_summary_generated_at`, `executive_summary_model`, `executive_summary_prompt_version`, and `executive_summary_input_hash`
- does not create a new analysis run
- does not recalculate scores
- does not modify responses
- does not modify `question_risk_results`

If Azure OpenAI times out, fails, or returns invalid structured output, the service persists a fallback summary, marks the summary status as `fallback`, and keeps the run in `completed_with_limitations`.

## Document Checklist Flow

`POST /api/v1/assessments/{assessment_id}/document-checklist/runs` creates a new checklist run every time. The run is immutable once created.

Generation sequence:

- load active `assessment_documents` for the assessment
- exclude rows with `deleted_at`
- resolve effective document type from the latest manual `document_classification_reviews` row, falling back to `assessment_documents.system_document_type`
- load the latest checklist reviewer decision from `document_checklist_item_reviews`
- read the latest eligible Vendor Reputation HITL certification row for the assessment
- create exactly three ordered checklist items:
  - SOC 2 Type II
  - ISO 27001
  - Architecture Diagram
- calculate deterministic `base_verdict`
- calculate effective verdict from the latest checklist reviewer verdict when present, otherwise `base_verdict`
- persist the run input snapshot with detected file status, document ids, verdicts, reviewer context, Vendor Reputation automatic/analyst/effective certification status, and limitations
- call the existing Azure summary client once using `app/prompts/document_checklist_summary.yaml`
- store summary fields on `document_checklist_runs`

The deterministic portion owns file detection, base verdicts, effective HITL verdicts, and immutable item creation. The AI portion only writes `summary_text`, `summary_status`, `summary_model`, `summary_prompt_version`, `summary_input_hash`, `summary_generated_at`, and `error_summary`. AI output never changes checklist verdicts.

If checklist summary generation fails, the service preserves the run and items, sets `summary_status = failed`, stores a concise `error_summary`, and lets the API commit the run.

## Document Upload Flow

`POST /api/v1/assessments/{assessment_id}/documents` accepts multipart upload metadata and file bytes. The current implementation calculates SHA-256 and stores document metadata in `assessment_documents`; it does not store bytes in PostgreSQL. Until Azure Blob Storage is implemented, bytes are written through a checklist-specific test storage interface.

Upload rules:

- filename, content type, and size are validated
- duplicate active content for the same assessment and SHA-256 is rejected
- `system_document_type` may be SOC 2 Type II, ISO 27001, Architecture Diagram, or Unclassified
- uploaded files affect checklist detection only after a new checklist run is generated
- existing checklist runs are not rewritten

`GET /api/v1/assessments/{assessment_id}/documents` returns active documents only. `DELETE /api/v1/assessments/{assessment_id}/documents/{document_id}` soft deletes the row by setting `deleted_at` and `deleted_by`.

## Manual Classification Flow

`POST /api/v1/assessments/{assessment_id}/documents/{document_id}/classification-reviews` appends a manual classification review for an active document that belongs to the assessment.

Allowed manual document types are:

- SOC 2 Type II
- ISO 27001
- Architecture Diagram

The latest review by `created_at`, then `id`, becomes the effective classification for future checklist generation. Prior reviews remain unchanged, soft-deleted documents are rejected, and existing checklist runs are not regenerated.

## Reviewer Override Flow

`POST /api/v1/assessments/{assessment_id}/document-checklist/items/{item_id}/reviews` appends a checklist item reviewer/HITL verdict.

Rules:

- the checklist item must belong to the assessment
- non-null reviewer verdict requires a reason
- null reviewer verdict clears the override and falls back to `base_verdict`
- previous reviews are never updated or deleted
- file detection remains based only on uploaded active documents captured in the run snapshot

GET and review responses resolve the item effective verdict from the latest review. A null latest review returns the item base verdict.

## Vendor Reputation Integration

Document Checklist reads Vendor Reputation data through [app/repositories/vendor_certification_repository.py](/C:/Users/Lenovo/Documents/SAR_INTAKE_AGENT/app/repositories/vendor_certification_repository.py). It maps only the existing Vendor Reputation tables needed for read access:

- `vendor_reputation_jobs`
- `vendor_reputation_hitl_reviews`

The repository is read-only. Analyst/HITL certification status overrides automatic certification status. Vendor Reputation can influence deterministic base verdicts for SOC 2 and ISO 27001 and is stored in the checklist run input snapshot, but it never marks a document as uploaded.

## Transaction Boundaries

For Document Checklist write operations:

- repositories call `flush()` and do not commit
- services call repositories and do not commit
- API routes commit once after successful service completion
- API routes roll back on handled errors

Checklist generation intentionally creates the run, items, and summary metadata in one API-owned transaction. If summary generation fails, the failed summary status is persisted in the same transaction as the run and items.

## Runtime and Schema Dependency

The maintained database contract is PostgreSQL schema `kpmg_sar` aligned to [db.txt](/C:/Users/Lenovo/Documents/SAR_INTAKE_AGENT/db.txt).

Known dependency:

- [migrations/20260721_add_question_analysis_run_executive_summary_metadata.py](/C:/Users/Lenovo/Documents/SAR_INTAKE_AGENT/migrations/20260721_add_question_analysis_run_executive_summary_metadata.py) only adds executive-summary metadata columns to `question_analysis_runs`
- it assumes the base table already exists
- it does not create the full schema from `db.txt`
- the executive-summary route change itself required no new migration
- Document Checklist uses the already-applied schema in `db.txt`; no checklist migrations are generated by the application

## Limitations and Future Enhancements

Implemented limitations:

- the document upload endpoint does not provide download
- Azure Blob Storage SDK integration is not implemented
- document classification is manual only
- checklist generation is deterministic except for the optional AI summary paragraph
- checklist runs are regenerated only by explicit API call
- Vendor Reputation is read-only from the checklist feature
