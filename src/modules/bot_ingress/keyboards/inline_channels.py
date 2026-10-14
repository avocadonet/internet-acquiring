from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.modules.bot_ingress.config import ChannelTariffDTO


def build_channels_keyboard(
    channels: Sequence[ChannelTariffDTO],
) -> InlineKeyboardMarkup:
    """Строит Inline-клавиатуру выбора целевого канала для публикации."""
    rows: list[list[InlineKeyboardButton]] = []
    for channel in channels:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{channel.title} — {channel.price_rubles} ₽",
                    callback_data=f"channel_select:{channel.channel_id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="❌ Отмена",
                callback_data="action:cancel",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)