class CompensationError(Exception):
    """Базовое исключение доменного контура компенсаций."""


class CustomerNotificationError(CompensationError):
    """Ошибка при попытке уведомить пользователя в Telegram."""


class BankRefundRejectedError(CompensationError):
    """Бизнес-отказ или неуспешный статус эквайринга при возврате."""


class InvalidRefundPayloadError(CompensationError):
    """Ошибка валидации данных полезной нагрузки возврата."""
