from typing import Protocol
import uuid
from pydantic import BaseModel, Field
from src.shared.contracts.orders import CustomerContactDTO


class InitPaymentRequestDTO(BaseModel):
    order_id: uuid.UUID
    amount_kopecks: int = Field(gt=0, description="Сумма в копейках")
    description: str = Field(max_length=250)
    contact: CustomerContactDTO


class InitPaymentResponseDTO(BaseModel):
    payment_id: str
    payment_url: str


class CancelPaymentRequestDTO(BaseModel):
    payment_id: str
    amount_kopecks: int | None = Field(
        default=None, description="None для полной отмены всей суммы заказа"
    )


class CancelPaymentResponseDTO(BaseModel):
    success: bool
    payment_id: str
    status: str
    original_amount_kopecks: int
    new_amount_kopecks: int


class IPaymentClient(Protocol):
    async def init_payment(self, data: InitPaymentRequestDTO) -> InitPaymentResponseDTO:
        """Регистрирует платеж в Т-Банке и возвращает ссылку."""
        ...

    async def cancel_payment(
        self, data: CancelPaymentRequestDTO
    ) -> CancelPaymentResponseDTO:
        """Отменяет транзакцию / выполняет возврат через POST /v2/Cancel."""
        ...