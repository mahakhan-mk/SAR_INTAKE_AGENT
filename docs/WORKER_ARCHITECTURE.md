# Headless Assessment Worker Architecture

## Runtime

`python -m app.main` starts a headless process. There is no HTTP server and no FastAPI route registration.

The entry point initializes once:

1. validated settings;
2. one SQLAlchemy async engine;
3. one async session factory;
4. one robust RabbitMQ connection;
5. exact topology declaration;
6. one composition root;
7. command registry and handlers;
8. workflow and document queue consumers;
9. result outbox publisher;
10. signal-based graceful shutdown.

## Composition root

`app/composition.py` constructs repositories, LLM client, storage clients, execution services, handlers, registry, processor, consumer, and outbox publisher once. Handlers receive transaction-scoped sessions from the processor. Infrastructure clients are not recreated per command.

## Database runtime

- Required configuration: `DATABASE_URL`, `DATABASE_SCHEMA`.
- Stable metadata schema token: `app_schema`.
- Runtime resolution: `schema_translate_map={"app_schema": DATABASE_SCHEMA}`.
- One engine and one session factory.
- No schema creation, alteration, migration, `create_all`, or `drop_all`.
- No hardcoded production schema name.

## Repository-to-table mapping

| Repository | Tables read or written |
|---|---|
| `AssessmentRepository` | `sar_assessments`, `questionnaire_versions`, `question_definitions`, `question_options`, `assessment_responses` |
| `AnalysisRepository` | `question_analysis_runs`, `question_risk_results` |
| `DocumentRepository` | `assessment_documents`, `document_classification_reviews`, `sar_assessments` |
| `DocumentChecklistRepository` | `document_checklist_runs`, `document_checklist_items`, `document_checklist_item_reviews` |
| `VendorCertificationRepository` | `vendor_reputation_jobs`, `vendor_reputation_hitl_reviews` |
| `VendorReputationReadRepository` | `vendor_reputation_jobs`, `vendor_reputation_rows` |
| `InitialSarReportRepository` | `initial_sar_report` |
| `WorkflowTaskExecutionRepository` | `workflow_tasks` |
| `ProcessedMessageRepository` | `processed_messages` |
| `WorkerOutboxRepository` | `outbox_messages` |

`workflow_instances` is mapped only to satisfy schema-accurate foreign-key context. The Worker does not apply workflow transitions.

## Command transaction

One outer database transaction processes one delivery:

1. Check `processed_messages` using `(consumer_name, message_id)`.
2. Lock and validate `workflow_tasks` by `taskId`.
3. Validate workflow, command type, expected workflow version, payload, and attempt.
4. Set the task to `running`, record attempt, lease owner, lease expiry, and start time.
5. Execute domain persistence inside a nested savepoint.
6. On success, mark task `succeeded`, add the exact result event to `outbox_messages`, and insert `processed_messages`.
7. On handled domain/execution failure, roll back only the domain savepoint, keep task `running`, add the exact failure event, and insert `processed_messages`.
8. Commit the outer transaction once.
9. Acknowledge RabbitMQ only after commit.

This boundary prevents duplicate LLM calls, risk runs, checklist runs, report uploads, report rows, and result events after redelivery.

## Idempotency and task fencing

- Primary durable duplicate key: exact broker `messageId` and logical consumer name.
- Logical execution fence: `taskId`, command type, workflow ID, expected workflow version, immutable payload, and exact attempt.
- A queued/retry task accepts only `attempt_count + 1`.
- A running task accepts only its current attempt and only when the lease is owned by this instance or expired.
- Terminal tasks are not executed again.
- Worker instance IDs are unique by default across pods and processes. `WORKER_INSTANCE_ID` may override the generated value.

## Risk behavior

### Calculate

- Loads the assessment and latest authoritative questionnaire responses.
- Creates a new immutable `question_analysis_runs` row.
- Persists per-response `question_risk_results`.
- Generates the executive summary from the new run.
- Preserves all prior runs.
- Emits `assessment.risk.completed` or `assessment.risk.failed`.

### Recalculate

- Repeats calculation from current responses into a new run.
- Preserves historical runs and results.
- Regenerates the executive summary.
- Marks current non-stale `initial_sar_report` rows stale.
- Emits the same exact risk result event family.

## Checklist behavior

### Generate

- Creates a new checklist run and exactly three deterministic checklist items.
- Reads current document and Vendor Reputation certification evidence.
- Generates the checklist summary using the existing prompt.
- Does not create reviewer decisions.
- Does not finalize the run.
- Emits `assessment.checklist.generated`.

### Finalize

- Loads the exact `checklistRunId` from the command.
- Validates that persisted reviewer decisions are tied to each item in that run.
- Does not reuse an older run's reviewer decisions.
- Emits `assessment.checklist.incomplete` when a decision is missing or an effective `Required` item has no detected document.
- Persists `completed` or `completed_with_limitations` only when complete.
- Emits `assessment.checklist.completed`, with `regenerate: true` only when a current report existed and was marked stale.
- Emits `assessment.checklist.failed` only for an actual execution failure.

## Mandatory HITL boundary

- The Gateway owns reviewer-decision submission and identity.
- The Worker only reads persisted decisions.
- The Worker never synthesizes, inserts, or bypasses reviewer decisions.
- The Orchestrator owns `AWAITING_CHECKLIST_REVIEW`, validation queuing, and the next workflow transition.
- RabbitMQ does not hold a message during human waiting time.

## Report behavior

### Generate

- Loads current assessment, questionnaire, latest usable risk run, current checklist state, architecture metadata, and latest Vendor Reputation rows.
- Renders the existing DOCX template.
- Uploads the artifact to Azure Blob Storage.
- Calculates and persists size and SHA-256 metadata.
- Inserts one completed row in singular `initial_sar_report`.
- Emits `assessment.report.completed` only after the transaction commits.

### Regenerate

- Calculates the next monotonic `report_version`.
- Marks previously current reports stale.
- Preserves all prior rows and Blob objects.
- Uploads and persists a new immutable artifact.
- Emits the same `assessment.report.completed` event.

Blob compensation deletes a newly uploaded object when report-row or transaction persistence fails. The Blob key is assessment and report scoped, not local-development scoped.

## Acknowledgement and failure behavior

| Condition | Database result | Broker action |
|---|---|---|
| Valid success | business data, succeeded task, result outbox, processed message committed | ACK |
| Handled domain/execution failure | failure outbox and processed message committed; task remains running for Orchestrator fencing | ACK |
| Duplicate message | no domain work | ACK |
| Malformed envelope, wrong schema/routing, unknown command, stale/future contract | no domain work | reject without requeue, route to DLQ |
| Transient infrastructure failure before commit | rollback everything | republish unchanged delivery through `sar.retry`; ACK original only after retry publish confirms |
| Retry transport limit reached | no false result event | reject without requeue, route to DLQ |

## Outbox dispatch

- Reads only `pending` schema-defined rows whose `available_at` has elapsed.
- Uses `SELECT ... FOR UPDATE SKIP LOCKED`.
- Holds row locks while publishing because the approved schema has no outbox lease columns.
- Publishes only to `sar.events`, using `message_type` as the routing key.
- Uses persistent messages and publisher confirms.
- Marks `published` only after confirmation.
- Applies bounded exponential backoff on failure.
- Marks terminally exhausted rows `failed` for operational intervention.

## Reconnection and shutdown

- RabbitMQ uses `aio_pika.connect_robust`.
- Robust channels and consumers recover after broker reconnects.
- SIGINT and SIGTERM set one shutdown event.
- Consumers are cancelled before channels close.
- The outbox task is supervised. Unexpected termination fails the process instead of silently leaving results unpublished.
- RabbitMQ and database resources are closed independently so one close failure does not prevent the remaining cleanup.
