import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiohttp import ClientConnectorError, ServerDisconnectedError

from src.modules.channel_publisher.anti_duplicate import AntiDuplicateGuard
from src.modules.channel_publisher.handler import ChannelPublisherHandler
from src.shared.contracts.orders import ContentTypeEnum, PostContentDTO
from src.shared.contracts.outbox import (
    FatalTaskError,
    OutboxTaskType,
    RateLimitTaskError,
    RetryableTaskError,
    TaskContextDTO,
)
from src.shared.contracts.publishing import PublishPostPayloadDTO
from tests.mocks.mock_order_service import MockOrderService


@pytest.fixture
def order_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def task_context(order_id: uuid.UUID) -> TaskContextDTO:
    payload = PublishPostPayloadDTO(
        order_id=order_id,
        target_chat_id=-1001234567890,
        content=PostContentDTO(
            content_type=ContentTypeEnum.TEXT,
            text="Тестовый рекламный пост",
            entities=[],
            media_items=[],
        ),
    )
    return TaskContextDTO(
        task_id=uuid.uuid4(),
        task_type=OutboxTaskType.PUBLISH_POST,
        payload=payload.model_dump(mode="json"),
        retry_count=0,
    )


@pytest.fixture
def mock_bot() -> AsyncMock:
    bot = AsyncMock(spec=Bot)
    bot.send_message = AsyncMock()
    bot.send_photo = AsyncMock()
    bot.send_video = AsyncMock()
    bot.send_media_group = AsyncMock()
    return bot


@pytest.fixture
def mock_order_service() -> MockOrderService:
    return MockOrderService()


@pytest.fixture
def anti_duplicate() -> AntiDuplicateGuard:
    return AntiDuplicateGuard()


@pytest.fixture
def handler(
    mock_bot: AsyncMock,
    mock_order_service: MockOrderService,
    anti_duplicate: AntiDuplicateGuard,
) -> ChannelPublisherHandler:
    return ChannelPublisherHandler(
        bot=mock_bot,
        order_service=mock_order_service,
        anti_duplicate=anti_duplicate,
    )


@pytest.mark.asyncio
async def test_mapping_telegram_retry_after(
    handler: ChannelPublisherHandler,
    mock_bot: AsyncMock,
    task_context: TaskContextDTO,
) -> None:
    """Проверка перехвата TelegramRetryAfter (429 FloodWait) и маппинга в RateLimitTaskError."""
    method_mock = MagicMock()
    mock_bot.send_message.side_effect = TelegramRetryAfter(
        method=method_mock,
        message="Too Many Requests: retry after 45",
        retry_after=45,
    )

    with pytest.raises(RateLimitTaskError) as exc_info:
        await handler.handle(task_context)

    assert exc_info.value.retry_after == 45


@pytest.mark.asyncio
async def test_mapping_telegram_forbidden(
    handler: ChannelPublisherHandler,
    mock_bot: AsyncMock,
    task_context: TaskContextDTO,
) -> None:
    """Проверка перехвата TelegramForbiddenError (403) и маппинга в FatalTaskError."""
    method_mock = MagicMock()
    mock_bot.send_message.side_effect = TelegramForbiddenError(
        method=method_mock,
        message="Forbidden: bot was kicked from the channel",
    )

    with pytest.raises(FatalTaskError) as exc_info:
        await handler.handle(task_context)

    assert "TelegramForbiddenError" in str(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_message,expected_error_name",
    [
        ("Bad Request: chat not found", "ChannelAccessError"),
        ("Bad Request: have no rights to send a message", "ChannelAccessError"),
        ("Bad Request: caption is too long", "InvalidContentError"),
        ("Bad Request: wrong file identifier/HTTP URL specified", "InvalidContentError"),
        ("Bad Request: general bad request syntax", "TelegramBadRequest"),
    ],
)
async def test_mapping_telegram_bad_request(
    handler: ChannelPublisherHandler,
    mock_bot: AsyncMock,
    task_context: TaskContextDTO,
    error_message: str,
    expected_error_name: str,
) -> None:
    """Проверка классификации различных вариантов TelegramBadRequest в фатальные ошибки."""
    method_mock = MagicMock()
    mock_bot.send_message.side_effect = TelegramBadRequest(
        method=method_mock,
        message=error_message,
    )

    with pytest.raises(FatalTaskError) as exc_info:
        await handler.handle(task_context)

    assert expected_error_name in str(exc_info.value)


@pytest.mark.asyncio
async def test_mapping_telegram_network_error(
    handler: ChannelPublisherHandler,
    mock_bot: AsyncMock,
    task_context: TaskContextDTO,
) -> None:
    """Проверка перехвата сбоев сети TelegramNetworkError и маппинга в RetryableTaskError."""
    method_mock = MagicMock()
    mock_bot.send_message.side_effect = TelegramNetworkError(
        method=method_mock,
        message="Network is unreachable",
    )

    with pytest.raises(RetryableTaskError) as exc_info:
        await handler.handle(task_context)

    assert "Network error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_mapping_client_connector_error(
    handler: ChannelPublisherHandler,
    mock_bot: AsyncMock,
    task_context: TaskContextDTO,
) -> None:
    """Проверка перехвата сетевого разрыва aiohttp ClientConnectorError."""
    mock_bot.send_message.side_effect = ClientConnectorError(
        connection_key=MagicMock(),
        os_error=OSError("Connection refused"),
    )

    with pytest.raises(RetryableTaskError) as exc_info:
        await handler.handle(task_context)

    assert "Network error" in str(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "timeout_exc",
    [
        TimeoutError("Socket read timeout"),
        TimeoutError("General timeout"),
        ServerDisconnectedError("Server disconnected while reading"),
    ],
)
async def test_mapping_read_timeout_suspected_duplicate(
    handler: ChannelPublisherHandler,
    mock_bot: AsyncMock,
    task_context: TaskContextDTO,
    anti_duplicate: AntiDuplicateGuard,
    order_id: uuid.UUID,
    timeout_exc: Exception,
) -> None:
    """
    Проверка аварийного протокола ReadTimeout: выброс RetryableTaskError
    и обязательная пометка заказа как SUSPECTED_DUPLICATE в AntiDuplicateGuard.
    """
    mock_bot.send_message.side_effect = timeout_exc

    with pytest.raises(RetryableTaskError) as exc_info:
        await handler.handle(task_context)

    assert "ReadTimeout" in str(exc_info.value)
    # Гарантируем, что статус заказа зафиксирован как подозрительный дубликат
    assert anti_duplicate.is_suspected_duplicate(order_id) is True