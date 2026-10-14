import html
import logging
import uuid
from typing import Protocol

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

logger = logging.getLogger(__name__)


class ICustomerNotifier(Protocol):
    """Контракт оповещения покупателя об изменении статуса заказа."""

    async def notify_refund_completed(
        self,
        customer_telegram_id: int,
        order_id: uuid.UUID,
        amount_kopecks: int,
        reason: str,
    ) -> bool: ...


class CustomerNotifierService:
    """Сервис отправки сервисных сообщений покупателю через aiogram.Bot."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def notify_refund_completed(
        self,
        customer_telegram_id: int,
        order_id: uuid.UUID,
        amount_kopecks: int,
        reason: str,
    ) -> bool:
        """Уведомляет клиента об отмене публикации и возврате средств.

        Мягко подавляет ошибки блокировки бота или недоступности чата.
        """
        amount_rubles = amount_kopecks / 100.0
        text = (
            f"📢 <b>Уведомление об отмене публикации</b>\n\n"
            f"К сожалению, размещение вашего рекламного поста по заказу "
            f"<code>{order_id}</code> не удалось.\n\n"
            f"<b>Причина:</b> <i>{html.escape(reason)}</i>\n"
            f"<b>Сумма возврата:</b> <b>{amount_rubles:.2f} ₽</b>\n\n"
            f"💳 Денежные средства автоматически отправлены обратно на вашу банковскую карту. "
            f"Срок зачисления зависит от вашего банка (обычно от 1 до 3 рабочих дней)."
        )

        try:
            await self.bot.send_message(
                chat_id=customer_telegram_id,
                text=text,
                parse_mode=ParseMode.HTML,
            )
            logger.info(
                "Уведомление о возврате успешно доставлено клиенту %s (Заказ: %s)",
                customer_telegram_id,
                order_id,
            )
            return True
        except TelegramForbiddenError as e:
            logger.warning(
                "Бот заблокирован пользователем %s. Возврат по заказу %s проведен успешно: %s",
                customer_telegram_id,
                order_id,
                e,
            )
            return False
        except TelegramBadRequest as e:
            logger.warning(
                "Чат с пользователем %s не найден при попытке уведомить о возврате заказа %s: %s",
                customer_telegram_id,
                order_id,
                e,
            )
            return False
        except Exception as e:  # noqa: BLE001
            logger.error(
                "Непредвиденная ошибка при отправке сообщения клиенту %s: %s",
                customer_telegram_id,
                e,
            )
            return False
