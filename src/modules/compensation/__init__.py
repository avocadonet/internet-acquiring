"""Модуль компенсаций и управления инцидентами (Package-by-Feature).

Обеспечивает автоматический возврат денежных средств клиентам при срыве публикаций,
нотификацию пользователей в Telegram-боте, отправку структурированных HTML-алертов
дежурным администраторам и мониторинг перманентно сбойных задач (DLQ).
"""

from src.modules.compensation.alerter import IncidentAlertDTO, TelegramIncidentAlerter
from src.modules.compensation.config import CompensationConfig
from src.modules.compensation.customer_notifier import CustomerNotifierService
from src.modules.compensation.dlq_service import DeadLetterTaskDTO, DLQService
from src.modules.compensation.refund_handler import (
    ExecuteRefundPayloadDTO,
    RefundTaskHandler,
)

__all__ = [
    "CompensationConfig",
    "CustomerNotifierService",
    "DLQService",
    "DeadLetterTaskDTO",
    "ExecuteRefundPayloadDTO",
    "IncidentAlertDTO",
    "RefundTaskHandler",
    "TelegramIncidentAlerter",
]
