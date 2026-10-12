import uuid
from typing import Final

from src.modules.order_domain.exceptions import InvalidStateTransitionError
from src.shared.contracts.orders import OrderStatus


class OrderStateMachine:
    """
    Детерминированная машина состояний заказа.
    Инкапсулирует правила жизненного цикла заказа, валидацию допустимых переходов
    и логику идемпотентной обработки дублирующих событий.
    """

    ALLOWED_TRANSITIONS: Final[dict[OrderStatus, frozenset[OrderStatus]]] = {
        OrderStatus.PENDING: frozenset({OrderStatus.PAID, OrderStatus.CANCELLED}),
        OrderStatus.PAID: frozenset({OrderStatus.PUBLISHING}),
        OrderStatus.PUBLISHING: frozenset(
            {OrderStatus.PUBLISHED, OrderStatus.REFUND_REQUIRED}
        ),
        OrderStatus.REFUND_REQUIRED: frozenset({OrderStatus.REFUNDED}),
        OrderStatus.PUBLISHED: frozenset(),
        OrderStatus.REFUNDED: frozenset(),
        OrderStatus.CANCELLED: frozenset(),
    }

    TERMINAL_STATUSES: Final[frozenset[OrderStatus]] = frozenset(
        {
            OrderStatus.PUBLISHED,
            OrderStatus.REFUNDED,
            OrderStatus.CANCELLED,
        }
    )

    # Карта идемпотентности: статус считается уже достигнутым, если заказ
    # находится в самом целевом статусе или в одном из последующих шагов пайплайна
    IDEMPOTENT_STATUSES: Final[dict[OrderStatus, frozenset[OrderStatus]]] = {
        OrderStatus.PAID: frozenset(
            {
                OrderStatus.PAID,
                OrderStatus.PUBLISHING,
                OrderStatus.PUBLISHED,
            }
        ),
        OrderStatus.PUBLISHING: frozenset(
            {
                OrderStatus.PUBLISHING,
                OrderStatus.PUBLISHED,
            }
        ),
        OrderStatus.PUBLISHED: frozenset({OrderStatus.PUBLISHED}),
        OrderStatus.REFUND_REQUIRED: frozenset(
            {
                OrderStatus.REFUND_REQUIRED,
                OrderStatus.REFUNDED,
            }
        ),
        OrderStatus.REFUNDED: frozenset({OrderStatus.REFUNDED}),
        OrderStatus.CANCELLED: frozenset({OrderStatus.CANCELLED}),
    }

    @classmethod
    def is_transition_allowed(
        cls, current_status: OrderStatus, target_status: OrderStatus
    ) -> bool:
        """Проверяет, разрешен ли прямой переход из текущего статуса в целевой."""
        return target_status in cls.ALLOWED_TRANSITIONS.get(current_status, frozenset())

    @classmethod
    def is_idempotent(
        cls, current_status: OrderStatus, target_status: OrderStatus
    ) -> bool:
        """
        Проверяет, является ли операция повторной и идемпотентной.
        Возвращает True, если текущий статус подтверждает, что целевой статус
        уже был успешно пройден ранее.
        """
        return current_status in cls.IDEMPOTENT_STATUSES.get(target_status, frozenset())

    @classmethod
    def is_terminal(cls, status: OrderStatus) -> bool:
        """Возвращает True, если статус является финальным (терминальным)."""
        return status in cls.TERMINAL_STATUSES

    @classmethod
    def validate_transition(
        cls,
        current_status: OrderStatus,
        target_status: OrderStatus,
        order_id: uuid.UUID | str | None = None,
    ) -> bool:
        """
        Валидирует допустимость перехода статуса.

        :param current_status: Текущий статус заказа в БД.
        :param target_status: Желаемый новый статус.
        :param order_id: Идентификатор заказа (для детального сообщения об ошибке).
        :return: True — переход допустим и требует выполнения мутации;
                 False — повторный/дублирующий запрос (идемпотентный no-op).
        :raises InvalidStateTransitionError: если переход нарушает бизнес-правила.
        """
        if cls.is_idempotent(current_status, target_status):
            return False

        if not cls.is_transition_allowed(current_status, target_status):
            raise InvalidStateTransitionError(
                current_status=str(current_status),
                target_status=str(target_status),
                order_id=order_id,
            )

        return True
