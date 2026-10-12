"""FastAPI Webhook router for T-Bank Acquiring notifications.

Located at: src/modules/payment_gateway/routers/webhook_router.py
Mounts endpoint: POST /api/v1/payments/tbank/webhook
Compliant with Section 5 and Section 7.2 of Payment Gateway specification,
FastAPI 0.115+, mypy --strict, and Python 3.12+.
"""

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from src.modules.payment_gateway.config import (
    PaymentGatewayConfig,
    get_payment_gateway_config,
)
from src.modules.payment_gateway.hasher import verify_tbank_token
from src.shared.contracts.orders import IOrderInternalService

logger = logging.getLogger(__name__)

# Маршрутизатор с базовым префиксом согласно ТЗ
router: APIRouter = APIRouter(
    prefix="/api/v1/payments/tbank",
    tags=["Payments Webhook"],
)


def get_order_service() -> IOrderInternalService:
    """Точка инжекции зависимости IOrderInternalService.

    Переопределяется в runtime-процессе (src/apps/api_runner.py) через:
    app.dependency_overrides[get_order_service] = ...
    """
    raise NotImplementedError(
        "IOrderInternalService provider must be registered in application container"
    )


@router.post(
    "/webhook",
    response_class=Response,
    status_code=status.HTTP_200_OK,
    summary="Прием нотификаций от эквайринга Т-Банка",
    description=(
        "Обрабатывает входящие callback-уведомления. Выполняет двухфакторную проверку "
        "(TerminalKey + SHA-256 Token) и возвращает строго 'OK' text/plain."
    ),
)
async def handle_tbank_webhook(
    request: Request,
    config: Annotated[PaymentGatewayConfig, Depends(get_payment_gateway_config)],
    order_service: Annotated[IOrderInternalService, Depends(get_order_service)],
) -> Response:
    """Обрабатывает входящее HTTP-уведомление от шлюза Т-Банка.

    Returns:
        Response с телом 'OK' и media_type='text/plain'.

    Raises:
        HTTPException(400): При некорректном JSON, битой подписи или невалидном OrderId.
        HTTPException(403): При несовпадении TerminalKey мерчанта.
        HTTPException(500): При транзиентных ошибках домена заказов (для повторов банка).
    """
    # 0. Извлечение и валидация тела JSON
    try:
        payload: dict[str, Any] = await request.json()
    except Exception as exc:
        logger.warning("Failed to parse webhook JSON body: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        ) from exc

    # 1. Шаг 1: Проверка TerminalKey (защита от подмены мерчанта)
    received_terminal_key = payload.get("TerminalKey")
    if received_terminal_key != config.terminal_key:
        logger.warning(
            "Отклонен вебхук с некорректным TerminalKey: %s (ожидался %s)",
            received_terminal_key,
            config.terminal_key,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="TerminalKey mismatch",
        )

    # 2. Шаг 2 и 3: Проверка цифровой подписи SHA-256 (Token)
    received_token = payload.get("Token")
    if not isinstance(received_token, str):
        logger.warning("Отсутствует или невалиден параметр Token в теле вебхука")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Token parameter",
        )

    secret_password = config.secret_password.get_secret_value()
    is_valid_signature = verify_tbank_token(
        payload=payload,
        secret_password=secret_password,
        expected_token=received_token,
    )

    if not is_valid_signature:
        logger.error(
            "Ошибка подписи вебхука Т-Банка для OrderId=%s, получен токен=%s",
            payload.get("OrderId"),
            received_token,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid token signature",
        )

    # 3. Маршрутизация статуса
    payment_status = str(payload.get("Status", ""))
    order_id_raw = payload.get("OrderId")
    payment_id = str(payload.get("PaymentId", ""))

    logger.info(
        "Получен валидный вебхук Т-Банка: OrderId=%s, Status=%s, PaymentId=%s",
        order_id_raw,
        payment_status,
        payment_id,
    )

    # 4. Обработка успешного списания (CONFIRMED)
    if payment_status == "CONFIRMED":
        if not order_id_raw:
            logger.error("Вебхук со статусом CONFIRMED не содержит OrderId")
            return Response(content="OK", media_type="text/plain", status_code=200)

        try:
            order_id = uuid.UUID(str(order_id_raw))
        except (ValueError, TypeError) as exc:
            logger.error("Некорректный формат UUID для OrderId: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Malformed OrderId UUID: {order_id_raw}",
            ) from exc

        try:
            await order_service.handle_payment_succeeded(order_id, payment_id)
        except Exception as exc:
            logger.exception("Ошибка при обработке успешного платежа в домене")
            # Возврат HTTP 500 предписан ТЗ, чтобы банк повторил доставку при транзиентном сбое БД
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Domain processing failure",
            ) from exc

    # Другие статусы (AUTHORIZED, REJECTED, REFUNDED) логируются, возвращается OK
    return Response(
        content="OK",
        media_type="text/plain",
        status_code=status.HTTP_200_OK,
    )