import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.shared.contracts.orders import (
    CreateOrderInputDTO,
    IOrderInternalService,
    IOrderService,
    OrderCreatedResultDTO,
    OrderStatus,
)


@dataclass
class MockOrderState:
    """Внутреннее представление заказа в памяти мок-сервиса."""

    order_id: uuid.UUID
    user_id: int
    target_channel_id: int
    amount_kopecks: int
    status: OrderStatus
    payment_id: str | None = None
    payment_url: str | None = None
    published_message_id: int | None = None
    refund_details: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class MockOrderService(IOrderService, IOrderInternalService):
    """
    Мок-сервис заказов, реализующий контракты IOrderService и IOrderInternalService.
    Используется для unit- и integration-тестирования смежных модулей.
    """

    def __init__(
        self,
        default_price_kopecks: int = 50_000,
        default_payment_url_prefix: str = "https://mock.bank/pay/",
    ) -> None:
        self.default_price_kopecks = default_price_kopecks
        self.default_payment_url_prefix = default_payment_url_prefix

        self.orders: dict[uuid.UUID, MockOrderState] = {}

        self.create_order_calls: list[CreateOrderInputDTO] = []
        self.payment_succeeded_calls: list[dict[str, Any]] = []
        self.publish_started_calls: list[uuid.UUID] = []
        self.publish_succeeded_calls: list[dict[str, Any]] = []
        self.publish_failed_calls: list[dict[str, Any]] = []
        self.refund_succeeded_calls: list[dict[str, Any]] = []

        self.raise_on_create: Exception | None = None
        self.raise_on_lifecycle: Exception | None = None

    def reset(self) -> None:
        """Сбрасывает сохраненные заказы, флаги ошибок и историю вызовов."""
        self.orders.clear()
        self.create_order_calls.clear()
        self.payment_succeeded_calls.clear()
        self.publish_started_calls.clear()
        self.publish_succeeded_calls.clear()
        self.publish_failed_calls.clear()
        self.refund_succeeded_calls.clear()
        self.raise_on_create = None
        self.raise_on_lifecycle = None

    async def create_order(self, data: CreateOrderInputDTO) -> OrderCreatedResultDTO:
        self.create_order_calls.append(data)

        if self.raise_on_create:
            raise self.raise_on_create

        order_id = uuid.uuid4()
        payment_url = f"{self.default_payment_url_prefix}{order_id}"

        self.orders[order_id] = MockOrderState(
            order_id=order_id,
            user_id=data.user_id,
            target_channel_id=data.target_channel_id,
            amount_kopecks=self.default_price_kopecks,
            status=OrderStatus.PENDING,
            payment_url=payment_url,
        )

        return OrderCreatedResultDTO(
            order_id=str(order_id),
            payment_url=payment_url,
            amount_kopecks=self.default_price_kopecks,
        )

    async def handle_payment_succeeded(
        self, order_id: uuid.UUID, payment_id: str
    ) -> None:
        self.payment_succeeded_calls.append(
            {"order_id": order_id, "payment_id": payment_id}
        )

        if self.raise_on_lifecycle:
            raise self.raise_on_lifecycle

        if order := self.orders.get(order_id):
            order.status = OrderStatus.PAID
            order.payment_id = payment_id

    async def handle_publish_started(self, order_id: uuid.UUID) -> None:
        self.publish_started_calls.append(order_id)

        if self.raise_on_lifecycle:
            raise self.raise_on_lifecycle

        if order := self.orders.get(order_id):
            order.status = OrderStatus.PUBLISHING

    async def handle_publish_succeeded(
        self, order_id: uuid.UUID, published_message_id: int
    ) -> None:
        self.publish_succeeded_calls.append(
            {"order_id": order_id, "published_message_id": published_message_id}
        )

        if self.raise_on_lifecycle:
            raise self.raise_on_lifecycle

        if order := self.orders.get(order_id):
            order.status = OrderStatus.PUBLISHED
            order.published_message_id = published_message_id

    async def handle_publish_failed(
        self, order_id: uuid.UUID, error_reason: str
    ) -> None:
        self.publish_failed_calls.append(
            {"order_id": order_id, "error_reason": error_reason}
        )

        if self.raise_on_lifecycle:
            raise self.raise_on_lifecycle

        if order := self.orders.get(order_id):
            order.status = OrderStatus.REFUND_REQUIRED
            order.refund_details = {
                "failed_at": datetime.now(UTC).isoformat(),
                "reason": error_reason,
            }

    async def handle_refund_succeeded(
        self, order_id: uuid.UUID, refund_info: dict[str, Any]
    ) -> None:
        self.refund_succeeded_calls.append(
            {"order_id": order_id, "refund_info": refund_info}
        )

        if self.raise_on_lifecycle:
            raise self.raise_on_lifecycle

        if order := self.orders.get(order_id):
            order.status = OrderStatus.REFUNDED
            details = order.refund_details or {}
            details["refunded_at"] = datetime.now(UTC).isoformat()
            details["provider_response"] = refund_info
            order.refund_details = details

    def get_order(self, order_id: uuid.UUID | str) -> MockOrderState | None:
        """Получает заказ из внутреннего in-memory хранилища."""
        target_uuid = (
            uuid.UUID(order_id) if isinstance(order_id, str) else order_id
        )
        return self.orders.get(target_uuid)