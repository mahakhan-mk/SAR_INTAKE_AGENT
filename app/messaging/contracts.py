from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SAR_EVENTS_EXCHANGE_NAME = "sar.events"
SAR_COMMANDS_EXCHANGE_NAME = "sar.commands"
SAR_RETRY_EXCHANGE_NAME = "sar.retry"
SAR_DLX_EXCHANGE_NAME = "sar.dlx"

ASSESSMENT_COMMAND_TYPES = (
    "assessment.risk.calculate",
    "assessment.risk.recalculate",
    "assessment.checklist.generate",
    "assessment.checklist.finalize",
    "assessment.report.generate",
    "assessment.report.regenerate",
)

ASSESSMENT_WORKER_EVENT_TYPES = (
    "assessment.risk.completed",
    "assessment.risk.failed",
    "assessment.checklist.generated",
    "assessment.checklist.completed",
    "assessment.checklist.incomplete",
    "assessment.checklist.failed",
    "assessment.report.completed",
    "assessment.report.failed",
)

ASSESSMENT_EVENT_PAYLOAD_FIELDS = {
    "assessment.risk.completed": (),
    "assessment.risk.failed": ("retryable", "errorSummary"),
    "assessment.checklist.generated": (),
    "assessment.checklist.completed": ("regenerate",),
    "assessment.checklist.incomplete": (),
    "assessment.checklist.failed": ("retryable", "errorSummary"),
    "assessment.report.completed": (),
    "assessment.report.failed": ("retryable", "errorSummary"),
}

ASSESSMENT_EVENT_REQUIRED_PAYLOAD_FIELDS = {
    "assessment.risk.failed": ("retryable", "errorSummary"),
    "assessment.checklist.failed": ("retryable", "errorSummary"),
    "assessment.report.failed": ("retryable", "errorSummary"),
}

COMMAND_SUCCESS_EVENT = {
    "assessment.risk.calculate": "assessment.risk.completed",
    "assessment.risk.recalculate": "assessment.risk.completed",
    "assessment.checklist.generate": "assessment.checklist.generated",
    "assessment.checklist.finalize": "assessment.checklist.completed",
    "assessment.report.generate": "assessment.report.completed",
    "assessment.report.regenerate": "assessment.report.completed",
}

COMMAND_FAILURE_EVENT = {
    "assessment.risk.calculate": "assessment.risk.failed",
    "assessment.risk.recalculate": "assessment.risk.failed",
    "assessment.checklist.generate": "assessment.checklist.failed",
    "assessment.checklist.finalize": "assessment.checklist.failed",
    "assessment.report.generate": "assessment.report.failed",
    "assessment.report.regenerate": "assessment.report.failed",
}

ASSESSMENT_WORKFLOW_COMMANDS = (
    "assessment.risk.calculate",
    "assessment.risk.recalculate",
    "assessment.checklist.generate",
    "assessment.checklist.finalize",
)
ASSESSMENT_DOCUMENT_COMMANDS = (
    "assessment.report.generate",
    "assessment.report.regenerate",
)


def validate_command_payload(command_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    if command_type not in ASSESSMENT_COMMAND_TYPES:
        raise ValueError(f"unknown assessment command: {command_type}")
    if not isinstance(payload, Mapping):
        raise ValueError("command payload must be a mapping")
    normalized = dict(payload)
    if command_type in {
        "assessment.risk.calculate",
        "assessment.checklist.generate",
        "assessment.report.generate",
        "assessment.report.regenerate",
    }:
        allowed: set[str] = set()
    elif command_type == "assessment.risk.recalculate":
        allowed = {"responseVersion", "reason"}
        if "responseVersion" not in normalized:
            raise ValueError("assessment.risk.recalculate requires responseVersion")
        response_version = normalized["responseVersion"]
        if not isinstance(response_version, int) or response_version < 0:
            raise ValueError("responseVersion must be a non-negative integer")
        reason = normalized.get("reason")
        if reason is not None and (not isinstance(reason, str) or not reason.strip()):
            raise ValueError("reason must be a non-blank string when supplied")
    else:
        allowed = {"checklistRunId", "reviewId"}
        if set(normalized) != allowed:
            raise ValueError(
                "assessment.checklist.finalize requires checklistRunId and reviewId"
            )
        from uuid import UUID
        for field in allowed:
            try:
                UUID(str(normalized[field]))
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{field} must be UUID-compatible") from exc
    extra = set(normalized) - allowed
    if extra:
        raise ValueError(f"{command_type} payload contains unsupported fields: {sorted(extra)}")
    return normalized


def validate_assessment_event_payload(event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    if event_type not in ASSESSMENT_EVENT_PAYLOAD_FIELDS:
        raise ValueError(f"unknown assessment event contract: {event_type}")
    if not isinstance(payload, Mapping):
        raise ValueError("payload must be a mapping")
    normalized = dict(payload)
    allowed = set(ASSESSMENT_EVENT_PAYLOAD_FIELDS[event_type])
    extra = set(normalized) - allowed
    if extra:
        raise ValueError(f"{event_type} payload contains unsupported fields: {sorted(extra)}")
    for field in ASSESSMENT_EVENT_REQUIRED_PAYLOAD_FIELDS.get(event_type, ()):
        if field not in normalized:
            raise ValueError(f"{event_type} payload requires {field}")
    if event_type.endswith(".failed"):
        if not isinstance(normalized.get("retryable"), bool):
            raise ValueError(f"{event_type} payload retryable must be a boolean")
        summary = normalized.get("errorSummary")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError(f"{event_type} payload errorSummary must be non-blank")
    if "regenerate" in normalized and not isinstance(normalized["regenerate"], bool):
        raise ValueError("assessment.checklist.completed payload regenerate must be a boolean")
    return normalized
