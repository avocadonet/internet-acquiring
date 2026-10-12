"""Unit and integration tests for T-Bank Acquiring HTTP client.

Located at: tests/unit/test_payment_gateway/test_client.py
Uses respx for mocking httpx AsyncClient calls.
Compliant with pytest, respx, mypy --strict, and Python 3.12+.
"""

import json
import uuid

import httpx
import pytest
import respx
from pydantic import HttpUrl, SecretStr

from src.modules.payment_gateway.client import TBankPaymentClient
from src.modules.payment_gateway.config import PaymentGatewayConfig
from src.modules.payment_gateway.exceptions import (
    PaymentGatewayTimeoutError,
    TBankAPIError,
)
from src.shared.contracts.orders import CustomerContactDTO
from src.shared.contracts.payments import (
    CancelPaymentRequestDTO,
    InitPaymentRequestDTO,
)


@pytest.fixture
def mock_config() -> PaymentGatewayConfig:
    """Фикстура тестовой конфигурации шлюза Т-Банка."""
    return PaymentGatewayConfig(
        terminal_key="TestTerminal123",
        secret_password=SecretStr("super_secret_pass"),
        api_url=HttpUrl("https://rest-api-test.tinkoff.ru/v2"),
        taxation="usn_income",
        item_tax="none",
        timeout_connect=1.0,
        timeout_read=2.0,
        timeout_write=1.0,
    )


class TestTBankPaymentClientInit:
    """Набор тестов для метода init_payment (/v2/Init)."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_init_payment_success(
        self, mock_config: PaymentGatewayConfig
    ) -> None:
        """Успешная инициализация платежа с генерацией чека 54-ФЗ и валидацией подписи."""
        order_id = uuid.uuid4()
        init_route = respx.post(
            f"{mock_config.base_url_str}/Init"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "Success": True,
                    "ErrorCode": "0",
                    "TerminalKey": "TestTerminal123",
                    "Status": "NEW",
                    "PaymentId": "987654321",
                    "OrderId": str(order_id),
                    "Amount": 150000,
                    "PaymentURL": "https://securepay.tinkoff.ru/rest/Authorize/987654321",
                },
            )
        )

        client = TBankPaymentClient(config=mock_config)
        request_dto = InitPaymentRequestDTO(
            order_id=order_id,
            amount_kopecks=150000,
            description="Размещение рекламы в канале",
            contact=CustomerContactDTO(
                email="buyer@test.com",
                phone="+79991234567",
            ),
        )

        result = await client.init_payment(request_dto)

        # Проверка ответа DTO
        assert result.payment_id == "987654321"
        assert result.payment_url == "https://securepay.tinkoff.ru/rest/Authorize/987654321"

        # Проверка параметров исходящего HTTP-запроса
        assert init_route.called
        sent_request = init_route.calls.last.request
        sent_json = sent_request.read().decode("utf-8")
        payload = json.loads(sent_json)

        assert payload["TerminalKey"] == "TestTerminal123"
        assert payload["Amount"] == 150000
        assert payload["OrderId"] == str(order_id)
        assert "Token" in payload
        assert "Receipt" in payload
        assert payload["Receipt"]["Email"] == "buyer@test.com"
        assert payload["Receipt"]["Phone"] == "+79991234567"
        assert payload["Receipt"]["Items"][0]["Price"] == 150000

    @pytest.mark.asyncio
    @respx.mock
    async def test_init_payment_business_error_raises_tbank_api_error(
        self, mock_config: PaymentGatewayConfig
    ) -> None:
        """Банк вернул Success=False (бизнес-ошибка шлюза)."""
        respx.post(f"{mock_config.base_url_str}/Init").mock(
            return_value=httpx.Response(
                200,
                json={
                    "Success": False,
                    "ErrorCode": "7",
                    "Message": "Неверные реквизиты терминала",
                    "Details": "Terminal blocked",
                },
            )
        )

        client = TBankPaymentClient(config=mock_config)
        request_dto = InitPaymentRequestDTO(
            order_id=uuid.uuid4(),
            amount_kopecks=10000,
            description="Тестовый заказ",
            contact=CustomerContactDTO(email="user@test.org"),
        )

        with pytest.raises(TBankAPIError) as exc_info:
            await client.init_payment(request_dto)

        assert exc_info.value.error_code == "7"
        assert "Неверные реквизиты терминала" in exc_info.value.message

    @pytest.mark.asyncio
    @respx.mock
    async def test_init_payment_http_error_raises_tbank_api_error(
        self, mock_config: PaymentGatewayConfig
    ) -> None:
        """Сервер банка вернул HTTP 503 Service Unavailable."""
        respx.post(f"{mock_config.base_url_str}/Init").mock(
            return_value=httpx.Response(503, text="Service Unavailable")
        )

        client = TBankPaymentClient(config=mock_config)
        request_dto = InitPaymentRequestDTO(
            order_id=uuid.uuid4(),
            amount_kopecks=10000,
            description="Заказ",
            contact=CustomerContactDTO(email="user@test.org"),
        )

        with pytest.raises(TBankAPIError) as exc_info:
            await client.init_payment(request_dto)

        assert exc_info.value.http_status == 503

    @pytest.mark.asyncio
    @respx.mock
    async def test_init_payment_timeout_raises_gateway_timeout_error(
        self, mock_config: PaymentGatewayConfig
    ) -> None:
        """Превышение таймаута чтения ответа приводит к PaymentGatewayTimeoutError."""
        respx.post(f"{mock_config.base_url_str}/Init").mock(
            side_effect=httpx.ReadTimeout("Read timed out")
        )

        client = TBankPaymentClient(config=mock_config)
        request_dto = InitPaymentRequestDTO(
            order_id=uuid.uuid4(),
            amount_kopecks=10000,
            description="Таймаут тест",
            contact=CustomerContactDTO(email="user@test.org"),
        )

        with pytest.raises(PaymentGatewayTimeoutError) as exc_info:
            await client.init_payment(request_dto)

        assert "Timeout exceeded" in exc_info.value.message


class TestTBankPaymentClientCancel:
    """Набор тестов для метода cancel_payment (/v2/Cancel)."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_cancel_payment_full_success(
        self, mock_config: PaymentGatewayConfig
    ) -> None:
        """Успешная полная отмена/возврат транзакции."""
        cancel_route = respx.post(
            f"{mock_config.base_url_str}/Cancel"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "Success": True,
                    "ErrorCode": "0",
                    "TerminalKey": "TestTerminal123",
                    "Status": "REFUNDED",
                    "PaymentId": "11223344",
                    "OriginalAmount": 50000,
                    "NewAmount": 0,
                },
            )
        )

        client = TBankPaymentClient(config=mock_config)
        request_dto = CancelPaymentRequestDTO(
            payment_id="11223344",
            amount_kopecks=None,  # Полная отмена
        )

        result = await client.cancel_payment(request_dto)

        assert result.success is True
        assert result.payment_id == "11223344"
        assert result.status == "REFUNDED"
        assert result.original_amount_kopecks == 50000
        assert result.new_amount_kopecks == 0

        assert cancel_route.called
        sent_payload = cancel_route.calls.last.request.read().decode("utf-8")
        assert "Amount" not in sent_payload  # При полной отмене поле Amount не передается

    @pytest.mark.asyncio
    @respx.mock
    async def test_cancel_payment_partial_amount_included(
        self, mock_config: PaymentGatewayConfig
    ) -> None:
        """Частичный возврат передает параметр Amount в запросе."""
        cancel_route = respx.post(
            f"{mock_config.base_url_str}/Cancel"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "Success": True,
                    "ErrorCode": "0",
                    "PaymentId": "11223344",
                    "Status": "PARTIALLY_REFUNDED",
                    "OriginalAmount": 100000,
                    "NewAmount": 80000,
                },
            )
        )

        client = TBankPaymentClient(config=mock_config)
        request_dto = CancelPaymentRequestDTO(
            payment_id="11223344",
            amount_kopecks=20000,  # Частичная сумма
        )

        result = await client.cancel_payment(request_dto)

        assert result.success is True
        assert result.new_amount_kopecks == 80000

        sent_payload = cancel_route.calls.last.request.read().decode("utf-8")
        assert '"Amount": 20000' in sent_payload or '"Amount":20000' in sent_payload

    @pytest.mark.asyncio
    @respx.mock
    async def test_cancel_payment_failure_raises_tbank_api_error(
        self, mock_config: PaymentGatewayConfig
    ) -> None:
        """Отказ в отмене транзакции банком вызывает TBankAPIError."""
        respx.post(f"{mock_config.base_url_str}/Cancel").mock(
            return_value=httpx.Response(
                200,
                json={
                    "Success": False,
                    "ErrorCode": "104",
                    "Message": "Транзакция уже отменена",
                },
            )
        )

        client = TBankPaymentClient(config=mock_config)
        request_dto = CancelPaymentRequestDTO(payment_id="99999999")

        with pytest.raises(TBankAPIError) as exc_info:
            await client.cancel_payment(request_dto)

        assert exc_info.value.error_code == "104"
        assert "Транзакция уже отменена" in exc_info.value.message