## Developer Ownership

### Developer 1

Owns:

- Intake Overview page
- Intake read API
- AI Analysis sub-page
- Question-level AI analysis
- Question-level HITL review
- AI Analysis DTO and assembler

Primary files:

- api/v1/intake.py
- api/v1/ai_analysis.py
- services/intake_service.py
- services/ai_analysis_service.py
- services/hitl_review_service.py
- assemblers/intake_assembler.py
- assemblers/ai_analysis_assembler.py
- repositories/assessment_repository.py
- repositories/response_repository.py
- repositories/analysis_repository.py
- llm/question_analysis.py
- prompts/structured_question_analysis.yaml
- prompts/unstructured_question_analysis.yaml

### Developer 2

Owns:

- Inherent Risk page
- AI Executive Summary
- Document Checklist
- Document metadata
- Report Preview
- Report generation
- Inherent Risk, Checklist, and Report DTOs

Primary files:

- api/v1/inherent_risk.py
- api/v1/document_checklist.py
- api/v1/documents.py
- api/v1/reports.py
- services/inherent_risk_service.py
- services/executive_summary_service.py
- services/document_checklist_service.py
- services/document_service.py
- services/report_service.py
- assemblers/inherent_risk_assembler.py
- assemblers/document_checklist_assembler.py
- assemblers/report_preview_assembler.py
- repositories/checklist_repository.py
- repositories/document_repository.py
- repositories/report_repository.py
- llm/executive_summary.py
- prompts/executive_summary.yaml

## Shared Contract

Both developers depend on:

- question_analysis_runs
- question_risk_results
- models/dto.py
- models/enums.py
- repositories/analysis_repository.py

Developer 1 writes the analysis output.

Developer 2 reads the latest completed analysis output to build the Inherent Risk page and executive summary.

Reviewer overrides must not overwrite AI-generated values.

## Backend Foundation Status

Implemented for Developer 2 ownership:

- Inherent Risk page
- Executive Summary projection state
- Shared analysis-run read path
- Analysis run creation API

Implemented files:

- `app/models/dto.py`
- `app/models/enums.py`
- `app/repositories/assessment_repository.py`
- `app/repositories/analysis_repository.py`
- `app/services/inherent_risk_service.py`
- `app/assemblers/inherent_risk_assembler.py`
- `app/api/v1/inherent_risk.py`
- focused API and service tests

Implemented scoring rule:

- Scoring rule version: `inherent-risk-v1-percentage`
- `total_score = sum(selected option risk_weight)`
- `max_score = sum(max option risk_weight for each answered triage question)`
- `score_percentage = total_score / max_score * 100`
- Overall mapping:
  - `low`: `0 <= percentage < 25`
  - `medium`: `25 <= percentage < 50`
  - `high`: `50 <= percentage < 75`
  - `critical`: `75 <= percentage <= 100`

Current schema note:

- `risk_domain` is available and used from the existing question definition record.
- No explicit triage-question required flag exists in the current schema, so limitation detection treats all active non-Vendor-Reputation triage questions as required.
