# API Contracts

## Overview

The SAR Assessment Service exposes APIs for:

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
  "technologyName": "Microsoft 365 Copilot",
  "sections": [
    {
      "title": "General",
      "questions": []
    }
  ]
}
```

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

## GET /api/v1/assessments/{assessmentId}/inherent-risk

Returns the summary page.

Response

```json
{
  "assessmentId": "uuid",
  "analysisRunId": "uuid",
  "status": "completed",
  "inherentRisk": {
    "level": "medium",
    "label": "Medium",
    "highRiskQuestionCount": 3,
    "sourceText": "Derived from SAR triage questions."
  },
  "topRiskDrivers": [
    {
      "domain": "Business Continuity",
      "level": "high"
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

- Returns `404` when `assessmentId` does not exist.
- Returns a controlled `not_assessed` response when no completed analysis exists.
- Returns the latest successful `question_analysis_runs` record when one already exists.
- If no successful run exists and answered triage responses are present, the service calculates and persists a deterministic run before returning the screen DTO.
- Does not expose numeric weights or aggregation formulas in the DTO.
- Excludes Vendor Reputation entirely from this payload.

---

# AI Analysis

## GET /api/v1/assessments/{assessmentId}/ai-analysis

Returns every analysed question.

Response

```json
{
  "assessmentId": "uuid",
  "questions": []
}
```

---

## PATCH /api/v1/assessments/{assessmentId}/ai-analysis/questions/{responseId}

Updates reviewer override.

Request

```json
{
  "reviewerRiskLevel": "high",
  "remarks": "...",
  "mitigation": "..."
}
```

---

# Document Checklist

## GET /api/v1/assessments/{assessmentId}/document-checklist

Returns checklist.

---

## PATCH /api/v1/assessments/{assessmentId}/document-checklist/items/{itemId}

Updates reviewer verdict.

---

## POST /api/v1/assessments/{assessmentId}/documents

Uploads metadata for a document.

---

# Report Preview

## GET /api/v1/assessments/{assessmentId}/report-preview

Returns the assembled report.

---

# Reports

## POST /api/v1/assessments/{assessmentId}/reports

Creates report snapshot.

---

## GET /api/v1/reports/{reportId}

Returns generated report.
