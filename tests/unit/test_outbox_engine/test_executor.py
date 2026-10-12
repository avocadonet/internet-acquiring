"""Unit tests for TaskExecutor service and retry/backoff policies."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.modules.outbox_engine.executor import TaskExecutor
from src.shared.contracts.outbox import (
    FatalTaskError,
    OutboxTaskType,
    RateLimitTaskError,
    RetryableTaskError,
    TaskContextDTO,
)
from tests.mocks.mock_outbox_handler import MockOutboxHandler


@pytest.fixture
def session_setup() -> tuple[MagicMock, AsyncMock]:
    """Fixture providing a mocked session factory and async session."""
    mock_session = AsyncMock()

    # session.begin() is synchronous and returns an async context manager
    mock_tx = MagicMock()
    mock_tx.__aenter__ = AsyncMock(return_value=None)
    mock_tx.__aexit__ = AsyncMock(return_value=None)
    mock_session.begin = MagicMock(return_value=mock_tx)

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    return mock_factory, mock_session


@pytest.fixture
def sample_context() -> TaskContextDTO:
    """Fixture generating a baseline TaskContextDTO."""
    return TaskContextDTO(
        task_id=uuid.uuid4(),
        task_type=OutboxTaskType.PUBLISH_POST,
        payload={"order_id": str(uuid.uuid4()), "chat_id": -10012345},
        retry_count=0,
    )


def test_calculate_backoff_delay_bounds_and_jitter() -> None:
    """Verify exponential backoff scaling and random jitter bounds."""
    # Attempt 0: base 5 * 2^0 = 5.0 + jitter [0.5, 3.0] -> [5.5, 8.0]
    delay_0 = TaskExecutor.calculate_backoff_delay(retry_count=0)
    assert 5.5 <= delay_0 <= 8.0

    # Attempt 1: base 5 * 2^1 = 10.0 + jitter [0.5, 3.0] -> [10.5, 13.0]
    delay_1 = TaskExecutor.calculate_backoff_delay(retry_count=1)
    assert 10.5 <= delay_1 <= 13.0

    # Attempt 2: base 5 * 2^2 = 20.0 + jitter [0.5, 3.0] -> [20.5, 23.0]
    delay_2 = TaskExecutor.calculate_backoff_delay(retry_count=2)
    assert 20.5 <= delay_2 <= 23.0

    # Large retry_count: cap at max_delay 300.0 + jitter [0.5, 3.0] -> [300.5, 303.0]
    delay_large = TaskExecutor.calculate_backoff_delay(retry_count=10)
    assert 300.5 <= delay_large <= 303.0


@pytest.mark.asyncio
async def test_execute_task_success(
    session_setup: tuple[MagicMock, AsyncMock],
    sample_context: TaskContextDTO,
) -> None:
    """Test successful task execution marks processed=True and unlocks lease."""
    mock_factory, mock_session = session_setup
    handler = MockOutboxHandler()
    executor = TaskExecutor(mock_factory)

    await executor.execute_task(
        context=sample_context,
        max_retries=5,
        handler=handler,
    )

    assert handler.call_count == 1
    assert handler.handled_contexts == [sample_context]

    # Verify database update values
    mock_session.execute.assert_awaited_once()
    stmt = mock_session.execute.call_args[0][0]
    params = stmt.compile().params

    assert params["processed"] is True
    assert params["locked_until"] is None
    assert params["last_error"] is None


@pytest.mark.asyncio
async def test_execute_task_rate_limit_preserves_retry_count(
    session_setup: tuple[MagicMock, AsyncMock],
    sample_context: TaskContextDTO,
) -> None:
    """Critical audit test: RateLimitTaskError does NOT increment retry_count and shifts execute_after."""
    mock_factory, mock_session = session_setup
    retry_timeout_seconds = 45
    handler = MockOutboxHandler(
        side_effect=RateLimitTaskError(
            retry_after=retry_timeout_seconds,
            message="Telegram FloodWait 429",
        )
    )
    executor = TaskExecutor(mock_factory)

    now_before = datetime.now(UTC)
    await executor.execute_task(
        context=sample_context,
        max_retries=5,
        handler=handler,
    )

    assert handler.call_count == 1
    mock_session.execute.assert_awaited_once()
    stmt = mock_session.execute.call_args[0][0]
    params = stmt.compile().params

    # retry_count must not be updated in the query
    assert "retry_count" not in params
    assert params["locked_until"] is None
    assert "Telegram FloodWait 429" in params["last_error"]

    # execute_after must be shifted approximately by retry_timeout_seconds
    execute_after: datetime = params["execute_after"]
    diff_seconds = (execute_after - now_before).total_seconds()
    assert 44.0 <= diff_seconds <= 48.0


@pytest.mark.asyncio
async def test_execute_task_transient_error_increments_retry_count(
    session_setup: tuple[MagicMock, AsyncMock],
) -> None:
    """Test transient error increments retry_count when retries remain."""
    mock_factory, mock_session = session_setup
    context = TaskContextDTO(
        task_id=uuid.uuid4(),
        task_type=OutboxTaskType.PUBLISH_POST,
        payload={"order_id": str(uuid.uuid4())},
        retry_count=1,
    )
    handler = MockOutboxHandler(
        side_effect=RetryableTaskError("Connection reset by peer")
    )
    executor = TaskExecutor(mock_factory)

    await executor.execute_task(
        context=context,
        max_retries=5,
        handler=handler,
    )

    assert handler.call_count == 1
    assert handler.fatal_failure_count == 0

    mock_session.execute.assert_awaited_once()
    stmt = mock_session.execute.call_args[0][0]
    params = stmt.compile().params

    assert params["retry_count"] == 2
    assert params["locked_until"] is None
    assert "Connection reset by peer" in params["last_error"]


@pytest.mark.asyncio
async def test_execute_task_max_retries_exhausted_triggers_fatal_failure(
    session_setup: tuple[MagicMock, AsyncMock],
) -> None:
    """Test exhausting max_retries triggers fatal failure and compensation hook."""
    mock_factory, mock_session = session_setup
    context = TaskContextDTO(
        task_id=uuid.uuid4(),
        task_type=OutboxTaskType.PUBLISH_POST,
        payload={"order_id": str(uuid.uuid4())},
        retry_count=4,
    )
    handler = MockOutboxHandler(
        side_effect=RetryableTaskError("Server error 503")
    )
    executor = TaskExecutor(mock_factory)

    await executor.execute_task(
        context=context,
        max_retries=5,
        handler=handler,
    )

    assert handler.call_count == 1
    assert handler.fatal_failure_count == 1
    assert handler.fatal_failure_calls[0][0] == context
    assert "Max retries (5) exhausted" in handler.fatal_failure_calls[0][1]

    mock_session.execute.assert_awaited_once()
    stmt = mock_session.execute.call_args[0][0]
    params = stmt.compile().params

    assert params["processed"] is False
    assert params["failed_permanently"] is True
    assert params["locked_until"] is None


@pytest.mark.asyncio
async def test_execute_task_fatal_error_triggers_compensation(
    session_setup: tuple[MagicMock, AsyncMock],
    sample_context: TaskContextDTO,
) -> None:
    """Test FatalTaskError immediately sets failed_permanently=True and invokes on_fatal_failure."""
    mock_factory, mock_session = session_setup
    handler = MockOutboxHandler(
        side_effect=FatalTaskError("Bot was kicked from channel (403)")
    )
    executor = TaskExecutor(mock_factory)

    await executor.execute_task(
        context=sample_context,
        max_retries=5,
        handler=handler,
    )

    assert handler.call_count == 1
    assert handler.fatal_failure_count == 1
    assert handler.fatal_failure_calls[0][0] == sample_context
    assert (
        "Bot was kicked from channel (403)"
        in handler.fatal_failure_calls[0][1]
    )

    mock_session.execute.assert_awaited_once()
    stmt = mock_session.execute.call_args[0][0]
    params = stmt.compile().params

    assert params["processed"] is False
    assert params["failed_permanently"] is True
    assert params["locked_until"] is None
    assert "Bot was kicked from channel (403)" in params["last_error"]


@pytest.mark.asyncio
async def test_fatal_failure_hook_exception_is_safely_handled(
    session_setup: tuple[MagicMock, AsyncMock],
    sample_context: TaskContextDTO,
) -> None:
    """Verify that an exception raised inside on_fatal_failure does not crash the executor."""
    mock_factory, mock_session = session_setup
    handler = MockOutboxHandler(side_effect=FatalTaskError("Fatal error"))

    async def failing_hook(ctx: TaskContextDTO, err: str) -> None:
        raise RuntimeError("Compensation webhook service unavailable")

    handler.on_fatal_failure = failing_hook  # type: ignore[assignment]
    executor = TaskExecutor(mock_factory)

    # Should complete without raising RuntimeError
    await executor.execute_task(
        context=sample_context,
        max_retries=5,
        handler=handler,
    )

    mock_session.execute.assert_awaited_once()