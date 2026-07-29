from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.messaging.contracts import (
    ASSESSMENT_COMMAND_TYPES,
    ASSESSMENT_WORKER_EVENT_TYPES,
    validate_assessment_event_payload,
    validate_command_payload,
)
from app.messaging.envelope import MessageEnvelope


def test_exact_command_registry_contract() -> None:
    assert ASSESSMENT_COMMAND_TYPES == (
        "assessment.risk.calculate",
        "assessment.risk.recalculate",
        "assessment.checklist.generate",
        "assessment.checklist.finalize",
        "assessment.report.generate",
        "assessment.report.regenerate",
    )


def test_exact_result_event_contract() -> None:
    assert ASSESSMENT_WORKER_EVENT_TYPES == (
        "assessment.risk.completed",
        "assessment.risk.failed",
        "assessment.checklist.generated",
        "assessment.checklist.completed",
        "assessment.checklist.incomplete",
        "assessment.checklist.failed",
        "assessment.report.completed",
        "assessment.report.failed",
    )


def test_failure_payload_is_strict() -> None:
    assert validate_assessment_event_payload(
        "assessment.risk.failed",
        {"retryable": True, "errorSummary": "timeout"},
    ) == {"retryable": True, "errorSummary": "timeout"}
    with pytest.raises(ValueError):
        validate_assessment_event_payload(
            "assessment.risk.failed",
            {"retryable": True, "errorSummary": "timeout", "code": "x"},
        )


def test_success_payload_rejects_extra_fields() -> None:
    with pytest.raises(ValueError):
        validate_assessment_event_payload(
            "assessment.report.completed",
            {"reportId": str(uuid4())},
        )


def test_finalize_command_payload_requires_both_ids() -> None:
    run_id = uuid4()
    review_id = uuid4()
    assert validate_command_payload(
        "assessment.checklist.finalize",
        {"checklistRunId": str(run_id), "reviewId": str(review_id)},
    ) == {"checklistRunId": str(run_id), "reviewId": str(review_id)}
    with pytest.raises(ValueError):
        validate_command_payload(
            "assessment.checklist.finalize",
            {"checklistRunId": str(run_id)},
        )


def test_wire_envelope_aliases_and_strictness() -> None:
    values = {
        "messageId": str(uuid4()),
        "messageType": "assessment.risk.calculate",
        "schemaVersion": 1,
        "assessmentId": str(uuid4()),
        "workflowId": str(uuid4()),
        "taskId": str(uuid4()),
        "causationId": str(uuid4()),
        "expectedWorkflowVersion": 4,
        "attempt": 1,
        "occurredAt": datetime.now(UTC).isoformat(),
        "actorId": "orchestrator-agent",
        "payload": {},
    }
    envelope = MessageEnvelope.model_validate(values)
    assert envelope.model_dump(mode="json", by_alias=True)["messageType"] == values["messageType"]
    with pytest.raises(Exception):
        MessageEnvelope.model_validate({**values, "correlationId": values["workflowId"]})
