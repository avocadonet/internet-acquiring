from aiogram import Router

from src.modules.bot_ingress.handlers.base_commands import (
    router as base_commands_router,
)
from src.modules.bot_ingress.handlers.channel_selection import (
    router as channel_selection_router,
)
from src.modules.bot_ingress.handlers.contact_submission import (
    router as contact_submission_router,
)
from src.modules.bot_ingress.handlers.content_submission import (
    router as content_submission_router,
)
from src.modules.bot_ingress.handlers.order_payment import (
    router as order_payment_router,
)


def build_bot_ingress_router() -> Router:
    """Создает и компонует корневой роутер модуля bot_ingress."""
    root_router = Router(name="bot_ingress")
    root_router.include_router(base_commands_router)
    root_router.include_router(channel_selection_router)
    root_router.include_router(content_submission_router)
    root_router.include_router(contact_submission_router)
    root_router.include_router(order_payment_router)
    return root_router


__all__ = ["build_bot_ingress_router"]