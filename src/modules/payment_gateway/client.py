"""T-Bank Acquiring v2 asynchronous client implementation.

Implements IPaymentClient contract from shared layer.
Handles /v2/Init and /v2/Cancel endpoints with 54-FZ fiscalization and SHA-256 tokens.
Compliant with mypy --strict, httpx 0.27+, and Python 3.12+.
"""

from typing import Any

import httpx

from src.modules.payment_gateway.config import (
    PaymentGatewayConfig,
    get_payment_gateway_config,
)
from src.modules.payment_gateway.exceptions import (
    PaymentGatewayTimeoutError,
    TBankAPIError,
    TBankNetworkError,
)
from src.modules.payment_gateway.hasher import generate_tbank_token
from src.modules.payment_gateway.receipt import ReceiptBuilder
from src.shared.contracts.payments import (
    CancelPaymentRequestDTO,
    CancelPaymentResponseDTO,
    InitPaymentRequestDTO,
    InitPaymentResponseDTO,
    IPaymentClient,
)


class TBankPaymentClient(IPaymentClient):
    """Асинхронный HTTP-клиент интернет-эквайринга Т-Банка (v2 API)."""

    def __init__(
        self,
        config: PaymentGatewayConfig | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Инициализирует платежный клиент.

        Args:
            config: Экземпляр конфигурации. Если None, используется get_payment_gateway_config().
            http_client: Внешний AsyncClient (для пулинга соединений или тестирования через respx).
        """
        self._config: PaymentGatewayConfig = config or get_payment_gateway_config()
        self._external_client: httpx.AsyncClient | None = http_client
        self._timeout = httpx.Timeout(
            connect=self._config.timeout_connect,
            read=self._config.timeout_read,
            write=self._config.timeout_write,
            pool=5.0,
        )
        self._receipt_builder = ReceiptBuilder(
            taxation=self._config.taxation,
            default_tax=self._config.item_tax,
        )

    def _get_http_client(self) -> httpx.AsyncClient:
        """Возвращает существующий AsyncClient или создает изолированный с таймаутами."""
        if self._external_client is not None:
            return self._external_client
        return httpx.AsyncClient(timeout=self._timeout)

    async def init_payment(
        self, data: InitPaymentRequestDTO
    ) -> InitPaymentResponseDTO:
        """Регистрирует платеж в Т-Банке, формирует чек 54-ФЗ и возвращает ссылку на оплату.

        Args:
            data: Входные параметры заказа и контакты покупателя.

        Returns:
            InitPaymentResponseDTO с payment_id и payment_url.

        Raises:
            PaymentGatewayTimeoutError: При превышении таймаута ответа шлюза.
            TBankAPIError: Если банк вернул ошибку проведения операции (Success=False или HTTP-ошибка).
            TBankNetworkError: При сетевом сбое подключения к шлюзу.
            FiscalizationError: Если контакты покупателя или суммы чека невалидны.
        """
        # 1. Генерация фискального чека 54-ФЗ
        receipt_payload = self._receipt_builder.build_receipt(
            amount_kopecks=data.amount_kopecks,
            description=data.description,
            contact=data.contact,
        )

        # 2. Подготовка тела запроса к /v2/Init
        payload: dict[str, Any] = {
            "TerminalKey": self._config.terminal_key,
            "Amount": data.amount_kopecks,
            "OrderId": str(data.order_id),
            "Description": data.description[:250],
            "Receipt": receipt_payload,
        }

        # 3. Расчет криптографической подписи SHA-256
        secret_password = self._config.secret_password.get_secret_value()
        payload["Token"] = generate_tbank_token(payload, secret_password)

        # 4. Выполнение сетевого запроса
        url = f"{self._config.base_url_str}/Init"
        client = self._get_http_client()
        should_close = self._external_client is None

        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            res_json: dict[str, Any] = response.json()
        except httpx.TimeoutException as exc:
            raise PaymentGatewayTimeoutError(
                f"Timeout exceeded during T-Bank /v2/Init call: {exc}",
                original_error=exc,
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise TBankAPIError(
                f"T-Bank Init HTTP {exc.response.status_code} error: {exc.response.text}",
                http_status=exc.response.status_code,
            ) from exc
        except httpx.RequestError as exc:
            raise TBankNetworkError(
                f"Failed to connect to T-Bank API Init: {exc}",
                original_error=exc,
            ) from exc
        finally:
            if should_close:
                await client.aclose()

        # 5. Проверка бизнес-статуса ответа банка
        if not res_json.get("Success", False):
            raise TBankAPIError(
                message=str(res_json.get("Message", "T-Bank Init failed")),
                error_code=str(res_json.get("ErrorCode", "")),
                response_payload=res_json,
            )

        return InitPaymentResponseDTO(
            payment_id=str(res_json["PaymentId"]),
            payment_url=str(res_json["PaymentURL"]),
        )

    async def cancel_payment(
        self, data: CancelPaymentRequestDTO
    ) -> CancelPaymentResponseDTO:
        """Отменяет транзакцию / выполняет возврат средств через POST /v2/Cancel.

        Args:
            data: DTO с идентификатором платежа и суммой отмены (None для полной отмены).

        Returns:
            CancelPaymentResponseDTO со статусом и остатком суммы.

        Raises:
            PaymentGatewayTimeoutError: При сетевом таймауте ответа.
            TBankAPIError: Если отмена отклонена банком.
            TBankNetworkError: При сетевом сбое.
        """
        # 1. Подготовка тела запроса к /v2/Cancel
        payload: dict[str, Any] = {
            "TerminalKey": self._config.terminal_key,
            "PaymentId": data.payment_id,
        }

        if data.amount_kopecks is not None:
            payload["Amount"] = data.amount_kopecks

        # 2. Расчет криптографической подписи SHA-256
        secret_password = self._config.secret_password.get_secret_value()
        payload["Token"] = generate_tbank_token(payload, secret_password)

        # 3. Выполнение сетевого запроса
        url = f"{self._config.base_url_str}/Cancel"
        client = self._get_http_client()
        should_close = self._external_client is None

        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            res_json: dict[str, Any] = response.json()
        except httpx.TimeoutException as exc:
            raise PaymentGatewayTimeoutError(
                f"Timeout exceeded during T-Bank /v2/Cancel call: {exc}",
                original_error=exc,
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise TBankAPIError(
                f"T-Bank Cancel HTTP {exc.response.status_code} error: {exc.response.text}",
                http_status=exc.response.status_code,
            ) from exc
        except httpx.RequestError as exc:
            raise TBankNetworkError(
                f"Failed to connect to T-Bank API Cancel: {exc}",
                original_error=exc,
            ) from exc
        finally:
            if should_close:
                await client.aclose()

        # 4. Проверка бизнес-статуса ответа банка
        if not res_json.get("Success", False):
            raise TBankAPIError(
                message=str(res_json.get("Message", "T-Bank Cancel failed")),
                error_code=str(res_json.get("ErrorCode", "")),
                response_payload=res_json,
            )

        return CancelPaymentResponseDTO(
            success=bool(res_json.get("Success", True)),
            payment_id=str(res_json.get("PaymentId", data.payment_id)),
            status=str(res_json.get("Status", "CANCELED")),
            original_amount_kopecks=int(res_json.get("OriginalAmount", 0)),
            new_amount_kopecks=int(res_json.get("NewAmount", 0)),
        )