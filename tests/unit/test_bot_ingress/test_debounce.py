from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, Message, MessageEntity, PhotoSize, User
from redis.asyncio import Redis

from src.modules.bot_ingress.middlewares.debounce_middleware import (
    MediaGroupDebounceMiddleware,
)
from src.modules.bot_ingress.services.debounce_consumer import (
    DEBOUNCE_ZSET_KEY,
    ITEMS_KEY_PREFIX,
    MediaGroupConsumerService,
)
from src.modules.bot_ingress.states import OrderCreationFSM
from src.shared.contracts.orders import ContentTypeEnum


class InMemoryRedisStub:
    """Легковесная in-memory эмуляция Redis для тестирования List, ZSET и Lua-скрипта дебаунса."""

    def __init__(self) -> None:
        self.lists: dict[str, list[bytes]] = {}
        self.zsets: dict[str, dict[str, float]] = {}
        self.sets: dict[str, set[str]] = {}
        self.kv: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def rpush(self, key: str, value: str) -> int:
        bucket = self.lists.setdefault(key, [])
        bucket.append(value.encode("utf-8"))
        return len(bucket)

    async def expire(self, key: str, ttl: int) -> bool:
        self.ttls[key] = ttl
        return True

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        zset = self.zsets.setdefault(key, {})
        zset.update(mapping)
        return len(mapping)

    async def zrem(self, key: str, *members: str) -> int:
        zset = self.zsets.get(key, {})
        removed = 0
        for member in members:
            if member in zset:
                del zset[member]
                removed += 1
        return removed

    async def sadd(self, key: str, *members: str) -> int:
        s = self.sets.setdefault(key, set())
        for m in members:
            s.add(m)
        return len(s)

    async def smembers(self, key: str) -> set[bytes]:
        return {m.encode("utf-8") for m in self.sets.get(key, set())}

    async def lrange(self, key: str, start: int, end: int) -> list[bytes]:
        items = self.lists.get(key, [])
        if end == -1:
            return list(items[start:])
        return list(items[start : end + 1])

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if key in self.lists:
                del self.lists[key]
                deleted += 1
            if key in self.kv:
                del self.kv[key]
                deleted += 1
            if key in self.sets:
                del self.sets[key]
                deleted += 1
        return deleted

    async def eval(
        self,
        script: str,
        numkeys: int,
        key: str,
        max_score: float,
    ) -> list[bytes]:
        assert numkeys == 1
        zset = self.zsets.get(key, {})
        ready_members = [
            member for member, score in zset.items() if score <= float(max_score)
        ][:10]
        for member in ready_members:
            del zset[member]
        return [m.encode("utf-8") for m in ready_members]

    async def set(
        self,
        key: str,
        value: str,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool:
        if nx and key in self.kv:
            return False
        self.kv[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True


def _make_album_photo_message(
    index: int,
    media_group_id: str = "album_555",
    user_id: int = 101,
    chat_id: int = 101,
) -> Message:
    msg = MagicMock(spec=Message)
    msg.media_group_id = media_group_id
    msg.message_id = 1000 + index
    msg.from_user = User(id=user_id, is_bot=False, first_name="Anton")
    msg.chat = Chat(id=chat_id, type="private")
    msg.photo = [
        PhotoSize(
            file_id=f"photo_file_{index}",
            file_unique_id=f"photo_uniq_{index}",
            width=1280,
            height=720,
        )
    ]
    msg.video = None
    msg.document = None
    msg.audio = None
    msg.animation = None
    msg.caption = "Подпись ко всему альбому" if index == 0 else None
    msg.caption_entities = (
        [MessageEntity(type="bold", offset=0, length=7)] if index == 0 else None
    )
    return msg


@pytest.mark.asyncio
async def test_sliding_window_debounce_assembles_5_part_album() -> None:
    redis_stub = InMemoryRedisStub()
    redis_client: Redis = redis_stub  # type: ignore[assignment]

    fsm_storage = MemoryStorage()
    bot = AsyncMock(spec=Bot)
    bot.id = 999

    user_id = 101
    chat_id = 101
    state_key = StorageKey(bot_id=bot.id, chat_id=chat_id, user_id=user_id)
    fsm_context = FSMContext(storage=fsm_storage, key=state_key)
    await fsm_context.set_state(OrderCreationFSM.WAITING_FOR_CONTENT)

    middleware = MediaGroupDebounceMiddleware(
        redis=redis_client,
        window_seconds=1.5,
        ttl_seconds=120,
    )
    downstream_handler = AsyncMock()

    # Эмулируем приход 5 частей одного альбома
    for idx in range(5):
        msg = _make_album_photo_message(index=idx, media_group_id="album_555")
        result = await middleware(downstream_handler, msg, {})
        assert result is None

    # Хэндлер не должен вызываться напрямую для частей альбома
    downstream_handler.assert_not_awaited()
    assert len(redis_stub.lists[f"{ITEMS_KEY_PREFIX}album_555"]) == 5
    assert redis_stub.ttls[f"{ITEMS_KEY_PREFIX}album_555"] == 120
    assert "album_555" in redis_stub.zsets[DEBOUNCE_ZSET_KEY]

    consumer = MediaGroupConsumerService(
        redis=redis_client,
        bot=bot,
        dispatcher=MagicMock(),
        fsm_storage=fsm_storage,
    )

    # До истечения окна дебаунса (now < score) группа не забирается
    early_ts = redis_stub.zsets[DEBOUNCE_ZSET_KEY]["album_555"] - 0.5
    assert await consumer.process_ready_groups(now=early_ts) == 0

    # После истечения окна дебаунса (now >= score) группа атомарно собирается
    ready_ts = redis_stub.zsets[DEBOUNCE_ZSET_KEY]["album_555"] + 0.1
    processed = await consumer.process_ready_groups(now=ready_ts)
    assert processed == 1

    # Проверяем, что FSM перешел в CONTENT_PREVIEW и содержит ровно 1 альбом из 5 элементов
    new_state = await fsm_context.get_state()
    assert new_state == OrderCreationFSM.CONTENT_PREVIEW.state

    data: dict[str, Any] = await fsm_context.get_data()
    content = data["content"]
    assert content["content_type"] == ContentTypeEnum.MEDIA_GROUP.value
    assert len(content["media_items"]) == 5
    assert content["caption"] == "Подпись ко всему альбому"
    assert content["entities"] == [{"type": "bold", "offset": 0, "length": 7}]

    # Проверяем, что превью альбома было отправлено пользователю
    bot.send_media_group.assert_awaited_once()
    bot.send_message.assert_awaited_once()