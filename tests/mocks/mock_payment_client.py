"""Mock implementation of IPaymentClient for isolated cross-module testing.

Located at: tests/mocks/mock_payment_client.py
Compliant with IPaymentClient protocol, mypy --strict, and Python 3.12+.
"""

import uuid

from src.shared.contracts.payments import (
    CancelPaymentRequestDTO,
    CancelPaymentResponseDTO,
    InitPaymentRequestDTO,
    InitPaymentResponseDTO,
    IPaymentClient,
)


class MockPaymentClient(IPaymentClient):
    """Автономный мок платежного шлюза для тестирования смежных модулей платформы.

    Фиксирует историю всех вызовов init_payment и cancel_payment,
    поддерживает эмуляцию отказов и генерацию детерминированных тестовых ссылок.
    """

    def __init__(
        self,
        *,
        default_payment_url_prefix: str = "https://securepay.mock.tbank.ru/pay/",
        should_fail_init: bool = False,
        should_fail_cancel: bool = False,
        init_exception: Exception | None = None,
        cancel_exception: Exception | None = None,
    ) -> None:
        """Инициализирует мок платежного клиента.

        Args:
            default_payment_url_prefix: Префикс формируемого тестового URL оплаты.
            should_fail_init: Флаг принудительной генерации ошибки при инициализации.
            should_fail_cancel: Флаг принудительной генерации ошибки при отмене.
            init_exception: Кастомное исключение для эмуляции сбоя init_payment.
            cancel_exception: Кастомное исключение для эмуляции сбоя cancel_payment.
        """
        self.default_payment_url_prefix: str = default_payment_url_prefix
        self.should_fail_init: bool = should_fail_init
        self.should_fail_cancel: bool = should_fail_cancel
        self.init_exception: Exception | None = init_exception
        self.cancel_exception: Exception | None = cancel_exception

        # Хранилище истории вызовов для инспекции в assertions тестов
        self.init_calls: list[InitPaymentRequestDTO] = []
        self.cancel_calls: list[CancelPaymentRequestDTO] = []

    async def init_payment(
        self, data: InitPaymentRequestDTO
    ) -> InitPaymentResponseDTO:
        """Регистрирует параметры вызова и возвращает тестовые данные платежной сессии."""
        self.init_calls.append(data)

        if self.should_fail_init:
            if self.init_exception is not None:
                raise self.init_exception
            raise RuntimeError("Mock payment init failure")

        payment_id = f"mock_pay_{uuid.uuid4().hex[:12]}"
        payment_url = f"{self.default_payment_url_prefix}{payment_id}"

        return InitPaymentResponseDTO(
            payment_id=payment_id,
            payment_url=payment_url,
        )

    async def cancel_payment(
        self, data: CancelPaymentRequestDTO
    ) -> CancelPaymentResponseDTO:
        """Регистрирует параметры отмены и возвращает успешный DTO возврата средств."""
        self.cancel_calls.append(data)

        if self.should_fail_cancel:
            if self.cancel_exception is not None:
                raise self.cancel_exception
            raise RuntimeError("Mock payment cancel failure")

        return CancelPaymentResponseDTO(
            success=True,
            payment_id=data.payment_id,
            status="CANCELED",
            original_amount_kopecks=data.amount_kopecks or 100000,
            new_amount_kopecks=0,
        )

    def reset(self) -> None:
        """Сбрасывает накопленную историю вызовов и флаги эмуляции ошибок."""
        self.init_calls.clear()
        self.cancel_calls.clear()
        self.should_fail_init = False
        self.should_fail_cancel = False
        self.init_exception = None
        self.cancel_exception = None