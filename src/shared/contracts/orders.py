from enum import StrEnum
from typing import Any, Protocol
import uuid
from pydantic import BaseModel, Field, field_validator
import re


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    PAID = "PAID"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    REFUND_REQUIRED = "REFUND_REQUIRED"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"


class ContentTypeEnum(StrEnum):
    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    MEDIA_GROUP = "media_group"


class MediaItemDTO(BaseModel):
    file_id: str
    file_unique_id: str
    media_type: str
    width: int | None = None
    height: int | None = None
    duration: int | None = None


class PostContentDTO(BaseModel):
    content_type: ContentTypeEnum
    text: str | None = None
    caption: str | None = None
    entities: list[dict[str, Any]] = Field(default_factory=list)
    media_items: list[MediaItemDTO] = Field(default_factory=list)


class CustomerContactDTO(BaseModel):
    phone: str | None = None
    email: str | None = None

    @field_validator("phone")
    @classmethod
    def validate_e164_phone(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = re.sub(r"[^\d+]", "", v)
        if cleaned.startswith("89") and len(cleaned) == 11:
            cleaned = "+79" + cleaned[2:]
        elif cleaned.startswith("79") and len(cleaned) == 11:
            cleaned = "+79" + cleaned[2:]
        elif cleaned.startswith("9") and len(cleaned) == 10:
            cleaned = "+79" + cleaned[1:]

        if not re.match(r"^\+79\d{9}$", cleaned):
            raise ValueError("Номер телефона должен соответствовать формату +79XXXXXXXXX")
        return cleaned

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str | None) -> str | None:
        if v is None:
            return None
        pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
        if not re.match(pattern, v):
            raise ValueError("Некорректный формат адреса электронной почты")
        return v.lower().strip()


class CreateOrderInputDTO(BaseModel):
    user_id: int
    target_channel_id: int
    content: PostContentDTO
    contact: CustomerContactDTO


class OrderCreatedResultDTO(BaseModel):
    order_id: str
    payment_url: str
    amount_kopecks: int


class IOrderService(Protocol):
    async def create_order(self, data: CreateOrderInputDTO) -> OrderCreatedResultDTO:
        """Регистрирует заказ в БД, инициирует сессию эквайринга и возвращает ссылку."""
        ...


class IOrderInternalService(Protocol):
    async def handle_payment_succeeded(self, order_id: uuid.UUID, payment_id: str) -> None:
        ...

    async def handle_publish_started(self, order_id: uuid.UUID) -> None:
        ...

    async def handle_publish_succeeded(self, order_id: uuid.UUID, published_message_id: int) -> None:
        ...

    async def handle_publish_failed(self, order_id: uuid.UUID, error_reason: str) -> None:
        ...

    async def handle_refund_succeeded(self, order_id: uuid.UUID, refund_info: dict[str, Any]) -> None:
        ...