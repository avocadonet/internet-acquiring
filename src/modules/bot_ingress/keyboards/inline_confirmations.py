from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def build_preview_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура под превью рекламного поста (состояние CONTENT_PREVIEW)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Все верно, далее",
                    callback_data="preview:confirm",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Загрузить заново",
                    callback_data="preview:retry",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="action:cancel",
                )
            ],
        ]
    )


def build_order_confirmation_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура подтверждения заказа перед оплатой (состояние ORDER_CONFIRMATION)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 Перейти к оплате",
                    callback_data="order:pay",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Изменить контакты",
                    callback_data="order:edit_contact",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="action:cancel",
                )
            ],
        ]
    )


def build_payment_keyboard(payment_url: str) -> InlineKeyboardMarkup:
    """Финальная клавиатура со ссылкой на оплату (состояние WAITING_FOR_PAYMENT)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Оплатить заказ",
                    url=payment_url,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Проверить статус",
                    callback_data="payment:check_status",
                )
            ],
        ]
    )