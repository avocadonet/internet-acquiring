from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove

from src.modules.bot_ingress.exceptions import ContactValidationError
from src.modules.bot_ingress.keyboards.inline_confirmations import (
    build_order_confirmation_keyboard,
)
from src.modules.bot_ingress.services.content_validator import ContentValidator
from src.modules.bot_ingress.states import OrderCreationFSM

router = Router(name="contact_submission")


@router.message(OrderCreationFSM.WAITING_FOR_CONTACT)
async def handle_contact_input(
    message: Message,
    state: FSMContext,
) -> None:
    """Принимает и валидирует телефон или Email покупателя для фискализации по 54-ФЗ."""
    raw_value: str | None = None
    if message.contact is not None:
        raw_value = message.contact.phone_number
    elif message.text is not None:
        raw_value = message.text

    try:
        contact_dto = ContentValidator.validate_contact(raw_value)
    except ContactValidationError as exc:
        await message.answer(text=exc.user_message)
        return

    fsm_data = await state.get_data()
    channel_title = fsm_data.get("channel_title", "Выбранный канал")
    amount_kopecks = int(fsm_data.get("amount_kopecks", 0))
    price_rubles = amount_kopecks // 100
    contact_display = contact_dto.phone or contact_dto.email or ""

    await state.update_data(
        contact=contact_dto.model_dump(mode="json"),
        payment_url=None,
        order_id=None,
    )
    await state.set_state(OrderCreationFSM.ORDER_CONFIRMATION)

    await message.answer(
        text="✅ Контактные данные для чека приняты.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer(
        text=(
            "📋 <b>Подтверждение рекламного заказа</b>\n\n"
            f"• <b>Канал:</b> {channel_title}\n"
            f"• <b>Стоимость:</b> {price_rubles} ₽\n"
            f"• <b>Контакт для чека (54-ФЗ):</b> <code>{contact_display}</code>\n\n"
            "Нажимая «💳 Перейти к оплате», вы подтверждаете согласие с условиями оферты."
        ),
        parse_mode="HTML",
        reply_markup=build_order_confirmation_keyboard(),
    )