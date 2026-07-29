# Assessment Worker Implementation Report

## Outcome

The older mixed Assessment API/service repository has been converted into a headless Assessment Worker. Only the Assessment repository was changed. The Orchestrator repository was inspected but not modified.

## Existing code preserved unchanged

- Executive-summary and checklist prompt files.
- Initial SAR DOCX template.
- Deterministic risk scoring thresholds and core calculation behavior.
- Existing questionnaire, assessment response, analysis, document, checklist, and report repository logic where already correct.
- Azure Blob adapters and report renderer behavior, except for contract/name corrections described below.

## Existing code relocated without behavioral change

- `report_preview_assembler.py` -> `report_context_assembler.py`.
- `report_service.py` -> `report_context_service.py`.
- `report_preview.py` -> `initial_sar_report_context.py`.

The relocation removes API/frontend ownership terminology. The code now assembles internal render context only.

## Existing code minimally modified

- `app/config.py`: Worker-only validated settings and unique pod/process lease identity.
- `app/database.py`: one async engine/session factory with schema translation.
- `app/models/database.py`: singular report table, platform reliability models, checklist final statuses, exact operational indexes, and required Vendor Reputation read models.
- `app/services/inherent_risk_service.py`: retained execution-only risk path and immutable new runs.
- `app/services/document_checklist_service.py`: added machine finalization without reviewer mutation.
- `app/repositories/document_checklist_repository.py`: added exact run loading, run-scoped latest-review lookup, and status update.
- Report generation, storage, renderer, context mapping, and template metadata: aligned with the internal Worker context and singular report contract.
- `app/llm/client.py`: configuration is supplied from the composition root instead of API dependency wiring.

## Newly added code

- Headless entry point and one composition root.
- Exact Orchestrator envelope and Assessment command/result contracts.
- RabbitMQ topology declaration, robust connection, dual-queue consumer, retry transport, and manual acknowledgements.
- Explicit six-command registry and command handlers.
- Atomic command processor with task fencing, inbox deduplication, and result outbox writes.
- Schema-compatible outbox publisher with row locking and publisher confirms.
- Workflow task, processed message, and outbox repositories.
- Vendor Reputation report read repository.
- Source dependency manifests, environment example, tests, and architecture/contract documentation.

## Removed API-only code

- Entire `app/api/**` tree.
- Entire `app/dependencies/**` tree.
- API-specific assemblers for intake, inherent risk, AI analysis, and checklist views.
- HTTP/client DTO modules.
- API-only intake, document upload/download, HITL mutation, AI query, and report preview/download services.
- FastAPI startup, exception handling, authentication/authorization dependencies, and router wiring.
- Unused repositories that only supported removed API query paths.

## Important correctness fixes

1. Checklist finalization now requires reviewer decisions tied to the command's checklist run items. Older-run reviews cannot satisfy the gate.
2. Report context uses the same current-run review rule.
3. Report context mapping now references fields the retained model actually exposes.
4. Report generation and regeneration preserve version history and staleness.
5. Newly uploaded reports are compensated when persistence fails.
6. Success task state and result event are committed atomically. Failure events retain the running task state required by the Orchestrator's failure fence.
7. Default Worker instance identity is unique across replicas. PID-only identity was unsafe in Kubernetes.

## Remaining contract mismatch outside this repository

The detailed schema specification defines `outbox_messages.status` as `pending | published | failed` and does not define `locked_by`, `lease_expires_at`, or `processing`. The supplied Orchestrator implementation includes those additional outbox fields and status. The Assessment Worker follows the schema document, as instructed, using `FOR UPDATE SKIP LOCKED` while publishing. No schema migration was invented.

This mismatch should be resolved centrally before a shared production database is finalized. It did not require modifying the Orchestrator or the Assessment schema.

## Validation status

Completed locally:

- Python compilation.
- Clean Worker entry-point import.
- Internal import audit.
- Command registry comparison against the Orchestrator.
- Result event comparison against the Orchestrator.
- RabbitMQ topology constant/binding comparison.
- Static searches for FastAPI, API route registration, hardcoded schema, forbidden report table names, invented events, `create_all`, and `drop_all`.
- Focused unit tests.

Not claimed:

- Live PostgreSQL transaction integration.
- Live RabbitMQ publish/consume/redelivery integration.
- Live Azure OpenAI execution.
- Live Azure Blob upload/compensation.

Those dependencies were not available in the execution environment. Production integration testing remains required.

## Final recorded validation results

- `python -m compileall -q app`: passed.
- Clean import of `app.main` and `app.composition`: passed.
- Orchestrator command constants: exact match.
- Orchestrator Assessment result events: exact match.
- Result payload fields and required fields: exact match.
- Envelope source: exact match with the Orchestrator.
- Assessment exchange, queue, retry, DLQ, and binding constants: exact match.
- Internal import audit: passed.
- FastAPI/router search: no matches.
- `create_all` / `drop_all` search: no matches.
- Hardcoded schema search in `app`: no matches.
- Forbidden report table names in `app`: no matches.
- Invented requested-event search: no matches.
- Focused tests: `15 passed`.
