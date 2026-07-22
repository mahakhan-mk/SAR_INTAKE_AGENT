# API Contracts

Verified against the registered FastAPI app on July 22, 2026 by importing `app.main` and enumerating `APIRoute` instances.

## Registered Routes

The current app registers exactly these six API endpoints:

| Method | Path | Route function | Response DTO |
| --- | --- | --- | --- |
| `GET` | `/api/v1/assessments/{assessment_id}/intake` | `app.api.v1.intake.get_intake_overview` | `IntakeOverviewResponseDTO` |
| `PATCH` | `/api/v1/assessments/{assessment_id}/questions/{question_id}` | `app.api.v1.intake.update_question_response` | `IntakeQuestionUpdateResponseDTO` |
| `GET` | `/api/v1/assessments/{assessment_id}/inherent-risk` | `app.api.v1.inherent_risk.get_inherent_risk` | `InherentRiskResponseDTO` |
| `POST` | `/api/v1/assessments/{assessment_id}/analysis-runs` | `app.api.v1.inherent_risk.create_analysis_run` | `AnalysisRunCreateResponseDTO` |
| `POST` | `/api/v1/assessments/{assessment_id}/inherent-risk/executive-summary` | `app.api.v1.inherent_risk.generate_executive_summary` | `ExecutiveSummaryGenerateResponseDTO` |
| `GET` | `/api/v1/assessments/{assessment_id}/ai-analysis` | `app.api.v1.ai_analysis.get_ai_analysis` | `AIAnalysisResponseDTO` |

## Before Adding A New Endpoint

1. Search existing routes.
2. Inspect service methods.
3. Inspect DTOs.
4. Inspect repository methods.
5. Inspect tests.
6. Extend existing code instead of duplicating it.

## Route To Service To Repository Matrix

| Method | Path | Service method called | Repository methods used | Classification |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/assessments/{assessment_id}/intake` | `IntakeService.get_intake_overview` | `AssessmentRepository.load_intake_overview` | Retrieval only |
| `PATCH` | `/api/v1/assessments/{assessment_id}/questions/{question_id}` | `IntakeService.update_question_response` | `AssessmentRepository.get_assessment`, `AssessmentRepository.get_question`, `AssessmentRepository.get_question_option`, `AssessmentRepository.get_question_option_by_label`, `AssessmentRepository.normalize_answer_value`, `ResponseRepository.get_response`, `ResponseRepository.upsert_response` | Retrieval + persistence |
| `GET` | `/api/v1/assessments/{assessment_id}/ai-analysis` | `AIAnalysisService.get_ai_analysis` | `AnalysisRepository.load_ai_analysis_view` | Retrieval only |
| `POST` | `/api/v1/assessments/{assessment_id}/analysis-runs` | `InherentRiskService.create_analysis_run` | `AssessmentRepository.get_assessment`, `AssessmentRepository.load_active_triage_question_responses`, `AnalysisRepository.create_analysis_run`, `AnalysisRepository.upsert_question_risk_results` | Scoring + persistence |
| `GET` | `/api/v1/assessments/{assessment_id}/inherent-risk` | `InherentRiskService.get_inherent_risk_screen` | `AssessmentRepository.get_assessment`, `AnalysisRepository.get_latest_completed_snapshot`, `AssessmentRepository.load_active_triage_question_responses`, `AnalysisRepository.create_analysis_run`, `AnalysisRepository.upsert_question_risk_results` | Retrieval, and may perform scoring + persistence on demand |
| `POST` | `/api/v1/assessments/{assessment_id}/inherent-risk/executive-summary` | `ExecutiveSummaryService.generate` | `AssessmentRepository.get_assessment`, `AnalysisRepository.get_latest_completed_snapshot`, `InherentRiskService.create_analysis_run`, `AnalysisRepository.update_executive_summary`, `AnalysisRepository.get_analysis_run` | AI + persistence; may also trigger scoring + persistence first |

## Endpoint Details

### GET `/api/v1/assessments/{assessment_id}/intake`

- Purpose: Return the intake overview projection for one assessment, including intake sections and visible triage questions.
- Path fields:
  - `assessment_id`: `UUID`
- Query fields:
  - None
- Body fields:
  - None
- Response DTO: `IntakeOverviewResponseDTO`
- Service method called: `IntakeService.get_intake_overview`
- Repository methods used:
  - `AssessmentRepository.load_intake_overview`
- Database tables read:
  - `sar_assessments`
  - `questionnaire_versions`
  - `question_definitions`
  - `assessment_responses`
  - `question_options`
- Database tables written:
  - None
- Classification:
  - Scoring: No
  - AI: No
  - Persistence: No
  - Retrieval only: Yes
- Expected side effects:
  - None
- Related tests:
  - `tests/api/test_intake_api.py`
  - `tests/unit/test_intake_service.py`
  - `tests/unit/test_intake_repository.py`
  - `tests/unit/test_intake_assembler.py`
  - `tests/unit/test_dto_models.py`
- Notes:
  - The registered route exists and is documented here.
  - The service expects `AssessmentRepository.load_intake_overview`, but that method is not present in the current `app/repositories/assessment_repository.py` file. This is an implementation mismatch, not a route-registration mismatch.

### PATCH `/api/v1/assessments/{assessment_id}/questions/{question_id}`

- Purpose: Create or update the stored response for a single question.
- Path fields:
  - `assessment_id`: `UUID`
  - `question_id`: `UUID`
- Query fields:
  - None
- Body fields:
  - `selectedOptionId`: `UUID | null`, optional
  - `answerValue`: `str | null`, optional
- Response DTO: `IntakeQuestionUpdateResponseDTO`
- Service method called: `IntakeService.update_question_response`
- Repository methods used:
  - `AssessmentRepository.get_assessment`
  - `AssessmentRepository.get_question`
  - `AssessmentRepository.get_question_option`
  - `AssessmentRepository.get_question_option_by_label`
  - `AssessmentRepository.normalize_answer_value`
  - `ResponseRepository.get_response`
  - `ResponseRepository.upsert_response`
- Database tables read:
  - `sar_assessments`
  - `question_definitions`
  - `question_options`
  - `assessment_responses`
- Database tables written:
  - `assessment_responses`
- Classification:
  - Scoring: No
  - AI: No
  - Persistence: Yes
  - Retrieval only: No
- Expected side effects:
  - May insert a new `assessment_responses` row.
  - May update an existing `assessment_responses` row.
  - Commits on success and rolls back on failure.
- Related tests:
  - `tests/api/test_intake_api.py`
  - `tests/unit/test_intake_service.py`
  - `tests/unit/test_response_repository.py`
  - `tests/unit/test_dto_models.py`
- Notes:
  - The request validator rejects an empty body.
  - If `selectedOptionId` is provided and non-null, the service normalizes `answerValue` to the selected option label.
  - The registered route exists and is documented here.
  - The service expects several `AssessmentRepository` helper methods that are not present in the current repository file. This is an implementation mismatch, not a route-registration mismatch.

### GET `/api/v1/assessments/{assessment_id}/ai-analysis`

- Purpose: Return the AI-analysis review projection for visible triage questions plus the latest successful analysis-run summary.
- Path fields:
  - `assessment_id`: `UUID`
- Query fields:
  - None
- Body fields:
  - None
- Response DTO: `AIAnalysisResponseDTO`
- Service method called: `AIAnalysisService.get_ai_analysis`
- Repository methods used:
  - `AnalysisRepository.load_ai_analysis_view`
- Database tables read:
  - `sar_assessments`
  - `question_analysis_runs`
  - `questionnaire_versions`
  - `question_definitions`
  - `assessment_responses`
  - `question_options`
  - `question_risk_results`
- Database tables written:
  - None
- Classification:
  - Scoring: No
  - AI: No
  - Persistence: No
  - Retrieval only: Yes
- Expected side effects:
  - None
- Related tests:
  - `tests/unit/test_ai_analysis_api.py`
  - `tests/unit/test_ai_analysis_service.py`
  - `tests/unit/test_ai_analysis_repository.py`
  - `tests/unit/test_ai_analysis_assembler.py`
  - `tests/unit/test_api_router.py`
  - `tests/unit/test_main.py`
- Notes:
  - The current DTO exposes `questionId`, `questionNumber`, `questionText`, `domain`, `selectedOptionId`, `answerValue`, `riskBand`, `riskScore`, `riskSignal`, `whyItMatters`, and `reviewerRemarks`.
  - The current route contract does not expose `aiExplanation` or `confidence`.

### POST `/api/v1/assessments/{assessment_id}/analysis-runs`

- Purpose: Create a new deterministic inherent-risk analysis run for the assessment.
- Path fields:
  - `assessment_id`: `UUID`
- Query fields:
  - None
- Body fields:
  - `force`: `bool = false`
- Response DTO: `AnalysisRunCreateResponseDTO`
- Service method called: `InherentRiskService.create_analysis_run`
- Repository methods used:
  - `AssessmentRepository.get_assessment`
  - `AssessmentRepository.load_active_triage_question_responses`
  - `AnalysisRepository.create_analysis_run`
  - `AnalysisRepository.upsert_question_risk_results`
- Database tables read:
  - `sar_assessments`
  - `questionnaire_versions`
  - `question_definitions`
  - `assessment_responses`
  - `question_options`
- Database tables written:
  - `question_analysis_runs`
  - `question_risk_results`
- Classification:
  - Scoring: Yes
  - AI: No
  - Persistence: Yes
  - Retrieval only: No
- Expected side effects:
  - Always creates a new `question_analysis_runs` row for an existing assessment.
  - Persists one `question_risk_results` row per resolved answered triage response.
  - Preserves prior runs; it does not overwrite the latest successful run.
  - Commits on success.
  - On scoring/persistence failure, rolls back the partial transaction, creates a new failed `question_analysis_runs` row, and commits that failed run.
- Exactly what the existing implementation already does:
  - Checks that the assessment exists.
  - Ignores the `force` flag; the current code accepts it but does not branch on it.
  - Loads active visible scorable triage questions and their answered responses.
  - Builds deterministic `ComputedQuestionRisk` rows from resolved answers.
  - Calculates `triage_score` as the sum of resolved risk weights.
  - Calculates `inherent_score` as a percentage of total resolved weight over total maximum weight.
  - Uses the configured inherent-risk scoring policy to determine the final `inherent_risk_level`.
  - Returns `completed` when scoring runs without limitations.
  - Returns `completed_with_limitations` when required questions are unanswered, stored answers cannot be resolved to configured options, or there are no scorable answered triage responses.
  - Returns `failed` if persistence fails after scoring.
  - Returns the newly created analysis-run ID in `analysisRunId`.
- Related tests:
  - `tests/api/test_inherent_risk_api.py`
  - `tests/unit/test_inherent_risk_service.py`
  - `tests/unit/test_executive_summary_service.py`

### GET `/api/v1/assessments/{assessment_id}/inherent-risk`

- Purpose: Return the inherent-risk screen DTO for the latest successful deterministic run, creating one on demand if needed and if resolved triage data exists.
- Path fields:
  - `assessment_id`: `UUID`
- Query fields:
  - None
- Body fields:
  - None
- Response DTO: `InherentRiskResponseDTO`
- Service method called: `InherentRiskService.get_inherent_risk_screen`
- Repository methods used:
  - `AssessmentRepository.get_assessment`
  - `AnalysisRepository.get_latest_completed_snapshot`
  - `AssessmentRepository.load_active_triage_question_responses`
  - `AnalysisRepository.create_analysis_run`
  - `AnalysisRepository.upsert_question_risk_results`
- Database tables read:
  - `sar_assessments`
  - `question_analysis_runs`
  - `question_risk_results`
  - `questionnaire_versions`
  - `question_definitions`
  - `assessment_responses`
  - `question_options`
- Database tables written:
  - None when a successful snapshot already exists.
  - `question_analysis_runs` and `question_risk_results` when the endpoint has to create a run on demand.
- Classification:
  - Scoring: Conditional
  - AI: No
  - Persistence: Conditional
  - Retrieval only: Only when a successful snapshot already exists
- Expected side effects:
  - May create and persist a deterministic analysis run if none exists and resolved triage responses are available.
  - Returns a not-assessed DTO with `analysisRunId: null` when no successful run exists and no resolved answered triage responses are available.
  - Does not return failed runs as the selected snapshot.
- Related tests:
  - `tests/api/test_inherent_risk_api.py`
  - `tests/unit/test_inherent_risk_service.py`
  - `tests/unit/test_dto_models.py`

### POST `/api/v1/assessments/{assessment_id}/inherent-risk/executive-summary`

- Purpose: Generate or reuse the executive summary for the latest successful inherent-risk run.
- Path fields:
  - `assessment_id`: `UUID`
- Query fields:
  - None
- Body fields:
  - `force`: `bool = false`
- Response DTO: `ExecutiveSummaryGenerateResponseDTO`
- Service method called: `ExecutiveSummaryService.generate`
- Repository methods used:
  - `AssessmentRepository.get_assessment`
  - `AnalysisRepository.get_latest_completed_snapshot`
  - `InherentRiskService.create_analysis_run`
  - `AnalysisRepository.update_executive_summary`
  - `AnalysisRepository.get_analysis_run`
- Database tables read:
  - `sar_assessments`
  - `question_analysis_runs`
  - `question_risk_results`
  - `questionnaire_versions`
  - `question_definitions`
  - `assessment_responses`
  - `question_options`
- Database tables written:
  - `question_analysis_runs`
- Classification:
  - Scoring: Conditional
  - AI: Yes
  - Persistence: Yes
  - Retrieval only: No
- Expected side effects:
  - If no successful analysis run exists yet, first creates one through `InherentRiskService.create_analysis_run`.
  - Reuses the stored summary when the computed input hash matches and `force` is `false`.
  - Otherwise calls the Azure summary client, then writes summary text and metadata back to the same `question_analysis_runs` row.
  - On AI timeout/request/output failure, writes a deterministic fallback summary, sets summary model to `fallback`, updates run status to `completed_with_limitations`, and stores the error summary.
- Current contract:
  - Response shape:
    - `assessmentId: UUID`
    - `analysisRunId: UUID`
    - `executiveSummary.text: str`
    - `executiveSummary.status: generated | fallback`
    - `executiveSummary.generatedAt: datetime`
  - `analysisRunId` currently refers to the underlying `question_analysis_runs.id` row whose summary was generated or reused.
- Pending `analysisRunId` change:
  - No pending `analysisRunId` contract change is implemented in the current registered app.
  - `ExecutiveSummaryGenerateResponseDTO.analysisRunId` is still required and non-null in code.
  - If a future change is planned to rename, remove, or make `analysisRunId` nullable, that change has not been applied to the route, DTO, service, or tests that currently back this endpoint.
- Related tests:
  - `tests/api/test_inherent_risk_api.py`
  - `tests/unit/test_executive_summary_service.py`
  - `tests/unit/test_inherent_risk_service.py`

## Verification And Mismatch Report

### Registered App Verification

- Verified route inventory from the live `FastAPI` app:
  - `GET /api/v1/assessments/{assessment_id}/intake`
  - `PATCH /api/v1/assessments/{assessment_id}/questions/{question_id}`
  - `GET /api/v1/assessments/{assessment_id}/inherent-risk`
  - `POST /api/v1/assessments/{assessment_id}/analysis-runs`
  - `POST /api/v1/assessments/{assessment_id}/inherent-risk/executive-summary`
  - `GET /api/v1/assessments/{assessment_id}/ai-analysis`
- No route-registration mismatch exists between this document and the current registered FastAPI app.

### Additional Mismatches Found In The Repository

- `app/api/v1/documents.py`, `app/api/v1/document_checklist.py`, and `app/api/v1/reports.py` exist under `app/api/v1` but are empty and are not registered in `app/api/router.py`.
- The intake routes are registered, but `IntakeService` currently references `AssessmentRepository.load_intake_overview`, `get_question`, `get_question_option`, `get_question_option_by_label`, and `normalize_answer_value`, and those methods are not present in the current `app/repositories/assessment_repository.py` file.
- The current AI-analysis DTO and assembler do not expose `aiExplanation` or `confidence`, but some tests still expect those fields:
  - `tests/unit/test_ai_analysis_service.py`
  - `tests/unit/test_api_router.py`
  - `tests/unit/test_dto_models.py`
- `tests/unit/test_inherent_risk_service.py` contains unresolved merge markers in the current worktree, so it is not currently collectible as a clean verification source.
