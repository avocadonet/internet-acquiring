import pytest
from aiogram.types import InputMediaPhoto, InputMediaVideo, MessageEntity

from src.modules.channel_publisher.exceptions import (
    InvalidMediaGroupSizeError,
    UnsupportedMediaTypeError,
)
from src.modules.channel_publisher.normalizer import ContentNormalizer
from src.shared.contracts.orders import ContentTypeEnum, MediaItemDTO, PostContentDTO


def test_parse_entities_empty() -> None:
    """Проверка парсинга пустого списка сущностей форматирования."""
    assert ContentNormalizer.parse_entities(None) == []
    assert ContentNormalizer.parse_entities([]) == []


def test_parse_entities_valid() -> None:
    """Проверка корректной десериализации разметки форматирования."""
    raw_entities = [
        {"type": "bold", "offset": 0, "length": 5},
        {"type": "italic", "offset": 6, "length": 4},
    ]
    parsed = ContentNormalizer.parse_entities(raw_entities)

    assert len(parsed) == 2
    assert isinstance(parsed[0], MessageEntity)
    assert parsed[0].type == "bold"
    assert parsed[0].offset == 0
    assert parsed[0].length == 5
    assert parsed[1].type == "italic"


def test_build_media_group_valid_caption_placement() -> None:
    """
    Проверка правила Telegram: подпись и разметка форматирования прикрепляются
    строго к первому элементу альбома, у последующих элементов они равны None.
    """
    items = [
        MediaItemDTO(
            file_id="photo_1", file_unique_id="u1", media_type="photo"
        ),
        MediaItemDTO(
            file_id="video_1", file_unique_id="u2", media_type="video"
        ),
        MediaItemDTO(
            file_id="photo_2", file_unique_id="u3", media_type="photo"
        ),
    ]
    content = PostContentDTO(
        content_type=ContentTypeEnum.MEDIA_GROUP,
        caption="Специальное предложение!",
        entities=[{"type": "bold", "offset": 0, "length": 10}],
        media_items=items,
    )

    media_group = ContentNormalizer.build_media_group(content)

    assert len(media_group) == 3

    # Первый элемент: фото с подписью и сущностями
    first = media_group[0]
    assert isinstance(first, InputMediaPhoto)
    assert first.media == "photo_1"
    assert first.caption == "Специальное предложение!"
    assert first.caption_entities is not None
    assert len(first.caption_entities) == 1
    assert first.caption_entities[0].type == "bold"

    # Второй элемент: видео без подписи
    second = media_group[1]
    assert isinstance(second, InputMediaVideo)
    assert second.media == "video_1"
    assert second.caption is None
    assert second.caption_entities is None

    # Третий элемент: фото без подписи
    third = media_group[2]
    assert isinstance(third, InputMediaPhoto)
    assert third.media == "photo_2"
    assert third.caption is None
    assert third.caption_entities is None


def test_build_media_group_max_ten_items() -> None:
    """Проверка успешной сборки максимально допустимого альбома из 10 элементов."""
    items = [
        MediaItemDTO(
            file_id=f"file_{i}",
            file_unique_id=f"uid_{i}",
            media_type="photo",
        )
        for i in range(10)
    ]
    content = PostContentDTO(
        content_type=ContentTypeEnum.MEDIA_GROUP,
        caption="Альбом из 10 фото",
        entities=[],
        media_items=items,
    )

    media_group = ContentNormalizer.build_media_group(content)
    assert len(media_group) == 10
    assert media_group[0].caption == "Альбом из 10 фото"
    for item in media_group[1:]:
        assert item.caption is None


@pytest.mark.parametrize("invalid_size", [0, 1, 11, 15])
def test_build_media_group_invalid_size(invalid_size: int) -> None:
    """Проверка валидации границ медиагруппы (от 2 до 10 элементов)."""
    items = [
        MediaItemDTO(
            file_id=f"file_{i}",
            file_unique_id=f"uid_{i}",
            media_type="photo",
        )
        for i in range(invalid_size)
    ]
    content = PostContentDTO(
        content_type=ContentTypeEnum.MEDIA_GROUP,
        caption="Тест",
        entities=[],
        media_items=items,
    )

    with pytest.raises(InvalidMediaGroupSizeError) as exc_info:
        ContentNormalizer.build_media_group(content)

    assert "от 2 до 10" in str(exc_info.value)


def test_build_media_group_unsupported_media_type() -> None:
    """Проверка выброса исключения при передаче неподдерживаемого типа медиа."""
    items = [
        MediaItemDTO(
            file_id="p1", file_unique_id="u1", media_type="photo"
        ),
        MediaItemDTO(
            file_id="a1", file_unique_id="u2", media_type="audio"
        ),
    ]
    content = PostContentDTO(
        content_type=ContentTypeEnum.MEDIA_GROUP,
        caption="Аудио не поддерживается в альбоме",
        entities=[],
        media_items=items,
    )

    with pytest.raises(UnsupportedMediaTypeError) as exc_info:
        ContentNormalizer.build_media_group(content)

    assert "audio" in str(exc_info.value)