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
