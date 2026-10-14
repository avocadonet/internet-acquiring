import asyncio
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.order_domain.exceptions import OrderNotFoundError
from src.modules.order_domain.models import OrderModel
from src.modules.order_domain.repository import OrderRepository
from src.modules.order_domain.state_machine import OrderStateMachine
from src.shared.contracts.orders import IOrderInternalService, OrderStatus
from src.shared.contracts.outbox import OutboxTaskType

logger = logging.getLogger(__name__)


class OrderLifecycleService(IOrderInternalService):
    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory

    async def _fetch_order_with_retry(
        self,
        order_id: uuid.UUID,
        max_attempts: int = 3,
        delay_seconds: float = 0.5,
    ) -> OrderModel:
        for attempt in range(1, max_attempts + 1):
            async with self._session_factory() as session, session.begin():
                repo = OrderRepository(session)
                order = await repo.get_by_id(order_id, for_update=True)
                if order is not None:
                    return order

            if attempt < max_attempts:
                logger.warning(
                    "Заказ %s не найден в БД (попытка %d/%d). Ожидание %s сек перед повтором.",
                    order_id,
                    attempt,
                    max_attempts,
                    delay_seconds,
                )
                await asyncio.sleep(delay_seconds)

        logger.critical(
            "CRITICAL: Заказ %s не обнаружен в базе данных после %d попыток при обработке вебхука оплаты.",
            order_id,
            max_attempts,
        )
        raise OrderNotFoundError(order_id)

    async def handle_payment_succeeded(
        self, order_id: uuid.UUID, payment_id: str
    ) -> None:
        await self._fetch_order_with_retry(order_id=order_id)

        async with self._session_factory() as session, session.begin():
            repo = OrderRepository(session)
            order = await repo.get_by_id(order_id, for_update=True)
            if not order:
                raise OrderNotFoundError(order_id)

            should_mutate = OrderStateMachine.validate_transition(
                current_status=order.status,
                target_status=OrderStatus.PAID,
                order_id=order.id,
            )
            if not should_mutate:
                logger.info(
                    "Идемпотентный пропуск: заказ %s уже находится в статусе %s",
                    order.id,
                    order.status,
                )
                return

            order.status = OrderStatus.PAID
            order.payment_id = payment_id

            outbox_payload = {
                "order_id": str(order.id),
                "target_chat_id": order.target_chat_id,
                "content": order.content_payload,
            }
            repo.add_outbox_task(
                task_type=OutboxTaskType.PUBLISH_POST,
                payload=outbox_payload,
                execute_after=datetime.now(UTC),
            )
            logger.info(
                "Заказ %s успешно переведен в статус PAID. Поставлена задача PUBLISH_POST.",
                order.id,
            )

    async def handle_publish_started(self, order_id: uuid.UUID) -> None:
        async with self._session_factory() as session, session.begin():
            repo = OrderRepository(session)
            order = await repo.get_by_id(order_id, for_update=True)
            if not order:
                raise OrderNotFoundError(order_id)

            should_mutate = OrderStateMachine.validate_transition(
                current_status=order.status,
                target_status=OrderStatus.PUBLISHING,
                order_id=order.id,
            )
            if not should_mutate:
                return

            order.status = OrderStatus.PUBLISHING
            logger.info("Заказ %s переведен в статус PUBLISHING.", order.id)

    async def handle_publish_succeeded(
        self, order_id: uuid.UUID, published_message_id: int
    ) -> None:
        async with self._session_factory() as session, session.begin():
            repo = OrderRepository(session)
            order = await repo.get_by_id(order_id, for_update=True)
            if not order:
                raise OrderNotFoundError(order_id)

            should_mutate = OrderStateMachine.validate_transition(
                current_status=order.status,
                target_status=OrderStatus.PUBLISHED,
                order_id=order.id,
            )
            if not should_mutate:
                return

            order.status = OrderStatus.PUBLISHED
            order.published_message_id = published_message_id
            logger.info(
                "Заказ %s успешно опубликован. ID сообщения: %d",
                order.id,
                published_message_id,
            )

    async def handle_publish_failed(
        self, order_id: uuid.UUID, error_reason: str
    ) -> None:
        async with self._session_factory() as session, session.begin():
            repo = OrderRepository(session)
            order = await repo.get_by_id(order_id, for_update=True)
            if not order:
                raise OrderNotFoundError(order_id)

            should_mutate = OrderStateMachine.validate_transition(
                current_status=order.status,
                target_status=OrderStatus.REFUND_REQUIRED,
                order_id=order.id,
            )
            if not should_mutate:
                logger.info(
                    "Заказ %s уже в статусе %s, повторный сбой игнорируется.",
                    order.id,
                    order.status,
                )
                return

            order.status = OrderStatus.REFUND_REQUIRED
            order.refund_details = {
                "failed_at": datetime.now(UTC).isoformat(),
                "reason": error_reason,
            }

            outbox_payload = {
                "order_id": str(order.id),
                "payment_id": order.payment_id,
                "amount_kopecks": order.amount_kopecks,
                "reason": error_reason,
                "customer_telegram_id": order.user_id,
            }
            repo.add_outbox_task(
                task_type=OutboxTaskType.EXECUTE_PAYMENT_REFUND,
                payload=outbox_payload,
                execute_after=datetime.now(UTC),
            )
            logger.warning(
                "Публикация заказа %s провалена (%s). Поставлена Outbox-задача возврата средств.",
                order.id,
                error_reason,
            )

    async def handle_refund_succeeded(
        self, order_id: uuid.UUID, refund_info: dict[str, Any]
    ) -> None:
        async with self._session_factory() as session, session.begin():
            repo = OrderRepository(session)
            order = await repo.get_by_id(order_id, for_update=True)
            if not order:
                raise OrderNotFoundError(order_id)

            should_mutate = OrderStateMachine.validate_transition(
                current_status=order.status,
                target_status=OrderStatus.REFUNDED,
                order_id=order.id,
            )
            if not should_mutate:
                return

            order.status = OrderStatus.REFUNDED
            current_details = order.refund_details or {}
            current_details.update(
                {
                    "refunded_at": datetime.now(UTC).isoformat(),
                    "provider_response": refund_info,
                }
            )
            order.refund_details = current_details
            logger.info(
                "Возврат средств по заказу %s успешно подтвержден.", order.id
            )