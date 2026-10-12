"""Outbox worker orchestrator for concurrent polling and task lifecycle dispatch."""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.outbox_engine.config import OutboxConfig
from src.modules.outbox_engine.dispatcher import TaskDispatcher
from src.modules.outbox_engine.executor import TaskExecutor
from src.modules.outbox_engine.poller import AcquiredTaskDTO, TaskPoller
from src.shared.contracts.outbox import TaskContextDTO

logger = logging.getLogger(__name__)


class OutboxWorker:
    """Background worker orchestrator with concurrency control and graceful shutdown."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        dispatcher: TaskDispatcher,
        config: OutboxConfig,
        poller: TaskPoller | None = None,
        executor: TaskExecutor | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._dispatcher = dispatcher
        self._config = config
        self._poller = poller or TaskPoller(session_factory, config=config)
        self._executor = executor or TaskExecutor(session_factory)
        self._semaphore = asyncio.Semaphore(config.max_concurrent_tasks)
        self._running: bool = False
        self._active_tasks: set[asyncio.Task[None]] = set()

    @property
    def is_running(self) -> bool:
        """Check if the worker loop is currently running."""
        return self._running

    async def run(self) -> None:
        """Execute the primary polling loop until stopped or cancelled."""
        self._running = True
        logger.info(
            "OutboxWorker started. Max concurrency: %d, poll interval: %.2fs",
            self._config.max_concurrent_tasks,
            self._config.poll_interval_seconds,
        )

        try:
            while self._running:
                try:
                    tasks = await self._poller.acquire_batch()
                    if not tasks:
                        await asyncio.sleep(self._config.poll_interval_seconds)
                        continue

                    for task_row in tasks:
                        if not self._running:
                            break
                        await self._semaphore.acquire()
                        coro = self._process_task_wrapper(task_row)
                        task = asyncio.create_task(coro)
                        self._active_tasks.add(task)
                        task.add_done_callback(self._active_tasks.discard)

                except asyncio.CancelledError:
                    logger.info("OutboxWorker loop received cancellation signal.")
                    break
                except Exception:
                    logger.exception(
                        "Unexpected error in OutboxWorker polling loop"
                    )
                    if self._running:
                        await asyncio.sleep(self._config.poll_interval_seconds)
        finally:
            self._running = False
            await self._drain_active_tasks()
            logger.info("OutboxWorker stopped successfully.")

    async def _process_task_wrapper(self, task_row: AcquiredTaskDTO) -> None:
        """Wrap individual task execution within semaphore release boundaries."""
        try:
            handler = self._dispatcher.get_handler(task_row.task_type)
            context = TaskContextDTO(
                task_id=task_row.id,
                task_type=task_row.task_type,
                payload=task_row.payload,
                retry_count=task_row.retry_count,
            )
            await self._executor.execute_task(
                context=context,
                max_retries=task_row.max_retries,
                handler=handler,
            )
        except Exception:
            logger.exception(
                "Unhandled error executing task %s (%s)",
                task_row.id,
                task_row.task_type,
            )
        finally:
            self._semaphore.release()

    async def _drain_active_tasks(self, timeout: float = 30.0) -> None:
        """Wait for currently running background tasks to complete during shutdown."""
        if not self._active_tasks:
            return

        logger.info(
            "Waiting for %d active task(s) to complete (drain timeout=%.1fs)...",
            len(self._active_tasks),
            timeout,
        )
        try:
            await asyncio.wait_for(
                asyncio.gather(*list(self._active_tasks), return_exceptions=True),
                timeout=timeout,
            )
        except TimeoutError:
            logger.warning(
                "Timeout exceeded while draining active tasks. Cancelling remaining %d task(s).",
                len(self._active_tasks),
            )
            for task in self._active_tasks:
                task.cancel()

    def stop(self) -> None:
        """Signal the worker loop to terminate gracefully."""
        logger.info("Stop requested for OutboxWorker.")
        self._running = False