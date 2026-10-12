"""Unit tests for TaskDispatcher registry."""

from typing import cast

import pytest

from src.modules.outbox_engine.dispatcher import TaskDispatcher
from src.shared.contracts.outbox import OutboxTaskType
from tests.mocks.mock_outbox_handler import MockOutboxHandler


def test_register_and_get_handler_success() -> None:
    """Test successful registration and retrieval of a task handler."""
    dispatcher = TaskDispatcher()
    handler = MockOutboxHandler()

    dispatcher.register_handler(OutboxTaskType.PUBLISH_POST, handler)

    retrieved = dispatcher.get_handler(OutboxTaskType.PUBLISH_POST)
    assert retrieved is handler
    assert dispatcher.has_handler(OutboxTaskType.PUBLISH_POST) is True
    assert dispatcher.has_handler(OutboxTaskType.EXECUTE_PAYMENT_REFUND) is False


def test_register_multiple_distinct_handlers() -> None:
    """Test registering independent handlers for different task types."""
    dispatcher = TaskDispatcher()
    publish_handler = MockOutboxHandler()
    refund_handler = MockOutboxHandler()

    dispatcher.register_handler(OutboxTaskType.PUBLISH_POST, publish_handler)
    dispatcher.register_handler(OutboxTaskType.EXECUTE_PAYMENT_REFUND, refund_handler)

    assert dispatcher.get_handler(OutboxTaskType.PUBLISH_POST) is publish_handler
    assert (
        dispatcher.get_handler(OutboxTaskType.EXECUTE_PAYMENT_REFUND)
        is refund_handler
    )


def test_get_unregistered_handler_raises_value_error() -> None:
    """Test ValueError is raised when requesting a handler that was not registered."""
    dispatcher = TaskDispatcher()

    with pytest.raises(
        ValueError,
        match=r"Обработчик для задачи PUBLISH_POST не зарегистрирован",
    ):
        dispatcher.get_handler(OutboxTaskType.PUBLISH_POST)


def test_register_invalid_task_type_raises_type_error() -> None:
    """Test TypeError is raised if non-OutboxTaskType enum key is provided."""
    dispatcher = TaskDispatcher()
    handler = MockOutboxHandler()

    with pytest.raises(
        TypeError,
        match=r"Expected task_type to be an instance of OutboxTaskType, got str",
    ):
        dispatcher.register_handler(
            cast(OutboxTaskType, "INVALID_TASK_TYPE"),
            handler,
        )


def test_override_registered_handler() -> None:
    """Test that registering a new handler for the same task type overrides the previous one."""
    dispatcher = TaskDispatcher()
    first_handler = MockOutboxHandler()
    second_handler = MockOutboxHandler()

    dispatcher.register_handler(OutboxTaskType.PUBLISH_POST, first_handler)
    dispatcher.register_handler(OutboxTaskType.PUBLISH_POST, second_handler)

    assert dispatcher.get_handler(OutboxTaskType.PUBLISH_POST) is second_handler