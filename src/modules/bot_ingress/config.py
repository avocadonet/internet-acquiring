from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ChannelTariffDTO(BaseModel):
    """Описание рекламного канала и стоимости размещения."""

    channel_id: int
    title: str
    price_kopecks: int = Field(gt=0)

    @property
    def price_rubles(self) -> int:
        return self.price_kopecks // 100


def _default_channels() -> list[ChannelTariffDTO]:
    return [
        ChannelTariffDTO(
            channel_id=-1001111111111,
            title="Канал IT Новости",
            price_kopecks=150_000,
        ),
        ChannelTariffDTO(
            channel_id=-1002222222222,
            title="Бизнес и Стартапы",
            price_kopecks=250_000,
        ),
        ChannelTariffDTO(
            channel_id=-1003333333333,
            title="Маркетинг и Digital",
            price_kopecks=300_000,
        ),
    ]


class BotIngressConfig(BaseSettings):
    """Конфигурация модуля Bot UX & Content Ingress."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    bot_token: str = Field(
        default="1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ",
        validation_alias="TELEGRAM_BOT_TOKEN",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias="REDIS_URL",
    )
    debounce_window_seconds: float = Field(default=1.5, gt=0.0)
    debounce_poll_interval_seconds: float = Field(default=0.2, gt=0.0)
    media_group_ttl_seconds: int = Field(default=120, gt=0)
    order_lock_ttl_seconds: int = Field(default=10, gt=0)
    channels: list[ChannelTariffDTO] = Field(default_factory=_default_channels)

    def get_channel(self, channel_id: int) -> ChannelTariffDTO | None:
        """Возвращает тариф канала по его Telegram ID."""
        for channel in self.channels:
            if channel.channel_id == channel_id:
                return channel
        return None