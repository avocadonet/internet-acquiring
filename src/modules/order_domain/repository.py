import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, Integer, func, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from src.modules.order_domain.models import Base, OrderModel
from src.shared.contracts.outbox import OutboxTaskType

try:
    from src.shared.contracts.outbox import OutboxTaskModel  # type: ignore[attr-defined]
except ImportError:

    class OutboxTaskModel(Base):  # type: ignore[no-redef]
        __tablename__ = "outbox_tasks"
        __table_args__ = {"extend_existing": True}  # noqa: RUF012

        id: Mapped[uuid.UUID] = mapped_column(
            UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
        )
        task_type: Mapped[OutboxTaskType] = mapped_column(
            Enum(OutboxTaskType, name="outbox_task_type_enum", native_enum=True),
            nullable=False,
        )
        payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
        execute_after: Mapped[datetime] = mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        )
        locked_until: Mapped[datetime | None] = mapped_column(
            DateTime(timezone=True), nullable=True
        )
        retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
        processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
        created_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        )


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self,
        order_id: uuid.UUID,
        for_update: bool = False,
    ) -> OrderModel | None:
        stmt = select(OrderModel).where(OrderModel.id == order_id)
        if for_update:
            stmt = stmt.with_for_update()

        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_payment_id(
        self,
        payment_id: str,
        for_update: bool = False,
    ) -> OrderModel | None:
        stmt = select(OrderModel).where(OrderModel.payment_id == payment_id)
        if for_update:
            stmt = stmt.with_for_update()

        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, order: OrderModel) -> OrderModel:
        self._session.add(order)
        await self._session.flush()
        return order

    def add_outbox_task(
        self,
        task_type: OutboxTaskType,
        payload: dict[str, Any],
        execute_after: datetime | None = None,
    ) -> OutboxTaskModel:
        if execute_after is None:
            execute_after = datetime.now(UTC)

        task = OutboxTaskModel(
            task_type=task_type,
            payload=payload,
            execute_after=execute_after,
        )
        self._session.add(task)
        return task