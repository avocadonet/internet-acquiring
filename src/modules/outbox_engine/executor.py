"""Task executor service for executing outbox tasks and managing retries/backoff."""

import logging
import random
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.outbox_engine.models import OutboxTaskModel
from src.shared.contracts.outbox import (
    FatalTaskError,
    IOutboxTaskHandler,
    RateLimitTaskError,
    RetryableTaskError,
    TaskContextDTO,
)

__all__ = ["TaskExecutor"]

logger = logging.getLogger(__name__)


class TaskExecutor:
    """Service for executing individual outbox tasks and committing execution outcomes."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def calculate_backoff_delay(retry_count: int) -> float:
        """Calculate exponential backoff delay with full random jitter."""
        base_delay = 5.0
        max_delay = 300.0
        backoff = min(max_delay, base_delay * (2**retry_count))
        jitter = random.uniform(0.5, 3.0)
        return float(backoff + jitter)

    async def execute_task(
        self,
        context: TaskContextDTO,
        max_retries: int,
        handler: IOutboxTaskHandler,
    ) -> None:
        """Execute task via handler and commit resulting status in an isolated transaction."""
        try:
            await handler.handle(context)
            await self._mark_success(context.task_id)

        except RateLimitTaskError as rle:
            logger.warning(
                "Task %s rate-limited (FloodWait). Rescheduling in %d seconds without incrementing retry_count.",
                context.task_id,
                rle.retry_after,
            )
            await self._handle_rate_limit(context.task_id, rle.retry_after, str(rle))

        except FatalTaskError as fte:
            logger.error(
                "Fatal non-recoverable error processing task %s: %s",
                context.task_id,
                fte,
            )
            await self._handle_fatal_failure(context, handler, str(fte))

        except (RetryableTaskError, Exception) as exc:  # noqa: BLE001
            next_retry_count = context.retry_count + 1
            logger.warning(
                "Transient error processing task %s (attempt %d/%d): %s",
                context.task_id,
                next_retry_count,
                max_retries,
                exc,
            )
            if next_retry_count >= max_retries:
                await self._handle_fatal_failure(
                    context,
                    handler,
                    f"Max retries ({max_retries}) exhausted: {exc}",
                )
            else:
                await self._handle_retryable_failure(context, str(exc))

    async def _mark_success(self, task_id: uuid.UUID) -> None:
        async with self._session_factory() as session, session.begin():
            stmt = (
                update(OutboxTaskModel)
                .where(OutboxTaskModel.id == task_id)
                .values(
                    processed=True,
                    locked_until=None,
                    last_error=None,
                    updated_at=datetime.now(UTC),
                )
            )
            await session.execute(stmt)

    async def _handle_rate_limit(
        self,
        task_id: uuid.UUID,
        retry_after: int,
        error_msg: str,
    ) -> None:
        next_execute_after = datetime.now(UTC) + timedelta(seconds=retry_after)
        async with self._session_factory() as session, session.begin():
            stmt = (
                update(OutboxTaskModel)
                .where(OutboxTaskModel.id == task_id)
                .values(
                    locked_until=None,
                    execute_after=next_execute_after,
                    last_error=error_msg,
                    updated_at=datetime.now(UTC),
                )
            )
            await session.execute(stmt)

    async def _handle_retryable_failure(
        self,
        context: TaskContextDTO,
        error_msg: str,
    ) -> None:
        delay_seconds = self.calculate_backoff_delay(context.retry_count)
        next_execute_after = datetime.now(UTC) + timedelta(
            seconds=delay_seconds
        )

        async with self._session_factory() as session, session.begin():
            stmt = (
                update(OutboxTaskModel)
                .where(OutboxTaskModel.id == context.task_id)
                .values(
                    locked_until=None,
                    execute_after=next_execute_after,
                    retry_count=context.retry_count + 1,
                    last_error=error_msg,
                    updated_at=datetime.now(UTC),
                )
            )
            await session.execute(stmt)

    async def _handle_fatal_failure(
        self,
        context: TaskContextDTO,
        handler: IOutboxTaskHandler,
        error_msg: str,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            stmt = (
                update(OutboxTaskModel)
                .where(OutboxTaskModel.id == context.task_id)
                .values(
                    processed=False,
                    failed_permanently=True,
                    locked_until=None,
                    last_error=error_msg,
                    updated_at=datetime.now(UTC),
                )
            )
            await session.execute(stmt)

        try:
            await handler.on_fatal_failure(context, error_msg)
        except Exception as hook_exc:
            logger.critical(
                "Exception raised within compensation hook on_fatal_failure for task %s: %s",
                context.task_id,
                hook_exc,
                exc_info=True,
            )