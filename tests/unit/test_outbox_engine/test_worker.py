"""Unit tests for OutboxWorker background orchestrator."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.modules.outbox_engine.config import OutboxConfig
from src.modules.outbox_engine.dispatcher import TaskDispatcher
from src.modules.outbox_engine.executor import TaskExecutor
from src.modules.outbox_engine.poller import AcquiredTaskDTO, TaskPoller
from src.modules.outbox_engine.worker import OutboxWorker
from src.shared.contracts.outbox import OutboxTaskType
from tests.mocks.mock_outbox_handler import MockOutboxHandler


def test_worker_initialization_defaults() -> None:
    """Verify default initialization, semaphore value and running state."""
    mock_session_factory = MagicMock()
    dispatcher = TaskDispatcher()
    config = OutboxConfig(max_concurrent_tasks=15)

    worker = OutboxWorker(
        session_factory=mock_session_factory,
        dispatcher=dispatcher,
        config=config,
    )

    assert worker.is_running is False
    assert worker._semaphore._value == 15


@pytest.mark.asyncio
async def test_worker_run_processes_tasks_and_graceful_shutdown() -> None:
    """Test standard poll loop cycle, task spawning and clean stop."""
    mock_session_factory = MagicMock()
    config = OutboxConfig(poll_interval_seconds=0.1, max_concurrent_tasks=5)
    dispatcher = TaskDispatcher()
    handler = MockOutboxHandler()
    dispatcher.register_handler(OutboxTaskType.PUBLISH_POST, handler)

    task_dto = AcquiredTaskDTO(
        id=uuid.uuid4(),
        task_type=OutboxTaskType.PUBLISH_POST,
        payload={"order_id": str(uuid.uuid4())},
        retry_count=0,
        max_retries=5,
    )

    mock_poller = MagicMock(spec=TaskPoller)
    mock_poller.acquire_batch = AsyncMock(side_effect=[[task_dto], []])

    mock_executor = MagicMock(spec=TaskExecutor)
    mock_executor.execute_task = AsyncMock()

    worker = OutboxWorker(
        session_factory=mock_session_factory,
        dispatcher=dispatcher,
        config=config,
        poller=mock_poller,
        executor=mock_executor,
    )

    run_task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    worker.stop()
    await run_task

    assert worker.is_running is False
    mock_executor.execute_task.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_run_handles_empty_queue_sleep() -> None:
    """Test worker sleeps and continues polling when poller returns no tasks."""
    mock_session_factory = MagicMock()
    config = OutboxConfig(poll_interval_seconds=0.1)
    dispatcher = TaskDispatcher()

    mock_poller = MagicMock(spec=TaskPoller)
    mock_poller.acquire_batch = AsyncMock(return_value=[])

    worker = OutboxWorker(
        session_factory=mock_session_factory,
        dispatcher=dispatcher,
        config=config,
        poller=mock_poller,
    )

    run_task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.25)
    worker.stop()
    await run_task

    assert mock_poller.acquire_batch.await_count >= 2


@pytest.mark.asyncio
async def test_worker_run_handles_poller_exception_resiliently() -> None:
    """Test unexpected database error during polling does not crash the worker."""
    mock_session_factory = MagicMock()
    config = OutboxConfig(poll_interval_seconds=0.1)
    dispatcher = TaskDispatcher()

    mock_poller = MagicMock(spec=TaskPoller)
    mock_poller.acquire_batch = AsyncMock(
        side_effect=[RuntimeError("PostgreSQL pool exhausted"), []]
    )

    worker = OutboxWorker(
        session_factory=mock_session_factory,
        dispatcher=dispatcher,
        config=config,
        poller=mock_poller,
    )

    run_task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.25)
    worker.stop()
    await run_task

    assert worker.is_running is False
    assert mock_poller.acquire_batch.await_count >= 2


@pytest.mark.asyncio
async def test_worker_run_cancellation_signal() -> None:
    """Test worker terminates cleanly upon receiving asyncio.CancelledError."""
    mock_session_factory = MagicMock()
    config = OutboxConfig(poll_interval_seconds=1.0)
    dispatcher = TaskDispatcher()

    mock_poller = MagicMock(spec=TaskPoller)
    mock_poller.acquire_batch = AsyncMock(return_value=[])

    worker = OutboxWorker(
        session_factory=mock_session_factory,
        dispatcher=dispatcher,
        config=config,
        poller=mock_poller,
    )

    run_task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.01)
    run_task.cancel()
    await run_task

    assert worker.is_running is False


@pytest.mark.asyncio
async def test_worker_process_task_wrapper_releases_semaphore_on_error() -> None:
    """Test semaphore release even if get_handler raises an unexpected error."""
    mock_session_factory = MagicMock()
    config = OutboxConfig(max_concurrent_tasks=2)
    dispatcher = TaskDispatcher()

    task_dto = AcquiredTaskDTO(
        id=uuid.uuid4(),
        task_type=OutboxTaskType.PUBLISH_POST,
        payload={},
        retry_count=0,
        max_retries=5,
    )

    worker = OutboxWorker(
        session_factory=mock_session_factory,
        dispatcher=dispatcher,
        config=config,
    )

    initial_semaphore_val = worker._semaphore._value
    await worker._semaphore.acquire()

    await worker._process_task_wrapper(task_dto)

    assert worker._semaphore._value == initial_semaphore_val


@pytest.mark.asyncio
async def test_drain_active_tasks_handles_empty_queue() -> None:
    """Test drain returns immediately if there are no active tasks."""
    mock_session_factory = MagicMock()
    config = OutboxConfig()
    dispatcher = TaskDispatcher()

    worker = OutboxWorker(
        session_factory=mock_session_factory,
        dispatcher=dispatcher,
        config=config,
    )

    await worker._drain_active_tasks(timeout=1.0)
    assert len(worker._active_tasks) == 0


@pytest.mark.asyncio
async def test_drain_active_tasks_timeout_cancels_remaining_tasks() -> None:
    """Test drain cancels tasks that exceed shutdown timeout."""
    mock_session_factory = MagicMock()
    config = OutboxConfig()
    dispatcher = TaskDispatcher()

    worker = OutboxWorker(
        session_factory=mock_session_factory,
        dispatcher=dispatcher,
        config=config,
    )

    async def long_running_task() -> None:
        await asyncio.sleep(10.0)

    task = asyncio.create_task(long_running_task())
    worker._active_tasks.add(task)

    await worker._drain_active_tasks(timeout=0.01)

    assert task.cancelled()
    try:
        await task
    except asyncio.CancelledError:
        pass