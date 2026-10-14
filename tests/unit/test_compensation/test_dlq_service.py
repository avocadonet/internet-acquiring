import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from src.modules.compensation.alerter import TelegramIncidentAlerter
from src.modules.compensation.dlq_service import DeadLetterTaskDTO, DLQService


@pytest.mark.asyncio
async def test_dlq_service_empty_queue() -> None:
    task_reader = AsyncMock()
    task_reader.get_permanently_failed_tasks.return_value = []
    alerter = AsyncMock(spec=TelegramIncidentAlerter)

    dlq_service = DLQService(task_reader=task_reader, alerter=alerter)

    count = await dlq_service.inspect_and_alert(batch_limit=10)

    assert count == 0
    task_reader.get_permanently_failed_tasks.assert_awaited_once_with(limit=10)
    alerter.send_critical_alert.assert_not_awaited()


@pytest.mark.asyncio
async def test_dlq_service_processes_failed_tasks() -> None:
    task_reader = AsyncMock()
    alerter = AsyncMock(spec=TelegramIncidentAlerter)

    order_id = uuid.uuid4()
    task_id_1 = uuid.uuid4()
    task_id_2 = uuid.uuid4()

    tasks = [
        DeadLetterTaskDTO(
            task_id=task_id_1,
            task_type="EXECUTE_PAYMENT_REFUND",
            payload={
                "order_id": str(order_id),
                "payment_id": "pay_dlq_1",
                "amount_kopecks": 250000,
                "reason": "Мерчант заблокирован",
            },
            retry_count=5,
            last_error="FatalTaskError: Terminal disabled",
            created_at=datetime.now(UTC),
        ),
        DeadLetterTaskDTO(
            task_id=task_id_2,
            task_type="PUBLISH_POST",
            payload={
                "order_id": "invalid-uuid-format",
                "reason": "Chat not found",
            },
            retry_count=5,
            last_error=None,
            created_at=datetime.now(UTC),
        ),
    ]

    task_reader.get_permanently_failed_tasks.return_value = tasks
    dlq_service = DLQService(task_reader=task_reader, alerter=alerter)

    count = await dlq_service.inspect_and_alert(batch_limit=20)

    assert count == 2
    task_reader.get_permanently_failed_tasks.assert_awaited_once_with(limit=20)
    assert alerter.send_critical_alert.await_count == 2

    # Проверка параметров первого вызова
    call_1_kwargs = alerter.send_critical_alert.await_args_list[0].kwargs
    assert call_1_kwargs["order_id"] == order_id
    assert call_1_kwargs["payment_id"] == "pay_dlq_1"
    assert call_1_kwargs["amount_kopecks"] == 250000
    assert call_1_kwargs["task_id"] == task_id_1
    assert "Terminal disabled" in call_1_kwargs["error_message"]

    # Проверка fallback для второго вызова с невалидным UUID
    call_2_kwargs = alerter.send_critical_alert.await_args_list[1].kwargs
    assert isinstance(call_2_kwargs["order_id"], uuid.UUID)
    assert call_2_kwargs["payment_id"] == "N/A"
    assert call_2_kwargs["amount_kopecks"] == 0
    assert call_2_kwargs["task_id"] == task_id_2
    assert "without explicit error" in call_2_kwargs["error_message"]
