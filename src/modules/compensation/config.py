from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CompensationConfig(BaseSettings):
    """Конфигурация контура компенсаций и диспетчеризации инцидентов."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    ADMIN_ALERT_CHAT_ID: int = Field(
        ...,
        validation_alias="TELEGRAM_ADMIN_CHAT_ID",
        description="ID чата/канала дежурных администраторов для алертов",
    )
    BOT_TOKEN_ALERTS: str = Field(
        ...,
        validation_alias="TELEGRAM_BOT_TOKEN",
        description="Токен Telegram-бота для отправки оповещений",
    )
