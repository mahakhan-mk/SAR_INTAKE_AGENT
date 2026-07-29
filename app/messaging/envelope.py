from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


class MessageEnvelope(BaseModel):
    """Canonical Stage 1 command and event envelope.

    The same wire contract is used by the API Gateway, Orchestrator, and
    workers. Component-specific data belongs in ``payload``.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    message_id: UUID = Field(
        validation_alias=AliasChoices("message_id", "messageId"),
        serialization_alias="messageId",
    )
    message_type: str = Field(
        validation_alias=AliasChoices("message_type", "messageType"),
        serialization_alias="messageType",
    )
    schema_version: int = Field(
        default=1,
        ge=1,
        validation_alias=AliasChoices("schema_version", "schemaVersion"),
        serialization_alias="schemaVersion",
    )
    assessment_id: UUID = Field(
        validation_alias=AliasChoices("assessment_id", "assessmentId"),
        serialization_alias="assessmentId",
    )
    workflow_id: UUID = Field(
        validation_alias=AliasChoices("workflow_id", "workflowId"),
        serialization_alias="workflowId",
    )
    task_id: UUID | None = Field(
        default=None,
        validation_alias=AliasChoices("task_id", "taskId"),
        serialization_alias="taskId",
    )
    causation_id: UUID | None = Field(
        default=None,
        validation_alias=AliasChoices("causation_id", "causationId"),
        serialization_alias="causationId",
    )
    expected_workflow_version: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices(
            "expected_workflow_version",
            "expectedWorkflowVersion",
        ),
        serialization_alias="expectedWorkflowVersion",
    )
    attempt: int = Field(default=1, ge=1)
    occurred_at: datetime = Field(
        validation_alias=AliasChoices("occurred_at", "occurredAt"),
        serialization_alias="occurredAt",
    )
    actor_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices("actor_id", "actorId"),
        serialization_alias="actorId",
    )
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("message_type", "actor_id")
    @classmethod
    def validate_non_blank_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must be a non-blank string")
        return normalized

    @field_validator("occurred_at", mode="before")
    @classmethod
    def deserialize_occurred_at(cls, value: object) -> object:
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        return value

    @field_validator("payload", mode="before")
    @classmethod
    def validate_payload(cls, value: object) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise ValueError("payload must be a mapping")
        return dict(value)


def create_message_envelope(
    *,
    message_type: str,
    assessment_id: UUID,
    workflow_id: UUID,
    actor_id: str,
    payload: Mapping[str, Any] | None = None,
    task_id: UUID | None = None,
    causation_id: UUID | None = None,
    expected_workflow_version: int | None = None,
    attempt: int = 1,
    schema_version: int = 1,
    message_id: UUID | None = None,
    occurred_at: datetime | None = None,
) -> MessageEnvelope:
    """Create and validate a canonical message envelope."""

    return MessageEnvelope(
        message_id=message_id or uuid4(),
        message_type=message_type,
        schema_version=schema_version,
        assessment_id=assessment_id,
        workflow_id=workflow_id,
        task_id=task_id,
        causation_id=causation_id,
        expected_workflow_version=expected_workflow_version,
        attempt=attempt,
        occurred_at=occurred_at or datetime.now(UTC),
        actor_id=actor_id,
        payload={} if payload is None else dict(payload),
    )
