from collections.abc import Mapping, Sequence
from typing import Any

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, MessageEntity

from src.modules.bot_ingress.exceptions import ContentValidationError
from src.modules.bot_ingress.services.content_validator import (
    UNSUPPORTED_CONTENT_MESSAGE,
    ContentValidator,
)
from src.modules.bot_ingress.services.preview_renderer import PreviewRendererService
from src.modules.bot_ingress.states import OrderCreationFSM
from src.shared.contracts.orders import (
    ContentTypeEnum,
    MediaItemDTO,
    PostContentDTO,
)


class ContentProcessorService:
    """Сервис сериализации контента и сборки PostContentDTO."""

    @staticmethod
    def serialize_entities(
        entities: Sequence[MessageEntity] | None,
    ) -> list[dict[str, Any]]:
        """Сериализует список MessageEntity в список словарей с сохранением offset и length."""
        if not entities:
            return []
        result: list[dict[str, Any]] = []
        for entity in entities:
            dumped = entity.model_dump(mode="json", exclude_none=True)
            result.append(dumped)
        return result

    @classmethod
    def process_single_message(cls, message: Message) -> PostContentDTO:
        """
        Формирует PostContentDTO из одиночного сообщения (текст, фото или видео).
        При неподдерживаемом типе или нарушении лимитов выбрасывает ContentValidationError.
        """
        # Отклоняем неподдерживаемые вложения даже при наличии caption
        if (
            message.voice is not None
            or message.video_note is not None
            or message.sticker is not None
            or message.poll is not None
            or message.location is not None
            or message.document is not None
            or message.audio is not None
            or message.animation is not None
            or message.contact is not None
        ):
            raise ContentValidationError(UNSUPPORTED_CONTENT_MESSAGE)

        if message.photo:
            caption = ContentValidator.validate_single_media_caption(message.caption)
            largest_photo = message.photo[-1]
            return PostContentDTO(
                content_type=ContentTypeEnum.PHOTO,
                caption=caption,
                entities=cls.serialize_entities(message.caption_entities),
                media_items=[
                    MediaItemDTO(
                        file_id=largest_photo.file_id,
                        file_unique_id=largest_photo.file_unique_id,
                        media_type="photo",
                        width=largest_photo.width,
                        height=largest_photo.height,
                    )
                ],
            )

        if message.video is not None:
            caption = ContentValidator.validate_single_media_caption(message.caption)
            video = message.video
            return PostContentDTO(
                content_type=ContentTypeEnum.VIDEO,
                caption=caption,
                entities=cls.serialize_entities(message.caption_entities),
                media_items=[
                    MediaItemDTO(
                        file_id=video.file_id,
                        file_unique_id=video.file_unique_id,
                        media_type="video",
                        width=video.width,
                        height=video.height,
                        duration=video.duration,
                    )
                ],
            )

        if message.text is not None:
            validated_text = ContentValidator.validate_text(message.text)
            return PostContentDTO(
                content_type=ContentTypeEnum.TEXT,
                text=validated_text,
                entities=cls.serialize_entities(message.entities),
                media_items=[],
            )

        raise ContentValidationError(UNSUPPORTED_CONTENT_MESSAGE)

    @classmethod
    def build_album_dto(
        cls,
        messages: Sequence[Mapping[str, Any]],
    ) -> PostContentDTO:
        """Валидирует собранный список элементов альбома и формирует PostContentDTO."""
        caption, caption_entities = ContentValidator.validate_album(messages)
        media_items: list[MediaItemDTO] = []

        for item in messages:
            media_items.append(
                MediaItemDTO(
                    file_id=str(item["file_id"]),
                    file_unique_id=str(item["file_unique_id"]),
                    media_type=str(item["media_type"]),
                    width=item.get("width"),
                    height=item.get("height"),
                    duration=item.get("duration"),
                )
            )

        return PostContentDTO(
            content_type=ContentTypeEnum.MEDIA_GROUP,
            caption=caption,
            entities=caption_entities,
            media_items=media_items,
        )

    @classmethod
    async def handle_assembled_album(
        cls,
        messages: list[dict[str, Any]],
        fsm_context: FSMContext,
        bot: Bot,
        chat_id: int,
    ) -> None:
        """
        Обрабатывает собранный дебаунсером альбом:
        - проверяет, что пользователь находится в состоянии WAITING_FOR_CONTENT;
        - валидирует альбом и сохраняет PostContentDTO в FSM;
        - переводит состояние в CONTENT_PREVIEW и отрисовывает превью.
        """
        current_state = await fsm_context.get_state()
        if current_state != OrderCreationFSM.WAITING_FOR_CONTENT.state:
            return

        try:
            post_content = cls.build_album_dto(messages)
        except ContentValidationError as exc:
            await bot.send_message(chat_id=chat_id, text=exc.user_message)
            return

        await fsm_context.update_data(content=post_content.model_dump(mode="json"))
        await fsm_context.set_state(OrderCreationFSM.CONTENT_PREVIEW)
        await PreviewRendererService.render_preview(
            bot=bot,
            chat_id=chat_id,
            content=post_content,
        )