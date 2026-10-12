import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Bot
from aiogram.types import Message

from src.modules.channel_publisher.anti_duplicate import AntiDuplicateGuard
from src.modules.channel_publisher.handler import ChannelPublisherHandler
from src.shared.contracts.orders import (
    ContentTypeEnum,
    MediaItemDTO,
    OrderStatus,
    PostContentDTO,
)
from src.shared.contracts.outbox import (
    OutboxTaskType,
    RetryableTaskError,
    TaskContextDTO,
)
from src.shared.contracts.publishing import PublishPostPayloadDTO
from tests.mocks.mock_order_service import MockOrderService


@pytest.fixture
def order_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def target_chat_id() -> int:
    return -1001987654321


@pytest.fixture
def mock_bot() -> AsyncMock:
    bot = AsyncMock(spec=Bot)
    bot.send_message = AsyncMock()
    bot.send_photo = AsyncMock()
    bot.send_video = AsyncMock()
    bot.send_media_group = AsyncMock()
    return bot


@pytest.fixture
def order_service(order_id: uuid.UUID, target_chat_id: int) -> MockOrderService:
    service = MockOrderService()
    # Регистрируем заказ в памяти для инспекции изменения статусов
    from src.shared.contracts.orders import OrderStatus
    from tests.mocks.mock_order_service import MockOrderState

    service.orders[order_id] = MockOrderState(
        order_id=order_id,
        user_id=12345,
        target_channel_id=target_chat_id,
        amount_kopecks=50_000,
        status=OrderStatus.PAID,
    )
    return service


@pytest.fixture
def anti_duplicate() -> AntiDuplicateGuard:
    return AntiDuplicateGuard()


@pytest.fixture
def handler(
    mock_bot: AsyncMock,
    order_service: MockOrderService,
    anti_duplicate: AntiDuplicateGuard,
) -> ChannelPublisherHandler:
    return ChannelPublisherHandler(
        bot=mock_bot,
        order_service=order_service,
        anti_duplicate=anti_duplicate,
    )


def make_context(order_id: uuid.UUID, target_chat_id: int, content: PostContentDTO) -> TaskContextDTO:
    payload = PublishPostPayloadDTO(
        order_id=order_id,
        target_chat_id=target_chat_id,
        content=content,
    )
    return TaskContextDTO(
        task_id=uuid.uuid4(),
        task_type=OutboxTaskType.PUBLISH_POST,
        payload=payload.model_dump(mode="json"),
        retry_count=0,
    )


@pytest.mark.asyncio
async def test_handle_text_success(
    handler: ChannelPublisherHandler,
    mock_bot: AsyncMock,
    order_service: MockOrderService,
    order_id: uuid.UUID,
    target_chat_id: int,
) -> None:
    """Проверка успешной публикации простого текстового поста."""
    fake_msg = MagicMock(spec=Message, message_id=42)
    mock_bot.send_message.return_value = fake_msg

    content = PostContentDTO(
        content_type=ContentTypeEnum.TEXT,
        text="Рекламный текст",
        entities=[],
        media_items=[],
    )
    context = make_context(order_id, target_chat_id, content)

    await handler.handle(context)

    # 1. Проверяем обращение к Telegram API
    mock_bot.send_message.assert_awaited_once_with(
        chat_id=target_chat_id,
        text="Рекламный текст",
        entities=[],
    )

    # 2. Проверяем хронологию доменного сервиса
    assert order_id in order_service.publish_started_calls
    assert len(order_service.publish_succeeded_calls) == 1
    assert order_service.publish_succeeded_calls[0] == {
        "order_id": order_id,
        "published_message_id": 42,
    }

    # 3. Проверяем финальный статус заказа в MockOrderService
    state = order_service.get_order(order_id)
    assert state is not None
    assert state.status == OrderStatus.PUBLISHED
    assert state.published_message_id == 42


@pytest.mark.asyncio
async def test_handle_photo_success(
    handler: ChannelPublisherHandler,
    mock_bot: AsyncMock,
    order_service: MockOrderService,
    order_id: uuid.UUID,
    target_chat_id: int,
) -> None:
    """Проверка публикации одиночного фотопоста с подписью."""
    fake_msg = MagicMock(spec=Message, message_id=105)
    mock_bot.send_photo.return_value = fake_msg

    content = PostContentDTO(
        content_type=ContentTypeEnum.PHOTO,
        caption="Фото-пост",
        entities=[],
        media_items=[
            MediaItemDTO(file_id="photo_file_id", file_unique_id="uniq_1", media_type="photo")
        ],
    )
    context = make_context(order_id, target_chat_id, content)

    await handler.handle(context)

    mock_bot.send_photo.assert_awaited_once_with(
        chat_id=target_chat_id,
        photo="photo_file_id",
        caption="Фото-пост",
        caption_entities=[],
    )
    assert order_service.publish_succeeded_calls[0]["published_message_id"] == 105


@pytest.mark.asyncio
async def test_handle_video_success(
    handler: ChannelPublisherHandler,
    mock_bot: AsyncMock,
    order_service: MockOrderService,
    order_id: uuid.UUID,
    target_chat_id: int,
) -> None:
    """Проверка публикации одиночного видеоролика с подписью."""
    fake_msg = MagicMock(spec=Message, message_id=208)
    mock_bot.send_video.return_value = fake_msg

    content = PostContentDTO(
        content_type=ContentTypeEnum.VIDEO,
        caption="Видео-пост",
        entities=[],
        media_items=[
            MediaItemDTO(file_id="video_file_id", file_unique_id="uniq_v", media_type="video")
        ],
    )
    context = make_context(order_id, target_chat_id, content)

    await handler.handle(context)

    mock_bot.send_video.assert_awaited_once_with(
        chat_id=target_chat_id,
        video="video_file_id",
        caption="Видео-пост",
        caption_entities=[],
    )
    assert order_service.publish_succeeded_calls[0]["published_message_id"] == 208


@pytest.mark.asyncio
async def test_handle_media_group_first_message_id_contract(
    handler: ChannelPublisherHandler,
    mock_bot: AsyncMock,
    order_service: MockOrderService,
    order_id: uuid.UUID,
    target_chat_id: int,
) -> None:
    """
    Проверка публикации медиагруппы: в доменное ядро должен
    передаваться ID строго первого сообщения из возвращенного списка.
    """
    msg_1 = MagicMock(spec=Message, message_id=501)
    msg_2 = MagicMock(spec=Message, message_id=502)
    mock_bot.send_media_group.return_value = [msg_1, msg_2]

    content = PostContentDTO(
        content_type=ContentTypeEnum.MEDIA_GROUP,
        caption="Альбом",
        entities=[],
        media_items=[
            MediaItemDTO(file_id="p1", file_unique_id="u1", media_type="photo"),
            MediaItemDTO(file_id="p2", file_unique_id="u2", media_type="photo"),
        ],
    )
    context = make_context(order_id, target_chat_id, content)

    await handler.handle(context)

    mock_bot.send_media_group.assert_awaited_once()
    assert order_service.publish_succeeded_calls[0]["published_message_id"] == 501


@pytest.mark.asyncio
async def test_handle_idempotency_already_published(
    handler: ChannelPublisherHandler,
    mock_bot: AsyncMock,
    order_service: MockOrderService,
    anti_duplicate: AntiDuplicateGuard,
    order_id: uuid.UUID,
    target_chat_id: int,
) -> None:
    """
    Проверка идемпотентности: если пост уже подтвержден, повторная отправка в Bot API
    не выполняется, а домен сразу получает подтверждение.
    """
    anti_duplicate.mark_confirmed(order_id=order_id, message_id=999)

    content = PostContentDTO(
        content_type=ContentTypeEnum.TEXT,
        text="Дублирующийся вызов",
        entities=[],
        media_items=[],
    )
    context = make_context(order_id, target_chat_id, content)

    await handler.handle(context)

    mock_bot.send_message.assert_not_awaited()
    assert len(order_service.publish_succeeded_calls) == 1
    assert order_service.publish_succeeded_calls[0]["published_message_id"] == 999


@pytest.mark.asyncio
async def test_handle_suspected_duplicate_guard(
    handler: ChannelPublisherHandler,
    mock_bot: AsyncMock,
    anti_duplicate: AntiDuplicateGuard,
    order_id: uuid.UUID,
    target_chat_id: int,
) -> None:
    """
    Проверка защиты от дублирования: если заказ помечен как SUSPECTED_DUPLICATE,
    новые сетевые запросы блокируются и выбрасывается RetryableTaskError.
    """
    anti_duplicate.mark_suspected_timeout(order_id=order_id, reason="Previous ReadTimeout")

    content = PostContentDTO(
        content_type=ContentTypeEnum.TEXT,
        text="Пост с риском дублирования",
        entities=[],
        media_items=[],
    )
    context = make_context(order_id, target_chat_id, content)

    with pytest.raises(RetryableTaskError) as exc_info:
        await handler.handle(context)

    assert "manual verification" in str(exc_info.value)
    mock_bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_fatal_failure_triggers_compensation(
    handler: ChannelPublisherHandler,
    order_service: MockOrderService,
    anti_duplicate: AntiDuplicateGuard,
    order_id: uuid.UUID,
    target_chat_id: int,
) -> None:
    """
    Проверка компенсационного механизма: on_fatal_failure переводит заказ в домене
    в статус REFUND_REQUIRED через вызов handle_publish_failed.
    """
    content = PostContentDTO(
        content_type=ContentTypeEnum.TEXT,
        text="Контент с ошибкой",
        entities=[],
        media_items=[],
    )
    context = make_context(order_id, target_chat_id, content)

    error_reason = "TelegramForbiddenError: bot was kicked from the channel"
    await handler.on_fatal_failure(context=context, error=error_reason)

    # 1. Проверяем вызов сервиса заказов
    assert len(order_service.publish_failed_calls) == 1
    assert order_service.publish_failed_calls[0] == {
        "order_id": order_id,
        "error_reason": error_reason,
    }

    # 2. Проверяем смену статуса заказа в домене на REFUND_REQUIRED
    state = order_service.get_order(order_id)
    assert state is not None
    assert state.status == OrderStatus.REFUND_REQUIRED
    assert state.refund_details is not None
    assert state.refund_details["reason"] == error_reason

    # 3. Проверяем фиксацию сбоя в трекере
    assert anti_duplicate._states[order_id].last_error == error_reason