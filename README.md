# KPMG SAR Assessment Worker

Headless RabbitMQ Worker for inherent-risk calculation, checklist generation/finalization, and Initial SAR report generation.

## Run

```bash
python -m app.main
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

The Worker requires existing PostgreSQL tables. It never creates, alters, or drops schema objects.

Required configuration:

- `DATABASE_URL`
- `DATABASE_SCHEMA`
- `RABBITMQ_URL`
- Azure OpenAI settings used by executive-summary and checklist-summary generation
- Azure Blob settings used by report artifact persistence

It consumes `assessment.workflow.q` and `assessment.documents.q`, commits execution results and outbox messages atomically, and publishes typed events to `sar.events`.

## Design documentation

- [Pre-change ownership audit](docs/PRE_CHANGE_OWNERSHIP_AUDIT.md)
- [Exact Orchestrator contract](docs/ORCHESTRATOR_CONTRACT.md)
- [Worker architecture and behavior](docs/WORKER_ARCHITECTURE.md)
- [Implementation report](docs/IMPLEMENTATION_REPORT.md)
- [Changed file inventory](docs/CHANGED_FILES.md)
- [Recorded validation results](docs/VALIDATION_RESULTS.txt)
