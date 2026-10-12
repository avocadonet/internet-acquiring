from typing import Protocol
import uuid
from pydantic import BaseModel
from src.shared.contracts.orders import PostContentDTO


class PublishPostPayloadDTO(BaseModel):
    order_id: uuid.UUID
    target_chat_id: int
    content: PostContentDTO


class PublishResultDTO(BaseModel):
    order_id: uuid.UUID
    published_message_id: int
    chat_id: int


class IPublisherService(Protocol):
    async def publish(self, payload: PublishPostPayloadDTO) -> PublishResultDTO:
        """Публикует пост в канале и возвращает идентификатор размещенного сообщения."""
        ...