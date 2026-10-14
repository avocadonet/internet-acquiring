from typing import Any
from unittest.mock import MagicMock

import pytest
from aiogram.types import Message, MessageEntity, PhotoSize

from src.modules.bot_ingress.exceptions import (
    ContactValidationError,
    ContentValidationError,
)
from src.modules.bot_ingress.services.content_processor import ContentProcessorService
from src.modules.bot_ingress.services.content_validator import ContentValidator
from src.shared.contracts.orders import ContentTypeEnum


@pytest.mark.parametrize(
    ("raw_phone", "expected_e164"),
    [
        ("+79001234567", "+79001234567"),
        ("89001234567", "+79001234567"),
        ("79001234567", "+79001234567"),
        ("9001234567", "+79001234567"),
        ("+7 (999) 111-22-33", "+79991112233"),
        ("8-912-345-67-89", "+79123456789"),
    ],
)
def test_validate_phone_positive(raw_phone: str, expected_e164: str) -> None:
    dto = ContentValidator.validate_contact(raw_phone)
    assert dto.phone == expected_e164
    assert dto.email is None


@pytest.mark.parametrize(
    "invalid_phone",
    [
        "+74951234567",    # Городской номер (код 495)
        "84951234567",     # Городской номер
        "+790012345",      # Короткий номер
        "+7900123456789",  # Слишком длинный номер
        "+12345678901",    # Иностранный код
        "phone_number",    # Буквы
        "",                # Пустая строка
    ],
)
def test_validate_phone_negative(invalid_phone: str) -> None:
    with pytest.raises(ContactValidationError) as exc_info:
        ContentValidator.validate_contact(invalid_phone)
    assert "+79XXXXXXXXX" in exc_info.value.user_message


@pytest.mark.parametrize(
    ("raw_email", "expected_email"),
    [
        ("User.Name+tag@Example.COM", "user.name+tag@example.com"),
        ("client@company.ru", "client@company.ru"),
    ],
)
def test_validate_email_positive(raw_email: str, expected_email: str) -> None:
    dto = ContentValidator.validate_contact(raw_email)
    assert dto.email == expected_email
    assert dto.phone is None


@pytest.mark.parametrize(
    "invalid_email",
    [
        "plainaddress",
        "@no-local-part.com",
        "user@",
        "user@domain",
    ],
)
def test_validate_email_negative(invalid_email: str) -> None:
    with pytest.raises(ContactValidationError):
        ContentValidator.validate_contact(invalid_email)


def test_text_length_limit_4096_passes() -> None:
    valid_text = "А" * 4096
    result = ContentValidator.validate_text(valid_text)
    assert len(result) == 4096


def test_text_length_limit_4097_rejected() -> None:
    over_limit_text = "Б" * 4097
    with pytest.raises(ContentValidationError) as exc_info:
        ContentValidator.validate_text(over_limit_text)
    assert "4096" in exc_info.value.user_message
    assert "4097" in exc_info.value.user_message


def test_single_media_caption_1024_passes() -> None:
    caption_1024 = "В" * 1024
    assert ContentValidator.validate_single_media_caption(caption_1024) == caption_1024
    assert ContentValidator.validate_single_media_caption(None) is None


def test_single_media_caption_1025_rejected() -> None:
    caption_1025 = "Г" * 1025
    with pytest.raises(ContentValidationError) as exc_info:
        ContentValidator.validate_single_media_caption(caption_1025)
    assert "1024" in exc_info.value.user_message
    assert "1025" in exc_info.value.user_message


def test_album_validation_rules() -> None:
    valid_items: list[dict[str, Any]] = [
        {
            "file_id": f"file_{i}",
            "file_unique_id": f"uniq_{i}",
            "media_type": "photo" if i % 2 == 0 else "video",
            "caption": "Рекламный альбом" if i == 0 else None,
            "caption_entities": [{"type": "bold", "offset": 0, "length": 9}],
        }
        for i in range(5)
    ]
    dto = ContentProcessorService.build_album_dto(valid_items)
    assert dto.content_type == ContentTypeEnum.MEDIA_GROUP
    assert len(dto.media_items) == 5
    assert dto.caption == "Рекламный альбом"
    assert dto.entities == [{"type": "bold", "offset": 0, "length": 9}]

    # Превышение лимита 10 элементов
    too_many_items = valid_items * 3  # 15 элементов
    with pytest.raises(ContentValidationError) as exc_many:
        ContentValidator.validate_album(too_many_items)
    assert "более 10 элементов" in exc_many.value.user_message

    # Недопустимый тип (документ в альбоме)
    bad_type_items: list[dict[str, Any]] = [
        *valid_items[:2],
        {"file_id": "doc_1", "file_unique_id": "u_doc", "media_type": "document"},
    ]
    with pytest.raises(ContentValidationError) as exc_type:
        ContentValidator.validate_album(bad_type_items)
    assert "только фото и видео" in exc_type.value.user_message

    # Превышение длины подписи альбома (> 1024)
    long_caption_items: list[dict[str, Any]] = [
        {
            "file_id": "f1",
            "file_unique_id": "u1",
            "media_type": "photo",
            "caption": "Д" * 1025,
        },
        {
            "file_id": "f2",
            "file_unique_id": "u2",
            "media_type": "photo",
            "caption": None,
        },
    ]
    with pytest.raises(ContentValidationError) as exc_cap:
        ContentValidator.validate_album(long_caption_items)
    assert "превышает лимит в 1024 символа" in exc_cap.value.user_message


def test_serialize_entities_preserves_offset_and_length() -> None:
    entities = [
        MessageEntity(type="bold", offset=0, length=6),
        MessageEntity(type="text_link", offset=7, length=10, url="https://example.com"),
        MessageEntity(type="spoiler", offset=18, length=5),
    ]
    serialized = ContentProcessorService.serialize_entities(entities)
    assert len(serialized) == 3
    assert serialized[0] == {"type": "bold", "offset": 0, "length": 6}
    assert serialized[1] == {
        "type": "text_link",
        "offset": 7,
        "length": 10,
        "url": "https://example.com",
    }
    assert serialized[2] == {"type": "spoiler", "offset": 18, "length": 5}


def test_process_single_photo_message_and_unsupported_types() -> None:
    msg = MagicMock(spec=Message)
    msg.voice = None
    msg.video_note = None
    msg.sticker = None
    msg.poll = None
    msg.location = None
    msg.document = None
    msg.audio = None
    msg.animation = None
    msg.contact = None
    msg.video = None
    msg.text = None
    msg.caption = "Описание фото"
    msg.caption_entities = [MessageEntity(type="italic", offset=0, length=8)]
    msg.photo = [
        PhotoSize(file_id="small_id", file_unique_id="u_s", width=100, height=100),
        PhotoSize(file_id="large_id", file_unique_id="u_l", width=800, height=600),
    ]

    dto = ContentProcessorService.process_single_message(msg)
    assert dto.content_type == ContentTypeEnum.PHOTO
    assert dto.caption == "Описание фото"
    assert len(dto.media_items) == 1
    assert dto.media_items[0].file_id == "large_id"
    assert dto.entities[0]["offset"] == 0
    assert dto.entities[0]["length"] == 8

    # Голосовое сообщение должно отклоняться
    voice_msg = MagicMock(spec=Message)
    voice_msg.voice = MagicMock()
    with pytest.raises(ContentValidationError) as exc_voice:
        ContentProcessorService.process_single_message(voice_msg)
    assert "не поддерживается" in exc_voice.value.user_message