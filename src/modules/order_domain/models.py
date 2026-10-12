import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Enum, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from src.shared.contracts.orders import OrderStatus


class Base(DeclarativeBase):
    """Базовый декларативный класс ORM для сущностей модуля."""


class OrderModel(Base):
    """
    ORM-модель заказа рекламы в PostgreSQL.
    Содержит идентификаторы участников, финансовые данные, полезную нагрузку
    публикации (JSONB), контакты заказчика и аудит жизненного цикла.
    """
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
    )
    target_chat_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    amount_kopecks: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status_enum", native_enum=True),
        nullable=False,
        default=OrderStatus.PENDING,
        index=True,
    )

    content_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )
    contact_info: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )

    payment_id: Mapped[str | None] = mapped_column(
        String(64),
        unique=True,
        nullable=True,
        index=True,
    )
    payment_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    published_message_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    refund_details: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )