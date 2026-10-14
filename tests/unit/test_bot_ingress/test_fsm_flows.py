from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, Contact, Message, User
from redis.asyncio import Redis

from src.modules.bot_ingress.config import BotIngressConfig
from src.modules.bot_ingress.handlers.base_commands import (
    handle_cancel_message,
    handle_start,
)
from src.modules.bot_ingress.handlers.channel_selection import handle_channel_selected
from src.modules.bot_ingress.handlers.contact_submission import handle_contact_input
from src.modules.bot_ingress.handlers.content_submission import (
    handle_preview_confirmed,
    handle_single_content_message,
)
from src.modules.bot_ingress.handlers.order_payment import handle_proceed_to_payment
from src.modules.bot_ingress.states import OrderCreationFSM
from src.shared.contracts.orders import OrderStatus
from tests.mocks.mock_order_service import MockOrderService
from tests.unit.test_bot_ingress.test_debounce import InMemoryRedisStub


def _create_fsm_context() -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=999, chat_id=777, user_id=777)
    return FSMContext(storage=storage, key=key)


def _make_message(
    text: str | None = None, contact_phone: str | None = None
) -> AsyncMock:
    msg = AsyncMock(spec=Message)
    msg.answer = AsyncMock()
    msg.from_user = User(id=777, is_bot=False, first_name="TestUser")
    msg.chat = Chat(id=777, type="private")
    msg.bot = AsyncMock(spec=Bot)
    msg.text = text
    msg.caption = None
    msg.entities = None
    msg.caption_entities = None
    msg.photo = None
    msg.video = None
    msg.voice = None
    msg.video_note = None
    msg.sticker = None
    msg.poll = None
    msg.location = None
    msg.document = None
    msg.audio = None
    msg.animation = None
    if contact_phone is not None:
        msg.contact = Contact(phone_number=contact_phone, first_name="TestUser")
    else:
        msg.contact = None
    return msg


def _make_callback(data: str) -> AsyncMock:
    cb = AsyncMock(spec=CallbackQuery)
    cb.answer = AsyncMock()
    cb.from_user = User(id=777, is_bot=False, first_name="TestUser")
    cb.data = data
    cb.message = _make_message()
    return cb


@pytest.mark.asyncio
async def test_full_fsm_happy_path_and_double_submit_guard() -> None:
    config = BotIngressConfig()
    redis_stub = InMemoryRedisStub()
    redis_client: Redis = redis_stub  # type: ignore[assignment]
    mock_order_service = MockOrderService(default_price_kopecks=150_000)
    state = _create_fsm_context()

    # 1. /start -> SELECT_CHANNEL
    start_msg = _make_message(text="/start")
    await handle_start(
        message=start_msg,
        state=state,
        config=config,
        redis=redis_client,
    )
    assert await state.get_state() == OrderCreationFSM.SELECT_CHANNEL.state

    # 2. Выбор канала -> WAITING_FOR_CONTENT
    target_channel = config.channels[0]
    ch_cb = _make_callback(data=f"channel_select:{target_channel.channel_id}")
    await handle_channel_selected(callback=ch_cb, state=state, config=config)
    assert await state.get_state() == OrderCreationFSM.WAITING_FOR_CONTENT.state

    # 3. Отправка текста поста -> CONTENT_PREVIEW
    content_msg = _make_message(text="Продаем облачную платформу! Скидка 20%.")
    await handle_single_content_message(message=content_msg, state=state)
    assert await state.get_state() == OrderCreationFSM.CONTENT_PREVIEW.state

    # 4. Подтверждение превью -> WAITING_FOR_CONTACT
    preview_cb = _make_callback(data="preview:confirm")
    await handle_preview_confirmed(callback=preview_cb, state=state)
    assert await state.get_state() == OrderCreationFSM.WAITING_FOR_CONTACT.state

    # 5. Отправка контакта (нормализация 89001234567 -> +79001234567) -> ORDER_CONFIRMATION
    contact_msg = _make_message(contact_phone="8 (900) 123-45-67")
    await handle_contact_input(message=contact_msg, state=state)
    assert await state.get_state() == OrderCreationFSM.ORDER_CONFIRMATION.state

    fsm_data = await state.get_data()
    assert fsm_data["contact"]["phone"] == "+79001234567"

    # 6. Переход к оплате -> вызов MockOrderService.create_order -> WAITING_FOR_PAYMENT
    pay_cb = _make_callback(data="order:pay")
    await handle_proceed_to_payment(
        callback=pay_cb,
        state=state,
        order_service=mock_order_service,
        redis=redis_client,
        config=config,
    )
    assert await state.get_state() == OrderCreationFSM.WAITING_FOR_PAYMENT.state
    assert len(mock_order_service.create_order_calls) == 1

    saved_data = await state.get_data()
    assert saved_data["payment_url"].startswith("https://mock.bank/pay/")

    created_order = mock_order_service.get_order(saved_data["order_id"])
    assert created_order is not None
    assert created_order.status == OrderStatus.PENDING
    assert created_order.amount_kopecks == 150_000

    # 7. Повторное нажатие кнопки оплаты (Double Submit) -> НЕ вызывает create_order повторно
    second_pay_cb = _make_callback(data="order:pay")
    await handle_proceed_to_payment(
        callback=second_pay_cb,
        state=state,
        order_service=mock_order_service,
        redis=redis_client,
        config=config,
    )
    assert len(mock_order_service.create_order_calls) == 1


@pytest.mark.asyncio
async def test_payment_redis_lock_and_bank_failure_recovery() -> None:
    config = BotIngressConfig()
    redis_stub = InMemoryRedisStub()
    redis_client: Redis = redis_stub  # type: ignore[assignment]
    failing_service = MockOrderService()
    failing_service.raise_on_create = RuntimeError(
        "Simulated OrderService bank connection timeout"
    )
    state = _create_fsm_context()

    await state.set_state(OrderCreationFSM.ORDER_CONFIRMATION)
    await state.update_data(
        target_channel_id=-1001111111111,
        content={
            "content_type": "text",
            "text": "Тестовый рекламный пост",
            "caption": None,
            "entities": [],
            "media_items": [],
        },
        contact={"phone": "+79001234567", "email": None},
    )

    # При сбое сервиса заказов блокировка должна очищаться, а данные сохраняться
    pay_cb = _make_callback(data="order:pay")
    await handle_proceed_to_payment(
        callback=pay_cb,
        state=state,
        order_service=failing_service,
        redis=redis_client,
        config=config,
    )
    assert "lock:order_create:777" not in redis_stub.kv
    assert await state.get_state() == OrderCreationFSM.ORDER_CONFIRMATION.state

    # Если блокировка уже установлена параллельным запросом — выводится предупреждение
    await redis_stub.set("lock:order_create:777", "1", nx=True, ex=10)
    concurrent_cb = _make_callback(data="order:pay")
    await handle_proceed_to_payment(
        callback=concurrent_cb,
        state=state,
        order_service=failing_service,
        redis=redis_client,
        config=config,
    )
    concurrent_cb.answer.assert_awaited_once_with(
        "Заказ уже формируется, пожалуйста, подождите...",
        show_alert=False,
    )


@pytest.mark.asyncio
async def test_global_cancel_clears_state_and_redis_keys() -> None:
    redis_stub = InMemoryRedisStub()
    redis_client: Redis = redis_stub  # type: ignore[assignment]
    state = _create_fsm_context()

    await state.set_state(OrderCreationFSM.WAITING_FOR_CONTACT)
    await redis_stub.set("lock:order_create:777", "1")

    cancel_msg = _make_message(text="/cancel")
    await handle_cancel_message(
        message=cancel_msg,
        state=state,
        redis=redis_client,
    )

    assert await state.get_state() is None
    assert "lock:order_create:777" not in redis_stub.kv