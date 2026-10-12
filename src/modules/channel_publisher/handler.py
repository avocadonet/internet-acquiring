import logging

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiohttp import ClientConnectorError, ClientPayloadError, ServerDisconnectedError

from src.shared.contracts.orders import IOrderInternalService
from src.shared.contracts.outbox import (
    FatalTaskError,
    IOutboxTaskHandler,
    RateLimitTaskError,
    RetryableTaskError,
    TaskContextDTO,
)
from src.shared.contracts.publishing import PublishPostPayloadDTO

from .anti_duplicate import AntiDuplicateGuard
from .client import PublisherService
from .exceptions import ContentNormalizationError, PublishingDeliveryError

logger = logging.getLogger(__name__)


class ChannelPublisherHandler(IOutboxTaskHandler):
    """
    Обработчик задачи OutboxTaskType.PUBLISH_POST.
    Управляет безопасным процессом выгрузки рекламного поста в канал.
    """

    def __init__(
        self,
        bot: Bot,
        order_service: IOrderInternalService,
        anti_duplicate: AntiDuplicateGuard | None = None,
        publisher_service: PublisherService | None = None,
    ) -> None:
        self.bot = bot
        self.order_service = order_service
        self.anti_duplicate = anti_duplicate or AntiDuplicateGuard()
        self.publisher_service = publisher_service or PublisherService(bot=bot)

    async def handle(self, context: TaskContextDTO) -> None:
        """
        Выполняет публикацию контента поста в целевой канал Telegram.
        """
        payload = PublishPostPayloadDTO.model_validate(context.payload)
        order_id = payload.order_id
        target_chat_id = payload.target_chat_id

        # 1. Проверка идемпотентности и защиты от дублей
        confirmed_message_id = self.anti_duplicate.is_already_published(order_id)
        if confirmed_message_id is not None:
            logger.warning(
                "Заказ %s уже успешно размещен (message_id=%s). Повторная отправка пропущена.",
                order_id,
                confirmed_message_id,
            )
            await self.order_service.handle_publish_succeeded(
                order_id=order_id,
                published_message_id=confirmed_message_id,
            )
            return

        if self.anti_duplicate.is_suspected_duplicate(order_id):
            logger.critical(
                "Заказ %s находится в статусе SUSPECTED_DUPLICATE после предыдущего ReadTimeout. "
                "Остановка повторных отправок для предотвращения спама в канал %s.",
                order_id,
                target_chat_id,
            )
            raise RetryableTaskError(
                f"Order {order_id} requires manual verification due to suspected duplicate delivery."
            )

        # 2. Оповещаем доменное ядро о старте процесса публикации
        await self.order_service.handle_publish_started(order_id)
        self.anti_duplicate.mark_in_flight(order_id)

        try:
            # 3. Непосредственная выгрузка контента в канал
            result = await self.publisher_service.publish(payload)

            # 4. Фиксация успешного размещения в трекере и домене
            self.anti_duplicate.mark_confirmed(
                order_id=order_id,
                message_id=result.published_message_id,
            )
            await self.order_service.handle_publish_succeeded(
                order_id=order_id,
                published_message_id=result.published_message_id,
            )
            logger.info(
                "Заказ %s успешно опубликован в канале %s (message_id=%s)",
                order_id,
                target_chat_id,
                result.published_message_id,
            )

        except TelegramRetryAfter as e:
            logger.warning(
                "Telegram FloodWait для заказа %s: retry_after=%s сек.",
                order_id,
                e.retry_after,
            )
            raise RateLimitTaskError(
                retry_after=e.retry_after,
                message=f"Telegram FloodWait: retry after {e.retry_after}s",
            ) from e

        except TelegramForbiddenError as e:
            logger.error(
                "Бот лишен прав или удален из канала %s (заказ %s): %s",
                target_chat_id,
                order_id,
                e,
            )
            self.anti_duplicate.mark_failed(order_id, str(e))
            raise FatalTaskError(f"TelegramForbiddenError: {e}") from e

        except TelegramBadRequest as e:
            err_msg = str(e).lower()
            self.anti_duplicate.mark_failed(order_id, str(e))

            if "chat not found" in err_msg or "have no rights" in err_msg:
                logger.error(
                    "Канал %s недоступен или бот не имеет прав администратора: %s",
                    target_chat_id,
                    e,
                )
                raise FatalTaskError(f"ChannelAccessError: {e}") from e

            if (
                "caption is too long" in err_msg
                or "message is too long" in err_msg
                or "wrong file identifier" in err_msg
            ):
                logger.error("Недопустимый контент для заказа %s: %s", order_id, e)
                raise FatalTaskError(f"InvalidContentError: {e}") from e

            # Прочие BadRequest также считаем фатальными ошибками валидации
            logger.error("TelegramBadRequest для заказа %s: %s", order_id, e)
            raise FatalTaskError(f"TelegramBadRequest: {e}") from e

        except (ContentNormalizationError, PublishingDeliveryError) as e:
            logger.error("Ошибка подготовки контента для заказа %s: %s", order_id, e)
            self.anti_duplicate.mark_failed(order_id, str(e))
            raise FatalTaskError(f"ContentError: {e}") from e

        except (ClientConnectorError, TelegramNetworkError) as e:
            logger.warning(
                "Транзиентная сетевая ошибка до завершения отправки заказа %s: %s",
                order_id,
                e,
            )
            raise RetryableTaskError(f"Network error: {e}") from e

        except (TimeoutError, ServerDisconnectedError, ClientPayloadError) as e:
            # Сетевой разрыв во время ожидания ответа: помечаем заказ как SUSPECTED_DUPLICATE
            self.anti_duplicate.mark_suspected_timeout(order_id, str(e))
            logger.critical(
                "Таймаут/обрыв сокета при чтении ответа Telegram API для заказа %s. "
                "Риск дублирования публикации! Ошибка: %s",
                order_id,
                e,
            )
            raise RetryableTaskError(
                f"ReadTimeout: possible unconfirmed delivery ({e})"
            ) from e

    async def on_fatal_failure(self, context: TaskContextDTO, error: str) -> None:
        """
        Вызывается движком Outbox при окончательном крахе задачи публикации.
        Переводит заказ в домене в статус REFUND_REQUIRED для инициации возврата средств.
        """
        payload = PublishPostPayloadDTO.model_validate(context.payload)
        order_id = payload.order_id

        self.anti_duplicate.mark_failed(order_id, error)
        logger.error(
            "Публикация заказа %s окончательно провалена. Запуск компенсации в домене. Причина: %s",
            order_id,
            error,
        )
        await self.order_service.handle_publish_failed(
            order_id=order_id,
            error_reason=error,
        )