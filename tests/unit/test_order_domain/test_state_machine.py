import uuid

import pytest

from src.modules.order_domain.exceptions import InvalidStateTransitionError
from src.modules.order_domain.state_machine import OrderStateMachine
from src.shared.contracts.orders import OrderStatus


class TestOrderStateMachine:
    """Набор тестов для проверки матрицы переходов OrderStateMachine."""

    @pytest.mark.parametrize(
        "current_status,target_status",
        [
            (OrderStatus.PENDING, OrderStatus.PAID),
            (OrderStatus.PENDING, OrderStatus.CANCELLED),
            (OrderStatus.PAID, OrderStatus.PUBLISHING),
            (OrderStatus.PUBLISHING, OrderStatus.PUBLISHED),
            (OrderStatus.PUBLISHING, OrderStatus.REFUND_REQUIRED),
            (OrderStatus.REFUND_REQUIRED, OrderStatus.REFUNDED),
        ],
    )
    def test_valid_transitions_allowed(
        self, current_status: OrderStatus, target_status: OrderStatus
    ) -> None:
        """Проверяет, что все разрешенные правилами переходы возвращают True."""
        assert (
            OrderStateMachine.is_transition_allowed(current_status, target_status)
            is True
        )

        order_id = uuid.uuid4()
        result = OrderStateMachine.validate_transition(
            current_status=current_status,
            target_status=target_status,
            order_id=order_id,
        )
        assert result is True

    @pytest.mark.parametrize(
        "current_status,target_status",
        [
            # Попытки перепрыгнуть через статусы
            (OrderStatus.PENDING, OrderStatus.PUBLISHING),
            (OrderStatus.PENDING, OrderStatus.PUBLISHED),
            (OrderStatus.PENDING, OrderStatus.REFUND_REQUIRED),
            (OrderStatus.PENDING, OrderStatus.REFUNDED),
            (OrderStatus.PAID, OrderStatus.PUBLISHED),
            (OrderStatus.PAID, OrderStatus.REFUNDED),
            (OrderStatus.PAID, OrderStatus.CANCELLED),
            # Попытки мутации из терминальных состояний
            (OrderStatus.PUBLISHED, OrderStatus.PENDING),
            (OrderStatus.PUBLISHED, OrderStatus.REFUND_REQUIRED),
            (OrderStatus.PUBLISHED, OrderStatus.CANCELLED),
            (OrderStatus.REFUNDED, OrderStatus.PAID),
            (OrderStatus.CANCELLED, OrderStatus.PAID),
            (OrderStatus.CANCELLED, OrderStatus.PENDING),
            # Недопустимые откаты назад
            (OrderStatus.PUBLISHING, OrderStatus.PENDING),
            (OrderStatus.REFUND_REQUIRED, OrderStatus.PUBLISHING),
            (OrderStatus.REFUND_REQUIRED, OrderStatus.PAID),
        ],
    )
    def test_invalid_transitions_raise_error(
        self, current_status: OrderStatus, target_status: OrderStatus
    ) -> None:
        """Проверяет, что несанкционированные переходы блокируются исключением."""
        assert (
            OrderStateMachine.is_transition_allowed(current_status, target_status)
            is False
        )

        order_id = uuid.uuid4()
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            OrderStateMachine.validate_transition(
                current_status=current_status,
                target_status=target_status,
                order_id=order_id,
            )

        assert exc_info.value.current_status == str(current_status)
        assert exc_info.value.target_status == str(target_status)
        assert exc_info.value.order_id == order_id

    @pytest.mark.parametrize(
        "current_status,target_status",
        [
            # Повторный вебхук оплаты, когда заказ уже оплачен или продвинулся дальше
            (OrderStatus.PAID, OrderStatus.PAID),
            (OrderStatus.PUBLISHING, OrderStatus.PAID),
            (OrderStatus.PUBLISHED, OrderStatus.PAID),
            # Повторный сигнал старта публикации
            (OrderStatus.PUBLISHING, OrderStatus.PUBLISHING),
            (OrderStatus.PUBLISHED, OrderStatus.PUBLISHING),
            # Повторное подтверждение успешной публикации
            (OrderStatus.PUBLISHED, OrderStatus.PUBLISHED),
            # Повторный сбой публикации
            (OrderStatus.REFUND_REQUIRED, OrderStatus.REFUND_REQUIRED),
            (OrderStatus.REFUNDED, OrderStatus.REFUND_REQUIRED),
            # Повторный сигнал завершения возврата
            (OrderStatus.REFUNDED, OrderStatus.REFUNDED),
            # Повторная отмена
            (OrderStatus.CANCELLED, OrderStatus.CANCELLED),
        ],
    )
    def test_idempotent_transitions_return_false(
        self, current_status: OrderStatus, target_status: OrderStatus
    ) -> None:
        """
        Проверяет идемпотентность: повторный приход событий не должен вызывать исключений,
        но метод должен вернуть False, сигнализируя об отсутствии необходимости мутаций.
        """
        assert OrderStateMachine.is_idempotent(current_status, target_status) is True

        result = OrderStateMachine.validate_transition(
            current_status=current_status,
            target_status=target_status,
        )
        assert result is False

    @pytest.mark.parametrize(
        "status,expected_terminal",
        [
            (OrderStatus.PENDING, False),
            (OrderStatus.PAID, False),
            (OrderStatus.PUBLISHING, False),
            (OrderStatus.REFUND_REQUIRED, False),
            (OrderStatus.PUBLISHED, True),
            (OrderStatus.REFUNDED, True),
            (OrderStatus.CANCELLED, True),
        ],
    )
    def test_terminal_statuses(
        self, status: OrderStatus, expected_terminal: bool
    ) -> None:
        """Проверяет корректность определения терминальных (конечных) статусов."""
        assert OrderStateMachine.is_terminal(status) is expected_terminal
