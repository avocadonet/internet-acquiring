import uuid
from typing import Any


class OrderDomainError(Exception):
    """Базовое исключение доменного слоя заказов."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class OrderNotFoundError(OrderDomainError):
    """Выбрасывается, когда запрашиваемый заказ не найден в базе данных."""

    def __init__(self, order_id: uuid.UUID | str) -> None:
        self.order_id = order_id
        super().__init__(f"Заказ с идентификатором '{order_id}' не найден.")


class InvalidStateTransitionError(OrderDomainError):
    """
    Выбрасывается при попытке выполнить невалидный переход статуса заказа.
    Гарантирует детерминированность машины состояний.
    """

    def __init__(
        self,
        current_status: str,
        target_status: str,
        order_id: uuid.UUID | str | None = None,
        reason: str | None = None,
    ) -> None:
        self.current_status = current_status
        self.target_status = target_status
        self.order_id = order_id
        self.reason = reason

        details = f"Переход из статуса '{current_status}' в '{target_status}' запрещен"
        if order_id:
            details += f" для заказа {order_id}"
        if reason:
            details += f": {reason}"
        else:
            details += "."

        super().__init__(details)


class OrderPricingError(OrderDomainError):
    """Выбрасывается при невозможности определить или рассчитать стоимость для канала."""

    def __init__(self, channel_id: int, reason: str) -> None:
        self.channel_id = channel_id
        self.reason = reason
        super().__init__(f"Ошибка расчета стоимости для канала {channel_id}: {reason}")


class PaymentInitializationError(OrderDomainError):
    """Выбрасывается при критическом сбое обращения к платежному шлюзу при создании заказа."""

    def __init__(self, order_id: uuid.UUID | str, original_error: Any) -> None:
        self.order_id = order_id
        self.original_error = original_error
        super().__init__(
            f"Не удалось инициализировать платеж для заказа {order_id}: {original_error}"
        )
