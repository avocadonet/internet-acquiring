from collections.abc import Mapping

from src.modules.order_domain.exceptions import OrderPricingError


class PricingService:
    DEFAULT_BASE_PRICE_KOPECKS: int = 50_000

    def __init__(self, channel_rates: Mapping[int, int] | None = None) -> None:
        self._channel_rates: dict[int, int] = dict(channel_rates) if channel_rates else {}

    def calculate_amount_kopecks(self, target_channel_id: int) -> int:
        if not target_channel_id:
            raise OrderPricingError(
                channel_id=target_channel_id,
                reason="Идентификатор целевого канала не может быть пустым или нулевым.",
            )

        amount = self._channel_rates.get(
            target_channel_id, self.DEFAULT_BASE_PRICE_KOPECKS
        )

        if amount <= 0:
            raise OrderPricingError(
                channel_id=target_channel_id,
                reason=f"Установлена некорректная стоимость размещения ({amount} коп.).",
            )

        return amount