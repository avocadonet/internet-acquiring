import uuid
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from src.modules.compensation.customer_notifier import CustomerNotifierService


@pytest.mark.asyncio
async def test_notify_refund_completed_success() -> None:
    bot = AsyncMock(spec=Bot)
    notifier = CustomerNotifierService(bot=bot)

    order_id = uuid.uuid4()
    user_id = 123456789
    amount_kopecks = 150000
    reason = "Канал временно недоступен"

    result = await notifier.notify_refund_completed(
        customer_telegram_id=user_id,
        order_id=order_id,
        amount_kopecks=amount_kopecks,
        reason=reason,
    )

    assert result is True
    bot.send_message.assert_awaited_once()
    call_kwargs = bot.send_message.await_args.kwargs
    assert call_kwargs["chat_id"] == user_id
    assert call_kwargs["parse_mode"] == ParseMode.HTML
    assert str(order_id) in call_kwargs["text"]
    assert "1500.00 ₽" in call_kwargs["text"]
    assert reason in call_kwargs["text"]


@pytest.mark.asyncio
async def test_notify_refund_completed_bot_blocked_suppression() -> None:
    bot = AsyncMock(spec=Bot)
    bot.send_message.side_effect = TelegramForbiddenError(
        method=cast(Any, "sendMessage"),
        message="Forbidden: bot was blocked by the user",
    )
    notifier = CustomerNotifierService(bot=bot)

    order_id = uuid.uuid4()
    user_id = 987654321

    result = await notifier.notify_refund_completed(
        customer_telegram_id=user_id,
        order_id=order_id,
        amount_kopecks=50000,
        reason="Тест блокировки бота",
    )

    # Ошибка должна быть мягко подавлена без прерывания выполнения
    assert result is False
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_notify_refund_completed_chat_not_found_suppression() -> None:
    bot = AsyncMock(spec=Bot)
    bot.send_message.side_effect = TelegramBadRequest(
        method=cast(Any, "sendMessage"),
        message="Bad Request: chat not found",
    )
    notifier = CustomerNotifierService(bot=bot)

    order_id = uuid.uuid4()
    user_id = 111222333

    result = await notifier.notify_refund_completed(
        customer_telegram_id=user_id,
        order_id=order_id,
        amount_kopecks=25000,
        reason="Тест отсутствующего чата",
    )

    assert result is False
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_notify_refund_completed_unexpected_error_suppression() -> None:
    bot = AsyncMock(spec=Bot)
    bot.send_message.side_effect = RuntimeError("Сетевой обрыв соединения")
    notifier = CustomerNotifierService(bot=bot)

    order_id = uuid.uuid4()
    user_id = 555666777

    result = await notifier.notify_refund_completed(
        customer_telegram_id=user_id,
        order_id=order_id,
        amount_kopecks=10000,
        reason="Тест непредвиденного сбоя",
    )

    assert result is False
    bot.send_message.assert_awaited_once()
