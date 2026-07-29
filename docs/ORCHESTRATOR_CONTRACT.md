# Orchestrator-derived Assessment Worker Contract

## Contract authority

The current Orchestrator implementation is the authority for command names, routing, envelope fields, workflow version and attempt propagation, result event names, payload validation, and retry ownership.

## Command matrix

| Command | Queue | Required payload | Handler | Success event | Failure event |
|---|---|---|---|---|---|
| `assessment.risk.calculate` | `assessment.workflow.q` | `{}` | `calculate_risk` | `assessment.risk.completed` | `assessment.risk.failed` |
| `assessment.risk.recalculate` | `assessment.workflow.q` | `responseVersion` non-negative integer; optional non-blank `reason` | `recalculate_risk` | `assessment.risk.completed` | `assessment.risk.failed` |
| `assessment.checklist.generate` | `assessment.workflow.q` | `{}` | `generate_checklist` | `assessment.checklist.generated` | `assessment.checklist.failed` |
| `assessment.checklist.finalize` | `assessment.workflow.q` | UUID-compatible `checklistRunId` and `reviewId` | `finalize_checklist` | `assessment.checklist.completed` or `assessment.checklist.incomplete` | `assessment.checklist.failed` |
| `assessment.report.generate` | `assessment.documents.q` | `{}` | `generate_report` | `assessment.report.completed` | `assessment.report.failed` |
| `assessment.report.regenerate` | `assessment.documents.q` | `{}` | `regenerate_report` | `assessment.report.completed` | `assessment.report.failed` |

Unknown commands are rejected and are never silently acknowledged.

## Result event matrix

| Event | Task types allowed | Payload |
|---|---|---|
| `assessment.risk.completed` | calculate, recalculate | `{}` |
| `assessment.risk.failed` | calculate, recalculate | required `retryable`, `errorSummary` |
| `assessment.checklist.generated` | generate | `{}` |
| `assessment.checklist.completed` | finalize | optional `regenerate` |
| `assessment.checklist.incomplete` | finalize | `{}` |
| `assessment.checklist.failed` | generate, finalize | required `retryable`, `errorSummary` |
| `assessment.report.completed` | generate, regenerate | `{}` |
| `assessment.report.failed` | generate, regenerate | required `retryable`, `errorSummary` |

## Envelope contract

The Worker uses the Orchestrator's exact Pydantic envelope implementation:

```text
messageId: UUID
messageType: non-blank string
schemaVersion: integer >= 1
assessmentId: UUID
workflowId: UUID
taskId: UUID for commands and Worker results
causationId: UUID or null
expectedWorkflowVersion: integer >= 0 for commands and Worker results
attempt: integer >= 1
occurredAt: timezone-aware datetime
actorId: non-blank string
payload: object
```

The envelope forbids extra fields. Result envelopes preserve assessment, workflow, task, expected workflow version, and attempt from the command. A new result `messageId` is generated. The consumed command `messageId` becomes `causationId`.

## Task-state compatibility

The Orchestrator treats Assessment success events differently from its fenced Vendor Reputation success events:

- Assessment success events are accepted only after the corresponding task is already terminal.
- Assessment failure events require the task to be `running` and require the same attempt.

Therefore the Worker atomically:

- marks the task `succeeded` before writing a success result outbox row;
- leaves the task `running` when writing a handled failure event;
- never marks a handled failure `failed`, schedules a retry, creates a replacement task, or changes workflow state.

The Orchestrator consumes the failure event and decides retry versus terminal failure.

## Retry separation

Two retry mechanisms are intentionally distinct:

1. Broker transport retry for a transient infrastructure failure before commit. The raw command is republished unchanged through `sar.retry`. The task attempt is not incremented.
2. Business task retry. The Worker emits a typed failure event. The Orchestrator decides whether to mark the task `retry`, increments the next attempt, and publishes the next command.

## RabbitMQ topology

### Exchanges

| Exchange | Type | Durable | Worker use |
|---|---|---:|---|
| `sar.commands` | topic | yes | consume commands through bound queues |
| `sar.events` | topic | yes | publish result events |
| `sar.retry` | topic | yes | transport retry for pre-commit infrastructure failures |
| `sar.dlx` | direct | yes | terminal broker dead letters |

### Queue groups

| Main queue | Main bindings | Retry queue | DLQ | DLQ routing key |
|---|---|---|---|---|
| `assessment.workflow.q` | `assessment.risk.calculate`, `assessment.risk.recalculate`, `assessment.checklist.generate`, `assessment.checklist.finalize` | `assessment.workflow.retry.q` | `assessment.workflow.dlq` | `assessment.workflow.dlq` |
| `assessment.documents.q` | `assessment.report.generate`, `assessment.report.regenerate` | `assessment.documents.retry.q` | `assessment.documents.dlq` | `assessment.documents.dlq` |

Both consumers use manual acknowledgement and configurable prefetch. One shared top-level execution semaphore preserves the approved one-slot initial deployment behavior. The workflow consumer is registered before the documents consumer.
