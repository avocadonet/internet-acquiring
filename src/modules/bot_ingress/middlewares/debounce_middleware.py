import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
from redis.asyncio import Redis

from src.modules.bot_ingress.services.content_processor import ContentProcessorService
from src.modules.bot_ingress.services.debounce_consumer import (
    DEBOUNCE_ZSET_KEY,
    ITEMS_KEY_PREFIX,
)


class MediaGroupDebounceMiddleware(BaseMiddleware):
    """
    Middleware буферизации и sliding-window дебаунса для входящих альбомов (media_group_id).
    Одиночные сообщения (media_group_id is None) пропускаются без задержки.
    """

    def __init__(
        self,
        redis: Redis,
        window_seconds: float = 1.5,
        ttl_seconds: int = 120,
    ) -> None:
        super().__init__()
        self.redis = redis
        self.window_seconds = window_seconds
        self.ttl_seconds = ttl_seconds

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or event.media_group_id is None:
            return await handler(event, data)

        media_group_id = event.media_group_id
        payload = self._extract_message_payload(event)

        items_key = f"{ITEMS_KEY_PREFIX}{media_group_id}"
        await self.redis.rpush(items_key, json.dumps(payload))
        await self.redis.expire(items_key, self.ttl_seconds)

        ready_timestamp = time.time() + self.window_seconds
        await self.redis.zadd(DEBOUNCE_ZSET_KEY, {media_group_id: ready_timestamp})

        if event.from_user is not None:
            user_mg_key = f"mg:user_active:{event.from_user.id}"
            await self.redis.sadd(user_mg_key, media_group_id)
            await self.redis.expire(user_mg_key, self.ttl_seconds)

        return None

    @staticmethod
    def _extract_message_payload(message: Message) -> dict[str, Any]:
        """Извлекает метаданные сообщения альбома для сериализации в JSON."""
        media_type = "unknown"
        file_id = ""
        file_unique_id = ""
        width: int | None = None
        height: int | None = None
        duration: int | None = None

        if message.photo:
            largest = message.photo[-1]
            media_type = "photo"
            file_id = largest.file_id
            file_unique_id = largest.file_unique_id
            width = largest.width
            height = largest.height
        elif message.video is not None:
            media_type = "video"
            file_id = message.video.file_id
            file_unique_id = message.video.file_unique_id
            width = message.video.width
            height = message.video.height
            duration = message.video.duration
        elif message.document is not None:
            media_type = "document"
            file_id = message.document.file_id
            file_unique_id = message.document.file_unique_id
        elif message.audio is not None:
            media_type = "audio"
            file_id = message.audio.file_id
            file_unique_id = message.audio.file_unique_id
        elif message.animation is not None:
            media_type = "animation"
            file_id = message.animation.file_id
            file_unique_id = message.animation.file_unique_id

        user_id = message.from_user.id if message.from_user is not None else message.chat.id

        return {
            "media_group_id": message.media_group_id,
            "message_id": message.message_id,
            "user_id": user_id,
            "chat_id": message.chat.id,
            "media_type": media_type,
            "file_id": file_id,
            "file_unique_id": file_unique_id,
            "width": width,
            "height": height,
            "duration": duration,
            "caption": message.caption,
            "caption_entities": ContentProcessorService.serialize_entities(
                message.caption_entities
            ),
        }