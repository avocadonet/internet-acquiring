import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

logger = logging.getLogger(__name__)


class DeliveryState(StrEnum):
    """Состояние доставки публикации в Telegram Bot API."""

    IDLE = "IDLE"
    IN_FLIGHT = "IN_FLIGHT"
    CONFIRMED = "CONFIRMED"
    SUSPECTED_DUPLICATE = "SUSPECTED_DUPLICATE"
    FAILED = "FAILED"


@dataclass(slots=True)
class PublicationAttempt:
    """Запись о фазе попытки публикации заказа."""

    order_id: uuid.UUID
    state: DeliveryState
    attempts_count: int
    published_message_id: int | None = None
    last_error: str | None = None
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


class AntiDuplicateGuard:
    """
    Механизм трекинга и защиты от дублирования постов при сетевых аномалиях.
    Предотвращает повторный вызов Bot API для заказов со статусом SUSPECTED_DUPLICATE или CONFIRMED.
    """

    def __init__(self) -> None:
        self._states: dict[uuid.UUID, PublicationAttempt] = {}

    def is_already_published(self, order_id: uuid.UUID) -> int | None:
        """
        Проверяет, зафиксирована ли уже успешная публикация для данного заказа.
        Возвращает published_message_id, если пост уже опубликован.
        """
        attempt = self._states.get(order_id)
        if attempt and attempt.state == DeliveryState.CONFIRMED:
            return attempt.published_message_id
        return None

    def is_suspected_duplicate(self, order_id: uuid.UUID) -> bool:
        """
        Проверяет, помечен ли заказ как потенциальный дубликат после ReadTimeout.
        """
        attempt = self._states.get(order_id)
        return bool(attempt and attempt.state == DeliveryState.SUSPECTED_DUPLICATE)

    def mark_in_flight(self, order_id: uuid.UUID) -> None:
        """
        Фиксирует переход в фазу сетевого запроса к Telegram Bot API.
        """
        current = self._states.get(order_id)
        attempts = (current.attempts_count + 1) if current else 1

        self._states[order_id] = PublicationAttempt(
            order_id=order_id,
            state=DeliveryState.IN_FLIGHT,
            attempts_count=attempts,
            published_message_id=None,
            last_error=None,
        )
        logger.debug(
            "Заказ %s переведен в фазу IN_FLIGHT (попытка %s)", order_id, attempts
        )

    def mark_confirmed(self, order_id: uuid.UUID, message_id: int) -> None:
        """
        Фиксирует подтвержденную успешную публикацию с идентификатором сообщения.
        """
        current = self._states.get(order_id)
        attempts = current.attempts_count if current else 1

        self._states[order_id] = PublicationAttempt(
            order_id=order_id,
            state=DeliveryState.CONFIRMED,
            attempts_count=attempts,
            published_message_id=message_id,
            last_error=None,
        )
        logger.info(
            "Заказ %s подтвержден как опубликованный (message_id=%s)",
            order_id,
            message_id,
        )

    def mark_suspected_timeout(self, order_id: uuid.UUID, reason: str) -> None:
        """
        Фиксирует сетевой обрыв во время чтения ответа (ReadTimeout / ServerDisconnected).
        Заказ переводится в подозрение на дублирование (SUSPECTED_DUPLICATE).
        """
        current = self._states.get(order_id)
        attempts = current.attempts_count if current else 1

        self._states[order_id] = PublicationAttempt(
            order_id=order_id,
            state=DeliveryState.SUSPECTED_DUPLICATE,
            attempts_count=attempts,
            published_message_id=None,
            last_error=reason,
        )
        logger.critical(
            "Заказ %s помечен как SUSPECTED_DUPLICATE: ответ Bot API не получен, "
            "возможна фантомная публикация. Ошибка: %s",
            order_id,
            reason,
        )

    def mark_failed(self, order_id: uuid.UUID, error: str) -> None:
        """
        Фиксирует окончательный сбой публикации.
        """
        current = self._states.get(order_id)
        attempts = current.attempts_count if current else 1

        self._states[order_id] = PublicationAttempt(
            order_id=order_id,
            state=DeliveryState.FAILED,
            attempts_count=attempts,
            published_message_id=None,
            last_error=error,
        )

    def reset(self, order_id: uuid.UUID) -> None:
        """Сбрасывает локальное состояние отслеживания заказа."""
        self._states.pop(order_id, None)