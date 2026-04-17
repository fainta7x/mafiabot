from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.types import WebAppInfo


# Главное меню пользователя (reply-клавиатура)
def main_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🕵️ Записаться на игру")
    builder.button(text="🧾 Список игроков")
    builder.button(text="👤 Мой профиль")
    builder.button(text="💳 Оплатить")
    builder.button(text="🛠 Перейти в админ-панель")
    builder.adjust(1, 2, 2)
    return builder.as_markup(resize_keyboard=True, is_persistent=True)


# Кнопки записи на игру (inline)
def booking_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Буду вовремя (20:00)", callback_data="book_ontime")
    builder.button(text="⏳ Буду позже", callback_data="book_late")
    builder.button(text="❌ Не смогу", callback_data="book_no")
    builder.adjust(1)
    return builder.as_markup()


# Кнопки подтверждения оплаты (для админа)
def admin_pay_kb(user_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=f"conf_{user_id}")
    builder.button(text="❌ Отклонить", callback_data=f"decl_{user_id}")
    builder.adjust(2)
    return builder.as_markup()


# Главное меню админа (inline)
def admin_main_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Список записи", callback_data="admin_show_players")
    builder.button(text="👥 Все игроки (База)", callback_data="admin_all_users")
    builder.button(text="💰 Разослать счета", callback_data="admin_send_bills")
    builder.adjust(1)
    return builder.as_markup()


# Кнопка «перейти к оплате» пользователю
def user_pay_now_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Перейти к оплате", callback_data="pay_now")
    return builder.as_markup()


# Кнопка «я оплатил(а)» для отправки запроса админу
def user_paid_kb(user_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Я оплатил(а)", callback_data=f"check_{user_id}")
    return builder.as_markup()


# Клавиатура профиля (изменить ник)
def profile_kb(debt: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Изменить ник", callback_data="edit_nickname")
    if debt < 0:
        builder.button(text="💳 Оплатить долг", callback_data="profile_pay")
    return builder.as_markup()


# ===== МЕНЮ АДМИНИСТРАТОРА (reply-клавиатуры) =====

def admin_menu():
    """
    Обычное админ-меню — показывается до/после игры.
    """
    builder = ReplyKeyboardBuilder()
    builder.button(text="🎲 Новая игра")
    builder.button(text="📋 Игроки")
    builder.button(text="💸 Разослать счета")
    builder.button(text="💰 Должники")
    builder.button(text="👥 Все пользователи")
    builder.button(text="❌ Отменить вечер")
    builder.button(text="📣 Сделать анонс")
    builder.button(text="📚 История вечеров")
    builder.button(text="🏠 В главное меню")
    builder.adjust(1, 2, 2, 2, 2)
    return builder.as_markup(resize_keyboard=True, is_persistent=True)


def game_admin_menu():
    """
    Минимальная клавиатура во время подготовки/проведения игры.
    Никаких лишних пунктов — только управление текущей игрой.
    """
    builder = ReplyKeyboardBuilder()
    builder.button(text="Ок")
    builder.button(text="Выставить")
    builder.button(text="Голоса")
    builder.button(text="Фол")
    builder.button(text="Убить")          # новая кнопка
    builder.button(text="Остановить игру")
    builder.adjust(3, 3)  # 1-я строка 3, 2-я строка 3
    return builder.as_markup(resize_keyboard=True, is_persistent=True)


def evenings_history_kb(evenings: list):
    builder = InlineKeyboardBuilder()
    for date_str, count in evenings:
        builder.button(
            text=f"{date_str} ({count} чел.)",
            callback_data=f"hist_{date_str}"
        )
    builder.adjust(1)
    return builder.as_markup()

def split_decision_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="Поднять всех", callback_data="split:kill_all")
    builder.button(text="Никого не заголосовывать", callback_data="split:keep_all")
    builder.adjust(1, 1)
    return builder.as_markup()

def game_finish_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🏙 Победа города", callback_data="game_end:city")
    builder.button(text="💀 Победа мафии", callback_data="game_end:mafia")
    builder.button(text="❌ Отмена игры", callback_data="game_end:cancel")
    builder.adjust(1)
    return builder.as_markup()
