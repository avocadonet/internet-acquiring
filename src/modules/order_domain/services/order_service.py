import uuid
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.order_domain.exceptions import PaymentInitializationError
from src.modules.order_domain.models import OrderModel
from src.modules.order_domain.repository import OrderRepository
from src.modules.order_domain.services.pricing_service import PricingService
from src.shared.contracts.orders import (
    CreateOrderInputDTO,
    IOrderService,
    OrderCreatedResultDTO,
    OrderStatus,
)
from src.shared.contracts.payments import InitPaymentRequestDTO, IPaymentClient


class OrderService(IOrderService):
    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        payment_client: IPaymentClient,
        pricing_service: PricingService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._payment_client = payment_client
        self._pricing_service = pricing_service or PricingService()

    async def create_order(self, data: CreateOrderInputDTO) -> OrderCreatedResultDTO:
        amount_kopecks = self._pricing_service.calculate_amount_kopecks(
            target_channel_id=data.target_channel_id
        )

        order_id = uuid.uuid4()

        init_payment_payload = InitPaymentRequestDTO(
            order_id=order_id,
            amount_kopecks=amount_kopecks,
            description=f"Рекламное размещение в канале {data.target_channel_id}",
            contact=data.contact,
        )

        try:
            payment_response = await self._payment_client.init_payment(
                init_payment_payload
            )
        except Exception as exc:
            raise PaymentInitializationError(
                order_id=order_id,
                original_error=exc,
            ) from exc

        order = OrderModel(
            id=order_id,
            user_id=data.user_id,
            target_chat_id=data.target_channel_id,
            amount_kopecks=amount_kopecks,
            status=OrderStatus.PENDING,
            content_payload=data.content.model_dump(mode="json"),
            contact_info=data.contact.model_dump(mode="json"),
            payment_id=payment_response.payment_id,
            payment_url=payment_response.payment_url,
        )

        async with self._session_factory() as session, session.begin():
            repository = OrderRepository(session)
            await repository.create(order)

        return OrderCreatedResultDTO(
            order_id=str(order_id),
            payment_url=payment_response.payment_url,
            amount_kopecks=amount_kopecks,
        )