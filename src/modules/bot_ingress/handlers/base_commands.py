from typing import Any

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from redis.asyncio import Redis

from src.modules.bot_ingress.config import BotIngressConfig
from src.modules.bot_ingress.keyboards.inline_channels import build_channels_keyboard
from src.modules.bot_ingress.services.debounce_consumer import (
    DEBOUNCE_ZSET_KEY,
    ITEMS_KEY_PREFIX,
)
from src.modules.bot_ingress.states import OrderCreationFSM

router = Router(name="base_commands")

CANCEL_TEXT_VARIANTS = frozenset(
    {
        "❌ отмена",
        "❌ отменить",
        "❌ отменить создание",
    }
)

CANCEL_RESPONSE_TEXT = (
    "Создание заказа отменено. Вы можете начать заново с помощью команды /start."
)

HELP_TEXT = (
    "ℹ️ <b>Справка по размещению рекламы</b>\n\n"
    "1. Нажмите /start и выберите целевой канал из списка.\n"
    "2. Отправьте рекламный пост (текст до 4096 символов, фото/видео или альбом от 2 до 10 файлов с подписью до 1024 символов).\n"
    "3. Проверьте превью поста и укажите телефон (+79XXXXXXXXX) или Email для получения чека по 54-ФЗ.\n"
    "4. Перейдите по ссылке на оплату. После подтверждения платежа пост будет опубликован автоматически.\n\n"
    "Для сброса текущего заказа в любой момент используйте команду /cancel."
)


async def _cleanup_user_redis_keys(redis: Redis, user_id: int) -> None:
    """Очищает временные ключи блокировок и буферов альбомов пользователя в Redis."""
    lock_key = f"lock:order_create:{user_id}"
    user_mg_key = f"mg:user_active:{user_id}"

    active_groups: set[Any] = await redis.smembers(user_mg_key)
    for mg_raw in active_groups:
        mg_id = mg_raw.decode("utf-8") if isinstance(mg_raw, bytes) else str(mg_raw)
        await redis.delete(f"{ITEMS_KEY_PREFIX}{mg_id}")
        await redis.zrem(DEBOUNCE_ZSET_KEY, mg_id)

    await redis.delete(lock_key, user_mg_key)


@router.message(CommandStart(), StateFilter("*"))
async def handle_start(
    message: Message,
    state: FSMContext,
    config: BotIngressConfig,
    redis: Redis,
) -> None:
    """Сбрасывает текущий прогресс и запускает мастер выбора рекламного канала."""
    if message.from_user is not None:
        await _cleanup_user_redis_keys(redis, message.from_user.id)
    await state.clear()
    await state.set_state(OrderCreationFSM.SELECT_CHANNEL)
    await message.answer(
        text="👋 Добро пожаловать в сервис размещения рекламы!\n"
        "Выберите целевой Telegram-канал для публикации:",
        reply_markup=build_channels_keyboard(config.channels),
    )


@router.message(Command("help"), StateFilter("*"))
async def handle_help(message: Message) -> None:
    """Выводит справочную информацию по работе с ботом."""
    await message.answer(text=HELP_TEXT, parse_mode="HTML")


@router.message(Command("cancel"), StateFilter("*"))
@router.message(
    F.text.func(lambda t: isinstance(t, str) and t.casefold() in CANCEL_TEXT_VARIANTS),
    StateFilter("*"),
)
async def handle_cancel_message(
    message: Message,
    state: FSMContext,
    redis: Redis,
) -> None:
    """Глобальная отмена создания заказа по команде /cancel или Reply-кнопке."""
    if message.from_user is not None:
        await _cleanup_user_redis_keys(redis, message.from_user.id)
    await state.clear()
    await message.answer(
        text=CANCEL_RESPONSE_TEXT,
        reply_markup=ReplyKeyboardRemove(),
    )


@router.callback_query(F.data == "action:cancel", StateFilter("*"))
async def handle_cancel_callback(
    callback: CallbackQuery,
    state: FSMContext,
    redis: Redis,
) -> None:
    """Глобальная отмена создания заказа по нажатию на Inline-кнопку отмены."""
    await _cleanup_user_redis_keys(redis, callback.from_user.id)
    await state.clear()
    await callback.answer("Заказ отменен")
    if isinstance(callback.message, Message):
        await callback.message.answer(
            text=CANCEL_RESPONSE_TEXT,
            reply_markup=ReplyKeyboardRemove(),
        )