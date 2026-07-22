# API Contracts

## Current Implemented Endpoints

The current application exposes three inherent-risk endpoints from [app/api/v1/inherent_risk.py](/C:/Users/Lenovo/Documents/SAR_INTAKE_AGENT/app/api/v1/inherent_risk.py):

- `GET /api/v1/assessments/{assessmentId}/inherent-risk`
- `POST /api/v1/assessments/{assessmentId}/analysis-runs`
- `POST /api/v1/assessments/{assessmentId}/inherent-risk/executive-summary`

## GET /api/v1/assessments/{assessmentId}/inherent-risk

Returns the inherent-risk screen projection for the latest successful deterministic run, or creates one on demand when answered triage data exists.

Response

```json
{
  "assessmentId": "uuid",
  "analysisRunId": "uuid",
  "status": "completed",
  "inherentRisk": {
    "level": "high",
    "label": "High",
    "highRiskQuestionCount": 2,
    "sourceText": "Derived from SAR triage questions."
  },
  "topRiskDrivers": [
    {
      "domain": "Business Continuity",
      "level": "critical"
    }
  ],
  "executiveSummary": {
    "text": null,
    "status": "not_generated",
    "generatedAt": null
  },
  "links": {
    "aiAnalysis": "/api/v1/assessments/{assessmentId}/ai-analysis",
    "reportPreview": "/api/v1/assessments/{assessmentId}/report-preview"
  }
}
```

Behavior

- Returns `404` when the assessment does not exist.
- Reads the latest `question_analysis_runs` row whose status is `completed` or `completed_with_limitations`.
- Ignores failed runs when selecting the latest snapshot.
- If no successful run exists and resolved answered triage responses are available, creates a new deterministic run before returning the DTO.
- If no successful run exists and no resolved triage responses are available, returns `analysisRunId: null`, `status: completed_with_limitations`, and `inherentRisk.level: not_assessed`.
- Exposes summary status and saved summary text from the selected run.

## POST /api/v1/assessments/{assessmentId}/analysis-runs

Creates a new deterministic analysis run and preserves prior runs.

Request

```json
{
  "force": false
}
```

Response

```json
{
  "analysisRunId": "uuid",
  "status": "completed_with_limitations"
}
```

Behavior

- Returns `404` when the assessment does not exist.
- Always creates a new `question_analysis_runs` row.
- Persists one `question_risk_results` row for each resolved answered triage response.
- Uses scoring rule version `inherent-risk-v1-percentage`.
- Sets run status to `completed` or `completed_with_limitations` based on required-question coverage and response resolution.
- Sets run status to `failed` and persists the failure when database persistence raises an exception.
- Accepts `force`, but the current implementation does not branch on that field.

## POST /api/v1/assessments/{assessmentId}/inherent-risk/executive-summary

Generates or reuses the executive summary for the latest successful inherent-risk run.

Request

```json
{
  "force": false
}
```

Response

```json
{
  "assessmentId": "uuid",
  "analysisRunId": "uuid",
  "executiveSummary": {
    "text": "Generated executive summary.",
    "status": "generated",
    "generatedAt": "2026-07-22T09:00:00Z"
  }
}
```

Behavior

- Returns `404` when the assessment does not exist.
- Ensures a successful inherent-risk analysis run exists before generating the summary.
- Reuses the saved summary when `executive_summary_input_hash` matches the newly built input payload and `force` is `false`.
- Loads the prompt from `app/prompts/executive_summary.yaml`.
- Persists summary text to `question_analysis_runs.executive_summary`.
- Persists summary metadata to:
  - `executive_summary_model`
  - `executive_summary_prompt_version`
  - `executive_summary_input_hash`
  - `executive_summary_generated_at`
- Returns `status: fallback` and stores a deterministic fallback summary when Azure OpenAI times out, fails, or returns invalid structured output.
