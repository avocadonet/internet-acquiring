from aiogram.fsm.state import State, StatesGroup


class OrderCreationFSM(StatesGroup):
    """Состояния мастера создания рекламного заказа."""

    SELECT_CHANNEL = State()       # Выбор рекламной площадки
    WAITING_FOR_CONTENT = State()  # Ожидание текста/медиа/альбома
    CONTENT_PREVIEW = State()      # Превью поста перед вводом контактов
    WAITING_FOR_CONTACT = State()  # Ожидание телефона или email для чека
    ORDER_CONFIRMATION = State()   # Экран подтверждения стоимости и условий
    WAITING_FOR_PAYMENT = State()  # Экран со ссылкой на оплату