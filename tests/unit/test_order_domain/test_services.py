import uuid
from types import TracebackType
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.modules.order_domain.exceptions import (
    InvalidStateTransitionError,
    OrderNotFoundError,
    OrderPricingError,
    PaymentInitializationError,
)
from src.modules.order_domain.models import OrderModel
from src.modules.order_domain.services.lifecycle_service import OrderLifecycleService
from src.modules.order_domain.services.order_service import OrderService
from src.modules.order_domain.services.pricing_service import PricingService
from src.shared.contracts.orders import (
    ContentTypeEnum,
    CreateOrderInputDTO,
    CustomerContactDTO,
    OrderStatus,
    PostContentDTO,
)
from src.shared.contracts.outbox import OutboxTaskType
from src.shared.contracts.payments import InitPaymentResponseDTO, IPaymentClient


class AsyncContextManagerMock:
    """Универсальный асинхронный контекстный менеджер для мокирования сессий SQLAlchemy."""

    def __init__(self, enter_value: Any | None = None) -> None:
        self.enter_value = enter_value

    async def __aenter__(self) -> Any:
        return self.enter_value

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        return None


@pytest.fixture
def sample_create_order_input() -> CreateOrderInputDTO:
    return CreateOrderInputDTO(
        user_id=123456789,
        target_channel_id=-1001234567890,
        content=PostContentDTO(
            content_type=ContentTypeEnum.TEXT,
            text="Тестовый пост",
        ),
        contact=CustomerContactDTO(
            phone="+79991234567",
            email="client@example.com",
        ),
    )


def build_mock_session_factory(mock_order: OrderModel | None = None):
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_order
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_session.begin = MagicMock(
        return_value=AsyncContextManagerMock(mock_session)
    )

    session_factory = MagicMock(
        return_value=AsyncContextManagerMock(mock_session)
    )
    return session_factory, mock_session


class TestPricingService:
    def test_default_rate_fallback(self) -> None:
        service = PricingService()
        amount = service.calculate_amount_kopecks(target_channel_id=-1009999999999)
        assert amount == PricingService.DEFAULT_BASE_PRICE_KOPECKS

    def test_explicit_rate_mapping(self) -> None:
        target_channel = -1001112223334
        service = PricingService(channel_rates={target_channel: 75_000})
        amount = service.calculate_amount_kopecks(target_channel_id=target_channel)
        assert amount == 75_000

    def test_invalid_channel_id_raises_error(self) -> None:
        service = PricingService()
        with pytest.raises(OrderPricingError):
            service.calculate_amount_kopecks(target_channel_id=0)

    def test_invalid_amount_raises_error(self) -> None:
        target_channel = -1001112223334
        service = PricingService(channel_rates={target_channel: 0})
        with pytest.raises(OrderPricingError):
            service.calculate_amount_kopecks(target_channel_id=target_channel)


class TestOrderService:
    @pytest.mark.asyncio
    async def test_create_order_success(
        self, sample_create_order_input: CreateOrderInputDTO
    ) -> None:
        session_factory, mock_session = build_mock_session_factory()

        mock_payment_client = AsyncMock(spec=IPaymentClient)
        mock_payment_client.init_payment.return_value = InitPaymentResponseDTO(
            payment_id="pay_test_12345",
            payment_url="https://securepay.tinkoff.ru/v2/test_url",
        )

        service = OrderService(
            session_factory=session_factory,
            payment_client=mock_payment_client,
        )

        result = await service.create_order(sample_create_order_input)

        assert result.payment_url == "https://securepay.tinkoff.ru/v2/test_url"
        assert result.amount_kopecks == PricingService.DEFAULT_BASE_PRICE_KOPECKS
        assert uuid.UUID(result.order_id)

        mock_payment_client.init_payment.assert_awaited_once()
        mock_session.add.assert_called_once()
        mock_session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_order_payment_failure_raises_error(
        self, sample_create_order_input: CreateOrderInputDTO
    ) -> None:
        session_factory, mock_session = build_mock_session_factory()

        mock_payment_client = AsyncMock(spec=IPaymentClient)
        mock_payment_client.init_payment.side_effect = RuntimeError("Сетевой сбой API банка")

        service = OrderService(
            session_factory=session_factory,
            payment_client=mock_payment_client,
        )

        with pytest.raises(PaymentInitializationError):
            await service.create_order(sample_create_order_input)

        mock_session.add.assert_not_called()


class TestOrderLifecycleService:
    @pytest.mark.asyncio
    async def test_handle_payment_succeeded_creates_outbox_task(self) -> None:
        order_id = uuid.uuid4()
        existing_order = OrderModel(
            id=order_id,
            user_id=123,
            target_chat_id=-100123,
            amount_kopecks=50000,
            status=OrderStatus.PENDING,
            content_payload={"type": "text"},
            contact_info={"phone": "+79991234567"},
        )

        session_factory, mock_session = build_mock_session_factory(existing_order)
        lifecycle = OrderLifecycleService(session_factory=session_factory)

        await lifecycle.handle_payment_succeeded(order_id, payment_id="pay_999")

        assert existing_order.status == OrderStatus.PAID
        assert existing_order.payment_id == "pay_999"

        assert mock_session.add.call_count == 1
        added_task = mock_session.add.call_args[0][0]
        assert added_task.task_type == OutboxTaskType.PUBLISH_POST
        assert added_task.payload["order_id"] == str(order_id)

    @pytest.mark.asyncio
    async def test_handle_payment_succeeded_idempotent_when_already_paid(self) -> None:
        order_id = uuid.uuid4()
        existing_order = OrderModel(
            id=order_id,
            user_id=123,
            target_chat_id=-100123,
            amount_kopecks=50000,
            status=OrderStatus.PAID,
            content_payload={"type": "text"},
            contact_info={"phone": "+79991234567"},
            payment_id="pay_existing",
        )

        session_factory, mock_session = build_mock_session_factory(existing_order)
        lifecycle = OrderLifecycleService(session_factory=session_factory)

        await lifecycle.handle_payment_succeeded(order_id, payment_id="pay_existing")

        mock_session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_publish_started_updates_status(self) -> None:
        order_id = uuid.uuid4()
        existing_order = OrderModel(
            id=order_id,
            user_id=123,
            target_chat_id=-100123,
            amount_kopecks=50000,
            status=OrderStatus.PAID,
            content_payload={},
            contact_info={},
        )

        session_factory, _ = build_mock_session_factory(existing_order)
        lifecycle = OrderLifecycleService(session_factory=session_factory)

        await lifecycle.handle_publish_started(order_id)
        assert existing_order.status == OrderStatus.PUBLISHING

    @pytest.mark.asyncio
    async def test_handle_publish_succeeded_sets_published(self) -> None:
        order_id = uuid.uuid4()
        existing_order = OrderModel(
            id=order_id,
            user_id=123,
            target_chat_id=-100123,
            amount_kopecks=50000,
            status=OrderStatus.PUBLISHING,
            content_payload={},
            contact_info={},
        )

        session_factory, _ = build_mock_session_factory(existing_order)
        lifecycle = OrderLifecycleService(session_factory=session_factory)

        await lifecycle.handle_publish_succeeded(order_id, published_message_id=777)

        assert existing_order.status == OrderStatus.PUBLISHED
        assert existing_order.published_message_id == 777

    @pytest.mark.asyncio
    async def test_handle_publish_failed_creates_refund_outbox_task(self) -> None:
        order_id = uuid.uuid4()
        existing_order = OrderModel(
            id=order_id,
            user_id=123,
            target_chat_id=-100123,
            amount_kopecks=50000,
            status=OrderStatus.PUBLISHING,
            content_payload={},
            contact_info={},
            payment_id="pay_123",
        )

        session_factory, mock_session = build_mock_session_factory(existing_order)
        lifecycle = OrderLifecycleService(session_factory=session_factory)

        await lifecycle.handle_publish_failed(order_id, error_reason="Bot was kicked")

        assert existing_order.status == OrderStatus.REFUND_REQUIRED
        assert existing_order.refund_details is not None
        assert existing_order.refund_details["reason"] == "Bot was kicked"

        assert mock_session.add.call_count == 1
        added_task = mock_session.add.call_args[0][0]
        assert added_task.task_type == OutboxTaskType.EXECUTE_PAYMENT_REFUND
        assert added_task.payload["order_id"] == str(order_id)
        assert added_task.payload["payment_id"] == "pay_123"

    @pytest.mark.asyncio
    async def test_handle_refund_succeeded_sets_refunded(self) -> None:
        order_id = uuid.uuid4()
        existing_order = OrderModel(
            id=order_id,
            user_id=123,
            target_chat_id=-100123,
            amount_kopecks=50000,
            status=OrderStatus.REFUND_REQUIRED,
            content_payload={},
            contact_info={},
            refund_details={"failed_at": "2026-01-01T00:00:00"},
        )

        session_factory, _ = build_mock_session_factory(existing_order)
        lifecycle = OrderLifecycleService(session_factory=session_factory)

        await lifecycle.handle_refund_succeeded(
            order_id, refund_info={"bank_refund_id": "ref_999"}
        )

        assert existing_order.status == OrderStatus.REFUNDED
        assert existing_order.refund_details["provider_response"] == {
            "bank_refund_id": "ref_999"
        }

    @pytest.mark.asyncio
    async def test_order_not_found_raises_error(self) -> None:
        order_id = uuid.uuid4()
        session_factory, _ = build_mock_session_factory(mock_order=None)
        lifecycle = OrderLifecycleService(session_factory=session_factory)

        with pytest.raises(OrderNotFoundError):
            await lifecycle.handle_publish_started(order_id)

    @pytest.mark.asyncio
    async def test_invalid_state_transition_raises_error(self) -> None:
        order_id = uuid.uuid4()
        existing_order = OrderModel(
            id=order_id,
            user_id=123,
            target_chat_id=-100123,
            amount_kopecks=50000,
            status=OrderStatus.CANCELLED,
            content_payload={},
            contact_info={},
        )

        session_factory, _ = build_mock_session_factory(existing_order)
        lifecycle = OrderLifecycleService(session_factory=session_factory)

        with pytest.raises(InvalidStateTransitionError):
            await lifecycle.handle_payment_succeeded(order_id, payment_id="pay_xxx")