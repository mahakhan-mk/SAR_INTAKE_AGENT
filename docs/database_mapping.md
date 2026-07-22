# Database Mapping

`db.txt` is the authoritative PostgreSQL schema reference for this repository. The SQLAlchemy models in [app/models/database.py](/C:/Users/Lenovo/Documents/SAR_INTAKE_AGENT/app/models/database.py) mirror the runtime tables used by the inherent-risk workflow.

## ORM Alignment

| PostgreSQL table | ORM model | Current usage |
| --- | --- | --- |
| `kpmg_sar.sar_assessments` | `SarAssessment` | assessment existence and display context |
| `kpmg_sar.questionnaire_versions` | `QuestionnaireVersion` | latest active triage version lookup |
| `kpmg_sar.question_definitions` | `QuestionDefinition` | triage question metadata, visibility, required flag, response type, domain |
| `kpmg_sar.question_options` | `QuestionOption` | option code, label, risk weight, risk band, why-it-matters, risk signal |
| `kpmg_sar.assessment_responses` | `AssessmentResponse` | stored JSONB answers and response status |
| `kpmg_sar.question_analysis_runs` | `QuestionAnalysisRun` | overall deterministic scoring and executive-summary persistence |
| `kpmg_sar.question_risk_results` | `QuestionRiskResult` | per-question persisted scoring output and input snapshot |

## Column Notes

- `QuestionAnalysisRun.executive_summary_text` maps to the physical column `question_analysis_runs.executive_summary`.
- `answer_value` and `input_snapshot` use `JSONB` on PostgreSQL through `JSONB_TYPE`.
- UUID columns use `UUIDType`, which preserves native PostgreSQL UUID behavior while keeping local compatibility paths available in SQLAlchemy.

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

## Migration Dependency

[migrations/20260721_add_question_analysis_run_executive_summary_metadata.py](/C:/Users/Lenovo/Documents/SAR_INTAKE_AGENT/migrations/20260721_add_question_analysis_run_executive_summary_metadata.py) adds:

- `executive_summary_model`
- `executive_summary_prompt_version`
- `executive_summary_input_hash`
- `executive_summary_generated_at`

It assumes `question_analysis_runs` already exists in the target PostgreSQL schema. Apply the base schema from `db.txt` before running the migration.
