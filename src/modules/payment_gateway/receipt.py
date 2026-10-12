"""54-FZ fiscal receipt builder for T-Bank Acquiring API v2.

Complies with Section 4.2 and Section 7.1 of Payment Gateway specification.
Integrates with CustomerContactDTO from shared contracts layer.
Compliant with mypy --strict and Python 3.12+.
"""

import re
from typing import Any

from src.modules.payment_gateway.config import TaxationType, TaxRateType
from src.modules.payment_gateway.exceptions import FiscalizationError
from src.shared.contracts.orders import CustomerContactDTO

# Ограничение длины поля Name товарной позиции по протоколу Т-Банка
MAX_ITEM_NAME_LENGTH: int = 128

# Регулярное выражение для базовой проверки формата E.164 (+7XXXXXXXXXX)
E164_PHONE_PATTERN: re.Pattern[str] = re.compile(r"^\+[1-9]\d{10,14}$")


class ReceiptBuilder:
    """Генератор фискального блока Receipt для API эквайринга Т-Банка."""

    def __init__(
        self,
        taxation: TaxationType | str = "usn_income",
        default_tax: TaxRateType | str = "none",
    ) -> None:
        """Инициализирует построитель чека налоговыми параметрами терминала.

        Args:
            taxation: Система налогообложения мерчанта (osn, usn_income и др.).
            default_tax: Ставка НДС позиции по умолчанию (none, vat0, vat20 и др.).
        """
        self.taxation: str = taxation
        self.default_tax: str = default_tax

    def build_receipt(
        self,
        amount_kopecks: int,
        description: str,
        contact: CustomerContactDTO,
    ) -> dict[str, Any]:
        """Формирует и валидирует словарь фискального чека 54-ФЗ.

        Args:
            amount_kopecks: Полная сумма чека в копейках.
            description: Описание услуги или наименование товара.
            contact: DTO контактов покупателя (email и/или phone).

        Returns:
            Словарь структуры 'Receipt' для передачи в метод /v2/Init.

        Raises:
            FiscalizationError: Если отсутствуют контакты или сумма некорректна.
        """
        # 1. Валидация суммы позиции
        if not isinstance(amount_kopecks, int) or amount_kopecks <= 0:
            raise FiscalizationError(
                f"Amount must be a positive integer in kopecks, got: {amount_kopecks}",
                field_name="amount_kopecks",
            )

        # 2. Валидация контактов покупателя (54-ФЗ требует минимум один канал доставки чека)
        email_val: str | None = contact.email.strip() if contact.email else None
        phone_val: str | None = contact.phone.strip() if contact.phone else None

        if not email_val and not phone_val:
            raise FiscalizationError(
                "Для формирования чека 54-ФЗ требуется Email или Phone",
                field_name="contact",
            )

        # 3. Нормализация телефона в формат E.164 при наличии
        if phone_val is not None:
            if not phone_val.startswith("+"):
                phone_val = f"+{phone_val}"
            if not E164_PHONE_PATTERN.match(phone_val):
                raise FiscalizationError(
                    f"Invalid phone format: '{phone_val}'. Expected E.164 (+7XXXXXXXXXX)",
                    field_name="phone",
                )

        # 4. Формирование наименования товарной позиции (лимит протокола: 128 символов)
        clean_description: str = description.strip()
        if not clean_description:
            clean_description = "Оплата рекламных услуг"
        item_name: str = clean_description[:MAX_ITEM_NAME_LENGTH]

        # 5. Сборка объекта товарной позиции в копейках
        item_payload: dict[str, Any] = {
            "Name": item_name,
            "Price": amount_kopecks,
            "Quantity": 1.00,
            "Amount": amount_kopecks,
            "PaymentMethod": "full_payment",
            "PaymentObject": "service",
            "Tax": self.default_tax,
        }

        # 6. Сборка итогового блока Receipt
        receipt: dict[str, Any] = {
            "Taxation": self.taxation,
            "Items": [item_payload],
        }

        if email_val:
            receipt["Email"] = email_val
        if phone_val:
            receipt["Phone"] = phone_val

        return receipt