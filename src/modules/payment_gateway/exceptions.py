"""Exceptions hierarchy for Payment Gateway module.

Fully aligned with Section 6 and Section 8 of Payment Gateway specification.
Compliant with mypy --strict and Python 3.12+.
"""

from typing import Any


class PaymentGatewayError(Exception):
    """Базовое исключение для всех ошибок модуля payment_gateway."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidSignatureError(PaymentGatewayError):
    """Исключение при несовпадении или невозможности расчета подписи (SHA-256 Token)."""

    def __init__(
        self,
        message: str = "Invalid request signature token",
        *,
        expected_token: str | None = None,
        received_token: str | None = None,
    ) -> None:
        super().__init__(message)
        self.expected_token = expected_token
        self.received_token = received_token


class TerminalMismatchError(PaymentGatewayError):
    """Исключение при несовпадении TerminalKey запроса с конфигурацией мерчанта."""

    def __init__(
        self,
        message: str = "TerminalKey does not match configured merchant key",
        *,
        received_terminal_key: str | None = None,
    ) -> None:
        super().__init__(message)
        self.received_terminal_key = received_terminal_key


class FiscalizationError(PaymentGatewayError):
    """Исключение при ошибках валидации или формирования фискального чека 54-ФЗ."""

    def __init__(self, message: str, *, field_name: str | None = None) -> None:
        super().__init__(message)
        self.field_name = field_name


class TBankAPIError(PaymentGatewayError):
    """Исключение при возврате ошибки API Т-Банка (Success=False или HTTP 4xx/5xx)."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        http_status: int | None = None,
        response_payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.http_status = http_status
        self.response_payload = response_payload or {}


class TBankNetworkError(PaymentGatewayError):
    """Исключение при сетевых сбоях или разрыве соединения httpx."""

    def __init__(
        self,
        message: str,
        *,
        original_error: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.original_error = original_error


class PaymentGatewayTimeoutError(TBankNetworkError):
    """Исключение при превышении сетевого таймаута httpx при запросах к API Т-Банка."""

    def __init__(
        self,
        message: str = "Request to T-Bank API timed out",
        *,
        original_error: Exception | None = None,
    ) -> None:
        super().__init__(message, original_error=original_error)