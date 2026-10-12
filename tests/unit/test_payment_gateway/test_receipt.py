"""Unit tests for 54-FZ fiscal receipt builder.

Located at: tests/unit/test_payment_gateway/test_receipt.py
Compliant with pytest, mypy --strict, and Python 3.12+.
"""

import pytest

from src.modules.payment_gateway.exceptions import FiscalizationError
from src.modules.payment_gateway.receipt import (
    MAX_ITEM_NAME_LENGTH,
    ReceiptBuilder,
)
from src.shared.contracts.orders import CustomerContactDTO


class TestReceiptBuilder:
    """Тестирование генерации фискального блока Receipt по 54-ФЗ."""

    def test_build_receipt_with_email_and_phone(self) -> None:
        """Формирование чека при наличии обоих каналов связи (Email и Phone)."""
        builder = ReceiptBuilder(taxation="usn_income", default_tax="none")
        contact = CustomerContactDTO(
            email="client@example.com",
            phone="+79991234567",
        )

        receipt = builder.build_receipt(
            amount_kopecks=150000,
            description="Размещение рекламы в канале",
            contact=contact,
        )

        assert receipt["Taxation"] == "usn_income"
        assert receipt["Email"] == "client@example.com"
        assert receipt["Phone"] == "+79991234567"
        assert len(receipt["Items"]) == 1

        item = receipt["Items"][0]
        assert item["Name"] == "Размещение рекламы в канале"
        assert item["Price"] == 150000
        assert item["Amount"] == 150000
        assert item["Quantity"] == 1.00
        assert item["PaymentMethod"] == "full_payment"
        assert item["PaymentObject"] == "service"
        assert item["Tax"] == "none"

    def test_build_receipt_with_email_only(self) -> None:
        """Успешное формирование чека только с Email."""
        builder = ReceiptBuilder(taxation="osn", default_tax="vat20")
        contact = CustomerContactDTO(email="user@test.org", phone=None)

        receipt = builder.build_receipt(
            amount_kopecks=5000,
            description="Тариф Базовый",
            contact=contact,
        )

        assert receipt["Taxation"] == "osn"
        assert receipt["Email"] == "user@test.org"
        assert "Phone" not in receipt
        assert receipt["Items"][0]["Tax"] == "vat20"

    def test_build_receipt_with_phone_only(self) -> None:
        """Успешное формирование чека только с Phone."""
        builder = ReceiptBuilder(taxation="patent", default_tax="none")
        contact = CustomerContactDTO(email=None, phone="+79123456789")

        receipt = builder.build_receipt(
            amount_kopecks=99000,
            description="Публикация поста",
            contact=contact,
        )

        assert receipt["Taxation"] == "patent"
        assert receipt["Phone"] == "+79123456789"
        assert "Email" not in receipt

    def test_build_receipt_without_contacts_raises_error(self) -> None:
        """Отсутствие обоих контактов вызывает FiscalizationError."""
        builder = ReceiptBuilder()
        contact = CustomerContactDTO(email=None, phone=None)

        with pytest.raises(FiscalizationError) as exc_info:
            builder.build_receipt(
                amount_kopecks=10000,
                description="Тест",
                contact=contact,
            )

        assert "Для формирования чека 54-ФЗ требуется Email или Phone" in str(
            exc_info.value
        )
        assert exc_info.value.field_name == "contact"

    def test_description_truncation_to_128_characters(self) -> None:
        """Наименование позиции длиннее 128 символов обрезается до MAX_ITEM_NAME_LENGTH."""
        builder = ReceiptBuilder()
        contact = CustomerContactDTO(email="test@example.com")
        long_description = "A" * 200

        receipt = builder.build_receipt(
            amount_kopecks=10000,
            description=long_description,
            contact=contact,
        )

        item_name = receipt["Items"][0]["Name"]
        assert len(item_name) == MAX_ITEM_NAME_LENGTH
        assert item_name == "A" * 128

    def test_empty_description_falls_back_to_default(self) -> None:
        """Передача пустой строки или пробелов в описании заменяется на дефолтное название услуги."""
        builder = ReceiptBuilder()
        contact = CustomerContactDTO(email="test@example.com")

        receipt = builder.build_receipt(
            amount_kopecks=5000,
            description="   ",
            contact=contact,
        )

        assert receipt["Items"][0]["Name"] == "Оплата рекламных услуг"

    @pytest.mark.parametrize("invalid_amount", [0, -100, -1])
    def test_invalid_amount_raises_error(self, invalid_amount: int) -> None:
        """Сумма позиции меньше либо равная 0 должна вызывать FiscalizationError."""
        builder = ReceiptBuilder()
        contact = CustomerContactDTO(email="test@example.com")

        with pytest.raises(FiscalizationError) as exc_info:
            builder.build_receipt(
                amount_kopecks=invalid_amount,
                description="Услуга",
                contact=contact,
            )

        assert "Amount must be a positive integer" in str(exc_info.value)
        assert exc_info.value.field_name == "amount_kopecks"