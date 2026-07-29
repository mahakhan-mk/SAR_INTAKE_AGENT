# Assessment Separation Inventory

This inventory covers the current Assessment FastAPI route modules:

- `app/api/v1/intake.py`
- `app/api/v1/documents.py`
- `app/api/v1/document_checklist.py`
- `app/api/v1/inherent_risk.py`
- `app/api/v1/ai_analysis.py`
- `app/api/v1/reports.py`

## Endpoint Inventory

| Method | Path | Route function | Service called | Repositories used | Blob usage | Executes business logic directly? | Final owner |
| --- | --- | --- | --- | --- | --- | --- | --- |
| GET | `/api/v1/assessments/{assessment_id}/intake` | `get_intake_overview` | `IntakeService.get_intake_overview` | `AssessmentRepository` through service | None | No. Route performs dependency injection and response DTO validation only. | API Gateway for HTTP route; Assessment Worker for service/repository execution |
| PATCH | `/api/v1/assessments/{assessment_id}/questions/{question_id}` | `update_question_response` | `IntakeService.update_question_response` | `AssessmentRepository`, `ResponseRepository` through service | None | No business calculation in route. Route maps request DTO to command and controls commit/rollback. | API Gateway for HTTP route; Assessment Worker for update logic |
| POST | `/api/v1/assessments/{assessment_id}/documents` | `upload_assessment_document` | `DocumentService.upload_document`; `DocumentService.compensate_failed_upload` on failure | `DocumentRepository` through service | `AzureBlobDocumentStorage` injected by route-level factory; service stores and compensates Blob object | Partially. Multipart parsing is HTTP adapter logic, but route owns Blob dependency construction and upload compensation orchestration. | API Gateway for HTTP upload parsing; Assessment Worker for document persistence and Blob side effects |
| GET | `/api/v1/assessments/{assessment_id}/documents` | `list_assessment_documents` | `DocumentService.list_active_documents` | `DocumentRepository` through service | None | No. Route maps service result to response DTO. | API Gateway for HTTP route; Assessment Worker for lookup |
| DELETE | `/api/v1/assessments/{assessment_id}/documents/{document_id}` | `delete_assessment_document` | `DocumentService.soft_delete_document` | `DocumentRepository` through service | None | No business calculation in route. Route controls commit/rollback. | API Gateway for HTTP route; Assessment Worker for soft-delete logic |
| POST | `/api/v1/assessments/{assessment_id}/documents/{document_id}/classification-reviews` | `create_document_classification_review` | `DocumentService.append_classification_review` | `DocumentRepository` through service | None | No business calculation in route. Route controls commit/rollback. | API Gateway for HTTP route; Assessment Worker for classification review logic |
| POST | `/api/v1/assessments/{assessment_id}/document-checklist/runs` | `create_document_checklist_run` | `DocumentChecklistService.generate_checklist`; `DocumentChecklistService.finalize_checklist` | `DocumentRepository`, `DocumentChecklistRepository`, `VendorCertificationRepository` through service | None | Yes. Route sequences generate + finalize workflow and commits the result. | Assessment Worker for checklist workflow; API Gateway for HTTP adapter |
| GET | `/api/v1/assessments/{assessment_id}/document-checklist` | `get_document_checklist` | `DocumentChecklistService.get_checklist` | `DocumentChecklistRepository`, `VendorCertificationRepository` through service read-state path | None | No. Route maps service result to response DTO. | API Gateway for HTTP route; Assessment Worker for checklist read model |
| POST | `/api/v1/assessments/{assessment_id}/document-checklist/items/{item_id}/reviews` | `create_document_checklist_item_review` | `DocumentChecklistService.apply_reviewer_override` | `DocumentChecklistRepository` through service | None | No business calculation in route. Route controls commit/rollback. | API Gateway for HTTP route; Assessment Worker for review application |
| GET | `/api/v1/assessments/{assessment_id}/inherent-risk` | `get_inherent_risk` | `InherentRiskService.get_inherent_risk_screen` | `AssessmentRepository`, `AnalysisRepository` through service | None | No. Route maps service result to response DTO. | API Gateway for HTTP route; Assessment Worker for scoring/read logic |
| POST | `/api/v1/assessments/{assessment_id}/analysis-runs` | `create_analysis_run` | `InherentRiskService.create_analysis_run` | `AssessmentRepository`, `AnalysisRepository` through service | None | No business calculation in route. Route controls commit/rollback. | API Gateway for HTTP route; Assessment Worker for analysis run creation |
| POST | `/api/v1/assessments/{assessment_id}/analysis-runs/{analysis_run_id}/executive-summary` | `generate_executive_summary` | `ExecutiveSummaryService.generate` | `AssessmentRepository`, `AnalysisRepository` through service | None | No business calculation in route. Route controls commit/rollback. | API Gateway for HTTP route; Assessment Worker for summary generation |
| GET | `/api/v1/assessments/{assessment_id}/ai-analysis` | `get_ai_analysis` | `AIAnalysisService.get_ai_analysis` | `AnalysisRepository` through service | None | No. Route maps service result to response DTO. | API Gateway for HTTP route; Assessment Worker for analysis read model |
| GET | `/api/v1/assessments/{assessment_id}/report-preview` | `get_report_preview` | `ReportPreviewService.get_report_preview` | `AssessmentRepository`, `AnalysisRepository`, `DocumentChecklistRepository`, `DocumentRepository` through service | None | No. Route maps service result to JSON response. | API Gateway for HTTP route; Assessment Worker for preview composition |
| POST | `/api/v1/assessments/{assessment_id}/reports` | `create_initial_sar_report` | `InitialSarReportGenerationService.generate_report`; `InitialSarReportGenerationService.compensate_failed_generation` on failure | `InitialSarReportRepository`, `DocumentRepository`, plus report-preview repositories through nested service | `InitialSarReportStorage.store_report/delete_report`; optional architecture image Blob open if document storage is injected | Partially. Route controls generation transaction and compensation trigger; generation/render/storage logic is in service. | Assessment Worker for report generation/storage; API Gateway for HTTP adapter |
| GET | `/api/v1/reports/{report_id}` | `get_initial_sar_report` | None | `InitialSarReportRepository` directly in route | None | Yes. Route directly performs repository read and response mapping. | Split required: API Gateway HTTP adapter, Assessment Worker report metadata lookup |
| GET | `/api/v1/reports/{report_id}/download` | `download_initial_sar_report` | None | `InitialSarReportRepository` directly in route | `InitialSarReportStorage.open_report` directly in route | Yes. Route directly performs repository lookup, Blob open, and streaming response creation. | Split required: API Gateway streaming adapter, Assessment Worker/storage adapter for report bytes |

## File Classification

### MOVE_TO_GATEWAY

- `app/api/v1/intake.py`
- `app/api/v1/documents.py`
- `app/api/v1/document_checklist.py`
- `app/api/v1/inherent_risk.py`
- `app/api/v1/ai_analysis.py`
- `app/api/v1/reports.py`
- `app/api/schemas.py`
- `app/api/errors.py`

### REMAIN_IN_WORKER

- `app/application/models.py`
- `app/domain/errors.py`
- `app/models/database.py`
- `app/models/enums.py`
- `app/models/intake.py`
- `app/models/ai_analysis.py`
- `app/models/dto.py`
- `app/models/document_checklist.py`
- `app/models/report_preview.py`
- `app/repositories/assessment_repository.py`
- `app/repositories/response_repository.py`
- `app/repositories/document_repository.py`
- `app/repositories/document_checklist_repository.py`
- `app/repositories/vendor_certification_repository.py`
- `app/repositories/analysis_repository.py`
- `app/repositories/report_repository.py`
- `app/services/intake_service.py`
- `app/services/document_service.py`
- `app/services/document_storage.py`
- `app/services/document_checklist_service.py`
- `app/services/inherent_risk_service.py`
- `app/services/executive_summary_service.py`
- `app/services/ai_analysis_service.py`
- `app/services/report_service.py`
- `app/services/initial_sar_report_generation_service.py`
- `app/services/initial_sar_report_renderer.py`
- `app/services/initial_sar_report_storage.py`
- `app/assemblers/intake_assembler.py`
- `app/assemblers/document_checklist_assembler.py`
- `app/assemblers/inherent_risk_assembler.py`
- `app/assemblers/ai_analysis_assembler.py`
- `app/assemblers/report_preview_assembler.py`
- `app/llm/client.py`
- `app/llm/executive_summary.py`
- `app/config.py`
- `app/database.py`

### SPLIT_REQUIRED

- `app/api/dependencies.py` - currently mixes FastAPI dependency providers with worker repository/service/storage construction.
- `app/api/v1/documents.py` - HTTP route module should move to Gateway, but Blob storage factory and compensation orchestration need worker-facing extraction.
- `app/api/v1/document_checklist.py` - HTTP route module should move to Gateway, but route-level checklist service construction and generate/finalize workflow sequencing should move behind worker/application boundary.
- `app/api/v1/ai_analysis.py` - HTTP route module should move to Gateway, but route-local `get_ai_analysis_service` constructs worker service/assembler directly.
- `app/api/v1/reports.py` - HTTP route module should move to Gateway, but report metadata/download currently call repository/storage directly and report generation compensation remains route-orchestrated.

## Endpoints Currently Mixing API And Worker Logic

- `POST /api/v1/assessments/{assessment_id}/documents`
- `POST /api/v1/assessments/{assessment_id}/document-checklist/runs`
- `POST /api/v1/assessments/{assessment_id}/reports`
- `GET /api/v1/reports/{report_id}`
- `GET /api/v1/reports/{report_id}/download`
