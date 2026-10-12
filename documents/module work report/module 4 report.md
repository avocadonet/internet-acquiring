# Отчет о реализации модуля 4: Transactional Outbox Engine (`outbox_engine`)

**Проект:** reklama-bot-platform

**Модуль:** `src/modules/outbox_engine/`

**Статус:** Реализован в полном объеме, верифицирован, Definition of Done достигнут.

---

## 1. Сводная матрица соответствия требованиям ТЗ

Все инженерные требования спецификации модуля `outbox_engine` выполнены в строгом соответствии с архитектурным регламентом платформы.

| № | Требование ТЗ | Реализованный компонент | Статус | Подтверждение / Реализация |
| --- | --- | --- | --- | --- |
| **1.1** | Декларативная ORM-модель `OutboxTaskModel` (SQLAlchemy 2.0, соответствие миграции `0001`)

 | `src/modules/outbox_engine/models.py` | Выполнено | Полное соответствие DDL таблицы `outbox_tasks`: типы UUIDv4, `JSONB`, PostgreSQL ENUM `outbox_task_type_enum`, поля `execute_after`, `locked_until`, `retry_count`, `processed`, `failed_permanently`.

 |
| **1.2** | Атомарный конкурентный захват задач (Poller Engine, CTE + `FOR UPDATE SKIP LOCKED`)

 | `src/modules/outbox_engine/poller.py` | Выполнено | Двухфазная схема выборки пачки задач с распределенным лизингом (`locked_until`), не удерживающая транзакций на время исполнения.

 |
| **1.3** | Реестр и диспетчеризация задач (`TaskDispatcher`)

 | `src/modules/outbox_engine/dispatcher.py` | Выполнено | Строгая валидация `OutboxTaskType`, регистрация и получение обработчиков `IOutboxTaskHandler`.

 |
| **1.4** | Экспоненциальный backoff с полным случайным джиттером (Full Jitter)

 | `src/modules/outbox_engine/executor.py` (`calculate_backoff_delay`) | Выполнено | Задержка $\min(300, 5 \cdot 2^{\text{retry\_count}}) + \text{uniform}(0.5, 3.0)$ с инкрементом `retry_count`.

 |
| **1.5** | Специальная обработка Rate Limit / FloodWait (429)

 | `src/modules/outbox_engine/executor.py` (`_handle_rate_limit`) | Выполнено | Перенос `execute_after` строго на `retry_after` секунд без увеличения `retry_count` и со сбросом `locked_until = None`.

 |
| **1.6** | Обработка фатальных сбоев и компенсационный хук (`on_fatal_failure`)

 | `src/modules/outbox_engine/executor.py` (`_handle_fatal_failure`) | Выполнено | Маркировка `failed_permanently = True`, фиксация `last_error`, вызов `handler.on_fatal_failure` с перехватом локальных исключений хука.

 |
| **1.7** | Фоновый воркер-оркестратор (`OutboxWorker`)

 | `src/modules/outbox_engine/worker.py` | Выполнено | Контроль конкурентности через `asyncio.Semaphore`, цикл поллинга, трекинг корутин и Graceful Shutdown с тайм-аутом ожидания активных задач.

 |
| **2.1** | Архитектурная изоляция Package-by-Feature (0 импортов из `src/modules/*`)

 | Весь модуль `outbox_engine` | Выполнено | Взаимодействие со смежными модулями организовано строго через контракты `src/shared/contracts/outbox.py`.

 |
| **2.2** | Стек технологий: Python 3.12+, SQLAlchemy 2.0+, Pydantic 2.8+

 | Конфигурация и исходный код модуля | Выполнено | Использован `datetime.UTC`, `pydantic-settings` с валидацией границ, строгая типизация SQLAlchemy 2.0.

 |
| **3.1** | Модульное тестирование (Pytest)

 | `tests/unit/test_outbox_engine/` (4 тестовых файла) | Выполнено | 24 модульных теста, покрывающих все сценарии и граничные условия.

 |
| **3.2** | Автономный мок-обработчик (`MockOutboxHandler`)

 | `tests/mocks/mock_outbox_handler.py` | Выполнено | Реализация `IOutboxTaskHandler` для параллельной разработки и тестирования смежных модулей (`channel_publisher`, `compensation`).

 |
| **4.1** | Статический анализ качества кода

 | `ruff check`, `mypy --strict` | Выполнено | 0 замечаний Ruff, строгая типизация Mypy пройдена по 11 файлам без единой ошибки. |
| **4.2** | Тестовое покрытие (норматив ТЗ $\ge 85\%$)

 | `pytest-cov` | Выполнено | Суммарное покрытие модуля кодом составило **99%**. |

---

## 2. Физическая структура модуля в репозитории

Модуль скомпонован по утвержденной модульной структуре монолита:

```text
src/
└── modules/
    └── outbox_engine/
        ├── __init__.py               # Публичный фасад модуля (экспорт моделей, воркера, диспетчера)
        ├── config.py                 # Pydantic Settings (валидация batch_size, lease, poll_interval)
        ├── dispatcher.py             # Реестр TaskDispatcher (регистрация и маршрутизация хэндлеров)
        ├── executor.py               # Сервис TaskExecutor (транзакции статусов, backoff, FloodWait 429)
        ├── models.py                 # SQLAlchemy 2.0 модель OutboxTaskModel
        ├── poller.py                 # Сервис атомарного захвата задач (CTE + FOR UPDATE SKIP LOCKED)
        └── worker.py                 # Оркестратор OutboxWorker (asyncio loop, Semaphore, Graceful Shutdown)

tests/
├── mocks/
│   └── mock_outbox_handler.py        # Автономный мок IOutboxTaskHandler с историей вызовов
└── unit/
    └── test_outbox_engine/
        ├── test_dispatcher.py        # Тесты диспетчера и валидации контрактов
        ├── test_executor.py          # Тесты логики backoff, сброса лизинга, 429 и Fatal сбоев
        ├── test_poller.py            # Тесты генерации CTE SQL-запроса и маппинга DTO
        └── test_worker.py            # Тесты оркестратора, семафора и Graceful Shutdown

```

---

## 3. Ключевые архитектурные и технические решения

### 3.1. Двухфазная модель захвата и распределенный лизинг (Lease Locking)

Для предотвращения блокировки пула соединений PostgreSQL транзакция не удерживается во время выполнения полезной нагрузки задачи:

1. **Короткая транзакция захвата (Acquire):** атомарный CTE-запрос с `FOR UPDATE SKIP LOCKED` накладывает лизинг `locked_until = NOW() + lease_seconds` на пачку созревших задач (`execute_after <= NOW()`) и фиксируется немедленно.


2. **Асинхронная обработка:** задача выполняется в пуле воркера под контролем семафора без активных транзакций БД.


3. **Короткая транзакция фиксации:** результат (успех, ретрай или фатальный сбой) фиксируется отдельным запросом со сбросом `locked_until = None`.


4. **Отказоустойчивость при аварии воркера (`kill -9`):** если процесс завершился аварийно, задача освобождается автоматически по истечении `locked_until < NOW()` и подхватывается другим инстансом без ручного вмешательства.



### 3.2. Детерминированная политика повторов и защита от FloodWait (429)

* **RateLimitTaskError (Telegram 429):** счетчик `retry_count` **не увеличивается**. Время следующего запуска `execute_after` сдвигается строго на интервал `retry_after`, а блокировка `locked_until` обнуляется. Это исключает ложную браковку оплаченных заказов при временных ограничениях API Telegram.


* **RetryableTaskError / Сетевые сбои:** применяется экспоненциальная задержка с добавлением случайного джиттера ($0.5$–$3.0$ с) для предотвращения эффекта "thundering herd", а `retry_count` инкрементируется на 1.


* **FatalTaskError / Исчерпание `max_retries`:** задача помечается терминальным флагом `failed_permanently = True`, после чего вызывается корутина компенсации `handler.on_fatal_failure` для автоматического запуска отмены платежа через модуль компенсаций.



### 3.3. Оркестрация и Graceful Shutdown

* Конкурентность регулируется через `asyncio.Semaphore(max_concurrent_tasks)`. Слот семафора освобождается в блоке `finally` корутины-обертки независимо от исхода выполнения задачи.


* При сигнале завершения работы флаг `_running` сбрасывается в `False`, и активируется механизм `_drain_active_tasks`, ожидающий завершения всех активных корутин до истечения таймаута (30 с) перед их отменой.



---

## 4. Результаты тестирования и статического анализа

### 4.1. Результаты модульного тестирования (Pytest)

Все 24 теста завершились успешно:

```text
tests/unit/test_outbox_engine/test_dispatcher.py ..... [ 20%]
tests/unit/test_outbox_engine/test_executor.py .......   [ 50%]
tests/unit/test_outbox_engine/test_poller.py ....       [ 66%]
tests/unit/test_outbox_engine/test_worker.py ........   [100%]
============================== 24 passed in 1.42s ==============================

```

### 4.2. Метрики покрытия кода (Coverage Report)

| Модуль | Число строк (Stmts) | Пропущено (Miss) | Покрытие (Cover) |
| --- | --- | --- | --- |
| `src/modules/outbox_engine/config.py` | 9 | 0 | **100%** |
| `src/modules/outbox_engine/dispatcher.py` | 18 | 0 | **100%** |
| `src/modules/outbox_engine/executor.py` | 59 | 0 | **100%** |
| `src/modules/outbox_engine/models.py` | 22 | 0 | **100%** |
| `src/modules/outbox_engine/poller.py` | 40 | 0 | **100%** |
| `src/modules/outbox_engine/worker.py` | 71 | 1 | **99%** |
| **Итого по модулю `outbox_engine**` | **219** | **1** | **99%** |

### 4.3. Строгая типизация (Mypy)

Проверка выполнена в максимально строгом режиме:

```powershell
mypy --strict src/modules/outbox_engine tests/unit/test_outbox_engine tests/mocks/mock_outbox_handler.py

```

**Результат:** `Success: no issues found in 11 source files`.

### 4.4. Статический анализ и линтинг (Ruff)

Кодовая база модуля и тестов полностью верифицирована:

```powershell
ruff check src/modules/outbox_engine tests/unit/test_outbox_engine tests/mocks/mock_outbox_handler.py

```

**Результат:** `All checks passed!`.

---

## 5. Готовность к интеграции со смежными модулями

Модуль 4 `outbox_engine` готов к промышленной эксплуатации и сквозной сборке в рантайме:

1. Для точки входа `src/apps/worker_runner.py`:
Класс `OutboxWorker` готов к инициализации с пулом сессий PostgreSQL и запуску через `await worker.run()`.


2. Для разработчика модуля `channel_publisher` (Блок 5):
Обработчик публикации рекламных постов регистрируется через:


```python
dispatcher.register_handler(OutboxTaskType.PUBLISH_POST, publisher_handler)

```


При получении ошибки `TelegramRetryAfter` обработчик выбрасывает `RateLimitTaskError(retry_after=...)`, гарантируя сохранение счетчика попыток.


3. Для разработчика модуля `compensation` (Блок 6):
Обработчик возвратов регистрируется через:


```python
dispatcher.register_handler(OutboxTaskType.EXECUTE_PAYMENT_REFUND, refund_handler)

```


При фатальных ошибках (`FatalTaskError` или исчерпание лимита попыток) воркер автоматически вызывает хук `on_fatal_failure`, инициируя процесс отмены транзакции в банке.


4. **Тестовая инфраструктура:**
Готовый `MockOutboxHandler` в `tests/mocks/mock_outbox_handler.py` доступен разработчикам смежных модулей для эмуляции поведения воркера Outbox в сквозных тестах.