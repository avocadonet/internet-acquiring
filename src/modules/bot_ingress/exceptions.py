class BotIngressError(Exception):
    """Базовое исключение модуля bot_ingress."""


class ContentValidationError(BotIngressError):
    """Ошибка валидации пользовательского контента (длина, тип, размер альбома)."""

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


class ContactValidationError(BotIngressError):
    """Ошибка валидации контактных данных покупателя для чека 54-ФЗ."""

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message