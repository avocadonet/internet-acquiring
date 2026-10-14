import uuid
from unittest.mock import AsyncMock

import pytest

from src.modules.compensation.alerter import TelegramIncidentAlerter
from src.modules.compensation.customer_notifier import CustomerNotifierService
from src.modules.compensation.refund_handler import RefundTaskHandler
from src.shared.contracts.outbox import (
    FatalTaskError,
    OutboxTaskType,
    RetryableTaskError,
    TaskContextDTO,
)
from src.shared.contracts.payments import CancelPaymentResponseDTO
from tests.mocks.mock_order_service import MockOrderService
from tests.mocks.mock_payment_client import MockPaymentClient


@pytest.fixture
def mock_payment_client() -> MockPaymentClient:
    return MockPaymentClient()


@pytest.fixture
def mock_order_service() -> MockOrderService:
    return MockOrderService()


@pytest.fixture
def mock_alerter() -> AsyncMock:
    return AsyncMock(spec=TelegramIncidentAlerter)


@pytest.fixture
def mock_customer_notifier() -> AsyncMock:
    return AsyncMock(spec=CustomerNotifierService)


@pytest.fixture
def refund_handler(
    mock_payment_client: MockPaymentClient,
    mock_order_service: MockOrderService,
    mock_alerter: AsyncMock,
    mock_customer_notifier: AsyncMock,
) -> RefundTaskHandler:
    return RefundTaskHandler(
        payment_client=mock_payment_client,
        order_service=mock_order_service,
        alerter=mock_alerter,
        customer_notifier=mock_customer_notifier,
    )


@pytest.mark.asyncio
async def test_refund_handler_happy_path(
    refund_handler: RefundTaskHandler,
    mock_payment_client: MockPaymentClient,
    mock_order_service: MockOrderService,
    mock_alerter: AsyncMock,
    mock_customer_notifier: AsyncMock,
) -> None:
    order_id = uuid.uuid4()
    task_id = uuid.uuid4()
    payment_id = "test_pay_12345"
    amount_kopecks = 75000
    user_id = 99887766

    context = TaskContextDTO(
        task_id=task_id,
        task_type=OutboxTaskType.EXECUTE_PAYMENT_REFUND,
        payload={
            "order_id": str(order_id),
            "payment_id": payment_id,
            "amount_kopecks": amount_kopecks,
            "reason": "Администратор отклонил пост",
            "customer_telegram_id": user_id,
        },
        retry_count=0,
    )

    await refund_handler.handle(context)

    # 1. Проверка вызова эквайринга
    assert len(mock_payment_client.cancel_calls) == 1
    cancel_call = mock_payment_client.cancel_calls[0]
    assert cancel_call.payment_id == payment_id
    assert cancel_call.amount_kopecks == amount_kopecks

    # 2. Проверка обновления статуса в домене заказов
    assert len(mock_order_service.refund_succeeded_calls) == 1
    refund_call = mock_order_service.refund_succeeded_calls[0]
    assert refund_call["order_id"] == order_id
    assert refund_call["refund_info"]["payment_id"] == payment_id
    assert refund_call["refund_info"]["bank_status"] == "CANCELED"

    # 3. Проверка уведомления покупателя
    mock_customer_notifier.notify_refund_completed.assert_awaited_once_with(
        customer_telegram_id=user_id,
        order_id=order_id,
        amount_kopecks=amount_kopecks,
        reason="Администратор отклонил пост",
    )

    # 4. Проверка отправки информационного алерта
    mock_alerter.send_info_alert.assert_awaited_once_with(
        title="Автоматический возврат выполнен",
        order_id=order_id,
        amount_kopecks=amount_kopecks,
        reason="Администратор отклонил пост",
    )


@pytest.mark.asyncio
async def test_refund_handler_without_customer_id(
    refund_handler: RefundTaskHandler,
    mock_customer_notifier: AsyncMock,
    mock_alerter: AsyncMock,
) -> None:
    order_id = uuid.uuid4()
    context = TaskContextDTO(
        task_id=uuid.uuid4(),
        task_type=OutboxTaskType.EXECUTE_PAYMENT_REFUND,
        payload={
            "order_id": str(order_id),
            "payment_id": "test_pay_without_user",
            "amount_kopecks": 50000,
            "reason": "Отсутствует telegram ID",
        },
        retry_count=0,
    )

    await refund_handler.handle(context)

    # Нотификация в боте пропускается, но выполнение завершается успехом
    mock_customer_notifier.notify_refund_completed.assert_not_awaited()
    mock_alerter.send_info_alert.assert_awaited_once()


@pytest.mark.asyncio
async def test_refund_handler_transient_network_timeout(
    refund_handler: RefundTaskHandler,
    mock_payment_client: MockPaymentClient,
) -> None:
    mock_payment_client.should_fail_cancel = True
    mock_payment_client.cancel_exception = TimeoutError("Таймаут шлюза Т-Банка")

    context = TaskContextDTO(
        task_id=uuid.uuid4(),
        task_type=OutboxTaskType.EXECUTE_PAYMENT_REFUND,
        payload={
            "order_id": str(uuid.uuid4()),
            "payment_id": "timeout_pay_id",
            "amount_kopecks": 100000,
            "reason": "Тест сетевого сбоя",
        },
        retry_count=1,
    )

    with pytest.raises(RetryableTaskError) as exc_info:
        await refund_handler.handle(context)

    assert "Network or timeout error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_refund_handler_fatal_bank_rejection(
    refund_handler: RefundTaskHandler,
    mock_payment_client: MockPaymentClient,
) -> None:
    # Банк вернул success=False (например, нехватка баланса мерчанта)
    mock_payment_client.cancel_payment = AsyncMock(  # type: ignore[method-assign]
        return_value=CancelPaymentResponseDTO(
            success=False,
            payment_id="rejected_pay_id",
            status="REJECTED",
            original_amount_kopecks=100000,
            new_amount_kopecks=100000,
        )
    )

    context = TaskContextDTO(
        task_id=uuid.uuid4(),
        task_type=OutboxTaskType.EXECUTE_PAYMENT_REFUND,
        payload={
            "order_id": str(uuid.uuid4()),
            "payment_id": "rejected_pay_id",
            "amount_kopecks": 100000,
            "reason": "Тест отказа банка",
        },
        retry_count=0,
    )

    with pytest.raises(FatalTaskError) as exc_info:
        await refund_handler.handle(context)

    assert "Bank refund rejected" in str(exc_info.value)


@pytest.mark.asyncio
async def test_refund_handler_corrupted_payload(
    refund_handler: RefundTaskHandler,
) -> None:
    context = TaskContextDTO(
        task_id=uuid.uuid4(),
        task_type=OutboxTaskType.EXECUTE_PAYMENT_REFUND,
        payload={
            "order_id": "not-a-valid-uuid",
            "amount_kopecks": -500,  # Отрицательная сумма
        },
        retry_count=0,
    )

    with pytest.raises(FatalTaskError) as exc_info:
        await refund_handler.handle(context)

    assert "Corrupted refund payload" in str(exc_info.value)


@pytest.mark.asyncio
async def test_refund_handler_on_fatal_failure_hook(
    refund_handler: RefundTaskHandler,
    mock_alerter: AsyncMock,
) -> None:
    order_id = uuid.uuid4()
    task_id = uuid.uuid4()
    payment_id = "fatal_pay_id"
    amount_kopecks = 300000
    reason = "Бот исключен из целевого канала"
    error_msg = "FatalTaskError: [7] Недостаточно средств на балансе мерчанта"

    context = TaskContextDTO(
        task_id=task_id,
        task_type=OutboxTaskType.EXECUTE_PAYMENT_REFUND,
        payload={
            "order_id": str(order_id),
            "payment_id": payment_id,
            "amount_kopecks": amount_kopecks,
            "reason": reason,
        },
        retry_count=5,
    )

    await refund_handler.on_fatal_failure(context=context, error=error_msg)

    mock_alerter.send_critical_alert.assert_awaited_once_with(
        title="СБОЙ КОМПЕНСАЦИИ: ДЕНЬГИ НЕ ВОЗВРАЩЕНЫ",
        order_id=order_id,
        payment_id=payment_id,
        amount_kopecks=amount_kopecks,
        error_message=error_msg,
        publish_failure_reason=reason,
        task_id=task_id,
    )
