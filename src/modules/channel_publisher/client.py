import logging
from typing import Any, cast

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import Message
from aiohttp import ClientTimeout, TCPConnector

from src.shared.contracts.orders import ContentTypeEnum, PostContentDTO
from src.shared.contracts.publishing import (
    IPublisherService,
    PublishPostPayloadDTO,
    PublishResultDTO,
)

from .config import ChannelPublisherConfig, publisher_config
from .exceptions import ContentNormalizationError, PublishingDeliveryError
from .normalizer import ContentNormalizer

logger = logging.getLogger(__name__)


def create_publisher_session(
    config: ChannelPublisherConfig | None = None,
) -> AiohttpSession:
    """
    Создает сессию AiohttpSession со строгим сетевым профилем для предотвращения зависания воркера.
    """
    cfg = config or publisher_config
    timeout = ClientTimeout(
        total=cfg.total_timeout,
        connect=cfg.connect_timeout,
        sock_connect=cfg.sock_connect_timeout,
        sock_read=cfg.sock_read_timeout,
    )
    connector = TCPConnector(
        limit=cfg.pool_limit,
        limit_per_host=cfg.pool_limit_per_host,
    )
    session = AiohttpSession(timeout=timeout)
    session._connector_type = type(connector)
    return session


def create_publisher_bot(
    token: str,
    config: ChannelPublisherConfig | None = None,
) -> Bot:
    """
    Фабрика создания экземпляра aiogram.Bot со специализированной сессией публикации.
    """
    session = create_publisher_session(config=config)
    return Bot(token=token, session=session)


class PublisherService(IPublisherService):
    """
    Реализация сервиса публикации постов в Telegram-каналы.
    Осуществляет нормализацию полезной нагрузки и прямые вызовы методов Bot API.
    """

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    @property
    def bot(self) -> Bot:
        """Возвращает базовый экземпляр aiogram.Bot."""
        return self._bot

    async def publish(self, payload: PublishPostPayloadDTO) -> PublishResultDTO:
        """
        Публикует пост в канале и возвращает идентификатор первого размещенного сообщения.
        """
        published_message_id = await self.send_content(
            target_chat_id=payload.target_chat_id,
            content=payload.content,
        )
        return PublishResultDTO(
            order_id=payload.order_id,
            published_message_id=published_message_id,
            chat_id=payload.target_chat_id,
        )

    async def send_content(self, target_chat_id: int, content: PostContentDTO) -> int:
        """
        Нормализует контент и выполняет адресный вызов Telegram API в зависимости от content_type.
        """
        entities = ContentNormalizer.parse_entities(content.entities)

        if content.content_type == ContentTypeEnum.TEXT:
            msg: Message = await self._bot.send_message(
                chat_id=target_chat_id,
                text=content.text or "",
                entities=entities,
            )
            return msg.message_id

        if content.content_type == ContentTypeEnum.PHOTO:
            if not content.media_items:
                raise ContentNormalizationError(
                    "Список media_items пуст для одиночного фото."
                )
            msg = await self._bot.send_photo(
                chat_id=target_chat_id,
                photo=content.media_items[0].file_id,
                caption=content.caption,
                caption_entities=entities,
            )
            return msg.message_id

        if content.content_type == ContentTypeEnum.VIDEO:
            if not content.media_items:
                raise ContentNormalizationError(
                    "Список media_items пуст для одиночного видео."
                )
            msg = await self._bot.send_video(
                chat_id=target_chat_id,
                video=content.media_items[0].file_id,
                caption=content.caption,
                caption_entities=entities,
            )
            return msg.message_id

        if content.content_type == ContentTypeEnum.MEDIA_GROUP:
            media_group = ContentNormalizer.build_media_group(content)
            messages = await self._bot.send_media_group(
                chat_id=target_chat_id,
                media=cast(list[Any], media_group),
            )
            if not messages:
                raise PublishingDeliveryError(
                    "Telegram Bot API вернул пустой список сообщений для медиагруппы."
                )
            return messages[0].message_id

        raise ContentNormalizationError(
            f"Неподдерживаемый тип контента: {content.content_type}"
        )

    async def close(self) -> None:
        """Закрывает базовую сессию Telegram-бота."""
        await self._bot.session.close()