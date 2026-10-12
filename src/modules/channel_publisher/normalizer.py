from typing import Any

from aiogram.types import InputMediaPhoto, InputMediaVideo, MessageEntity

from src.shared.contracts.orders import PostContentDTO

from .exceptions import InvalidMediaGroupSizeError, UnsupportedMediaTypeError


class ContentNormalizer:
    """Сервис нормализации и сборки контента в нативные структуры Telegram Bot API."""

    @staticmethod
    def parse_entities(raw_entities: list[dict[str, Any]] | None) -> list[MessageEntity]:
        """
        Преобразует список словарей сущностей в типизированные объекты MessageEntity aiogram.
        """
        if not raw_entities:
            return []
        return [MessageEntity.model_validate(entity) for entity in raw_entities]

    @classmethod
    def build_media_group(
        cls, content: PostContentDTO
    ) -> list[InputMediaPhoto | InputMediaVideo]:
        """
        Формирует список объектов InputMedia для пакетной отправки альбома.

        Правила сборки:
        1. Размер альбома строго от 2 до 10 элементов.
        2. Подпись (caption) и разметка (caption_entities) прикрепляются строго
           к первому элементу списка media_items.
        3. Все последующие элементы обязаны содержать caption=None и caption_entities=None.
        """
        items_count = len(content.media_items)
        if items_count < 2 or items_count > 10:
            raise InvalidMediaGroupSizeError(
                f"Количество элементов медиагруппы должно быть от 2 до 10 (получено: {items_count})."
            )

        media_group: list[InputMediaPhoto | InputMediaVideo] = []
        parsed_entities = cls.parse_entities(content.entities)

        for idx, item in enumerate(content.media_items):
            # Подпись и сущности форматирования прикрепляются только к первому элементу
            caption = content.caption if idx == 0 else None
            caption_entities = (
                parsed_entities if (idx == 0 and parsed_entities) else None
            )

            if item.media_type == "photo":
                media_group.append(
                    InputMediaPhoto(
                        media=item.file_id,
                        caption=caption,
                        caption_entities=caption_entities,
                    )
                )
            elif item.media_type == "video":
                media_group.append(
                    InputMediaVideo(
                        media=item.file_id,
                        caption=caption,
                        caption_entities=caption_entities,
                    )
                )
            else:
                raise UnsupportedMediaTypeError(
                    f"Неподдерживаемый media_type: '{item.media_type}'. Разрешены только 'photo' и 'video'."
                )

        return media_group