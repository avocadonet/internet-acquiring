from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.modules.bot_ingress.exceptions import ContentValidationError
from src.modules.bot_ingress.keyboards.reply_contacts import (
    build_cancel_reply_keyboard,
    build_contact_reply_keyboard,
)
from src.modules.bot_ingress.services.content_processor import ContentProcessorService
from src.modules.bot_ingress.services.preview_renderer import PreviewRendererService
from src.modules.bot_ingress.states import OrderCreationFSM

router = Router(name="content_submission")


@router.message(OrderCreationFSM.WAITING_FOR_CONTENT)
async def handle_single_content_message(
    message: Message,
    state: FSMContext,
) -> None:
    """
    Обрабатывает одиночные сообщения (текст, фото, видео) в состоянии WAITING_FOR_CONTENT.
    Альбомы перехватываются на уровне MediaGroupDebounceMiddleware.
    """
    try:
        post_content = ContentProcessorService.process_single_message(message)
    except ContentValidationError as exc:
        await message.answer(text=exc.user_message)
        return

    await state.update_data(content=post_content.model_dump(mode="json"))
    await state.set_state(OrderCreationFSM.CONTENT_PREVIEW)

    if message.bot is not None:
        await PreviewRendererService.render_preview(
            bot=message.bot,
            chat_id=message.chat.id,
            content=post_content,
        )


@router.callback_query(
    OrderCreationFSM.CONTENT_PREVIEW,
    F.data == "preview:confirm",
)
async def handle_preview_confirmed(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Подтверждает превью поста и переводит в состояние ввода контактов (54-ФЗ)."""
    await state.set_state(OrderCreationFSM.WAITING_FOR_CONTACT)
    await callback.answer()

    if isinstance(callback.message, Message):
        await callback.message.answer(
            text=(
                "🧾 Для формирования электронного кассового чека по 54-ФЗ укажите ваши "
                "контактные данные:\n"
                "• нажмите кнопку <b>«📱 Отправить мой контакт»</b>;\n"
                "• или введите номер телефона в формате <code>+79XXXXXXXXX</code> / Email вручную."
            ),
            parse_mode="HTML",
            reply_markup=build_contact_reply_keyboard(),
        )


@router.callback_query(
    OrderCreationFSM.CONTENT_PREVIEW,
    F.data == "preview:retry",
)
async def handle_preview_retry(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Возвращает пользователя к повторной загрузке контента поста."""
    await state.set_state(OrderCreationFSM.WAITING_FOR_CONTENT)
    await callback.answer("Отправьте новый пост")

    if isinstance(callback.message, Message):
        await callback.message.answer(
            text="✏️ Отправьте новый текст, фото, видео или альбом для публикации:",
            reply_markup=build_cancel_reply_keyboard(),
        )