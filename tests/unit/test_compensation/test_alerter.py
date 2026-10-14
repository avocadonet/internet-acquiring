import uuid
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.enums import ParseMode

from src.modules.compensation.alerter import IncidentAlertDTO, TelegramIncidentAlerter
from src.modules.compensation.config import CompensationConfig


@pytest.fixture
def compensation_config() -> CompensationConfig:
    return CompensationConfig(
        ADMIN_ALERT_CHAT_ID=-100123456789,
        BOT_TOKEN_ALERTS="123456:TEST_TOKEN",
    )


@pytest.mark.asyncio
async def test_send_info_alert_success(
    compensation_config: CompensationConfig,
) -> None:
    bot = AsyncMock(spec=Bot)
    alerter = TelegramIncidentAlerter(bot=bot, config=compensation_config)

    order_id = uuid.uuid4()
    amount_kopecks = 250000
    reason = "Канал <VIP_Ads> отклонил пост & удалил бота"

    await alerter.send_info_alert(
        title="Возврат средств выполнен",
        order_id=order_id,
        amount_kopecks=amount_kopecks,
        reason=reason,
    )

    bot.send_message.assert_awaited_once()
    call_kwargs = bot.send_message.await_args.kwargs
    assert call_kwargs["chat_id"] == compensation_config.ADMIN_ALERT_CHAT_ID
    assert call_kwargs["parse_mode"] == ParseMode.HTML

    text = call_kwargs["text"]
    assert str(order_id) in text
    assert "2500.00 ₽" in text
    # Проверка обязательного экранирования HTML
    assert "&lt;VIP_Ads&gt;" in text
    assert "&amp;" in text


@pytest.mark.asyncio
async def test_send_critical_alert_success(
    compensation_config: CompensationConfig,
) -> None:
    bot = AsyncMock(spec=Bot)
    alerter = TelegramIncidentAlerter(bot=bot, config=compensation_config)

    order_id = uuid.uuid4()
    task_id = uuid.uuid4()
    payment_id = "tbank_pay_987654"
    amount_kopecks = 100000
    error_msg = "TBankAPIError: [7] Недостаточно средств <BalanceError>"
    publish_reason = "Admin revoked rights & kicked bot"

    await alerter.send_critical_alert(
        title="СБОЙ КОМПЕНСАЦИИ ЗАКАЗА",
        order_id=order_id,
        payment_id=payment_id,
        amount_kopecks=amount_kopecks,
        error_message=error_msg,
        publish_failure_reason=publish_reason,
        task_id=task_id,
    )

    bot.send_message.assert_awaited_once()
    call_kwargs = bot.send_message.await_args.kwargs
    assert call_kwargs["chat_id"] == compensation_config.ADMIN_ALERT_CHAT_ID
    assert call_kwargs["parse_mode"] == ParseMode.HTML

    text = call_kwargs["text"]
    assert str(order_id) in text
    assert str(task_id) in text
    assert payment_id in text
    assert "1000.00 ₽" in text
    assert "ЛК Т-Бизнес" in text
    # Проверка обязательного экранирования HTML
    assert "&lt;BalanceError&gt;" in text
    assert "&amp;" in text


@pytest.mark.asyncio
async def test_send_alert_dto_success(
    compensation_config: CompensationConfig,
) -> None:
    bot = AsyncMock(spec=Bot)
    alerter = TelegramIncidentAlerter(bot=bot, config=compensation_config)

    alert_dto = IncidentAlertDTO(
        level="FATAL",
        title="Системный сбой БД",
        order_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        error_message="Deadlock detected <0xDEADBEEF>",
    )

    await alerter.send_alert(alert_dto)

    bot.send_message.assert_awaited_once()
    call_kwargs = bot.send_message.await_args.kwargs
    text = call_kwargs["text"]
    assert "[FATAL]" in text
    assert str(alert_dto.order_id) in text
    assert str(alert_dto.task_id) in text
    assert "&lt;0xDEADBEEF&gt;" in text


@pytest.mark.asyncio
async def test_safe_send_suppresses_exceptions(
    compensation_config: CompensationConfig,
) -> None:
    bot = AsyncMock(spec=Bot)
    bot.send_message.side_effect = RuntimeError("Telegram Network Timeout")
    alerter = TelegramIncidentAlerter(bot=bot, config=compensation_config)

    # Метод не должен выбрасывать исключение наружу
    await alerter.send_info_alert(
        title="Тестовый алерт",
        order_id=uuid.uuid4(),
        amount_kopecks=1000,
        reason="Тест",
    )

    bot.send_message.assert_awaited_once()
