# Pre-change Ownership and Dependency Audit

## Scope inspected

The complete older Assessment repository and the complete current Orchestrator repository were inspected before conversion. The architecture plan and detailed schema specification were used for ownership and persistence boundaries. The explicit project override makes `initial_sar_report` the only valid report table name.

## 1. API-only modules in the older repository

These belonged to the API Gateway and were removed from the Worker:

- `app/main.py` FastAPI application construction and router registration.
- `app/api/**`, including versioned routes for intake, inherent risk, AI analysis, documents, checklist, and reports.
- `app/api/dependencies.py`, `app/api/errors.py`, `app/api/router.py`, and `app/api/schemas.py`.
- `app/dependencies/api.py` and API-owned dependency wiring.
- Frontend/API assemblers: `ai_analysis_assembler.py`, `document_checklist_assembler.py`, `inherent_risk_assembler.py`, and `intake_assembler.py`.
- HTTP/client DTOs in `app/models/dto.py` and `app/models/document_checklist.py`.
- API-only services: `ai_analysis_service.py`, `document_service.py`, `hitl_review_service.py`, and `intake_service.py`.
- Public document upload/download, report preview/download, ownership, authorization, HTTP exception translation, and request-context behavior.

## 2. Worker-execution modules retained

The following execution code was preserved and adapted only where the runtime contract required it:

- Deterministic inherent-risk calculation and historical run persistence.
- Executive-summary LLM client, prompt loader, and service.
- Checklist generation, deterministic item logic, summary prompt, and persistence.
- Report context assembly, renderer, report template, Blob writer, and report metadata repository.
- Assessment, analysis, document, checklist, report, and Vendor Reputation read repositories required by execution.
- ORM models for the tables the Worker reads or writes.
- Worker-relevant domain errors.

## 3. Genuinely shared modules required by the Worker

- Questionnaire and assessment read models.
- Risk result and analysis-run persistence.
- Assessment document metadata reads for checklist and report generation.
- Checklist run, item, and reviewer-decision reads.
- Vendor Reputation certification and analyst-facing row reads.
- Initial report rendering and Azure Blob artifact storage.
- Prompt and template assets.

These remain local to the Worker because execution must read and write its own domain state even when the API Gateway has separate persistence code.

## 4. Imports that would break after API removal

The older repository coupled service construction to API dependency modules. Removing the API would break:

- `app/main.py -> app.api.router`.
- Routers -> API schemas, API dependency providers, frontend assemblers, and HTTP exception mapping.
- Report preview service -> API-facing `ReportPreview*` DTOs and assembler naming.
- Checklist query/review paths -> API-only reviewer mutation and response models.
- Worker dependency wiring -> the old mixed API/worker dependency module.

Resolution:

- Added a single Worker composition root.
- Reframed report preview code as internal report context code without changing report behavior.
- Removed API-owned imports rather than copying API code back.
- Kept execution repositories and models locally.

## 5. Missing production dependencies

The archive had no dependency manifest. Source imports require:

- `aio-pika`
- `SQLAlchemy`
- `asyncpg`
- `pydantic`
- `python-dotenv`
- `openai`
- `azure-storage-blob`
- `PyYAML`

A production `requirements.txt` and a test-only `requirements-dev.txt` were added.

## 6. Exact Orchestrator commands consumed

- `assessment.risk.calculate`
- `assessment.risk.recalculate`
- `assessment.checklist.generate`
- `assessment.checklist.finalize`
- `assessment.report.generate`
- `assessment.report.regenerate`

## 7. Exact result events published

- `assessment.risk.completed`
- `assessment.risk.failed`
- `assessment.checklist.generated`
- `assessment.checklist.completed`
- `assessment.checklist.incomplete`
- `assessment.checklist.failed`
- `assessment.report.completed`
- `assessment.report.failed`

The broad Orchestrator event `assessment.failed` is not an accepted Assessment Worker result contract and is not emitted.

## 8. Exact RabbitMQ topology

Exchanges:

- `sar.commands`, topic, durable.
- `sar.events`, topic, durable.
- `sar.retry`, topic, durable.
- `sar.dlx`, direct, durable.

Assessment command queues:

- `assessment.workflow.q`, bound to risk and checklist commands.
- `assessment.documents.q`, bound to report commands.

Operational queues:

- `assessment.workflow.retry.q`
- `assessment.workflow.dlq`
- `assessment.documents.retry.q`
- `assessment.documents.dlq`

Retry queues apply a configured TTL and dead-letter back to `sar.commands`. Main queues dead-letter terminally rejected deliveries to `sar.dlx` using the exact queue-specific dead-letter routing keys.

## 9. Exact envelope fields

Wire aliases are:

- `messageId`
- `messageType`
- `schemaVersion`
- `assessmentId`
- `workflowId`
- `taskId`
- `causationId`
- `expectedWorkflowVersion`
- `attempt`
- `occurredAt`
- `actorId`
- `payload`

The current schema version is `1`. Commands and Worker results require `taskId` and `expectedWorkflowVersion`. Result `causationId` is the consumed command `messageId`. Result `actorId` defaults to `assessment-worker` and is configurable.

## 10. Exact allowed result payloads

| Result event | Allowed payload |
|---|---|
| `assessment.risk.completed` | `{}` |
| `assessment.risk.failed` | `retryable: bool`, `errorSummary: non-blank string` |
| `assessment.checklist.generated` | `{}` |
| `assessment.checklist.completed` | optional `regenerate: bool` |
| `assessment.checklist.incomplete` | `{}` |
| `assessment.checklist.failed` | `retryable: bool`, `errorSummary: non-blank string` |
| `assessment.report.completed` | `{}` |
| `assessment.report.failed` | `retryable: bool`, `errorSummary: non-blank string` |

Extra payload fields are rejected.

## Exact incompatibilities that required changes

1. The main runtime was FastAPI, not a headless command consumer.
2. No RabbitMQ consumer, explicit command registry, inbox, transactional result outbox, or outbox dispatcher existed.
3. Database construction was mixed with API dependency wiring and did not provide the required single schema-token runtime.
4. Checklist finalization did not validate persisted reviewer decisions tied to the requested checklist run.
5. Report persistence used the wrong report-table contract and lacked complete version/staleness behavior.
6. Report context mapping referenced fields not exposed by the retained internal model.
7. Report context could reuse reviewer decisions from an older checklist run.
8. The old Blob key contained a local-development prefix.
9. The repository had no source dependency manifest.

No working scoring prompt, checklist prompt, risk thresholds, report template, or report prose behavior was redesigned.
