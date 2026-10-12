class ChannelPublisherError(Exception):
    """Базовое исключение модуля channel_publisher."""



class ContentNormalizationError(ChannelPublisherError):
    """Ошибка при валидации или преобразовании структуры контента в объекты Telegram."""



class UnsupportedMediaTypeError(ContentNormalizationError):
    """Передан неподдерживаемый тип медиафайла."""



class InvalidMediaGroupSizeError(ContentNormalizationError):
    """Количество элементов медиагруппы не укладывается в лимиты Telegram (от 2 до 10)."""



class PublishingDeliveryError(ChannelPublisherError):
    """Ошибка на этапе отправки контента в Telegram Bot API."""



class UnconfirmedDeliveryError(PublishingDeliveryError):
    """
    Сетевой сбой при чтении ответа (ReadTimeout / ServerDisconnectedError).
    Статус размещения неизвестен, существует высокий риск дублирования публикации.
    """

