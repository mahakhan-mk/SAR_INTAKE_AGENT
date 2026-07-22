# API Contracts

## Current Implemented Endpoints

The current application exposes three inherent-risk endpoints from [app/api/v1/inherent_risk.py](/C:/Users/Lenovo/Documents/SAR_INTAKE_AGENT/app/api/v1/inherent_risk.py):

<<<<<<< HEAD
- `GET /api/v1/assessments/{assessmentId}/inherent-risk`
- `POST /api/v1/assessments/{assessmentId}/analysis-runs`
- `POST /api/v1/assessments/{assessmentId}/inherent-risk/executive-summary`
=======
- Intake Overview
- Inherent Risk
- AI Analysis
- HITL Review
- Document Checklist
- Document Management
- Report Preview
- Report Generation

Vendor Reputation is handled by a separate service.

---

# Intake

## GET /api/v1/assessments/{assessmentId}/intake

Returns the complete intake questionnaire with responses.

Response

```json
{
  "assessmentId": "uuid",
  "header": {
    "technologyName": "Microsoft 365 Copilot",
    "sourceSystem": null,
    "questionnaireVersion": "intake-v1"
  },
  "sections": [
    {
      "code": "general",
      "title": "General",
      "questions": [
        {
          "questionId": "uuid",
          "questionCode": "GEN-001",
          "label": "What is the solution called?",
          "answer": "Selected",
          "responseType": "single_select",
          "required": true,
          "riskDomain": "Operations"
        }
      ]
    }
  ],
  "triage": [
    {
      "questionId": "uuid",
      "questionCode": "TRIAGE-001",
      "label": "Does it handle sensitive data?",
      "answer": "Yes"
    }
  ]
}
```

Behavior

- Returns `404` when `assessmentId` does not exist.
- Returns only visible intake questions ordered by `section_code` then `question_order`.
- Returns only visible triage questions ordered by `question_order`.
- Resolves selected option labels into `answer` when `selected_option_id` is present.

---

## PATCH /api/v1/assessments/{assessmentId}/questions/{questionId}

Creates or updates the stored response for a single intake/triage question.

Request

```json
{
  "selectedOptionId": "uuid",
  "answerValue": "Yes"
}
```

Response

```json
{
  "questionId": "uuid",
  "selectedOptionId": "uuid",
  "answerValue": "Yes"
}
```

Behavior

- Returns `404` when `assessmentId` does not exist.
- Returns `404` when `questionId` does not exist.
- Returns `404` when the question exists but is not visible.
- Returns `400` when `selectedOptionId` does not belong to the specified question.
- Returns `422` when both request fields are omitted.
- Preserves omitted fields and allows explicit `null` values to clear stored data.

---

# Analysis Run

## POST /api/v1/assessments/{assessmentId}/analysis-runs

Creates a new deterministic analysis run for triage-based inherent risk.

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
  "status": "completed"
}
```

Behavior

- Returns `404` when `assessmentId` does not exist.
- Persists one `question_analysis_runs` row and one `question_risk_results` row for each answered triage response.
- Uses scoring rule version `inherent-risk-v1-percentage`.
- Preserves previous runs.
- Marks the run as `completed_with_limitations` when active triage questions are missing responses or when answer resolution required `answer_value` fallback.
- Marks the run as `failed` when persistence fails; failed runs are never returned by the inherent-risk GET as the latest successful result.

---

# Inherent Risk
>>>>>>> origin/main

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
