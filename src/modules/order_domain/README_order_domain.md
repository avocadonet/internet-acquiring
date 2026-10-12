
# README: Модуль Order Domain & State Machine (`order_domain`)

Данный документ представляет собой полную техническую и архитектурную спецификацию модуля `order_domain`. Модуль спроектирован по паттерну **Package-by-Feature (модульный монолит)** с жесткой изоляцией и является центральным ядром управления заказами и машиной состояний платформы `reklama-bot-platform`.

---

## 1. Паспорт модуля и границы ответственности

* **Идентификатор модуля:** `order_domain`.
* **Расположение в репозитории:** `src/modules/order_domain/`.
* **Стек технологий:** Python 3.12+, SQLAlchemy 2.0+ (`AsyncSession`, `mapped_column`, `declarative_base`), `asyncpg`, Pydantic 2.8+.
* **Интерфейсные контракты:** `src/shared/contracts/orders.py`, `src/shared/contracts/payments.py`, `src/shared/contracts/outbox.py`.

### Входит в зону ответственности (In-Scope)
* **Персистентность заказов:** Декларативная ORM-модель `OrderModel` и сохранение заказов в PostgreSQL.
* **Детерминированная машина состояний (State Machine):** Валидация жизненного цикла заказа, запрет невалидных мутаций и идемпотентная обработка повторных событий.
* **Публичный контракт создания заказа (`IOrderService`):** Расчет стоимости, генерация ID, вызов шлюза эквайринга `IPaymentClient.init_payment()` и фиксация заказа в статусе `PENDING`.
* **Управление жизненным циклом (`IOrderInternalService`):** Обработка событий успешной оплаты (`handle_payment_succeeded`), старта публикации (`handle_publish_started`), успешного размещения (`handle_publish_succeeded`), сбоя публикации (`handle_publish_failed`) и возврата средств (`handle_refund_succeeded`).
* **Transactional Outbox:** Атомарная вставка задач (`PUBLISH_POST`, `EXECUTE_PAYMENT_REFUND`) в таблицу `outbox_tasks` в рамках одной ACID-транзакции со сменой статуса заказа.
* **Защита от состояний гонки (Race Conditions):** Пессимистическая блокировка строк `SELECT ... FOR UPDATE` и механизм повторного поиска заказа при опережающих вебхуках.

### НЕ входит в зону ответственности (Out-of-Scope)
* Сбор данных через Telegram UI, FSM диалогов и Redis-дебаунс альбомов (зона ответственности `bot_ingress`).
* Низкоуровневые HTTP-запросы к API Т-Банка, подсчет токенов SHA-256 и чеки 54-ФЗ (зона ответственности `payment_gateway`).
* Фоновый поллинг `SELECT ... FOR UPDATE SKIP LOCKED` и диспетчеризация очередей (зона ответственности `outbox_engine`).
* Непосредственная отправка постов в Telegram-каналы (зона ответственности `channel_publisher`).
* Вызов API отмены транзакций `/v2/Cancel` и отправка системных алертов (зона ответственности `compensation`).

---

## 2. Архитектурная изоляция и правила импортов

В соответствии с правилами Package-by-Feature в кодовой базе действуют строгие ограничения на зависимости:

```text
ЗАПРЕЩЕНО:
  src/modules/order_domain/ ──X──> src/modules/bot_ingress/
  src/modules/order_domain/ ──X──> src/modules/payment_gateway/
  src/modules/order_domain/ ──X──> src/modules/outbox_engine/
  src/modules/order_domain/ ──X──> src/modules/channel_publisher/
  src/modules/order_domain/ ──X──> src/modules/compensation/

РАЗРЕШЕНО:
  src/modules/order_domain/ ─────> Стандартная библиотека Python
  src/modules/order_domain/ ─────> Сторонние библиотеки (SQLAlchemy, Pydantic)
  src/modules/order_domain/ ─────> src/shared/contracts/ (orders, payments, outbox)
  src/modules/order_domain/ ─────> src/shared/ (database, logging, config)

```

* Любой импорт из параллельных функциональных директорий `src/modules/*` строго запрещен.


* Взаимодействие со смежными компонентами строится исключительно через `Protocol` и DTO из `src/shared/contracts/`.



---

## 3. Физическая структура файлов модуля

```text
src/modules/order_domain/
├── __init__.py                # Корневой фасад модуля: экспорт моделей, репозитория, сервисов и ошибок
├── exceptions.py              # Доменные исключения (InvalidStateTransitionError, OrderNotFoundError и др.)
├── state_machine.py           # Чистая логика машины состояний: матрицы переходов и правила идемпотентности
├── models.py                  # Декларативная ORM-модель SQLAlchemy 2.0 (OrderModel, Base)
├── repository.py              # Слой доступа к данным (OrderRepository, SELECT FOR UPDATE, Outbox Tasks)
└── services/
    ├── __init__.py            # Экспорт сервисного слоя
    ├── pricing_service.py     # Расчет стоимости размещения по целевым каналам
    ├── order_service.py       # Реализация публичного контракта IOrderService (create_order)
    └── lifecycle_service.py   # Реализация IOrderInternalService (handle_payment_succeeded и др.)

```

---

## 4. Схема данных (PostgreSQL DDL)

### 4.1. Таблица `orders`

```sql
CREATE TYPE order_status_enum AS ENUM (
    'PENDING',          -- Ожидает оплаты пользователем
    'PAID',             -- Оплата подтверждена эквайрингом
    'PUBLISHING',       -- Взято в работу воркером публикации
    'PUBLISHED',        -- Успешно размещено в канале (терминальный статус)
    'REFUND_REQUIRED',  -- Публикация провалена, требуется компенсация
    'REFUNDED',         -- Возврат средств завершен (терминальный статус)
    'CANCELLED'         -- Отменен пользователем или таймаут (терминальный статус)
);

CREATE TABLE orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id BIGINT NOT NULL,
    target_chat_id BIGINT NOT NULL,
    amount_kopecks BIGINT NOT NULL,
    status order_status_enum NOT NULL DEFAULT 'PENDING',
    content_payload JSONB NOT NULL,
    contact_info JSONB NOT NULL,
    payment_id VARCHAR(64) UNIQUE,
    payment_url TEXT,
    published_message_id BIGINT,
    refund_details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_orders_user_id ON orders (user_id);
CREATE INDEX idx_orders_status ON orders (status);
CREATE INDEX idx_orders_payment_id ON orders (payment_id) WHERE payment_id IS NOT NULL;

```

### 4.2. Таблица `outbox_tasks`

```sql
CREATE TYPE outbox_task_type_enum AS ENUM (
    'PUBLISH_POST',
    'EXECUTE_PAYMENT_REFUND'
);

CREATE TABLE outbox_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_type outbox_task_type_enum NOT NULL,
    payload JSONB NOT NULL,
    execute_after TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    locked_until TIMESTAMPTZ,
    retry_count INT NOT NULL DEFAULT 0,
    processed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_outbox_tasks_poll ON outbox_tasks (execute_after) 
WHERE processed = FALSE AND locked_until IS NULL;

```

---

## 5. Машина состояний (Order State Machine)

### 5.1. Граф жизненного цикла

```text
                  ┌───────────────┐
                  │    PENDING    │
                  └───────┬───────┘
                          │
             ┌────────────┴────────────┐
             │ (успех оплаты)          │ (таймаут / отмена)
             ▼                         ▼
      ┌─────────────┐           ┌─────────────┐
      │    PAID     │           │  CANCELLED  │ (терминал)
      └──────┬──────┘           └─────────────┘
             │ (воркер берет в работу)
             ▼
      ┌─────────────┐
      │ PUBLISHING  │
      └──────┬──────┘
             │
     ┌───────┴────────────────────────┐
     │ (успешная отправка в канал)    │ (сбой отправки: исчерпаны ретраи / 403)
     ▼                                ▼
┌───────────┐                ┌─────────────────┐
│ PUBLISHED │ (терминал)     │ REFUND_REQUIRED │
└───────────┘                └────────┬────────┘
                                      │ (успех /v2/Cancel в Т-Банке)
                                      ▼
                             ┌─────────────────┐
                             │    REFUNDED     │ (терминал)
                             └─────────────────┘

```

### 5.2. Матрица переходов и транзакционные сайд-эффекты

| Текущий статус | Целевой статус | Инициирующий метод | Сайд-эффект в БД (Transactional Outbox) |
| --- | --- | --- | --- |
| `PENDING` | `PAID` | `handle_payment_succeeded`<br> | Создание задачи `PUBLISH_POST` в `outbox_tasks`<br> |
| `PENDING` | `CANCELLED` | Таймаут оплаты / отмена

 | Сайд-эффектов нет

 |
| `PAID` | `PUBLISHING` | `handle_publish_started`<br> | Сайд-эффектов нет

 |
| `PUBLISHING` | `PUBLISHED` | `handle_publish_succeeded`<br> | Запись `published_message_id`<br> |
| `PUBLISHING` | `REFUND_REQUIRED` | `handle_publish_failed`<br> | Создание задачи `EXECUTE_PAYMENT_REFUND` в `outbox_tasks`<br> |
| `REFUND_REQUIRED` | `REFUNDED` | `handle_refund_succeeded`<br> | Запись метаданных компенсации в `refund_details`<br> |

### 5.3. Правила идемпотентности

Если внешняя система или воркер повторно вызывает обработчик перехода (например, дубль вебхука `CONFIRMED` или сетевой таймаут):

1. `OrderStateMachine.validate_transition` определяет статус как идемпотентно пройденный и возвращает `False`.


2. Метод сервиса немедленно прерывает выполнение без ошибки.


3. Повторная задача в таблицу `outbox_tasks` **не генерируется**.



---

## 6. Межмодульные контракты (Shared Contracts)

### 6.1. Предоставляемые интерфейсы

* **`IOrderService`** (`src/shared/contracts/orders.py`):
* Метод: `async def create_order(self, data: CreateOrderInputDTO) -> OrderCreatedResultDTO`.


* Вызывается модулем `bot_ingress` при оформлении заказа.




* **`IOrderInternalService`** (`src/shared/contracts/orders.py`):
* `async def handle_payment_succeeded(self, order_id: uuid.UUID, payment_id: str) -> None`.


* `async def handle_publish_started(self, order_id: uuid.UUID) -> None`.


* `async def handle_publish_succeeded(self, order_id: uuid.UUID, published_message_id: int) -> None`.


* `async def handle_publish_failed(self, order_id: uuid.UUID, error_reason: str) -> None`.


* `async def handle_refund_succeeded(self, order_id: uuid.UUID, refund_info: dict[str, Any]) -> None`.


* Вызывается модулями `payment_gateway`, `channel_publisher` и `compensation`.





### 6.2. Потребляемые интерфейсы

* **`IPaymentClient`** (`src/shared/contracts/payments.py`):
* Метод: `async def init_payment(self, data: InitPaymentRequestDTO) -> InitPaymentResponseDTO`.


* Инжектируется в `OrderService` для регистрации счета в банке.





---

## 7. Граничные сценарии и транзакционная надежность

* **Атомарность Outbox:** Смена статуса заказа и вставка задачи в `outbox_tasks` происходят внутри одного блока `async with session.begin()`. Это исключает рассинхронизацию при падении контейнера.


* **Пессимистическая блокировка:** Все операции жизненного цикла выполняют чтение заказа через `SELECT ... FOR UPDATE` в `OrderRepository.get_by_id`, исключая race conditions.


* **Опережающий вебхук (Fast Webhook Race):** При мгновенной оплате вебхук `CONFIRMED` может прийти до коммита `create_order`. Метод `_fetch_order_with_retry` выполняет 3 повторные попытки с задержкой 500 мс.



---

## 8. Исключения доменного слоя (`exceptions.py`)

* `OrderNotFoundError`: Заказ не найден по переданному `order_id`.


* `InvalidStateTransitionError`: Запрещенный правилами переход состояния (например, `PENDING` -> `PUBLISHED`).


* `OrderPricingError`: Ошибка расчета стоимости (некорректный ID канала или невалидная цена).
* `PaymentInitializationError`: Сбой на стороне внешнего платежного шлюза при создании заказа.



---

## 9. Руководство для ИИ-агентов (AI Maintenance Guide)

При анализе или доработке данного модуля строго соблюдайте следующие правила:

1. **Точки поиска:** Доменные модели находятся в `models.py`, SQL-запросы — в `repository.py`, правила состояний — в `state_machine.py`, сервисы — в `services/`.


2. **Изоляция:** Никогда не добавляйте прямые импорты из `src/modules/{bot_ingress, payment_gateway, outbox_engine, channel_publisher, compensation}`.


3. **Блокировки:** Любая выборка перед мутацией статуса должна использовать `for_update=True`.


4. **Атомарность:** Запрещено сохранять статус и создавать запись в `outbox_tasks` в разных транзакциях.



