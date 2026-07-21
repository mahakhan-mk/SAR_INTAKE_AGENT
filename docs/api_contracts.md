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

Creates a new AI analysis run.

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
  "status": "running"
}
```

---

# Inherent Risk

## GET /api/v1/assessments/{assessmentId}/inherent-risk

Returns the summary page.

Response

```json
{
  "assessmentId": "uuid",
  "analysisRunId": "uuid",
  "inherentRisk": {
    "level": "medium",
    "highRiskQuestionCount": 3
  },
  "topRiskDrivers": [],
  "executiveSummary": {
    "text": "...",
    "generatedAt": "..."
  }
}
```

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
