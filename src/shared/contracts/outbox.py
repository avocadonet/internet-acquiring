from enum import StrEnum
from typing import Any, Protocol
import uuid
from pydantic import BaseModel


class OutboxTaskType(StrEnum):
    PUBLISH_POST = "PUBLISH_POST"
    EXECUTE_PAYMENT_REFUND = "EXECUTE_PAYMENT_REFUND"


class TaskContextDTO(BaseModel):
    task_id: uuid.UUID
    task_type: OutboxTaskType
    payload: dict[str, Any]
    retry_count: int


class OutboxTaskError(Exception):
    """Базовое исключение ошибки обработки задачи."""
    pass


class RetryableTaskError(OutboxTaskError):
    """Транзиентная ошибка. Требует стандартного retry с backoff."""
    pass


class RateLimitTaskError(OutboxTaskError):
    """Ошибка лимита запросов (например, Telegram FloodWait / 429)."""
    def __init__(self, retry_after: int, message: str = "Rate limited"):
        super().__init__(message)
        self.retry_after = retry_after


class FatalTaskError(OutboxTaskError):
    """Фатальная ошибка. Повторы отменяются."""
    pass


class IOutboxTaskHandler(Protocol):
    async def handle(self, context: TaskContextDTO) -> None:
        """Выполняет полезную нагрузку задачи."""
        ...

    async def on_fatal_failure(self, context: TaskContextDTO, error: str) -> None:
        """Вызывается при окончательном крахе задачи."""
        ...