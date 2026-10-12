"""Unit tests for TaskPoller service."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.modules.outbox_engine.config import OutboxConfig
from src.modules.outbox_engine.poller import ACQUIRE_TASKS_SQL, TaskPoller
from src.shared.contracts.outbox import OutboxTaskType


def test_sql_query_contains_required_cte_and_locking_clauses() -> None:
    """Verify that ACQUIRE_TASKS_SQL conforms to CTE and SKIP LOCKED specification."""
    query_upper = ACQUIRE_TASKS_SQL.upper()
    assert "WITH CANDIDATE_TASKS AS (" in query_upper
    assert "FOR UPDATE SKIP LOCKED" in query_upper
    assert "WHERE PROCESSED = FALSE" in query_upper
    assert "FAILED_PERMANENTLY = FALSE" in query_upper
    assert "LOCKED_UNTIL IS NULL OR LOCKED_UNTIL < NOW()" in query_upper
    assert "UPDATE OUTBOX_TASKS" in query_upper
    assert "RETURNING" in query_upper


def test_task_poller_initialization_with_config_and_overrides() -> None:
    """Test TaskPoller parameter initialization with config and manual overrides."""
    session_factory = MagicMock()
    config = OutboxConfig(batch_size=25, lease_seconds=120)

    poller_default = TaskPoller(session_factory, config=config)
    assert poller_default.batch_size == 25
    assert poller_default.lease_duration_seconds == 120

    poller_override = TaskPoller(
        session_factory,
        config=config,
        batch_size=5,
        lease_duration_seconds=30,
    )
    assert poller_override.batch_size == 5
    assert poller_override.lease_duration_seconds == 30

    poller_fallback = TaskPoller(session_factory)
    assert poller_fallback.batch_size == 10
    assert poller_fallback.lease_duration_seconds == 60


@pytest.mark.asyncio
async def test_acquire_batch_success_mapping() -> None:
    """Test acquire_batch correctly maps database cursor rows to AcquiredTaskDTO."""
    task_id = uuid.uuid4()
    mock_row = (
        task_id,
        "PUBLISH_POST",
        {"order_id": str(uuid.uuid4()), "chat_id": -10012345},
        1,
        5,
    )

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row]

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    # session.begin() is synchronous and returns an async context manager
    mock_tx = MagicMock()
    mock_tx.__aenter__ = AsyncMock(return_value=None)
    mock_tx.__aexit__ = AsyncMock(return_value=None)
    mock_session.begin = MagicMock(return_value=mock_tx)

    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(
        return_value=mock_session
    )
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    poller = TaskPoller(
        mock_session_factory, batch_size=15, lease_duration_seconds=45
    )
    acquired = await poller.acquire_batch()

    assert len(acquired) == 1
    task = acquired[0]
    assert task.id == task_id
    assert task.task_type == OutboxTaskType.PUBLISH_POST
    assert task.payload == {
        "order_id": mock_row[2]["order_id"],
        "chat_id": -10012345,
    }
    assert task.retry_count == 1
    assert task.max_retries == 5

    mock_session.execute.assert_awaited_once()
    call_args = mock_session.execute.call_args
    params = call_args[0][1]
    assert params["batch_size"] == 15
    assert params["lease_duration_seconds"] == 45


@pytest.mark.asyncio
async def test_acquire_batch_returns_empty_list_when_no_tasks_ready() -> None:
    """Test acquire_batch returns empty list when no candidate rows exist in DB."""
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    mock_tx = MagicMock()
    mock_tx.__aenter__ = AsyncMock(return_value=None)
    mock_tx.__aexit__ = AsyncMock(return_value=None)
    mock_session.begin = MagicMock(return_value=mock_tx)

    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(
        return_value=mock_session
    )
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    poller = TaskPoller(mock_session_factory)
    acquired = await poller.acquire_batch()

    assert acquired == []
    mock_session.execute.assert_awaited_once()