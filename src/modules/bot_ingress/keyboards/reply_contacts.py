from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def build_cancel_reply_keyboard() -> ReplyKeyboardMarkup:
    """Reply-клавиатура отмены на шаге ожидания контента."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❌ Отменить создание")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def build_contact_reply_keyboard() -> ReplyKeyboardMarkup:
    """Reply-клавиатура отправки контакта для чека 54-ФЗ."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Отправить мой контакт", request_contact=True)],
            [KeyboardButton(text="❌ Отменить")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )