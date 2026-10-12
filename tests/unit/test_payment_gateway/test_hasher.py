"""Unit tests for T-Bank SHA-256 signature generator and validator.

Located at: tests/unit/test_payment_gateway/test_hasher.py
Compliant with pytest, mypy --strict, and Python 3.12+.
"""

import hashlib

from src.modules.payment_gateway.hasher import (
    generate_tbank_token,
    verify_tbank_token,
)


class TestTBankHasher:
    """Тестирование функции генерации токена generate_tbank_token."""

    def test_official_protocol_sample_vector(self) -> None:
        """Проверка расчета подписи на эталонном тестовом векторе протокола Т-Банка.

        Параметры:
          Amount: 1000
          OrderId: "order_123"
          TerminalKey: "TestTerminal"
          Password: "secret_password"

        Лексикографическая сортировка:
          Amount -> 1000
          OrderId -> order_123
          Password -> secret_password
          TerminalKey -> TestTerminal

        Строка конкатенации: "1000order_123secret_passwordTestTerminal"
        """
        payload = {
            "TerminalKey": "TestTerminal",
            "OrderId": "order_123",
            "Amount": 1000,
        }
        secret_password = "secret_password"
        expected_raw = "1000order_123secret_passwordTestTerminal"
        expected_hash = hashlib.sha256(expected_raw.encode("utf-8")).hexdigest().lower()

        token = generate_tbank_token(payload, secret_password)

        assert token == expected_hash

    def test_excluded_keys_are_filtered(self) -> None:
        """Служебные ключи Token, Receipt, DATA, Shops не должны входить в расчет подписи."""
        payload = {
            "TerminalKey": "Merchant123",
            "Amount": 50000,
            "Token": "existing_random_token_to_ignore",
            "Receipt": {"Items": [{"Price": 50000, "Name": "Test"}]},
            "DATA": {"custom_meta": "value"},
            "Shops": [{"ShopCode": "1"}],
        }
        secret_password = "pass"

        # Ожидаемые плоские ключи: Amount, Password, TerminalKey
        raw_string = "50000passMerchant123"
        expected_hash = hashlib.sha256(raw_string.encode("utf-8")).hexdigest().lower()

        token = generate_tbank_token(payload, secret_password)

        assert token == expected_hash

    def test_none_values_are_ignored(self) -> None:
        """Поля со значением None должны отбрасываться и не приводиться к строке 'None'."""
        payload_with_none = {
            "TerminalKey": "Key1",
            "OrderId": "123",
            "Description": None,
            "Success": None,
        }
        payload_without_none = {
            "TerminalKey": "Key1",
            "OrderId": "123",
        }
        secret_password = "pass"

        token_1 = generate_tbank_token(payload_with_none, secret_password)
        token_2 = generate_tbank_token(payload_without_none, secret_password)

        assert token_1 == token_2

    def test_nested_composite_types_are_ignored(self) -> None:
        """Вложенные словари и списки должны исключаться из формирования подписи."""
        payload = {
            "TerminalKey": "Key1",
            "Amount": 200,
            "nested_dict": {"k": "v"},
            "nested_list": [1, 2, 3],
        }
        secret_password = "pass"

        clean_payload = {
            "TerminalKey": "Key1",
            "Amount": 200,
        }

        assert generate_tbank_token(payload, secret_password) == generate_tbank_token(
            clean_payload, secret_password
        )

    def test_boolean_values_normalized_strictly_to_lowercase_strings(self) -> None:
        """Булевы True и False должны конвертироваться в 'true' и 'false' (не 'True', 'False', '1', '0')."""
        payload = {
            "TerminalKey": "Key1",
            "Success": True,
            "RedirectDueDate": False,
        }
        secret_password = "pwd"

        # Сортировка: Password, RedirectDueDate, Success, TerminalKey
        # Значения: pwd + false + true + Key1
        expected_raw = "pwdfalsetrueKey1"
        expected_hash = hashlib.sha256(expected_raw.encode("utf-8")).hexdigest().lower()

        token = generate_tbank_token(payload, secret_password)

        assert token == expected_hash

    def test_lexicographical_sorting_order(self) -> None:
        """Ключи должны сортироваться строго в алфавитном порядке независимо от порядка вставки."""
        payload_a = {
            "Z_key": "last",
            "A_key": "first",
            "M_key": "middle",
        }
        payload_b = {
            "A_key": "first",
            "M_key": "middle",
            "Z_key": "last",
        }
        secret_password = "secret"

        token_a = generate_tbank_token(payload_a, secret_password)
        token_b = generate_tbank_token(payload_b, secret_password)

        assert token_a == token_b


class TestTBankTokenVerification:
    """Тестирование функции валидации токена verify_tbank_token."""

    def test_verify_valid_token_matches(self) -> None:
        """Корректный токен подтверждается как валидный."""
        payload = {
            "TerminalKey": "Term1",
            "PaymentId": 1234567,
            "Status": "CONFIRMED",
        }
        secret_password = "my_secret_token"
        expected_token = generate_tbank_token(payload, secret_password)

        # Передаем токен в payload
        payload_with_token = {**payload, "Token": expected_token}

        assert verify_tbank_token(
            payload=payload_with_token,
            secret_password=secret_password,
            expected_token=expected_token,
        ) is True

    def test_verify_case_insensitive_token(self) -> None:
        """Проверка должна быть нечувствительна к регистру (uppercase vs lowercase hex)."""
        payload = {"TerminalKey": "Term1", "Amount": 100}
        secret_password = "secret"
        expected_token = generate_tbank_token(payload, secret_password)

        assert verify_tbank_token(
            payload=payload,
            secret_password=secret_password,
            expected_token=expected_token.upper(),
        ) is True

    def test_verify_tampered_payload_fails(self) -> None:
        """Изменение суммы или статуса должно приводить к провалу валидации."""
        payload = {
            "TerminalKey": "Term1",
            "Amount": 1000,
            "Status": "CONFIRMED",
        }
        secret_password = "secret"
        valid_token = generate_tbank_token(payload, secret_password)

        # Злоумышленник изменил сумму
        tampered_payload = {**payload, "Amount": 10}

        assert verify_tbank_token(
            payload=tampered_payload,
            secret_password=secret_password,
            expected_token=valid_token,
        ) is False

    def test_verify_empty_or_none_expected_token_returns_false(self) -> None:
        """Передача пустой строки токена не должна вызывать исключений и возвращать False."""
        payload = {"TerminalKey": "Term1"}
        assert verify_tbank_token(payload, "secret", "") is False