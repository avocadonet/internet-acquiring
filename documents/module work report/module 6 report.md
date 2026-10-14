# Отчет о реализации модуля 6: Compensation & Incident Management (`compensation`)

**Проект:** reklama-bot-platform

**Модуль:** `src/modules/compensation/`

**Статус:** Реализован в полном объеме, верифицирован, Definition of Done достигнут

---

## 1. Сводная матрица соответствия требованиям ТЗ

Все требования инженерной спецификации модуля `compensation` выполнены в строгом соответствии с архитектурным регламентом платформы.

| № | Требование ТЗ | Реализованный компонент | Статус | Подтверждение / Реализация |
| --- | --- | --- | --- | --- |
| **1.1** | Реализация контракта `IOutboxTaskHandler` для задачи `EXECUTE_PAYMENT_REFUND`<br> | `src/modules/compensation/refund_handler.py`<br> | Выполнено | Класс `RefundTaskHandler` реализует методы `handle()` и `on_fatal_failure()`, выполняя строгую валидацию `ExecuteRefundPayloadDTO`.

 |
| **1.2** | Вызов метода отмены/возврата эквайринга `IPaymentClient.cancel_payment()`<br> | `src/modules/compensation/refund_handler.py`<br> | Выполнено | Вызов метода `/v2/Cancel` Т-Банка с передачей `payment_id` и `amount_kopecks` без генерации SHA-256 (делегировано `payment_gateway`).

 |
| **1.3** | Фиксация результата возврата в доменном слое через `IOrderInternalService`<br> | `src/modules/compensation/refund_handler.py`<br> | Выполнено | Вызов `order_service.handle_refund_succeeded(order_id, refund_info)` с обновлением статуса заказа до терминального `REFUNDED`.

 |
| **1.4** | Клиентское информирование с мягким подавлением блокировки бота

 | `src/modules/compensation/customer_notifier.py`<br> | Выполнено | Перехват `TelegramForbiddenError` и `TelegramBadRequest` в `CustomerNotifierService` без прерывания основной транзакции возврата.

 |
| **1.5** | Контур алертинга инцидентов (`TelegramIncidentAlerter`)

 | `src/modules/compensation/alerter.py`<br> | Выполнено | Формирование структурированных HTML-алертов с экранированием `html.escape()`: информационные (`INFO`) и аварийные (`CRITICAL`).

 |
| **1.6** | Реализация компенсационного хука `on_fatal_failure()`<br> | `src/modules/compensation/refund_handler.py`<br> | Выполнено | Формирование и отправка экстренного `CRITICAL` алерта дежурным администраторам с указанием `order_id`, `task_id`, `payment_id` и требования ручного вмешательства в ЛК Т-Бизнес.

 |
| **1.7** | Мониторинг перманентно сбойных задач (`DLQService`)

 | `src/modules/compensation/dlq_service.py`<br> | Выполнено | Сервис аудита задач со статусом `failed_permanently = TRUE` и рассылки групповых/индивидуальных тревожных сводок.

 |
| **2.1** | Архитектурная изоляция Package-by-Feature (0 импортов из `src/modules/*`)

 | Весь модуль `compensation`<br> | Выполнено | Взаимодействие со смежными компонентами платформы организовано исключительно через разделяемые контракты `src/shared/contracts/`.

 |
| **2.2** | Стек технологий: Python 3.12+, aiogram 3.13+, Pydantic 2.8+

 | Конфигурация и код модуля

 | Выполнено | Конфигурация через `pydantic-settings` с флагом `populate_by_name=True`, интеграция с `aiogram.Bot`.

 |
| **3.1** | Модульное тестирование (Pytest)

 | `tests/unit/test_compensation/`<br> | Выполнено | 16 модульных тестов с полной изоляцией внешних зависимостей через `MockPaymentClient`, `MockOrderService` и `AsyncMock(spec=Bot)`.

 |
| **4.1** | Статический анализ качества кода

 | `ruff check`, `ruff format`, `mypy --strict`<br> | Выполнено | 0 замечаний линтера Ruff, 11 файлов отформатированы по стандарту, строгая типизация Mypy пройдена без единой ошибки.

 |
| **4.2** | Тестовое покрытие кода (норматив ТЗ $\ge 85\%$)

 | `pytest-cov`<br> | Выполнено | Итоговое покрытие кодовой базы модуля составило **97%**.

 |

---

## 2. Физическая структура файлов модуля в репозитории

Модуль скомпонован по правилам модульного монолита без циклических и перекрестных зависимостей:

```text
reklama-bot-platform/
│
├── src/
│   └── modules/
│       └── compensation/
│           ├── __init__.py               # Публичный фасад модуля (экспорт хэндлера, алертера, DLQ)
│           ├── alerter.py                # Сервис отправки HTML-алертов администраторам (TelegramIncidentAlerter)
│           ├── config.py                 # Pydantic Settings (ADMIN_ALERT_CHAT_ID, BOT_TOKEN_ALERTS)
│           ├── customer_notifier.py      # Сервис информирования покупателя об отмене заказа
│           ├── dlq_service.py            # Мониторинг и аудит перманентно сбойных задач (DLQService)
│           ├── exceptions.py             # Доменная иерархия исключений компенсаций
│           └── refund_handler.py         # Реализация IOutboxTaskHandler (RefundTaskHandler)
│
└── tests/
    └── unit/
        └── test_compensation/
            ├── test_alerter.py           # Тесты формирования и безопасной доставки HTML-алертов (4 теста)
            ├── test_customer_notifier.py # Тесты отправки сообщений клиенту и подавления блокировки (4 теста)
            ├── test_dlq_service.py       # Тесты инспекции очереди DLQ и генерации сводок (2 теста)
            └── test_refund_handler.py    # Тесты сценариев возврата, ретраев и отказов банка (6 тестов)

```

---

## 3. Ключевые архитектурные и инженерные решения

### 3.1. Детерминированная классификация отказов эквайринга Т-Банка

Протокол `/v2/Cancel` интернет-эквайринга Т-Банка полностью идемпотентен: повторные вызовы по уже отмененной или возвращенной транзакции возвращают успешный статус. В `RefundTaskHandler` реализована строгая классификация исключений:

* **Транзиентные сетевые ошибки:** таймауты (`TimeoutError`, `httpx.TimeoutException`, обрывы TCP-соединений) транслируются в `RetryableTaskError`. Фоновый воркер `outbox_engine` выполняет повторную попытку возврата по экспоненциальному таймлайну с рандомизированным джиттером.


* **Бизнес-отказы банка:** ответы со статусом `success == False` (недостаточно средств на счете мерчанта, блокировка терминала, несовпадение статуса) выбрасывают `FatalTaskError`. Задача немедленно снимается с цикла автоматических повторов.


* **Повреждение полезной нагрузки:** ошибки валидации `ValidationError` при парсинге `ExecuteRefundPayloadDTO` также классифицируются как `FatalTaskError`, предотвращая зацикливание заведомо некорректных задач.



### 3.2. Компенсационный хук `on_fatal_failure` и протокол эскалации

При исчерпании лимита повторных попыток (`retry_count >= max_retries`) или при жестком отказе банка Outbox Engine вызывает метод `RefundTaskHandler.on_fatal_failure`:

1. Извлекается контекст неудавшейся транзакции (`order_id`, `payment_id`, `amount_kopecks`, причина отмены публикации).


2. Формируется тревожное сообщение уровня `CRITICAL` с явным предписанием: **«Требуется ручное вмешательство в ЛК Т-Бизнес!»**.


3. Это исключает потерю зависших клиентских средств и гарантирует оперативное информирование оператора поддержки.



### 3.3. Приоритет финансового возврата над нотификацией

В сервисе `CustomerNotifierService` реализована защита от срыва бизнес-транзакции:

* Блокировка бота клиентом (`TelegramForbiddenError`) или отсутствие диалога (`TelegramBadRequest`) мягко перехватываются с логированием факта недоставки.


* Ошибки доставки пользовательских сообщений **не вызывают исключений наружу** и не откатывают статус заказа в базе данных, так как фактический финансовый возврат средств на карту имеет наивысший приоритет.



### 3.4. Защита от инъекций разметки и надежность канала алертинга

* Все пользовательские и внешние строковые поля (`reason`, `publish_failure_reason`, `error_message`) проходят обязательную экранизацию через `html.escape()`, предотвращая сбои парсера Telegram HTML при наличии спецсимволов (`<`, `>`, `&`).


* Метод `_safe_send` оборачивает отправку алерта в защитный блок с подавлением ошибок, гарантируя, что недоступность мониторингового чата не сломает основной сценарий возврата.



---

## 4. Результаты тестирования и статического анализа

### 4.1. Модульное тестирование (Pytest)

Все 16 модульных тестов завершились со статусом `PASSED`:

```text
tests/unit/test_compensation/test_alerter.py ....            [ 25%]
tests/unit/test_compensation/test_customer_notifier.py ....  [ 50%]
tests/unit/test_compensation/test_dlq_service.py ..         [ 62%]
tests/unit/test_compensation/test_refund_handler.py ......   [100%]

============================== 16 passed in 3.29s ==============================

```

#### Детализация тестовых сценариев:

| Тестовый модуль | Число тестов | Проверяемая функциональность | Результат |
| --- | --- | --- | --- |
| `test_alerter.py`<br> | 4 | Форматирование INFO и CRITICAL алертов, экранирование спецсимволов HTML, доставка `IncidentAlertDTO`, подавление сетевых ошибок в `_safe_send`.

 | `PASSED` |
| `test_customer_notifier.py`<br> | 4 | Корректная отправка сообщений покупателю, подавление блокировки бота (`TelegramForbiddenError`), подавление `TelegramBadRequest` и непредвиденных исключений.

 | `PASSED` |
| `test_dlq_service.py`<br> | 2 | Пропуск пустой очереди, аудит перманентно сбойных задач, устойчивость к поврежденным UUID и рассылка критических алертов.

 | `PASSED` |
| `test_refund_handler.py`<br> | 6 | Happy Path (отмена $\to$ фиксация в домене $\to$ клиент $\to$ алерт), обработка таймаута сети (`RetryableTaskError`), бизнес-отказ банка (`FatalTaskError`), битый payload, компенсационный хук `on_fatal_failure`.

 | `PASSED` |

### 4.2. Метрики покрытия кода (Coverage Report)

Норматив тестового покрытия ТЗ ($\ge 85\%$) перевыполнен:

| Модуль | Stmts | Miss | Cover | Missing |
| --- | --- | --- | --- | --- |
| `src/modules/compensation/__init__.py`<br> | 6 | 0 | **100%** | — |
| `src/modules/compensation/alerter.py`<br> | 38 | 0 | **100%** | — |
| `src/modules/compensation/config.py`<br> | 6 | 0 | **100%** | — |
| `src/modules/compensation/customer_notifier.py`<br> | 28 | 0 | **100%** | — |
| `src/modules/compensation/dlq_service.py`<br> | 36 | 0 | **100%** | — |
| `src/modules/compensation/exceptions.py`<br> | 4 | 0 | **100%** | — |
| `src/modules/compensation/refund_handler.py`<br> | 65 | 5 | **92%** | 122, 155, 159-162 |
| **Итого по модулю `compensation**`<br> | **183** | **5** | **97%** |  |

### 4.3. Строгая типизация (Mypy)

Проверка выполнена в максимально строгом режиме `--strict`:

```powershell
mypy --strict src/modules/compensation tests/unit/test_compensation

```

**Результат:** `Success: no issues found in 11 source files`.

Сквозная проверка всех модулей платформы (`compensation`, `channel_publisher`, `outbox_engine`, `payment_gateway`, `order_domain`):

```powershell
mypy --strict src/modules/compensation src/modules/channel_publisher src/modules/outbox_engine src/modules/payment_gateway src/modules/order_domain

```

**Результат:** `Success: no issues found in 35 source files`.

### 4.4. Статический анализ и форматирование (Ruff)

```powershell
ruff check src/modules/compensation tests/unit/test_compensation --fix
All checks passed!

ruff format src/modules/compensation tests/unit/test_compensation
11 files left unchanged

```

---

## 5. Готовность к интеграции со смежными модулями

Модуль 6 `compensation` полностью протестирован, изолирован и готов к эксплуатации в составе монолита:

1. **Для композиционного корня демона (`src/apps/worker_runner.py`):**

Класс `RefundTaskHandler` готов к регистрации в `TaskDispatcher`:
```python
from src.modules.compensation import (
    CompensationConfig,
    CustomerNotifierService,
    DLQService,
    RefundTaskHandler,
    TelegramIncidentAlerter,
)
from src.shared.contracts.outbox import OutboxTaskType

comp_config = CompensationConfig()
alerter = TelegramIncidentAlerter(bot=alert_bot, config=comp_config)
notifier = CustomerNotifierService(bot=bot)

refund_handler = RefundTaskHandler(
    payment_client=payment_gateway_client,
    order_service=order_lifecycle_service,
    alerter=alerter,
    customer_notifier=notifier,
)
dispatcher.register_handler(
    OutboxTaskType.EXECUTE_PAYMENT_REFUND, refund_handler
)

```


2. **Для контура периодического аудита (DLQ Worker):**
Класс `DLQService` готов к периодическому вызову по расписанию для мониторинга перманентно сбойных задач и оповещения дежурной смены.


3. **Для модуля публикации `channel_publisher` (Блок 5):**
Фатальный сбой публикации рекламного поста в канале гарантированно инициирует создание Outbox-задачи `EXECUTE_PAYMENT_REFUND`, которая будет успешно обработана текущим модулем.



Разработка модуля **Compensation & Incident Management** полностью завершена. Система готова к началу работ над завершающим модулем платформы — **Блоком 1 (`bot_ingress`)**.