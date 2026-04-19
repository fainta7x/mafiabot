from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.types import WebAppInfo


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def _mobile_adjust(*sizes: int, max_per_row: int = 3):
    """
    Адаптивная настройка кнопок для мобильных устройств.
    На маленьких экранах лучше не ставить больше 3 кнопок в ряд.
    """
    return min(max_per_row, max(sizes)) if len(sizes) == 1 else sizes


# ========== ГЛАВНОЕ МЕНЮ ПОЛЬЗОВАТЕЛЯ ==========
def main_menu():
    """Главное меню — оптимизировано для мобильных (3 кнопки в ряд максимум)."""
    builder = ReplyKeyboardBuilder()
    buttons = [
        "🕵️ Записаться на игру",
        "🧾 Список игроков",
        "👤 Мой профиль",
        "💳 Оплатить",
        "📊 Статистика",
        "📜 Мои игры",
        "📜 Все игры",
        "🛠 Админ-панель"
    ]
    for btn in buttons:
        builder.button(text=btn)

    # На мобильных лучше 3-2-3 вместо 2-2-3-2-1
    builder.adjust(3, 2, 3)
    return builder.as_markup(resize_keyboard=True, is_persistent=True)


# ========== ЗАПИСЬ НА ИГРУ ==========
def booking_kb():
    """Кнопки записи — вертикальные, так как тексты длинные."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Вовремя (20:00)", callback_data="book_ontime")
    builder.button(text="⏳ Позже", callback_data="book_late")
    builder.button(text="❌ Не смогу", callback_data="book_no")
    builder.adjust(1)  # вертикально — удобнее для мобильных
    return builder.as_markup()


# ========== ФИНАНСЫ ==========
def admin_pay_kb(user_id: int):
    """Кнопки подтверждения оплаты."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=f"conf_{user_id}")
    builder.button(text="❌ Отклонить", callback_data=f"decl_{user_id}")
    builder.adjust(2)
    return builder.as_markup()


def user_pay_now_kb():
    """Кнопка перехода к оплате."""
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Перейти к оплате", callback_data="pay_now")
    return builder.as_markup()


def user_paid_kb(user_id: int):
    """Кнопка 'Я оплатил'."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Я оплатил(а)", callback_data=f"check_{user_id}")
    return builder.as_markup()


def profile_kb(debt: int):
    """Клавиатура профиля."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Изменить ник", callback_data="edit_nickname")
    if debt < 0:
        builder.button(text="💳 Оплатить долг", callback_data="profile_pay")
    builder.adjust(1)
    return builder.as_markup()


# ========== АДМИН-МЕНЮ (REPLY) ==========
def admin_menu():
    """
    Админ-меню — оптимизировано для мобильных.
    Группируем связанные действия.
    """
    builder = ReplyKeyboardBuilder()

    # Игровые действия
    builder.button(text="🎲 Новая игра")
    builder.button(text="♻️ Продолжить игру")

    # Управление игроками
    builder.button(text="📋 Игроки")
    builder.button(text="👥 Все пользователи")
    builder.button(text="💰 Должники")

    # Финансы и анонсы
    builder.button(text="📣 Сделать анонс")
    builder.button(text="💸 Разослать счета")

    # История и отмена
    builder.button(text="📚 История вечеров")
    builder.button(text="❌ Отменить вечер")

    # Выход
    builder.button(text="🏠 В главное меню")

    # На мобильных: 2-3-2-2-1
    builder.adjust(2, 3, 2, 2, 1)
    return builder.as_markup(resize_keyboard=True, is_persistent=True)


def game_admin_menu():
    """
    Игровое меню — оптимизировано для быстрого доступа.
    Самые частые действия — ближе к центру/правой стороне.
    """
    builder = ReplyKeyboardBuilder()

    # Основные действия (первые 5)
    builder.button(text="Ок")
    builder.button(text="Выставить")
    builder.button(text="Голоса")
    builder.button(text="Фол")
    builder.button(text="Убить")

    # Редактирование и вспомогательные
    builder.button(text="✏️ Редактировать")  # НОВАЯ КНОПКА
    builder.button(text="🧹 Очистить")

    # Завершение
    builder.button(text="⏹ Остановить")
    builder.button(text="🏁 Завершить")

    # 3-2-2 (Ок,Выставить,Голоса) + (Фол,Убить) + (Редактировать,Очистить) + (Остановить,Завершить)
    builder.adjust(3, 2, 2, 2)
    return builder.as_markup(resize_keyboard=True, is_persistent=True)


# ========== INLINE КЛАВИАТУРЫ ==========
def evenings_history_kb(evenings: list):
    """Список вечеров — вертикальный."""
    builder = InlineKeyboardBuilder()
    for date_str, count in evenings:
        builder.button(text=f"📅 {date_str} ({count} чел.)", callback_data=f"hist_{date_str}")
    builder.adjust(1)
    return builder.as_markup()


def split_decision_keyboard():
    """Решение по попилу — крупные кнопки."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⚡ Поднять всех", callback_data="split:kill_all")
    builder.button(text="🔄 Оставить всех", callback_data="split:keep_all")
    builder.adjust(1)  # вертикально для мобильных
    return builder.as_markup()


def game_finish_keyboard():
    """Завершение игры — крупные кнопки."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🏙 Победа города", callback_data="game_end:city")
    builder.button(text="💀 Победа мафии", callback_data="game_end:mafia")
    builder.button(text="❌ Отмена", callback_data="game_end:cancel")
    builder.adjust(1)
    return builder.as_markup()


def games_list_kb(games: list, prefix: str):
    """
    Список игр — оптимизирован для мобильных.
    Короткие названия, вертикальный список.
    """
    builder = InlineKeyboardBuilder()
    for game_id, title, number in games:
        # Укорачиваем слишком длинные названия для мобильных
        if len(title) > 35:
            title = title[:32] + "..."
        builder.button(text=title, callback_data=f"{prefix}:{game_id}:{number}")
    builder.adjust(1)  # вертикально — удобнее листать
    return builder.as_markup()


# ========== ДОПОЛНИТЕЛЬНЫЕ УДОБНЫЕ КЛАВИАТУРЫ ==========
def numeric_keyboard(max_buttons: int = 10, row_size: int = 5):
    """
    Цифровая клавиатура для ввода номеров слотов.
    Оптимизирована для мобильных — 5 кнопок в ряд.
    """
    builder = InlineKeyboardBuilder()
    for i in range(1, max_buttons + 1):
        builder.button(text=str(i), callback_data=f"num_{i}")
    builder.adjust(row_size)
    return builder.as_markup()


def quick_actions_kb():
    """
    Быстрые действия для ведущего.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="🎲 Раздать роли", callback_data="quick_roles")
    builder.button(text="⚡ Показать живых", callback_data="quick_alive")
    builder.button(text="📊 Текущий счёт", callback_data="quick_score")
    builder.button(text="🔄 Сбросить голоса", callback_data="quick_reset_votes")
    builder.adjust(2, 2)
    return builder.as_markup()


def confirmation_kb(action: str):
    """
    Универсальная клавиатура подтверждения.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да", callback_data=f"confirm_{action}_yes")
    builder.button(text="❌ Нет", callback_data=f"confirm_{action}_no")
    builder.adjust(2)
    return builder.as_markup()