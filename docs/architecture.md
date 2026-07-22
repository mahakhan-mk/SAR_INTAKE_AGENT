# Architecture

## Current Implemented Scope

The current application surface is the inherent-risk workflow and its executive-summary companion:

- deterministic analysis-run creation
- inherent-risk read API
- executive-summary generation and persistence

The FastAPI app currently mounts only [app/api/v1/inherent_risk.py](/C:/Users/Lenovo/Documents/SAR_INTAKE_AGENT/app/api/v1/inherent_risk.py). `db.txt` is the schema source of truth for PostgreSQL.

## Layer Responsibilities

- API routes validate request models and delegate to services.
- Repositories load and persist ORM entities without building response DTOs.
- Services own scoring, limitation handling, run creation, and executive-summary orchestration.
- The assembler converts `InherentRiskScreenState` into the API DTO.

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

## Runtime and Schema Dependency

The maintained database contract is PostgreSQL schema `kpmg_sar` aligned to [db.txt](/C:/Users/Lenovo/Documents/SAR_INTAKE_AGENT/db.txt).

Known dependency:

- [migrations/20260721_add_question_analysis_run_executive_summary_metadata.py](/C:/Users/Lenovo/Documents/SAR_INTAKE_AGENT/migrations/20260721_add_question_analysis_run_executive_summary_metadata.py) only adds executive-summary metadata columns to `question_analysis_runs`
- it assumes the base table already exists
- it does not create the full schema from `db.txt`
- the executive-summary route change itself required no new migration
