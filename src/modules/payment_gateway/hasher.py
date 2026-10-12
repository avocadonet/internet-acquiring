"""SHA-256 signature generator and validator for T-Bank Acquiring API v2.

Strictly follows T-Bank protocol hashing requirements:
1. Excludes keys: Token, Receipt, DATA, Shops.
2. Excludes keys with None values.
3. Excludes composite objects (dicts, lists).
4. Normalizes booleans strictly to lowercase "true" / "false".
5. Appends Password: <secret_password>.
6. Sorts keys alphabetically (lexicographical order).
7. Concatenates values without delimiters.
8. Computes lowercase SHA-256 hexdigest.

Compliant with mypy --strict and Python 3.12+.
"""

import hashlib
import hmac
from typing import Any

# Служебные ключи протокола Т-Банка, исключаемые из расчета подписи
EXCLUDED_KEYS: frozenset[str] = frozenset({"Token", "Receipt", "DATA", "Shops"})


def generate_tbank_token(payload: dict[str, Any], secret_password: str) -> str:
    """Генерирует SHA-256 токен подписи запроса или вебхука Т-Банка.

    Args:
        payload: Словарь параметров запроса или уведомления банка.
        secret_password: Секретный пароль терминала мерчанта.

    Returns:
        Шестнадцатеричная строка хеша SHA-256 в нижнем регистре.
    """
    flat_params: dict[str, str] = {}

    for key, value in payload.items():
        # 1. Исключаем служебные ключи протокола
        if key in EXCLUDED_KEYS:
            continue

        # 2. Исключаем None (значение "None" ломает хеш)
        if value is None:
            continue

        # 3. Исключаем составные объекты (словари и массивы)
        if isinstance(value, (dict, list)):
            continue

        # 4. Нормализация типов: булевы значения строго "true"/"false"
        # Важно: в Python bool является подтипом int, поэтому проверка идет первой
        if isinstance(value, bool):
            flat_params[str(key)] = "true" if value else "false"
        else:
            flat_params[str(key)] = str(value)

    # 5. Добавляем секретный пароль терминала
    flat_params["Password"] = secret_password

    # 6. Лексикографическая сортировка ключей в алфавитном порядке
    sorted_keys = sorted(flat_params.keys())

    # 7. Конкатенация только значений словаря без разделителей
    raw_signature = "".join(flat_params[k] for k in sorted_keys)

    # 8. Расчет SHA-256 в нижнем регистре
    return hashlib.sha256(raw_signature.encode("utf-8")).hexdigest().lower()


def verify_tbank_token(
    payload: dict[str, Any],
    secret_password: str,
    expected_token: str,
) -> bool:
    """Проверяет подлинность токена входящего вебхука Т-Банка.

    Использует hmac.compare_digest для защиты от timing-атак.

    Args:
        payload: Тело полученного уведомления от банка.
        secret_password: Секретный пароль терминала мерчанта.
        expected_token: Значение токена из поля 'Token' уведомления.

    Returns:
        True, если подпись валидна, иначе False.
    """
    if not expected_token:
        return False

    calculated_token = generate_tbank_token(payload, secret_password)
    return hmac.compare_digest(calculated_token, expected_token.lower())