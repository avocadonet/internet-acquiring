"""Configuration settings for Payment Gateway module.

Strictly aligned with deploy/env.example and T-Bank Acquiring API v2.
Compliant with Pydantic v2 / pydantic-settings and mypy --strict.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Системы налогообложения 54-ФЗ, поддерживаемые Т-Банком
TaxationType = Literal[
    "osn",                 # Общая СНО
    "usn_income",          # Упрощенная СНО (доходы)
    "usn_income_outcome",  # Упрощенная СНО (доходы минус расходы)
    "envd",                # Единый налог на вмененный доход
    "esn",                 # Единый сельскохозяйственный налог
    "patent",              # Патентная СНО
]

# Ставки НДС 54-ФЗ, поддерживаемые Т-Банком
TaxRateType = Literal[
    "none",    # Без НДС
    "vat0",    # НДС 0%
    "vat10",   # НДС 10%
    "vat20",   # НДС 20%
    "vat110",  # НДС по расчетной ставке 10/110
    "vat120",  # НДС по расчетной ставке 20/120
]


class PaymentGatewayConfig(BaseSettings):
    """Настройки эквайринга Т-Банка и фискализации 54-ФЗ."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Идентификатор терминала Т-Банка
    terminal_key: str = Field(
        ...,
        validation_alias="TBANK_TERMINAL_KEY",
        description="Ключ терминала мерчанта Т-Банка",
    )

    # Секретный пароль терминала
    secret_password: SecretStr = Field(
        ...,
        validation_alias="TBANK_SECRET_PASSWORD",
        description="Секретный пароль терминала для формирования токена подписи SHA-256",
    )

    # Базовый URL API (по умолчанию тестовый контур, согласно env.example)
    api_url: HttpUrl = Field(
        default=HttpUrl("https://rest-api-test.tinkoff.ru/v2"),
        validation_alias="TBANK_API_URL",
        description="Базовый адрес API эквайринга Т-Банка v2",
    )

    # Система налогообложения мерчанта по 54-ФЗ
    taxation: TaxationType = Field(
        default="usn_income",
        validation_alias="TBANK_TAXATION",
        description="Система налогообложения по 54-ФЗ",
    )

    # Ставка НДС позиции чека (в env.example: TBANK_ITEM_TAX=none)
    item_tax: TaxRateType = Field(
        default="none",
        validation_alias="TBANK_ITEM_TAX",
        description="Ставка НДС для фискальной позиции чека",
    )

    # Сетевые таймауты httpx (секунды)
    timeout_connect: float = Field(
        default=5.0,
        validation_alias="TBANK_TIMEOUT_CONNECT",
        ge=0.1,
        description="Таймаут установки соединения httpx",
    )
    timeout_read: float = Field(
        default=10.0,
        validation_alias="TBANK_TIMEOUT_READ",
        ge=0.1,
        description="Таймаут чтения ответа httpx",
    )
    timeout_write: float = Field(
        default=5.0,
        validation_alias="TBANK_TIMEOUT_WRITE",
        ge=0.1,
        description="Таймаут записи/отправки запроса httpx",
    )

    @property
    def base_url_str(self) -> str:
        """Нормализованный URL без завершающего слеша."""
        return str(self.api_url).rstrip("/")


@lru_cache(maxsize=1)
def get_payment_gateway_config() -> PaymentGatewayConfig:
    """Синглтон фабрики конфигурации для FastAPI Depends."""
    return PaymentGatewayConfig()  # type: ignore[call-arg]