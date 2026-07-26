# Database Mapping

`db.txt` is the authoritative PostgreSQL schema reference for this repository. The SQLAlchemy models in [app/models/database.py](/C:/Users/Lenovo/Documents/SAR_INTAKE_AGENT/app/models/database.py) mirror the runtime tables used by the inherent-risk and Document Checklist workflows.

## ORM Alignment

| PostgreSQL table | ORM model | Current usage |
| --- | --- | --- |
| `kpmg_sar.sar_assessments` | `SarAssessment` | assessment existence and display context |
| `kpmg_sar.questionnaire_versions` | `QuestionnaireVersion` | latest active triage version lookup |
| `kpmg_sar.question_definitions` | `QuestionDefinition` | triage question metadata, visibility, required flag, response type, domain |
| `kpmg_sar.question_options` | `QuestionOption` | option code, label, risk weight, risk band, why-it-matters, risk signal |
| `kpmg_sar.assessment_responses` | `AssessmentResponse` | stored JSONB answers and response status |
| `kpmg_sar.assessment_documents` | `AssessmentDocument` | uploaded document metadata and soft delete state |
| `kpmg_sar.document_classification_reviews` | `DocumentClassificationReview` | manual document classification history |
| `kpmg_sar.document_checklist_runs` | `DocumentChecklistRun` | immutable checklist run, input snapshot, and AI summary metadata |
| `kpmg_sar.document_checklist_items` | `DocumentChecklistItem` | exactly three ordered deterministic checklist items per run |
| `kpmg_sar.document_checklist_item_reviews` | `DocumentChecklistItemReview` | checklist item reviewer/HITL override history |
| `kpmg_sar.question_analysis_runs` | `QuestionAnalysisRun` | overall deterministic scoring and executive-summary persistence |
| `kpmg_sar.question_risk_results` | `QuestionRiskResult` | per-question persisted scoring output and input snapshot |
| `kpmg_sar.vendor_reputation_jobs` | Core `Table` in `vendor_certification_repository.py` | read-only latest eligible Vendor Reputation job lookup |
| `kpmg_sar.vendor_reputation_hitl_reviews` | Core `Table` in `vendor_certification_repository.py` | read-only certification automatic/reviewer status lookup |

## Column Notes

- `QuestionAnalysisRun.executive_summary_text` maps to the physical column `question_analysis_runs.executive_summary`.
- `AssessmentDocument.document_metadata` maps to the physical column `assessment_documents.metadata`.
- `answer_value` and `input_snapshot` use `JSONB` on PostgreSQL through `JSONB_TYPE`.
- UUID columns use `UUIDType`, which preserves native PostgreSQL UUID behavior while keeping local compatibility paths available in SQLAlchemy.
- `assessment_documents.deleted_at` is the soft-delete marker. Active document queries always exclude rows where `deleted_at` is set.
- `uq_assessment_documents_active_hash` enforces one active document per assessment and SHA-256.
- `document_checklist_items` has one unique item order and one unique document type per run.

## Repository-to-Table Mapping

### AssessmentRepository

[app/repositories/assessment_repository.py](/C:/Users/Lenovo/Documents/SAR_INTAKE_AGENT/app/repositories/assessment_repository.py) reads the deterministic scoring inputs:

- `sar_assessments`
  - `id`
- `questionnaire_versions`
  - `questionnaire_type`
  - `status`
  - `created_at`
- `question_definitions`
  - `questionnaire_version_id`
  - `question_code`
  - `question_text`
  - `response_type`
  - `is_required`
  - `risk_domain`
  - `is_visible`
  - `question_order`
- `assessment_responses`
  - `assessment_id`
  - `question_id`
  - `answer_value`
  - `response_status`
  - `created_at`
- `question_options`
  - `question_id`
  - `option_code`
  - `option_label`
  - `risk_weight`
  - `risk_band`
  - `why_it_matters`
  - `risk_signal`
  - `display_order`

Selection rules:

- only the latest active triage questionnaire version is used
- only visible scorable questions are loaded
- only `single_select` and `multi_select` questions participate
- only `answered` responses participate
- option matching is `option_code` first, then `option_label`

### AnalysisRepository

[app/repositories/analysis_repository.py](/C:/Users/Lenovo/Documents/SAR_INTAKE_AGENT/app/repositories/analysis_repository.py) owns run and result persistence:

- `question_analysis_runs`
  - `assessment_id`
  - `status`
  - `scoring_rule_version`
  - `intake_score`
  - `triage_score`
  - `inherent_score`
  - `inherent_risk_level`
  - `executive_summary`
  - `executive_summary_model`
  - `executive_summary_prompt_version`
  - `executive_summary_input_hash`
  - `executive_summary_generated_at`
  - `error_summary`
  - `started_at`
  - `completed_at`
  - `created_at`
- `question_risk_results`
  - `analysis_run_id`
  - `response_id`
  - `risk_domain`
  - `risk_score`
  - `risk_level`
  - `risk_impact`
  - `risk_signal`
  - `explanation`
  - `confidence`
  - `input_snapshot`
  - `created_at`

`get_latest_completed_snapshot()` rebuilds question-level results from the stored `question_risk_results` rows and their `input_snapshot` payloads. The read path does not recalculate `why_it_matters`, `risk_signal`, selected option label, or risk weights from live questionnaire tables.

### DocumentRepository

[app/repositories/document_repository.py](/C:/Users/Lenovo/Documents/SAR_INTAKE_AGENT/app/repositories/document_repository.py) owns uploaded document metadata and manual classification reviews:

- `sar_assessments`
  - `id`
- `assessment_documents`
  - `assessment_id`
  - `original_filename`
  - `content_type`
  - `file_size_bytes`
  - `sha256`
  - `storage_container`
  - `storage_key`
  - `upload_source`
  - `system_document_type`
  - `uploaded_by`
  - `created_at`
  - `deleted_at`
  - `deleted_by`
  - `metadata`
- `document_classification_reviews`
  - `document_id`
  - `document_type`
  - `reason`
  - `reviewed_by`
  - `created_at`

Selection rules:

- active document reads require matching `assessment_id` and `deleted_at IS NULL`
- duplicate active uploads are rejected by checking `assessment_id` and `sha256`
- manual classification reads use latest review by `created_at DESC, id DESC`
- effective classification is latest manual review document type, otherwise `assessment_documents.system_document_type`

Allowed stored system document types are:

- SOC 2 Type II
- ISO 27001
- Architecture Diagram
- Unclassified

Allowed manual classification review types are:

- SOC 2 Type II
- ISO 27001
- Architecture Diagram

### DocumentChecklistRepository

[app/repositories/document_checklist_repository.py](/C:/Users/Lenovo/Documents/SAR_INTAKE_AGENT/app/repositories/document_checklist_repository.py) owns checklist run, item, and reviewer override persistence:

- `document_checklist_runs`
  - `assessment_id`
  - `status`
  - `summary_text`
  - `summary_status`
  - `summary_model`
  - `summary_prompt_version`
  - `summary_input_hash`
  - `summary_generated_at`
  - `input_snapshot`
  - `limitations`
  - `error_summary`
  - `created_at`
- `document_checklist_items`
  - `checklist_run_id`
  - `document_type`
  - `base_verdict`
  - `item_order`
  - `created_at`
- `document_checklist_item_reviews`
  - `assessment_id`
  - `source_item_id`
  - `document_type`
  - `reviewer_verdict`
  - `reason`
  - `reviewed_by`
  - `created_at`

Checklist run rules:

- every generated run has exactly three items
- item order is always 1, 2, 3
- item types are SOC 2 Type II, ISO 27001, and Architecture Diagram
- base verdict values are `Required`, `Recommended`, or `N/A`
- reviewer verdict values are `Required`, `Recommended`, `N/A`, or null
- repositories flush only and do not commit

Latest reviewer resolution:

- latest review is selected by `created_at DESC, id DESC`
- non-null reviewer verdict overrides the base verdict
- null reviewer verdict clears the override and falls back to the base verdict

### VendorCertificationRepository

[app/repositories/vendor_certification_repository.py](/C:/Users/Lenovo/Documents/SAR_INTAKE_AGENT/app/repositories/vendor_certification_repository.py) uses SQLAlchemy Core table mappings for read-only Vendor Reputation access:

- `vendor_reputation_jobs`
  - `id`
  - `assessment_id`
  - `status`
  - `created_at`
- `vendor_reputation_hitl_reviews`
  - `id`
  - `job_id`
  - `soc2_auto_status`
  - `soc2_reviewer_status`
  - `iso27001_auto_status`
  - `iso27001_reviewer_status`
  - `created_at`

Eligible jobs are the latest rows with status:

- `awaiting_hitl_review`
- `review_submitted`
- `completed`
- `completed_with_limitations`

Reviewer certification status overrides automatic certification status. This repository does not write Vendor Reputation data.

## JSONB Answer Parsing

`assessment_responses.answer_value` is parsed as follows:

- string: use the value directly
- object: inspect `optionCode`, `option_code`, `selectedResponse`, `optionLabel`, `option_label`, `value`
- list: keep non-empty strings

The repository de-duplicates candidate values, then matches configured options in two passes:

1. `question_options.option_code`
2. `question_options.option_label`

Responses that still cannot be resolved, or that resolve to options missing `risk_weight` or `risk_band`, are excluded from `question_risk_results` and cause the run to be marked with limitations.

## question_risk_results Snapshot Contract

Each persisted `input_snapshot` currently contains:

- `questionCode`
- `questionId`
- `questionText`
- `selectedOptionId`
- `selectedOptionCode`
- `selectedOptionLabel`
- `selectedResponse`
- `riskWeight`
- `maxRiskWeight`
- `whyItMatters`
- `riskSignal`
- `riskBand`
- `scoringRuleVersion`

This snapshot is the persistence contract that supports later inherent-risk reads and executive-summary input assembly without re-resolving the original `answer_value`.

## document_checklist_runs Snapshot Contract

Each generated checklist run stores `input_snapshot` for immutable reads and summary generation. The snapshot contains:

- `assessmentId`
- `vendorCertificationHitlReviewId`
- `items`
  - `itemOrder`
  - `documentType`
  - `detectedFile`
  - `detectedDocumentIds`
  - `baseVerdict`
  - `reviewerVerdict`
  - `effectiveVerdict`
  - `latestReviewId`
  - `certification`
    - `automaticStatus`
    - `analystStatus`
    - `effectiveStatus`

GET checklist reads use the stored snapshot for detected file status and Vendor Reputation details. They do not query Vendor Reputation and do not regenerate a checklist.

## Migration Dependency

[migrations/20260721_add_question_analysis_run_executive_summary_metadata.py](/C:/Users/Lenovo/Documents/SAR_INTAKE_AGENT/migrations/20260721_add_question_analysis_run_executive_summary_metadata.py) adds:

- `executive_summary_model`
- `executive_summary_prompt_version`
- `executive_summary_input_hash`
- `executive_summary_generated_at`

It assumes `question_analysis_runs` already exists in the target PostgreSQL schema. Apply the base schema from `db.txt` before running the migration.

Document Checklist tables and Vendor Reputation read tables are expected to exist from the applied `db.txt` schema. The Document Checklist implementation does not add migrations.
