from __future__ import annotations

from types import SimpleNamespace

from app.messaging.contracts import ASSESSMENT_COMMAND_TYPES
from app.worker.registry import CommandRegistry


async def _handler(session, envelope):
    return None


def test_registry_covers_every_orchestrator_command() -> None:
    handlers = SimpleNamespace(
        calculate_risk=_handler,
        recalculate_risk=_handler,
        generate_checklist=_handler,
        finalize_checklist=_handler,
        generate_report=_handler,
        regenerate_report=_handler,
    )
    registry = CommandRegistry(handlers)
    assert registry.command_types == frozenset(ASSESSMENT_COMMAND_TYPES)
