from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.outbox_engine.models import OutboxTaskModel


class SqlAlchemyDLQTaskReader:
    """Адаптер чтения перманентно сбойных задач (failed_permanently = TRUE) для DLQService."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    async def get_permanently_failed_tasks(
        self,
        limit: int = 50,
    ) -> list[Any]:
        """Возвращает список задач из outbox_tasks, переведенных в статус failed_permanently."""
        stmt = (
            select(OutboxTaskModel)
            .where(OutboxTaskModel.failed_permanently.is_(True))
            .order_by(OutboxTaskModel.created_at.desc())
            .limit(limit)
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())