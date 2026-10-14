import asyncio
import json
import logging
import time
from typing import Any

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from redis.asyncio import Redis

from src.modules.bot_ingress.services.content_processor import ContentProcessorService

logger = logging.getLogger(__name__)

DEBOUNCE_ZSET_KEY = "mg:debounce:zset"
ITEMS_KEY_PREFIX = "mg:items:"

LUA_POP_READY_GROUPS = """
local ready = redis.call('ZRANGEBYSCORE', KEYS[1], 0, ARGV[1], 'LIMIT', 0, 10)
if #ready > 0 then
    redis.call('ZREM', KEYS[1], unpack(ready))
end
return ready
"""


class MediaGroupConsumerService:
    """Фоновый сервис сборки медиагрупп (альбомов) по истечении окна дебаунса."""

    def __init__(
        self,
        redis: Redis,
        bot: Bot,
        dispatcher: Any,
        fsm_storage: BaseStorage,
        poll_interval: float = 0.2,
    ) -> None:
        self.redis = redis
        self.bot = bot
        self.dp = dispatcher
        self.fsm_storage = fsm_storage
        self.poll_interval = poll_interval
        self._running = False

    async def start(self) -> None:
        """Запускает бесконечный цикл опроса ZSET готовых медиагрупп."""
        self._running = True
        while self._running:
            try:
                processed_count = await self.process_ready_groups()
                if processed_count == 0:
                    await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                self._running = False
                raise
            except Exception:
                logger.exception("Error while processing ready media groups in consumer")
                await asyncio.sleep(0.5)

    async def process_ready_groups(self, now: float | None = None) -> int:
        """
        Выполняет одну итерацию выборки созревших групп через Lua-скрипт.
        Возвращает количество обработанных медиагрупп.
        """
        current_ts = now if now is not None else time.time()
        ready_groups: list[Any] = await self.redis.eval(
            LUA_POP_READY_GROUPS,
            1,
            DEBOUNCE_ZSET_KEY,
            current_ts,
        )

        if not ready_groups:
            return 0

        for mg_id_raw in ready_groups:
            mg_id = (
                mg_id_raw.decode("utf-8")
                if isinstance(mg_id_raw, bytes)
                else str(mg_id_raw)
            )
            await self._process_media_group(mg_id)

        return len(ready_groups)

    async def _process_media_group(self, media_group_id: str) -> None:
        """Забирает буферизованные сообщения из списка Redis и передает в FSM."""
        items_key = f"{ITEMS_KEY_PREFIX}{media_group_id}"
        raw_items: list[Any] = await self.redis.lrange(items_key, 0, -1)
        await self.redis.delete(items_key)

        if not raw_items:
            return

        messages: list[dict[str, Any]] = []
        for item in raw_items:
            raw_str = item.decode("utf-8") if isinstance(item, bytes) else str(item)
            parsed: dict[str, Any] = json.loads(raw_str)
            messages.append(parsed)

        messages.sort(key=lambda m: int(m.get("message_id", 0)))
        await self._dispatch_to_fsm(messages)

    async def _dispatch_to_fsm(self, messages: list[dict[str, Any]]) -> None:
        """Восстанавливает FSMContext пользователя и вызывает ContentProcessorService."""
        first = messages[0]
        user_id = int(first["user_id"])
        chat_id = int(first["chat_id"])

        state_key = StorageKey(
            bot_id=self.bot.id,
            chat_id=chat_id,
            user_id=user_id,
        )
        fsm_context = FSMContext(storage=self.fsm_storage, key=state_key)

        await ContentProcessorService.handle_assembled_album(
            messages=messages,
            fsm_context=fsm_context,
            bot=self.bot,
            chat_id=chat_id,
        )

    def stop(self) -> None:
        """Останавливает цикл опроса консьюмера."""
        self._running = False