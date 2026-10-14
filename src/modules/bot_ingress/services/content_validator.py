from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from src.modules.bot_ingress.exceptions import (
    ContactValidationError,
    ContentValidationError,
)
from src.shared.contracts.orders import CustomerContactDTO

MAX_TEXT_LENGTH = 4096
MAX_CAPTION_LENGTH = 1024
MIN_ALBUM_ITEMS = 2
MAX_ALBUM_ITEMS = 10
ALLOWED_MEDIA_TYPES = frozenset({"photo", "video"})

UNSUPPORTED_CONTENT_MESSAGE = (
    "⚠️ Данный тип сообщения не поддерживается для рекламных публикаций. "
    "Отправьте текст, фото, видео или альбом."
)

INVALID_CONTACT_MESSAGE = (
    "⚠️ Пожалуйста, введите корректный номер мобильного телефона в формате "
    "+79XXXXXXXXX или валидный Email для отправки электронного чека."
)


class ContentValidator:
    """Сервис валидации контента публикации и контактов покупателя."""

    @staticmethod
    def validate_text(text: str | None) -> str:
        """Проверяет одиночное текстовое сообщение (до 4096 символов)."""
        if not text:
            raise ContentValidationError(UNSUPPORTED_CONTENT_MESSAGE)
        length = len(text)
        if length > MAX_TEXT_LENGTH:
            raise ContentValidationError(
                f"⚠️ Текст сообщения превышает 4096 символов (сейчас: {length}). "
                "Пожалуйста, сократите текст публикации."
            )
        return text

    @staticmethod
    def validate_single_media_caption(caption: str | None) -> str | None:
        """Проверяет длину подписи одиночного фото или видео (до 1024 символов)."""
        actual_len = len(caption or "")
        if actual_len > MAX_CAPTION_LENGTH:
            raise ContentValidationError(
                f"⚠️ Подпись к медиафайлу не может превышать 1024 символа "
                f"(сейчас: {actual_len}). Пожалуйста, сократите подпись."
            )
        return caption

    @staticmethod
    def validate_album(
        messages: Sequence[Mapping[str, Any]],
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """
        Проверяет собранный альбом (медиагруппу):
        - количество элементов от 2 до 10;
        - только типы photo и video;
        - подпись из первого непустого элемента <= 1024 символов.
        Возвращает кортеж (caption, caption_entities).
        """
        count = len(messages)
        if count > MAX_ALBUM_ITEMS:
            raise ContentValidationError(
                "⚠️ Telegram не поддерживает альбомы более 10 элементов."
            )
        if count < MIN_ALBUM_ITEMS:
            raise ContentValidationError(
                "⚠️ Альбом должен содержать минимум 2 элемента."
            )

        for item in messages:
            media_type = item.get("media_type")
            if media_type not in ALLOWED_MEDIA_TYPES:
                raise ContentValidationError(
                    "⚠️ В альбом можно объединять только фото и видео."
                )

        caption: str | None = None
        caption_entities: list[dict[str, Any]] = []

        for item in messages:
            raw_caption = item.get("caption")
            if isinstance(raw_caption, str) and raw_caption != "":
                caption = raw_caption
                raw_entities = item.get("caption_entities")
                if isinstance(raw_entities, list):
                    caption_entities = list(raw_entities)
                break

        if caption is not None and len(caption) > MAX_CAPTION_LENGTH:
            raise ContentValidationError(
                "⚠️ Подпись к альбому превышает лимит в 1024 символа."
            )

        return caption, caption_entities

    @staticmethod
    def validate_contact(raw_input: str | None) -> CustomerContactDTO:
        """
        Валидирует и нормализует телефон (E.164 +79XXXXXXXXX) или Email
        с использованием контрактного DTO CustomerContactDTO.
        """
        if not raw_input or not raw_input.strip():
            raise ContactValidationError(INVALID_CONTACT_MESSAGE)

        cleaned = raw_input.strip()
        try:
            if "@" in cleaned:
                dto = CustomerContactDTO(email=cleaned)
            else:
                dto = CustomerContactDTO(phone=cleaned)
        except ValidationError as exc:
            raise ContactValidationError(INVALID_CONTACT_MESSAGE) from exc

        if dto.phone is None and dto.email is None:
            raise ContactValidationError(INVALID_CONTACT_MESSAGE)

        return dto