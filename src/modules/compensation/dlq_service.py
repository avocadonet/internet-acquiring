import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from src.modules.compensation.alerter import TelegramIncidentAlerter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeadLetterTaskDTO:
    """Представление перманентно сбойной задачи (DLQ)."""

    task_id: uuid.UUID
    task_type: str
    payload: dict[str, Any]
    retry_count: int
    last_error: str | None
    created_at: datetime


class IDLQTaskReader(Protocol):
    """Абстракция источника задач DLQ (предоставляется репозиторием воркера)."""

    async def get_permanently_failed_tasks(
        self, limit: int = 50
    ) -> Sequence[DeadLetterTaskDTO]: ...


class DLQService:
    """Сервис инспекции и регулярной генерации сводок по зависшим задачам (DLQ)."""

    def __init__(
        self,
        task_reader: IDLQTaskReader,
        alerter: TelegramIncidentAlerter,
    ) -> None:
        self.task_reader = task_reader
        self.alerter = alerter

    async def inspect_and_alert(self, batch_limit: int = 20) -> int:
        """Выполняет аудит задач в статусе failed_permanently = TRUE

        и отправляет предупреждения в служебный чат мониторинга.
        """
        logger.info("Запуск инспекции Dead Letter Queue (лимит: %d)", batch_limit)
        failed_tasks = await self.task_reader.get_permanently_failed_tasks(
            limit=batch_limit
        )

        if not failed_tasks:
            logger.info("В Dead Letter Queue нет необработанных задач.")
            return 0

        for task in failed_tasks:
            order_id_val = task.payload.get("order_id")
            order_id: uuid.UUID | None = None
            if order_id_val:
                try:
                    order_id = (
                        order_id_val
                        if isinstance(order_id_val, uuid.UUID)
                        else uuid.UUID(str(order_id_val))
                    )
                except (ValueError, TypeError):
                    order_id = None

            payment_id = str(task.payload.get("payment_id", "N/A"))
            amount_kopecks = int(task.payload.get("amount_kopecks", 0))
            reason = str(task.payload.get("reason", "Unknown failure"))
            err_msg = task.last_error or "Permanently failed without explicit error"

            await self.alerter.send_critical_alert(
                title=f"DLQ АЛЕРТ: ЗАДАЧА {task.task_type} ЗАБЛОКИРОВАНА",
                order_id=order_id or uuid.uuid4(),
                payment_id=payment_id,
                amount_kopecks=amount_kopecks,
                error_message=f"[DLQ Retry: {task.retry_count}] {err_msg}",
                publish_failure_reason=reason,
                task_id=task.task_id,
            )

        logger.warning(
            "Инспекция DLQ завершена: сформировано алертов: %d",
            len(failed_tasks),
        )
        return len(failed_tasks)
