# README: Сервисный слой модуля Order Domain (`services/`)

Данный документ представляет собой специализированное инженерное руководство по сервисному слою модуля `order_domain` (`src/modules/order_domain/services/`)[cite: 4]. В нем подробно описаны архитектура сервисов, сценарии выполнения (Flows), принципы внедрения зависимостей (Dependency Injection), обеспечение идемпотентности и транзакционная надежность (Transactional Outbox & Row-Level Locking)[cite: 4].

---

## 1. Назначение и паспорт сервисного слоя

Сервисный слой инкапсулирует сценарии бизнес-логики (Use Cases) обработки заказов рекламы[cite: 4]. Он изолирован от сетевых протоколов (Telegram Bot API, HTTP-эндпоинтов FastAPI) и обращается только к абстракциям ядра платформы и контрактам[cite: 1, 2, 4].

* **Расположение:** `src/modules/order_domain/services/`[cite: 4]
* **Реализуемые контракты:**
  * `IOrderService` (`src/shared/contracts/orders.py`)[cite: 4, 5]
  * `IOrderInternalService` (`src/shared/contracts/orders.py`)[cite: 4, 5]
* **Потребляемые контракты:**
  * `IPaymentClient` (`src/shared/contracts/payments.py`)[cite: 4, 7]
* **Ключевые зависимости ядра:**
  * `AsyncSession` / `async_sessionmaker` (`src/shared/database.py`)[cite: 2, 4]
  * Модели и репозиторий: `OrderModel`, `OrderRepository`, `OrderStateMachine`[cite: 4]

---

## 2. Структура файлов и матрица ответственности

```text
src/modules/order_domain/services/
├── __init__.py            # Публичный экспорт: OrderService, PricingService, OrderLifecycleService
├── pricing_service.py     # Расчет стоимости публикации и проверка тарифов по каналам
├── order_service.py       # Реализация IOrderService: оформление заказа и инициация оплаты
└── lifecycle_service.py   # Реализация IOrderInternalService: реакции на вебхуки, публикацию и возвраты

```

| Компонент | Назначение | Клиенты (Кто вызывает) |
| --- | --- | --- |
| `PricingService` | Валидация ID каналов и расчет суммы в копейках.

 | `OrderService` |
| `OrderService` | Регистрация заказа в `PENDING`, вызов эквайринга, выдача ссылки на оплату.

 | `bot_ingress` (через `IOrderService`)

 |
| `OrderLifecycleService` | Управление статусами под `FOR UPDATE`, генерация задач в `outbox_tasks`.

 | `payment_gateway`, `channel_publisher`, `compensation`<br> |

---

## 3. Детальная спецификация компонентов

### 3.1. `PricingService` (`pricing_service.py`)

Сервис тарификации, исключающий появление заказов с нулевой или отрицательной стоимостью.

* **Конструктор:** `PricingService(channel_rates: Mapping[int, int] | None = None)`
* `channel_rates`: словарь соответствия `chat_id -> стоимость в копейках`.
* Если тариф для канала не передан явно, применяется базовый тариф по умолчанию (`DEFAULT_BASE_PRICE_KOPECKS = 50_000` коп. / 500 руб.).




* **Метод `calculate_amount_kopecks(target_channel_id: int) -> int`:**
* Проверяет непустоту и валидность идентификатора канала.


* Возвращает итоговую сумму в копейках.


* Выбрасывает `OrderPricingError`, если ID канала некорректен или стоимость $\le 0$.





---

### 3.2. `OrderService` (`order_service.py`)

Реализует контракт `IOrderService` для создания заказа.

```
┌─────────────┐       create_order()       ┌──────────────┐
│ bot_ingress ├───────────────────────────►│ OrderService │
└─────────────┘                            └───┬──────┬───┘
                                               │      │
                        1. calculate_amount()  │      │ 2. init_payment()
                                               ▼      ▼
                                       ┌─────────┐  ┌─────────────────┐
                                       │ Pricing │  │ IPaymentClient  │
                                       │ Service │  │(payment_gateway)│
                                       └─────────┘  └────────┬────────┘
                                                             │
                                   3. OrderModel(PENDING)    │ payment_id,
                                      await repo.create()    │ payment_url
                                               ▼             ▼
                                       ┌──────────────────────┐
                                       │      PostgreSQL      │
                                       └──────────────────────┘

```

#### Сценарий выполнения `create_order(data: CreateOrderInputDTO) -> OrderCreatedResultDTO`

1. **Расчет стоимости:** Вызывает `_pricing_service.calculate_amount_kopecks(data.target_channel_id)`.


2. **Генерация ID:** Генерирует клиентский UUIDv4 заказа (`order_id = uuid.uuid4()`).


3. **Инициация оплаты:** Формирует `InitPaymentRequestDTO` и вызывает метод `await _payment_client.init_payment(...)`.


* При сетевой ошибке или отклонении банком оборачивает исключение в `PaymentInitializationError`.




4. **Персистентность в БД:**
* Создает экземпляр `OrderModel` со статусом `OrderStatus.PENDING`, сериализуя Pydantic-схемы `content` и `contact` в `dict` через `.model_dump(mode="json")`.


* Открывает транзакцию `async with session.begin()` и сохраняет запись через `OrderRepository.create()`.




5. **Результат:** Возвращает DTO `OrderCreatedResultDTO(order_id, payment_url, amount_kopecks)` в модуль `bot_ingress`.



---

### 3.3. `OrderLifecycleService` (`lifecycle_service.py`)

Реализует контракт `IOrderInternalService`. Управляет мутациями заказа при наступлении внешних событий, гарантируя строгую детерминированность машины состояний и атомарность паттерна Transactional Outbox.

#### Защита от опережающего вебхука (`_fetch_order_with_retry`)

* **Контекст проблемы:** Пользователь мгновенно оплачивает заказ через СБП, и вебхук `CONFIRMED` от банка доставляется до завершения транзакции метода `create_order` в БД.


* **Решение:** Метод выполняет до 3 попыток выборки заказа с интервалом 0.5 секунды. Если запись не появилась по истечении всех попыток, логируется `CRITICAL` и выбрасывается `OrderNotFoundError`.



#### Обработчики жизненного цикла:

1. **`handle_payment_succeeded(order_id: uuid.UUID, payment_id: str) -> None`**
* Вызывается модулем `payment_gateway` при получении валидного вебхука `CONFIRMED`.


* Блокирует строку заказа: `SELECT ... FOR UPDATE`.


* Валидирует переход в `PAID` через `OrderStateMachine.validate_transition()`. Если статус уже `PAID`, `PUBLISHING` или `PUBLISHED`, безопасно прерывает работу (идемпотентный no-op).


* Мутирует статус: `order.status = OrderStatus.PAID`, сохраняет `order.payment_id`.


* **Атомарная постановка Outbox:** В той же транзакции вызывает `repo.add_outbox_task` с типом `PUBLISH_POST`.


* Сайд-эффект: воркер публикации получает сигнал на отправку поста в канал.




2. **`handle_publish_started(order_id: uuid.UUID) -> None`**
* Вызывается воркером при взятии задачи в работу.


* Блокирует запись `FOR UPDATE` и переводит заказ в статус `PUBLISHING`.


* Сайд-эффектов Outbox не порождает.




3. **`handle_publish_succeeded(order_id: uuid.UUID, published_message_id: int) -> None`**
* Вызывается модулем `channel_publisher` после успешного вызова Telegram Bot API.


* Переводит заказ в терминальный статус `PUBLISHED` под блокировкой `FOR UPDATE`.


* Записывает идентификатор опубликованного сообщения `order.published_message_id`.




4. **`handle_publish_failed(order_id: uuid.UUID, error_reason: str) -> None`**
* Вызывается при фатальном сбое публикации (бот исключен из канала, ошибка 403 Forbidden, исчерпаны ретраи).


* Проверяет переход в `REFUND_REQUIRED` через `OrderStateMachine`.


* Мутирует статус: `order.status = OrderStatus.REFUND_REQUIRED`.


* Сохраняет детали сбоя в `order.refund_details` (`failed_at`, `reason`).


* **Атомарная постановка Outbox:** В той же транзакции создает задачу `EXECUTE_PAYMENT_REFUND` с данными платежа и суммой в копейках.


* Сайд-эффект: модуль `compensation` инициирует возврат денег через API Т-Банка.




5. **`handle_refund_succeeded(order_id: uuid.UUID, refund_info: dict[str, Any]) -> None`**
* Вызывается модулем `compensation` после успешного выполнения возврата в эквайринге.


* Переводит заказ в терминальный статус `REFUNDED` под блокировкой `FOR UPDATE`.


* Дополняет JSONB-поле `order.refund_details` меткой времени и ответом платежного провайдера.





---

## 4. Паттерн Transactional Outbox: спецификация задач

Сервисы `order_domain` являются **производителями (Producers)** задач Outbox. Задачи записываются в таблицу `outbox_tasks` строго внутри того же блока `session.begin()`, в котором меняется статус заказа.

```
                     ACID ТРАНЗАКЦИЯ (session.begin())
┌────────────────────────────────────────────────────────────────────────┐
│                                                                        │
│  1. UPDATE orders SET status = 'PAID' WHERE id = :id                   │
│                                                                        │
│  2. INSERT INTO outbox_tasks (task_type, payload, execute_after)       │
│     VALUES ('PUBLISH_POST', '{"order_id": ...}', NOW())                │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘

```

### Структура полезной нагрузки (Payload) задач:

#### 1. Задача `PUBLISH_POST` (порождается при успехе оплаты):

```json
{
  "order_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "target_chat_id": -1001987654321,
  "content": {
    "content_type": "photo",
    "text": null,
    "caption": "Текст рекламного объявления",
    "entities": [],
    "media_items": [
      {
        "file_id": "AgACAgIAAxkBAAE...",
        "file_unique_id": "AQAD...",
        "media_type": "photo"
      }
    ]
  }
}

```

#### 2. Задача `EXECUTE_PAYMENT_REFUND` (порождается при сбое публикации):

```json
{
  "order_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "payment_id": "3128947291",
  "amount_kopecks": 50000,
  "reason": "TelegramForbiddenError: bot was kicked from the channel"
}

```

---

## 5. Конкурентность и идемпотентность

1. **Пессимистическая блокировка (`with_for_update`):**
Каждый метод `OrderLifecycleService` запрашивает заказ с блокировкой строки. Если два события (например, параллельные вебхуки) приходят одновременно, второй запрос ждет снятия блокировки первым и затем обрабатывается как повторный.


2. **Идемпотентный No-Op:**
Если статус заказа в базе уже соответствует или опережает целевой статус (например, пришел дубль `CONFIRMED`, когда заказ уже `PUBLISHED`), `OrderStateMachine.validate_transition` возвращает `False`. Сервис не выбрасывает исключение и не генерирует дублирующих Outbox-задач, возвращая `None`.



---

## 6. Пример инициализации сервисов (Composition Root)

В точках монтирования приложения (`src/apps/bot_runner.py`, `api_runner.py`, `worker_runner.py`) сервисы собираются через Dependency Injection:

```python
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from src.modules.order_domain.services import (
    OrderService,
    OrderLifecycleService,
    PricingService,
)
# В реальном рантайме payment_client импортируется из модуля payment_gateway
# только в точках входа apps/* (внутри order_domain это запрещено)

engine = create_async_engine("postgresql+asyncpg://user:pass@localhost/db")
session_factory = async_sessionmaker(engine, expire_on_commit=False)

pricing_service = PricingService(channel_rates={-1001234567890: 75_000})

# Сервис для модуля бота (bot_ingress)
order_service = OrderService(
    session_factory=session_factory,
    payment_client=payment_client_instance,
    pricing_service=pricing_service,
)

# Сервис жизненного цикла для API вебхуков и воркеров
lifecycle_service = OrderLifecycleService(
    session_factory=session_factory,
)
```

---

## 7. Руководство для ИИ и разработчиков по отладке и тестированию

1. **Мокирование в тестах:**
* Для тестирования `OrderService` используйте мок контракта `IPaymentClient` (`AsyncMock(spec=IPaymentClient)`).


* Для изоляции базы данных используйте фикстуру сессии SQLite (in-memory) или PostgreSQL testcontainers.




2. **Проверка атомарности:**
* В интеграционных тестах проверяйте, что при принудительном rollback после смены статуса запись в `outbox_tasks` также откатывается.




3. **Строгая изоляция импортов:**
* Запрещено импортировать классы из `src/modules/payment_gateway/client.py` или `src/modules/bot_ingress/` напрямую в сервисы `order_domain`. Используйте только типы из `src/shared/contracts/`.
