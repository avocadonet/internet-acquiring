import html
import logging
import uuid
from typing import Any, Protocol

from aiogram import Bot
from aiogram.enums import ParseMode
from pydantic import BaseModel, Field

from src.modules.compensation.config import CompensationConfig

logger = logging.getLogger(__name__)


class IncidentAlertDTO(BaseModel):
    """Структура данных для регистрации и передачи инцидента."""

    level: str  # "INFO" | "WARNING" | "CRITICAL" | "FATAL"
    title: str
    order_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    error_message: str
    context: dict[str, Any] = Field(default_factory=dict)


class IIncidentAlerter(Protocol):
    """Интерфейс сервиса отправки алертов."""

    async def send_alert(self, alert: IncidentAlertDTO) -> None:
        """Отправляет форматированное оповещение в служебный чат."""
        ...


class TelegramIncidentAlerter:
    """Сервис формирования и доставки HTML-алертов дежурным инженерам."""

    def __init__(self, bot: Bot, config: CompensationConfig) -> None:
        self.bot = bot
        self.chat_id = config.ADMIN_ALERT_CHAT_ID

    async def send_info_alert(
        self,
        title: str,
        order_id: uuid.UUID,
        amount_kopecks: int,
        reason: str,
    ) -> None:
        """Отправляет информационный алерт об успешном возврате средств."""
        amount_rubles = amount_kopecks / 100.0
        text = (
            f"ℹ️ <b>[INFO] {html.escape(title)}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Order ID:</b> <code>{order_id}</code>\n"
            f"<b>Сумма возврата:</b> <code>{amount_rubles:.2f} ₽</code>\n"
            f"<b>Причина отмены:</b> <i>{html.escape(reason)}</i>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Средства возвращены на карту покупателя.</i>"
        )
        await self._safe_send(text)

    async def send_critical_alert(
        self,
        title: str,
        order_id: uuid.UUID,
        payment_id: str,
        amount_kopecks: int,
        error_message: str,
        publish_failure_reason: str,
        task_id: uuid.UUID | None = None,
    ) -> None:
        """Отправляет критический алерт о сбое возврата (требуется ручное вмешательство)."""
        amount_rubles = amount_kopecks / 100.0
        task_line = f"<b>Task ID:</b> <code>{task_id}</code>\n" if task_id else ""
        text = (
            f"🚨 <b>[CRITICAL] {html.escape(title)}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Order ID:</b> <code>{order_id}</code>\n"
            f"{task_line}"
            f"<b>Payment ID:</b> <code>{payment_id}</code>\n"
            f"<b>Сумма:</b> <code>{amount_rubles:.2f} ₽</code>\n\n"
            f"<b>Причина сбоя публикации:</b>\n"
            f"<code>{html.escape(publish_failure_reason)}</code>\n\n"
            f"<b>Ошибка возврата:</b>\n"
            f"<code>{html.escape(error_message)}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ <b>Требуется ручное вмешательство в ЛК Т-Бизнес!</b>"
        )
        await self._safe_send(text)

    async def send_alert(self, alert: IncidentAlertDTO) -> None:
        """Реализация обобщенной отправки IncidentAlertDTO."""
        order_line = (
            f"<b>Order ID:</b> <code>{alert.order_id}</code>\n"
            if alert.order_id
            else ""
        )
        task_line = (
            f"<b>Task ID:</b> <code>{alert.task_id}</code>\n" if alert.task_id else ""
        )
        text = (
            f"⚠️ <b>[{html.escape(alert.level)}] {html.escape(alert.title)}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{order_line}{task_line}"
            f"<b>Ошибка:</b> <code>{html.escape(alert.error_message)}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )
        await self._safe_send(text)

    async def _safe_send(self, text: str) -> None:
        """Отправляет сообщение с подавлением сетевых ошибок алертинга."""
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:  # noqa: BLE001
            logger.critical("Не удалось отправить алерт инцидента в Telegram: %s", e)
