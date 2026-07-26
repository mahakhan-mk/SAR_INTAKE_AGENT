# API Contracts

## Current Implemented Endpoints

The current application exposes inherent-risk, executive-summary, and Document Checklist endpoints:

- `GET /api/v1/assessments/{assessmentId}/inherent-risk`
- `POST /api/v1/assessments/{assessmentId}/analysis-runs`
- `POST /api/v1/assessments/{assessmentId}/analysis-runs/{analysisRunId}/executive-summary`
- `POST /api/v1/assessments/{assessmentId}/document-checklist/runs`
- `GET /api/v1/assessments/{assessmentId}/document-checklist`
- `POST /api/v1/assessments/{assessmentId}/document-checklist/items/{itemId}/reviews`
- `POST /api/v1/assessments/{assessmentId}/documents`
- `GET /api/v1/assessments/{assessmentId}/documents`
- `DELETE /api/v1/assessments/{assessmentId}/documents/{documentId}`
- `POST /api/v1/assessments/{assessmentId}/documents/{documentId}/classification-reviews`

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

## POST /api/v1/assessments/{assessmentId}/analysis-runs/{analysisRunId}/executive-summary

Generates or reuses the executive summary for a specific existing inherent-risk analysis run.

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

- `assessmentId` and `analysisRunId` are UUID path parameters.
- `analysisRunId` maps to `question_analysis_runs.id`.
- Loads the run using both `question_analysis_runs.assessment_id` and `question_analysis_runs.id`.
- Returns `404` when the assessment/run pair does not identify a matching run.
- Returns `409` when the targeted run status is `queued`, `running`, or `failed`.
- Allows only `completed` and `completed_with_limitations`.
- Reuses the saved summary when `executive_summary_input_hash` matches the newly built input payload and `force` is `false`.
- Reuses the existing executive-summary generation flow and the existing LLM client.
- Loads the prompt from `app/prompts/executive_summary.yaml`.
- Saves the summary on the same `question_analysis_runs` row that was requested.
- Persists summary text and metadata to:
  - `executive_summary`
  - `executive_summary_generated_at`
  - `executive_summary_model`
  - `executive_summary_prompt_version`
  - `executive_summary_input_hash`
- Does not infer the latest run.
- Does not create a new run.
- Does not recalculate scores.
- Does not modify responses.
- Does not modify `question_risk_results`.
- Returns `status: fallback` and stores a deterministic fallback summary when Azure OpenAI times out, fails, or returns invalid structured output.
- Replaced the removed assessment-only route `POST /api/v1/assessments/{assessmentId}/inherent-risk/executive-summary`.
- This route change required no new database migration.

## POST /api/v1/assessments/{assessmentId}/document-checklist/runs

Generates a new immutable Document Checklist run.

Response

```json
{
  "run_id": "uuid",
  "assessment_id": "uuid",
  "status": "draft",
  "summary_text": "Generated checklist summary.",
  "summary_status": "generated",
  "limitations": [],
  "created_at": "2026-07-22T09:00:00Z",
  "items": [
    {
      "item_id": "uuid",
      "document_type": "SOC 2 Type II",
      "item_order": 1,
      "base_verdict": "Required",
      "effective_verdict": "Required",
      "detected_file_status": "missing",
      "detected_document_id": null,
      "reviewer_verdict": null,
      "reviewer_reason": null,
      "vendor_certification_automatic_status": "Available",
      "vendor_certification_analyst_status": null,
      "vendor_certification_effective_status": "Available"
    }
  ]
}
```

Behavior

- Always creates a new `document_checklist_runs` row.
- Creates exactly three `document_checklist_items` rows ordered 1, 2, 3.
- Item types are SOC 2 Type II, ISO 27001, and Architecture Diagram.
- Uses active uploaded documents only for file detection.
- Uses latest manual classification review as effective document type, otherwise the stored system document type.
- Excludes soft-deleted documents.
- Reads Vendor Reputation certification data for SOC 2 and ISO 27001, but never treats it as an uploaded file.
- Stores Vendor Reputation automatic, analyst, and effective status in the run input snapshot.
- Applies latest checklist reviewer/HITL verdict when present.
- Calls the existing Azure summary client once after deterministic items are created.
- Summary failure does not fail generation; the run and items are preserved with `summary_status: failed`.
- API commits once after service completion.

## GET /api/v1/assessments/{assessmentId}/document-checklist

Returns the latest checklist run for an assessment.

Response shape is the same as `POST /document-checklist/runs`.

Behavior

- Returns `404` when no checklist run exists.
- Does not regenerate a checklist.
- Does not query Vendor Reputation.
- Reads detected file status and Vendor Reputation details from the stored run input snapshot.
- Resolves effective verdict from the latest checklist item review; null reviewer verdict clears the override and falls back to `base_verdict`.
- Does not commit.

## POST /api/v1/assessments/{assessmentId}/document-checklist/items/{itemId}/reviews

Appends a checklist reviewer/HITL verdict review.

Request

```json
{
  "reviewer_verdict": "Recommended",
  "reason": "Reviewer accepted the certification evidence.",
  "reviewed_by": "analyst@example.com"
}
```

`reviewer_verdict` may be `Required`, `Recommended`, `N/A`, or null. A null verdict clears the override.

Response

```json
{
  "item_id": "uuid",
  "document_type": "ISO 27001",
  "item_order": 2,
  "base_verdict": "Required",
  "effective_verdict": "Recommended",
  "detected_file_status": "missing",
  "detected_document_id": null,
  "reviewer_verdict": "Recommended",
  "reviewer_reason": "Reviewer accepted the certification evidence.",
  "vendor_certification_automatic_status": "Available",
  "vendor_certification_analyst_status": "Not Available",
  "vendor_certification_effective_status": "Not Available"
}
```

Behavior

- Verifies the item belongs to the assessment.
- Appends a new `document_checklist_item_reviews` row.
- Never updates or deletes prior reviews.
- Requires `reason` when `reviewer_verdict` is non-null.
- Does not change `base_verdict`.
- Does not change detected file status.
- API commits once.

## POST /api/v1/assessments/{assessmentId}/documents

Uploads document metadata and file bytes for storage outside PostgreSQL.

Request

Multipart form data:

- `file`: uploaded document
- `system_document_type`: optional, one of SOC 2 Type II, ISO 27001, Architecture Diagram, Unclassified
- `uploaded_by`: optional

Response

```json
{
  "document_id": "uuid",
  "assessment_id": "uuid",
  "original_filename": "soc2.pdf",
  "content_type": "application/pdf",
  "file_size_bytes": 12345,
  "sha256": "hex-digest",
  "system_document_type": "SOC 2 Type II",
  "upload_source": "sar_request",
  "uploaded_by": null,
  "created_at": "2026-07-22T09:00:00Z",
  "deleted_at": null
}
```

Behavior

- Validates filename, content type, and size.
- Calculates SHA-256.
- Rejects duplicate active content by assessment and SHA-256 with `409`.
- Persists metadata in `assessment_documents`.
- Does not store file bytes in PostgreSQL.
- Uses the checklist-specific test storage interface until Blob Storage is implemented.
- Does not regenerate checklist runs.
- API commits once.

## GET /api/v1/assessments/{assessmentId}/documents

Returns active documents only.

Response

```json
{
  "documents": [
    {
      "document_id": "uuid",
      "assessment_id": "uuid",
      "original_filename": "soc2.pdf",
      "content_type": "application/pdf",
      "file_size_bytes": 12345,
      "sha256": "hex-digest",
      "system_document_type": "SOC 2 Type II",
      "upload_source": "sar_request",
      "uploaded_by": null,
      "created_at": "2026-07-22T09:00:00Z",
      "deleted_at": null
    }
  ]
}
```

Behavior

- Returns `404` when the assessment does not exist.
- Excludes soft-deleted documents.
- Does not commit.

## DELETE /api/v1/assessments/{assessmentId}/documents/{documentId}

Soft deletes a document.

Query parameters:

- `deleted_by`: optional

Response shape is the same single-document DTO as upload.

Behavior

- Verifies the document belongs to the assessment.
- Rejects already-deleted or cross-assessment documents with `404`.
- Sets `deleted_at` and `deleted_by`.
- Never physically deletes the row.
- Does not regenerate checklist runs.
- API commits once.

## POST /api/v1/assessments/{assessmentId}/documents/{documentId}/classification-reviews

Appends a manual document classification review.

Request

```json
{
  "document_type": "Architecture Diagram",
  "reason": "Reviewer identified the uploaded diagram.",
  "reviewed_by": "analyst@example.com"
}
```

Response

```json
{
  "review_id": "uuid",
  "document_id": "uuid",
  "assessment_id": "uuid",
  "document_type": "Architecture Diagram",
  "reason": "Reviewer identified the uploaded diagram.",
  "reviewed_by": "analyst@example.com",
  "created_at": "2026-07-22T09:00:00Z",
  "effective_document_type": "Architecture Diagram"
}
```

Behavior

- Verifies the document belongs to the assessment.
- Rejects soft-deleted and cross-assessment documents with `404`.
- Allows only SOC 2 Type II, ISO 27001, and Architecture Diagram.
- Requires non-empty `reason`.
- Appends a new `document_classification_reviews` row.
- Never updates or deletes previous reviews.
- Latest review by `created_at`, then `id`, becomes effective classification for future checklist generation.
- Does not regenerate checklist runs.
- API commits once.
