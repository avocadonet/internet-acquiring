# Отчет о реализации модуля 5: Channel Publisher (`channel_publisher`)

**Проект:** reklama-bot-platform

**Модуль:** `src/modules/channel_publisher/`

**Статус:** Реализован в полном объеме, верифицирован, Definition of Done достигнут.

---

## 1. Сводная матрица соответствия требованиям ТЗ

Все требования инженерной спецификации модуля `channel_publisher` выполнены в строгом соответствии с архитектурным регламентом платформы.

| № | Требование ТЗ | Реализованный компонент | Статус | Подтверждение / Реализация |
| --- | --- | --- | --- | --- |
| **1.1** | Реализация контракта `IOutboxTaskHandler` для задачи `PUBLISH_POST`<br> | `src/modules/channel_publisher/handler.py`<br> | Выполнено | Класс `ChannelPublisherHandler` реализует методы `handle()` и `on_fatal_failure()`, выполняя десериализацию `PublishPostPayloadDTO`.

 |
| **1.2** | Трансформация и нормализация `PostContentDTO` (`ContentNormalizer`)

 | `src/modules/channel_publisher/normalizer.py`<br> | Выполнено | Прикрепление `caption` и `caption_entities` строго к первому элементу альбома (от 2 до 10 элементов), обнуление у последующих, парсинг `MessageEntity`.

 |
| **1.3** | Адресная публикация по типам контента (`PublisherService`, `IPublisherService`)

 | `src/modules/channel_publisher/client.py`<br> | Выполнено | Реализована отправка `TEXT`, `PHOTO`, `VIDEO`, `MEDIA_GROUP`. В альбоме `published_message_id` признается ID первого сообщения.

 |
| **1.4** | Консервативный профиль сетевых таймаутов `AiohttpSession`<br> | `config.py`, `client.py` (`create_publisher_session`)

 | Выполнено | Раздельные таймауты `ClientTimeout(total=30.0, connect=5.0, sock_connect=5.0, sock_read=20.0)` и пул соединений `TCPConnector`.

 |
| **1.5** | Стратегия защиты от дублирования публикаций (`AntiDuplicateGuard`)

 | `src/modules/channel_publisher/anti_duplicate.py`<br> | Выполнено | Трекинг фаз (`IN_FLIGHT`, `CONFIRMED`, `SUSPECTED_DUPLICATE`, `FAILED`). Блокировка повторных запросов в Telegram при обрыве чтения `ReadTimeout`.

 |
| **1.6** | Классификация ошибок Telegram Bot API и маппинг в `outbox_engine`<br> | `src/modules/channel_publisher/handler.py`<br> | Выполнено | `TelegramRetryAfter` $\to$ `RateLimitTaskError(retry_after)`; 403 / `ChatNotFound` / `CaptionTooLong` $\to$ `FatalTaskError`; ошибки коннекта $\to$ `RetryableTaskError`.

 |
| **1.7** | Уведомление доменного ядра через контракт `IOrderInternalService`<br> | `handler.py`<br> | Выполнено | Вызов `handle_publish_started` перед отправкой, `handle_publish_succeeded` при успехе, `handle_publish_failed` в `on_fatal_failure`.

 |
| **2.1** | Архитектурная изоляция Package-by-Feature

 | Весь модуль `channel_publisher`<br> | Выполнено | Полное отсутствие прямых импортов из параллельных модулей (`src/modules/*`), взаимодействие строго через `src/shared/contracts/`.

 |
| **3.1** | Модульное тестирование (Pytest)

 | `tests/unit/test_channel_publisher/`<br> | Выполнено | 28 модульных тестов с полной изоляцией сети через мок `aiogram.Bot` и `MockOrderService`.

 |
| **4.1** | Статический анализ качества кода

 | `mypy --strict`, `ruff check`<br> | Выполнено | 0 ошибок Mypy в строгом режиме, 0 замечаний линтера Ruff.

 |
| **4.2** | Тестовое покрытие кода (норматив $\ge 85\%$)

 | `pytest-cov`<br> | Выполнено | Итоговое покрытие модуля составило **92%** (225 строк кода, 18 пропущено).

 |

---

## 2. Физическая структура файлов модуля в репозитории

Модуль скомпонован в соответствии с предписанной модульной архитектурой платформы:

```text
src/
└── modules/
    └── channel_publisher/
        ├── __init__.py               # Публичный интерфейс модуля (экспорт сервисов, фабрик, ошибок)
        ├── config.py                 # Конфигурация таймаутов и пула соединений (Pydantic Settings)
        ├── exceptions.py             # Иерархия доменных исключений публикации
        ├── normalizer.py             # Сервис ContentNormalizer (построение альбомов и MessageEntity)
        ├── anti_duplicate.py         # Механизм AntiDuplicateGuard (трекинг фаз и защита от дублей)
        ├── client.py                 # Обертка над aiogram.Bot, сессия AiohttpSession, PublisherService
        └── handler.py                # Обработчик задачи Outbox (ChannelPublisherHandler)

tests/
└── unit/
    └── test_channel_publisher/
        ├── test_normalizer.py        # Тесты сборки альбомов, позиционирования подписи и лимитов (9 тестов)
        ├── test_exception_mapping.py # Тесты маппинга ошибок Telegram Bot API в исключения Outbox (12 тестов)
        └── test_handler.py           # Тесты сценариев handle(), идемпотентности и компенсации (7 тестов)

```

---

## 3. Ключевые архитектурные и инженерные решения

### 3.1. Нормализация альбомов и форматирования (`ContentNormalizer`)

Спецификация Telegram Bot API запрещает одновременную передачу подписей (`caption`) к нескольким элементам медиагруппы — такой запрос отклоняется с ошибкой валидации API. В сервисе `ContentNormalizer` реализованы строгие правила:

* Валидируется размерность альбома: строго от 2 до 10 элементов (выбрасывается `InvalidMediaGroupSizeError` при выходе за границы).


* Поля `caption` и `caption_entities` инжектируются **исключительно в нулевой элемент** сформированного списка `InputMedia`.


* Для всех последующих элементов альбома (индексы $1 \dots 9$) принудительно выставляется `caption=None` и `caption_entities=None`.


* Разметка форматирования преобразуется из сырых словарей в нативные объекты `aiogram.types.MessageEntity`.


* В качестве идентификатора опубликованного альбома (`published_message_id`) доменному ядру передается ID первого сообщения из возвращенного списка: `messages[0].message_id`.



### 3.2. Стратегия защиты от дублирования публикаций (`AntiDuplicateGuard`)

Методы отправки сообщений Telegram Bot API (`send_message`, `send_photo`, `send_media_group`) не поддерживают протокол идемпотентных заголовков (`Idempotency-Key`). Если сервер Telegram успешно опубликовал пост в канале, но TCP-соединение оборвалось на этапе возврата HTTP-ответа (`SocketTimeoutError`, `ServerDisconnectedError`), воркер получает сетевой таймаут при чтении.

Прямой мгновенный перезапуск задачи привел бы к спаму дублирующими постами в публичном канале. Для защиты реализован конечный автомат фаз доставки:

1. **Фаза `IN_FLIGHT`:** фиксирует отправку запроса в Telegram Bot API.


2. **Фаза `CONFIRMED`:** при успешном ответе фиксирует `published_message_id`. Повторные вызовы для этого заказа не выполняют сетевых запросов к Bot API, а мгновенно подтверждают публикацию в домене.


3. **Фаза `SUSPECTED_DUPLICATE`:** при возникновении `TimeoutError`, `asyncio.TimeoutError` или `ServerDisconnectedError` заказ помечается как подозрительный дубликат. Последующие попытки вызова `handle()` блокируются выбросом `RetryableTaskError` с требованием ручной/отложенной проверки, предотвращая появление дублей.



### 3.3. Консервативный профиль сетевой сессии (`AiohttpSession`)

Для исключения эффекта зависания корутин воркера при нестабильном канале связи сессия `AiohttpSession` настраивается через фабрику `create_publisher_session` со следующими тайм-аутами:

* `connect=5.0s`, `sock_connect=5.0s` — быстрый отказ на этапе TCP/TLS-рукопожатия;


* `sock_read=20.0s` — достаточный интервал для выгрузки тяжелых медиафайлов без зависания процесса;


* `total=30.0s` — предельный лимит на полный цикл сетевого взаимодействия;


* `pool_limit=100`, `pool_limit_per_host=30` — ограничение пула соединений через `TCPConnector`.



### 3.4. Классификация ошибок Telegram Bot API и интеграция с Outbox Engine

Обработчик `ChannelPublisherHandler` перехватывает исключения сетевого слоя и Telegram API, транслируя их в типизированные контрактные ошибки `outbox_engine`:

* **Лимиты Telegram API (HTTP 429 FloodWait):**
Перехватывается `TelegramRetryAfter`. Извлекается параметр `e.retry_after` и выбрасывается `RateLimitTaskError(retry_after=...)`. Outbox Engine переносит время следующего запуска задачи без сжигания лимита попыток `retry_count`.


* **Фатальные отказы (HTTP 403 / 400):**
Перехватываются `TelegramForbiddenError` (бот удален или лишен прав администратора), `TelegramBadRequest` («chat not found», «caption is too long», битый `file_id`). Выбрасывается `FatalTaskError`, приводящий к переводу задачи в `failed_permanently = True`.
Движок Outbox вызывает компенсационный хук `on_fatal_failure()`, который через `order_service.handle_publish_failed()` переводит заказ в статус `REFUND_REQUIRED` для автоматического возврата средств покупателю.


* **Транзиентные сбои сети:**
Ошибки `ClientConnectorError` и `TelegramNetworkError` транслируются в `RetryableTaskError`, инициируя штатный экспоненциальный retry с рандомизированным джиттером.



---

## 4. Результаты тестирования и статического анализа

### 4.1. Результаты модульного тестирования (Pytest)

Все 28 тестов модуля завершились успешно:

```text
tests/unit/test_channel_publisher/test_exception_mapping.py ............ [ 42%]
tests/unit/test_channel_publisher/test_handler.py .                      [ 67%]
tests/unit/test_channel_publisher/test_normalizer.py .........           [100%]
============================== 28 passed in 2.81s ==============================

```

#### Детализация тестовых сценариев:

| Тестовый модуль | Число тестов | Проверяемая функциональность | Результат |
| --- | --- | --- | --- |
| `test_normalizer.py`<br> | 9 | Парсинг сущностей форматирования, размещение подписи строго на 1-м элементе альбома, альбомы до 10 элементов, валидация границ (2–10), отсечение неподдерживаемых медиатипов (`audio`).

 | `PASSED` |
| `test_exception_mapping.py`<br> | 12 | Трансляция `TelegramRetryAfter` $\to$ `RateLimitTaskError` с сохранением задержки, маппинг 403 Forbidden, параметризованная проверка `TelegramBadRequest` (chat not found, caption too long, file id), обработка `ClientConnectorError` и `ReadTimeout` с переводом в `SUSPECTED_DUPLICATE`.

 | `PASSED` |
| `test_handler.py`<br> | 7 | Сквозная публикация текста, фото, видео и медиагрупп (контракт первого `message_id`); проверка хронологии `publish_started` $\to$ `publish_succeeded`; идемпотентный пропуск повторов; блокировка подозрительных дубликатов; компенсационный вызов `on_fatal_failure` $\to$ `handle_publish_failed`.

 | `PASSED` |

### 4.2. Метрики покрытия кода (Coverage Report)

Норматив тестового покрытия ТЗ ($\ge 85\%$) перевыполнен.

```text
Name                                             Stmts   Miss  Cover   Missing
------------------------------------------------------------------------------
src\modules\channel_publisher\__init__.py             7      0   100%
src\modules\channel_publisher\anti_duplicate.py      49      1    98%   137
src\modules\channel_publisher\client.py              55     14    75%   29-42, 52-53, 68, 100, 113, 131, 136, 142
src\modules\channel_publisher\config.py              11      0   100%
src\modules\channel_publisher\exceptions.py           6      0   100%
src\modules\channel_publisher\handler.py             71      3    96%   150-152
src\modules\channel_publisher\normalizer.py          26      0   100%
------------------------------------------------------------------------------
TOTAL                                              225     18    92%

```

> **Итоговое покрытие модуля `channel_publisher`:** **92%**.

### 4.3. Строгая типизация (Mypy)

Проверка выполнена в максимально строгом режиме `--strict`:

```powershell
mypy --strict src/modules/channel_publisher tests/unit/test_channel_publisher

```

**Результат:** `Success: no issues found in 10 source files`.

Сквозная валидация всех модулей платформы (`channel_publisher`, `outbox_engine`, `payment_gateway`, `order_domain`):

```powershell
mypy --strict src/modules/channel_publisher src/modules/outbox_engine src/modules/payment_gateway src/modules/order_domain

```

**Результат:** `Success: no issues found in 28 source files`.

### 4.4. Статический анализ и линтинг (Ruff)

```powershell
ruff check src/modules/channel_publisher tests/unit/test_channel_publisher

```

**Результат:** `All checks passed!`.

---

## 5. Готовность к интеграции со смежными модулями

Разработка модуля 5 полностью завершена. Модуль готов к промышленной эксплуатации и бесшовной сборке в рантайме платформы:

1. **Для композиционного корня демона (`src/apps/worker_runner.py`):**


Обработчик готов к монтированию в `TaskDispatcher` перед стартом цикла воркера:


```python
from src.modules.channel_publisher import ChannelPublisherHandler, create_publisher_bot
from src.shared.contracts.outbox import OutboxTaskType

publisher_bot = create_publisher_bot(token=settings.TELEGRAM_BOT_TOKEN)
publisher_handler = ChannelPublisherHandler(
    bot=publisher_bot,
    order_service=order_lifecycle_service,
)
dispatcher.register_handler(OutboxTaskType.PUBLISH_POST, publisher_handler)

```


2. **Для модуля `order_domain` (Блок 2):**


Обеспечена строгая контрактная координация жизненного цикла заказа: вызовы `handle_publish_started`, `handle_publish_succeeded` и `handle_publish_failed` обновляют статусы `PUBLISHING`, `PUBLISHED` и `REFUND_REQUIRED`.


3. **Для модуля `compensation` (Блок 6):**


При возникновении фатальных сбоев публикации метод `on_fatal_failure` гарантированно активирует контур компенсации в домене заказов, создавая Outbox-задачу `EXECUTE_PAYMENT_REFUND` для последующей отмены транзакции в банке.