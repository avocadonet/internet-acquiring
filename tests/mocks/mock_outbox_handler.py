"""Mock implementation of IOutboxTaskHandler for unit and integration testing."""

from collections.abc import Callable
from typing import Any

from src.shared.contracts.outbox import IOutboxTaskHandler, TaskContextDTO


class MockOutboxHandler:
    """Mock task handler satisfying IOutboxTaskHandler with inspection capabilities."""

    def __init__(
        self,
        side_effect: Exception | Callable[[TaskContextDTO], Any] | None = None,
    ) -> None:
        self.handled_contexts: list[TaskContextDTO] = []
        self.fatal_failure_calls: list[tuple[TaskContextDTO, str]] = []
        self.side_effect: Exception | Callable[[TaskContextDTO], Any] | None = (
            side_effect
        )
        self.call_count: int = 0
        self.fatal_failure_count: int = 0

    async def handle(self, context: TaskContextDTO) -> None:
        """Record handle invocation and trigger configured side_effect if present."""
        self.call_count += 1
        self.handled_contexts.append(context)

        if isinstance(self.side_effect, Exception):
            raise self.side_effect
        if callable(self.side_effect):
            result = self.side_effect(context)
            if hasattr(result, "__await__"):
                await result

    async def on_fatal_failure(self, context: TaskContextDTO, error: str) -> None:
        """Record fatal failure compensation hook invocation."""
        self.fatal_failure_count += 1
        self.fatal_failure_calls.append((context, error))

    def reset(self) -> None:
        """Clear recorded interactions and state."""
        self.handled_contexts.clear()
        self.fatal_failure_calls.clear()
        self.call_count = 0
        self.fatal_failure_count = 0
        self.side_effect = None


# Compile-time verification that MockOutboxHandler conforms to IOutboxTaskHandler
_type_check: IOutboxTaskHandler = MockOutboxHandler()