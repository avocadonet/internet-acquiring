"""Integration unit tests for T-Bank Acquiring Webhook router.

Located at: tests/unit/test_payment_gateway/test_webhook.py
Tests POST /api/v1/payments/tbank/webhook endpoint.
Compliant with pytest, httpx.AsyncClient, mypy --strict, and Python 3.12+.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from pydantic import HttpUrl, SecretStr

from src.modules.payment_gateway.config import (
    PaymentGatewayConfig,
    get_payment_gateway_config,
)
from src.modules.payment_gateway.hasher import generate_tbank_token
from src.modules.payment_gateway.routers.webhook_router import (
    get_order_service,
)
from src.modules.payment_gateway.routers.webhook_router import (
    router as webhook_router,
)
from src.shared.contracts.orders import IOrderInternalService

# Константы для тестового окружения
TEST_TERMINAL_KEY = "TBankTerminalTest"
TEST_SECRET_PASSWORD = "test_merchant_secret"


@pytest.fixture
def test_config() -> PaymentGatewayConfig:
    """Фикстура конфигурации платежного шлюза для тестов роутера."""
    return PaymentGatewayConfig(
        terminal_key=TEST_TERMINAL_KEY,
        secret_password=SecretStr(TEST_SECRET_PASSWORD),
        api_url=HttpUrl("https://rest-api-test.tinkoff.ru/v2"),
        taxation="usn_income",
        item_tax="none",
    )


@pytest.fixture
def mock_order_service() -> AsyncMock:
    """Фикстура мока доменного сервиса заказов IOrderInternalService."""
    service = AsyncMock(spec=IOrderInternalService)
    service.handle_payment_succeeded.return_value = None
    return service


@pytest.fixture
def test_app(
    test_config: PaymentGatewayConfig,
    mock_order_service: AsyncMock,
) -> FastAPI:
    """Создает изолированное приложение FastAPI с зарегистрированным роутером и overrides."""
    app = FastAPI()
    app.include_router(webhook_router)

    # Инжекция зависимостей конфигурации и сервиса заказов
    app.dependency_overrides[get_payment_gateway_config] = lambda: test_config
    app.dependency_overrides[get_order_service] = lambda: mock_order_service

    return app


@pytest.fixture
async def async_client(test_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Асинхронный HTTP-клиент для вызовов тестируемого FastAPI приложения."""
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


def make_signed_payload(
    payload: dict[str, Any],
    secret_password: str = TEST_SECRET_PASSWORD,
) -> dict[str, Any]:
    """Вспомогательная функция формирования полезной нагрузки с валидной подписью Token."""
    signed = dict(payload)
    token = generate_tbank_token(signed, secret_password)
    signed["Token"] = token
    return signed


class TestTBankWebhookSecurity:
    """Тестирование контура двухфакторной безопасности входящего вебхука."""

    @pytest.mark.asyncio
    async def test_terminal_key_mismatch_returns_403(
        self, async_client: httpx.AsyncClient
    ) -> None:
        """Несовпадение TerminalKey мерчанта возвращает 403 Forbidden."""
        payload = {
            "TerminalKey": "ForeignAttackerTerminal",
            "OrderId": str(uuid.uuid4()),
            "Status": "CONFIRMED",
            "PaymentId": 123456,
        }
        signed_payload = make_signed_payload(payload)

        response = await async_client.post(
            "/api/v1/payments/tbank/webhook",
            json=signed_payload,
        )

        assert response.status_code == 403
        assert "TerminalKey mismatch" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_invalid_signature_returns_400(
        self, async_client: httpx.AsyncClient
    ) -> None:
        """Искаженная или невалидная подпись Token возвращает 400 Bad Request."""
        payload = {
            "TerminalKey": TEST_TERMINAL_KEY,
            "OrderId": str(uuid.uuid4()),
            "Status": "CONFIRMED",
            "PaymentId": 123456,
            "Token": "tampered_fake_signature_hash_123456",
        }

        response = await async_client.post(
            "/api/v1/payments/tbank/webhook",
            json=payload,
        )

        assert response.status_code == 400
        assert "Invalid token signature" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_missing_token_returns_400(
        self, async_client: httpx.AsyncClient
    ) -> None:
        """Отсутствие поля Token в запросе возвращает 400 Bad Request."""
        payload = {
            "TerminalKey": TEST_TERMINAL_KEY,
            "OrderId": str(uuid.uuid4()),
            "Status": "CONFIRMED",
        }

        response = await async_client.post(
            "/api/v1/payments/tbank/webhook",
            json=payload,
        )

        assert response.status_code == 400
        assert "Missing Token parameter" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_invalid_json_body_returns_400(
        self, async_client: httpx.AsyncClient
    ) -> None:
        """Невалидный синтаксис JSON в теле запроса возвращает 400 Bad Request."""
        response = await async_client.post(
            "/api/v1/payments/tbank/webhook",
            content=b"invalid { broken json payload",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 400
        assert "Invalid JSON payload" in response.json()["detail"]


class TestTBankWebhookStatusHandling:
    """Тестирование обработки бизнес-статусов и вызовов доменного слоя."""

    @pytest.mark.asyncio
    async def test_confirmed_status_triggers_order_domain_and_returns_ok(
        self,
        async_client: httpx.AsyncClient,
        mock_order_service: AsyncMock,
    ) -> None:
        """Статус CONFIRMED вызывает handle_payment_succeeded и возвращает строку OK."""
        target_order_id = uuid.uuid4()
        target_payment_id = "987654321"

        payload = {
            "TerminalKey": TEST_TERMINAL_KEY,
            "OrderId": str(target_order_id),
            "PaymentId": target_payment_id,
            "Status": "CONFIRMED",
            "Success": True,
            "Amount": 150000,
        }
        signed_payload = make_signed_payload(payload)

        response = await async_client.post(
            "/api/v1/payments/tbank/webhook",
            json=signed_payload,
        )

        # Проверка HTTP ответа по протоколу Т-Банка
        assert response.status_code == 200
        assert response.text == "OK"
        assert response.headers["content-type"].startswith("text/plain")

        # Проверка вызова доменного сервиса
        mock_order_service.handle_payment_succeeded.assert_awaited_once_with(
            target_order_id,
            target_payment_id,
        )

    @pytest.mark.asyncio
    async def test_confirmed_with_malformed_order_id_uuid_returns_400(
        self,
        async_client: httpx.AsyncClient,
        mock_order_service: AsyncMock,
    ) -> None:
        """Невалидный UUID в OrderId при CONFIRMED возвращает 400 Bad Request."""
        payload = {
            "TerminalKey": TEST_TERMINAL_KEY,
            "OrderId": "not-a-valid-uuid-string",
            "PaymentId": "112233",
            "Status": "CONFIRMED",
        }
        signed_payload = make_signed_payload(payload)

        response = await async_client.post(
            "/api/v1/payments/tbank/webhook",
            json=signed_payload,
        )

        assert response.status_code == 400
        assert "Malformed OrderId UUID" in response.json()["detail"]
        mock_order_service.handle_payment_succeeded.assert_not_called()

    @pytest.mark.asyncio
    async def test_domain_processing_error_returns_500_for_bank_retries(
        self,
        async_client: httpx.AsyncClient,
        mock_order_service: AsyncMock,
    ) -> None:
        """Сбой в БД домена возвращает 500, чтобы Т-Банк повторил попытку доставки вебхука."""
        mock_order_service.handle_payment_succeeded.side_effect = RuntimeError(
            "PostgreSQL transient connection timeout"
        )

        target_order_id = uuid.uuid4()
        payload = {
            "TerminalKey": TEST_TERMINAL_KEY,
            "OrderId": str(target_order_id),
            "PaymentId": "555555",
            "Status": "CONFIRMED",
        }
        signed_payload = make_signed_payload(payload)

        response = await async_client.post(
            "/api/v1/payments/tbank/webhook",
            json=signed_payload,
        )

        assert response.status_code == 500
        assert "Domain processing failure" in response.json()["detail"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("other_status", ["AUTHORIZED", "REJECTED", "REFUNDED", "3DS_CHECKING"])
    async def test_other_statuses_return_ok_without_calling_order_service(
        self,
        async_client: httpx.AsyncClient,
        mock_order_service: AsyncMock,
        other_status: str,
    ) -> None:
        """Промежуточные и сервисные статусы не дергают домен и подтверждаются ответом OK."""
        payload = {
            "TerminalKey": TEST_TERMINAL_KEY,
            "OrderId": str(uuid.uuid4()),
            "PaymentId": "777888",
            "Status": other_status,
        }
        signed_payload = make_signed_payload(payload)

        response = await async_client.post(
            "/api/v1/payments/tbank/webhook",
            json=signed_payload,
        )

        assert response.status_code == 200
        assert response.text == "OK"
        assert response.headers["content-type"].startswith("text/plain")
        mock_order_service.handle_payment_succeeded.assert_not_called()