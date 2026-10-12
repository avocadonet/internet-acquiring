"""Task dispatcher and handler registry for outbox engine."""

import logging

from src.shared.contracts.outbox import IOutboxTaskHandler, OutboxTaskType

logger = logging.getLogger(__name__)


class TaskDispatcher:
    """Registry and dispatcher for outbox task handlers."""

    def __init__(self) -> None:
        self._handlers: dict[OutboxTaskType, IOutboxTaskHandler] = {}

    def register_handler(
        self,
        task_type: OutboxTaskType,
        handler: IOutboxTaskHandler,
    ) -> None:
        """Register a handler for a specific outbox task type."""
        if not isinstance(task_type, OutboxTaskType):
            raise TypeError(
                f"Expected task_type to be an instance of OutboxTaskType, got {type(task_type).__name__}"
            )
        self._handlers[task_type] = handler
        logger.info("Registered handler for outbox task type: %s", task_type.value)

    def get_handler(self, task_type: OutboxTaskType) -> IOutboxTaskHandler:
        """Retrieve registered handler for task type. Raises ValueError if missing."""
        handler = self._handlers.get(task_type)
        if handler is None:
            raise ValueError(f"Обработчик для задачи {task_type} не зарегистрирован")
        return handler

    def has_handler(self, task_type: OutboxTaskType) -> bool:
        """Check whether a handler has been registered for the specified task type."""
        return task_type in self._handlers