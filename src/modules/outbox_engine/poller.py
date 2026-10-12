"""Poller service for atomic lease acquisition of outbox tasks."""

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.outbox_engine.config import OutboxConfig
from src.shared.contracts.outbox import OutboxTaskType

logger = logging.getLogger(__name__)

ACQUIRE_TASKS_SQL: Final[str] = """
WITH candidate_tasks AS (
    SELECT id
    FROM outbox_tasks
    WHERE processed = FALSE
      AND failed_permanently = FALSE
      AND execute_after <= NOW()
      AND (locked_until IS NULL OR locked_until < NOW())
    ORDER BY execute_after ASC, created_at ASC
    LIMIT :batch_size
    FOR UPDATE SKIP LOCKED
)
UPDATE outbox_tasks t
SET locked_until = NOW() + (INTERVAL '1 second' * :lease_duration_seconds),
    updated_at = NOW()
FROM candidate_tasks c
WHERE t.id = c.id
RETURNING t.id, t.task_type, t.payload, t.retry_count, t.max_retries;
"""


@dataclass(frozen=True, slots=True)
class AcquiredTaskDTO:
    """DTO representing an atomically locked outbox task ready for execution."""

    id: uuid.UUID
    task_type: OutboxTaskType
    payload: dict[str, Any]
    retry_count: int
    max_retries: int


class TaskPoller:
    """Service responsible for atomic batch lease acquisition of ready outbox tasks."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        config: OutboxConfig | None = None,
        batch_size: int | None = None,
        lease_duration_seconds: int | None = None,
    ) -> None:
        self._session_factory = session_factory
        if config is not None:
            self._batch_size = (
                batch_size if batch_size is not None else config.batch_size
            )
            self._lease_duration_seconds = (
                lease_duration_seconds
                if lease_duration_seconds is not None
                else config.lease_seconds
            )
        else:
            self._batch_size = batch_size if batch_size is not None else 10
            self._lease_duration_seconds = (
                lease_duration_seconds if lease_duration_seconds is not None else 60
            )

    @property
    def batch_size(self) -> int:
        return self._batch_size

    @property
    def lease_duration_seconds(self) -> int:
        return self._lease_duration_seconds

    async def acquire_batch(self) -> list[AcquiredTaskDTO]:
        """Acquires a batch of due tasks using SELECT ... FOR UPDATE SKIP LOCKED.

        Immediately commits the lease update to release row locks.
        """
        async with self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(ACQUIRE_TASKS_SQL),
                    {
                        "batch_size": self._batch_size,
                        "lease_duration_seconds": self._lease_duration_seconds,
                    },
                )
                rows = result.fetchall()

            acquired_tasks: list[AcquiredTaskDTO] = []
            for row in rows:
                raw_id, raw_type, payload, retry_count, max_retries = (
                    row[0],
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                )
                task_id = (
                    raw_id if isinstance(raw_id, uuid.UUID) else uuid.UUID(str(raw_id))
                )
                task_type = (
                    raw_type
                    if isinstance(raw_type, OutboxTaskType)
                    else OutboxTaskType(str(raw_type))
                )
                acquired_tasks.append(
                    AcquiredTaskDTO(
                        id=task_id,
                        task_type=task_type,
                        payload=payload if isinstance(payload, dict) else dict(payload),
                        retry_count=int(retry_count),
                        max_retries=int(max_retries),
                    )
                )

            if acquired_tasks:
                logger.debug(
                    "Acquired %d outbox tasks for processing", len(acquired_tasks)
                )
            return acquired_tasks