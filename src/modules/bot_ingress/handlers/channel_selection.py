from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.modules.bot_ingress.config import BotIngressConfig
from src.modules.bot_ingress.keyboards.reply_contacts import build_cancel_reply_keyboard
from src.modules.bot_ingress.states import OrderCreationFSM

router = Router(name="channel_selection")


@router.callback_query(
    OrderCreationFSM.SELECT_CHANNEL,
    F.data.startswith("channel_select:"),
)
async def handle_channel_selected(
    callback: CallbackQuery,
    state: FSMContext,
    config: BotIngressConfig,
) -> None:
    """Сохраняет выбранный канал в FSM и переводит в ожидание контента поста."""
    raw_data = callback.data or ""
    try:
        channel_id = int(raw_data.split(":", maxsplit=1)[1])
    except (IndexError, ValueError):
        await callback.answer("Некорректный идентификатор канала", show_alert=True)
        return

    channel = config.get_channel(channel_id)
    if channel is None:
        await callback.answer("Выбранный канал временно недоступен", show_alert=True)
        return

    await state.update_data(
        target_channel_id=channel.channel_id,
        channel_title=channel.title,
        amount_kopecks=channel.price_kopecks,
    )
    await state.set_state(OrderCreationFSM.WAITING_FOR_CONTENT)
    await callback.answer()

    if isinstance(callback.message, Message):
        await callback.message.answer(
            text=(
                f"📢 Выбран канал: <b>{channel.title}</b> ({channel.price_rubles} ₽).\n\n"
                "Отправьте ваш рекламный пост:\n"
                "• текстовое сообщение (до 4096 символов);\n"
                "• фото или видео с подписью (до 1024 символов);\n"
                "• альбом из 2–10 фото/видео."
            ),
            parse_mode="HTML",
            reply_markup=build_cancel_reply_keyboard(),
        )