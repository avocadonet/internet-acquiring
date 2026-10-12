from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ChannelPublisherConfig(BaseSettings):
    """Конфигурация сетевого контура и параметров публикации модуля channel_publisher."""

    model_config = SettingsConfigDict(
        env_prefix="PUBLISHER_",
        env_file=".env",
        extra="ignore",
    )

    # Сетевые таймауты (в секундах)
    connect_timeout: float = Field(
        default=5.0,
        description="Таймаут установки TCP-соединения",
    )
    sock_connect_timeout: float = Field(
        default=5.0,
        description="Таймаут подключения к сокету",
    )
    sock_read_timeout: float = Field(
        default=20.0,
        description="Таймаут чтения сокета при ожидании ответа Telegram API",
    )
    total_timeout: float = Field(
        default=30.0,
        description="Общий предельный таймаут HTTP-запроса",
    )

    # Параметры пула TCP-соединений
    pool_limit: int = Field(
        default=100,
        description="Максимальное количество одновременных соединений в пуле",
    )
    pool_limit_per_host: int = Field(
        default=30,
        description="Максимальное количество одновременных соединений к api.telegram.org",
    )


publisher_config = ChannelPublisherConfig()