from typing import Any

from aiogram import Bot
from aiogram.types import (
    InputMediaAudio,
    InputMediaDocument,
    InputMediaLivePhoto,
    InputMediaPhoto,
    InputMediaVideo,
    MessageEntity,
)

from src.modules.bot_ingress.keyboards.inline_confirmations import (
    build_preview_keyboard,
)
from src.shared.contracts.orders import ContentTypeEnum, PostContentDTO

PREVIEW_PROMPT_TEXT = (
    "👁 <b>Превью вашего рекламного поста сформировано.</b>\n"
    "Проверьте текст, форматирование и вложения. Если все корректно, нажмите «Все верно, далее»."
)


class PreviewRendererService:
    """Сервис генерации и отправки превью рекламного поста."""

    @staticmethod
    def deserialize_entities(
        raw_entities: list[dict[str, Any]],
    ) -> list[MessageEntity]:
        """Восстанавливает список объектов aiogram MessageEntity из словарей."""
        return [MessageEntity.model_validate(item) for item in raw_entities]

    @classmethod
    async def render_preview(
        cls,
        bot: Bot,
        chat_id: int,
        content: PostContentDTO,
    ) -> None:
        """Отправляет пользователю превью поста и клавиатуру подтверждения."""
        entities = cls.deserialize_entities(content.entities)

        if content.content_type == ContentTypeEnum.TEXT:
            await bot.send_message(
                chat_id=chat_id,
                text=content.text or "",
                entities=entities if entities else None,
            )
        elif content.content_type == ContentTypeEnum.PHOTO:
            media_item = content.media_items[0]
            await bot.send_photo(
                chat_id=chat_id,
                photo=media_item.file_id,
                caption=content.caption,
                caption_entities=entities if entities else None,
            )
        elif content.content_type == ContentTypeEnum.VIDEO:
            media_item = content.media_items[0]
            await bot.send_video(
                chat_id=chat_id,
                video=media_item.file_id,
                caption=content.caption,
                caption_entities=entities if entities else None,
            )
        elif content.content_type == ContentTypeEnum.MEDIA_GROUP:
            media_group: list[
                InputMediaAudio
                | InputMediaDocument
                | InputMediaLivePhoto
                | InputMediaPhoto
                | InputMediaVideo
            ] = []
            for idx, item in enumerate(content.media_items):
                item_caption = content.caption if idx == 0 else None
                item_entities = entities if (idx == 0 and entities) else None
                if item.media_type == "photo":
                    media_group.append(
                        InputMediaPhoto(
                            media=item.file_id,
                            caption=item_caption,
                            caption_entities=item_entities,
                        )
                    )
                elif item.media_type == "video":
                    media_group.append(
                        InputMediaVideo(
                            media=item.file_id,
                            caption=item_caption,
                            caption_entities=item_entities,
                        )
                    )
            await bot.send_media_group(chat_id=chat_id, media=media_group)

        await bot.send_message(
            chat_id=chat_id,
            text=PREVIEW_PROMPT_TEXT,
            parse_mode="HTML",
            reply_markup=build_preview_keyboard(),
        )