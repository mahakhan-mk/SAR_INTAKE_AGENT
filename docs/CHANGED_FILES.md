# Changed File Inventory

## New runtime and messaging files

- `app/__init__.py`
- `app/composition.py`
- `app/messaging/__init__.py`
- `app/messaging/contracts.py`
- `app/messaging/envelope.py`
- `app/messaging/topology.py`
- `app/messaging/rabbitmq.py`
- `app/messaging/consumer.py`
- `app/messaging/outbox_publisher.py`
- `app/worker/__init__.py`
- `app/worker/handlers.py`
- `app/worker/registry.py`
- `app/worker/processor.py`
- `app/repositories/worker_messaging_repository.py`
- `app/repositories/vendor_reputation_repository.py`

## Relocated internal report files

- `app/assemblers/report_preview_assembler.py` -> `app/assemblers/report_context_assembler.py`
- `app/services/report_service.py` -> `app/services/report_context_service.py`
- `app/models/report_preview.py` -> `app/models/initial_sar_report_context.py`

## Existing files minimally adapted

- `app/main.py`
- `app/config.py`
- `app/database.py`
- `app/application/models.py`
- `app/domain/errors.py`
- `app/llm/client.py`
- `app/models/database.py`
- `app/models/enums.py`
- `app/repositories/document_checklist_repository.py`
- `app/repositories/vendor_certification_repository.py`
- `app/services/document_checklist_service.py`
- `app/services/inherent_risk_service.py`
- `app/services/initial_sar_report_generation_service.py`
- `app/services/initial_sar_report_renderer.py`
- `app/services/initial_sar_report_storage.py`
- `app/report_templates/initial_sar_report.schema.json`
- `app/report_templates/report_template_mapping.yaml`

## Existing execution assets preserved

- `app/prompts/document_checklist_summary.yaml`
- `app/prompts/executive_summary.yaml`
- `app/report_templates/initial_sar_report.docx`
- Existing assessment, analysis, document, report, and execution repositories not listed as modified.

## Removed Gateway-owned files

- `app/api/dependencies.py`
- `app/api/errors.py`
- `app/api/router.py`
- `app/api/schemas.py`
- `app/api/v1/ai_analysis.py`
- `app/api/v1/document_checklist.py`
- `app/api/v1/documents.py`
- `app/api/v1/inherent_risk.py`
- `app/api/v1/intake.py`
- `app/api/v1/reports.py`
- `app/dependencies/__init__.py`
- `app/dependencies/api.py`
- `app/dependencies/worker.py`
- `app/assemblers/ai_analysis_assembler.py`
- `app/assemblers/document_checklist_assembler.py`
- `app/assemblers/inherent_risk_assembler.py`
- `app/assemblers/intake_assembler.py`
- `app/models/document_checklist.py`
- `app/models/dto.py`
- `app/repositories/checklist_repository.py`
- `app/repositories/response_repository.py`
- `app/services/ai_analysis_service.py`
- `app/services/document_service.py`
- `app/services/hitl_review_service.py`
- `app/services/intake_service.py`

## Configuration, tests, and documentation added

- `.env.example`
- `requirements.txt`
- `requirements-dev.txt`
- `README.md`
- `tests/test_checklist_finalization.py`
- `tests/test_contracts.py`
- `tests/test_registry.py`
- `tests/test_report_context.py`
- `tests/test_report_context_current_reviews.py`
- `tests/test_schema_contract.py`
- `tests/test_settings_and_storage.py`
- `docs/PRE_CHANGE_OWNERSHIP_AUDIT.md`
- `docs/ORCHESTRATOR_CONTRACT.md`
- `docs/WORKER_ARCHITECTURE.md`
- `docs/IMPLEMENTATION_REPORT.md`
- `docs/CHANGED_FILES.md`
- `docs/VALIDATION_RESULTS.txt`
