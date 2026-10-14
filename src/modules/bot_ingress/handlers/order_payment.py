import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis

from src.modules.bot_ingress.config import BotIngressConfig
from src.modules.bot_ingress.keyboards.inline_confirmations import (
    build_payment_keyboard,
)
from src.modules.bot_ingress.keyboards.reply_contacts import (
    build_contact_reply_keyboard,
)
from src.modules.bot_ingress.states import OrderCreationFSM
from src.shared.contracts.orders import (
    CreateOrderInputDTO,
    CustomerContactDTO,
    IOrderService,
    PostContentDTO,
)

logger = logging.getLogger(__name__)

router = Router(name="order_payment")

BANK_ERROR_MESSAGE = (
    "⚠️ Не удалось связаться с банком для генерации ссылки на оплату. "
    "Ваши данные сохранены. Попробуйте нажать кнопку оплаты еще раз через минуту."
)


@router.callback_query(
    OrderCreationFSM.ORDER_CONFIRMATION,
    F.data == "order:edit_contact",
)
async def handle_edit_contact(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Возвращает пользователя на шаг ввода телефона или Email."""
    await state.update_data(payment_url=None, order_id=None)
    await state.set_state(OrderCreationFSM.WAITING_FOR_CONTACT)
    await callback.answer()

    if isinstance(callback.message, Message):
        await callback.message.answer(
            text="✏️ Введите новый номер телефона (+79XXXXXXXXX) или Email для чека:",
            reply_markup=build_contact_reply_keyboard(),
        )


@router.callback_query(
    OrderCreationFSM.ORDER_CONFIRMATION,
    F.data == "order:pay",
)
@router.callback_query(
    OrderCreationFSM.WAITING_FOR_PAYMENT,
    F.data == "order:pay",
)
async def handle_proceed_to_payment(
    callback: CallbackQuery,
    state: FSMContext,
    order_service: IOrderService,
    redis: Redis,
    config: BotIngressConfig,
) -> None:
    """
    Обрабатывает нажатие на кнопку «💳 Перейти к оплате»:
    1. Проверяет наличие уже созданного payment_url в данных FSM.
    2. Устанавливает атомарную блокировку SET lock:order_create:{user_id} 1 NX EX 10.
    3. Вызывает IOrderService.create_order() и выдает пользователю ссылку на оплату.
    """
    user_id = callback.from_user.id
    fsm_data = await state.get_data()

    existing_payment_url = fsm_data.get("payment_url")
    if isinstance(existing_payment_url, str) and existing_payment_url:
        await state.set_state(OrderCreationFSM.WAITING_FOR_PAYMENT)
        await callback.answer()
        if isinstance(callback.message, Message):
            await callback.message.answer(
                text="💳 Ссылка на оплату вашего заказа уже сформирована:",
                reply_markup=build_payment_keyboard(existing_payment_url),
            )
        return

    lock_key = f"lock:order_create:{user_id}"
    acquired = await redis.set(
        lock_key,
        "1",
        nx=True,
        ex=config.order_lock_ttl_seconds,
    )
    if not acquired:
        await callback.answer(
            "Заказ уже формируется, пожалуйста, подождите...",
            show_alert=False,
        )
        return

    try:
        target_channel_id = int(fsm_data["target_channel_id"])
        content_dto = PostContentDTO.model_validate(fsm_data["content"])
        contact_dto = CustomerContactDTO.model_validate(fsm_data["contact"])

        order_input = CreateOrderInputDTO(
            user_id=user_id,
            target_channel_id=target_channel_id,
            content=content_dto,
            contact=contact_dto,
        )
        result = await order_service.create_order(order_input)
    except Exception:
        logger.exception("Failed to create order for user_id=%s", user_id)
        await redis.delete(lock_key)
        await callback.answer()
        if isinstance(callback.message, Message):
            await callback.message.answer(text=BANK_ERROR_MESSAGE)
        return

    await state.update_data(
        order_id=result.order_id,
        payment_url=result.payment_url,
        amount_kopecks=result.amount_kopecks,
    )
    await state.set_state(OrderCreationFSM.WAITING_FOR_PAYMENT)
    await callback.answer()

    if isinstance(callback.message, Message):
        price_rubles = result.amount_kopecks // 100
        await callback.message.answer(
            text=(
                f"💳 <b>Заказ №{result.order_id} сформирован!</b>\n"
                f"Сумма к оплате: <b>{price_rubles} ₽</b>.\n\n"
                "Нажмите на кнопку ниже для перехода на защищенную страницу оплаты Т-Банка:"
            ),
            parse_mode="HTML",
            reply_markup=build_payment_keyboard(result.payment_url),
        )


@router.callback_query(
    OrderCreationFSM.WAITING_FOR_PAYMENT,
    F.data == "payment:check_status",
)
async def handle_check_payment_status(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Информирует пользователя о механизме автоматической проверки оплаты."""
    fsm_data = await state.get_data()
    order_id = fsm_data.get("order_id", "—")
    await callback.answer(
        text=(
            f"Заказ {order_id}: статус обновится автоматически сразу после "
            "подтверждения платежа банком."
        ),
        show_alert=True,
    )