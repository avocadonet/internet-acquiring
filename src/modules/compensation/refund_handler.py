import logging
import uuid
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from src.modules.compensation.alerter import TelegramIncidentAlerter
from src.modules.compensation.customer_notifier import CustomerNotifierService
from src.modules.compensation.exceptions import BankRefundRejectedError
from src.shared.contracts.orders import IOrderInternalService
from src.shared.contracts.outbox import (
    FatalTaskError,
    IOutboxTaskHandler,
    RetryableTaskError,
    TaskContextDTO,
)
from src.shared.contracts.payments import (
    CancelPaymentRequestDTO,
    IPaymentClient,
)

logger = logging.getLogger(__name__)


class ExecuteRefundPayloadDTO(BaseModel):
    """Полезная нагрузка Outbox-задачи на возврат денежных средств."""

    order_id: uuid.UUID
    payment_id: str
    amount_kopecks: int = Field(gt=0, description="Сумма возврата в копейках")
    reason: str
    customer_telegram_id: int | None = Field(
        default=None,
        description="Telegram ID заказчика для нотификации в боте",
    )


class RefundTaskHandler(IOutboxTaskHandler):
    """Обработчик Outbox-задачи OutboxTaskType.EXECUTE_PAYMENT_REFUND."""

    def __init__(
        self,
        payment_client: IPaymentClient,
        order_service: IOrderInternalService,
        alerter: TelegramIncidentAlerter,
        customer_notifier: CustomerNotifierService,
    ) -> None:
        self.payment_client = payment_client
        self.order_service = order_service
        self.alerter = alerter
        self.customer_notifier = customer_notifier

    async def handle(self, context: TaskContextDTO) -> None:
        """Выполняет процедуру возврата средств через эквайринг и нотификацию."""
        try:
            payload = ExecuteRefundPayloadDTO.model_validate(context.payload)
        except ValidationError as exc:
            logger.error(
                "Невалидный payload задачи возврата %s: %s", context.task_id, exc
            )
            raise FatalTaskError(f"Corrupted refund payload: {exc}") from exc

        order_id = payload.order_id
        payment_id = payload.payment_id

        logger.info(
            "Старт процедуры возврата средств по заказу %s (Payment ID: %s, task_id: %s)",
            order_id,
            payment_id,
            context.task_id,
        )

        try:
            # 1. Запрос отмены/возврата к API банка
            cancel_response = await self.payment_client.cancel_payment(
                CancelPaymentRequestDTO(
                    payment_id=payment_id,
                    amount_kopecks=payload.amount_kopecks,
                )
            )

            if not cancel_response.success:
                raise BankRefundRejectedError(
                    f"Банк вернул неуспешный статус: {cancel_response.status}"
                )

            # 2. Фиксация результата в доменном слое заказов
            refund_info: dict[str, Any] = {
                "payment_id": payment_id,
                "refunded_amount_kopecks": cancel_response.new_amount_kopecks,
                "bank_status": cancel_response.status,
                "reason": payload.reason,
            }
            await self.order_service.handle_refund_succeeded(
                order_id=order_id,
                refund_info=refund_info,
            )

            # 3. Информирование заказчика в боте (с мягким подавлением сбоев доставки)
            if payload.customer_telegram_id is not None:
                await self.customer_notifier.notify_refund_completed(
                    customer_telegram_id=payload.customer_telegram_id,
                    order_id=order_id,
                    amount_kopecks=payload.amount_kopecks,
                    reason=payload.reason,
                )
            else:
                logger.info(
                    "customer_telegram_id не передан для заказа %s, нотификация в боте пропущена",
                    order_id,
                )

            # 4. Отправка информационного алерта администраторам
            await self.alerter.send_info_alert(
                title="Автоматический возврат выполнен",
                order_id=order_id,
                amount_kopecks=payload.amount_kopecks,
                reason=payload.reason,
            )

        except (RetryableTaskError, FatalTaskError):
            raise
        except Exception as e:
            err_msg = str(e).lower()
            is_network_timeout = (
                isinstance(e, TimeoutError)
                or "timeout" in err_msg
                or "connect" in err_msg
                or "network" in err_msg
            )

            if is_network_timeout:
                logger.warning(
                    "Сетевая ошибка при возврате средств по заказу %s: %s",
                    order_id,
                    e,
                )
                raise RetryableTaskError(
                    f"Network or timeout error during refund: {e}"
                ) from e

            logger.critical(
                "Фатальный сбой при возврате средств по заказу %s: %s",
                order_id,
                e,
            )
            raise FatalTaskError(f"Bank refund rejected or failed: {e}") from e

    async def on_fatal_failure(self, context: TaskContextDTO, error: str) -> None:
        """Хук окончательного сбоя задачи: отправка критического алерта дежурным."""
        payload_data = context.payload
        order_id_raw = payload_data.get("order_id")
        order_id: uuid.UUID
        if isinstance(order_id_raw, uuid.UUID):
            order_id = order_id_raw
        elif order_id_raw:
            try:
                order_id = uuid.UUID(str(order_id_raw))
            except (ValueError, TypeError):
                order_id = uuid.uuid4()
        else:
            order_id = uuid.uuid4()

        payment_id = str(payload_data.get("payment_id", "UNKNOWN_PAYMENT_ID"))
        amount_kopecks = int(payload_data.get("amount_kopecks", 0))
        reason = str(payload_data.get("reason", "Причина не указана"))

        logger.critical(
            "КРИТИЧЕСКИЙ ИНЦИДЕНТ: Не удалось автоматически вернуть средства по заказу %s: %s",
            order_id,
            error,
        )

        await self.alerter.send_critical_alert(
            title="СБОЙ КОМПЕНСАЦИИ: ДЕНЬГИ НЕ ВОЗВРАЩЕНЫ",
            order_id=order_id,
            payment_id=payment_id,
            amount_kopecks=amount_kopecks,
            error_message=error,
            publish_failure_reason=reason,
            task_id=context.task_id,
        )
