from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.messaging.contracts import ASSESSMENT_COMMAND_TYPES
from app.messaging.envelope import MessageEnvelope
from app.worker.handlers import AssessmentCommandHandlers, CommandExecutionResult

CommandHandler = Callable[[AsyncSession, MessageEnvelope], Awaitable[CommandExecutionResult]]


class CommandRegistry:
    def __init__(self, handlers: AssessmentCommandHandlers) -> None:
        self._handlers: dict[str, CommandHandler] = {
            "assessment.risk.calculate": handlers.calculate_risk,
            "assessment.risk.recalculate": handlers.recalculate_risk,
            "assessment.checklist.generate": handlers.generate_checklist,
            "assessment.checklist.finalize": handlers.finalize_checklist,
            "assessment.report.generate": handlers.generate_report,
            "assessment.report.regenerate": handlers.regenerate_report,
        }
        if set(self._handlers) != set(ASSESSMENT_COMMAND_TYPES):
            raise RuntimeError("assessment command registry is incomplete")

    def resolve(self, command_type: str) -> CommandHandler:
        try:
            return self._handlers[command_type]
        except KeyError as exc:
            raise LookupError(f"unknown assessment command: {command_type}") from exc

    @property
    def command_types(self) -> frozenset[str]:
        return frozenset(self._handlers)
