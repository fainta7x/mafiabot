from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.types import WebAppInfo
from aiogram.types import InlineKeyboardMarkup


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

    builder.adjust(3, 2, 3)
    return builder.as_markup(resize_keyboard=True, is_persistent=True)


# ========== ЗАПИСЬ НА ИГРУ ==========
def booking_kb():
    """Кнопки записи — вертикальные."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Вовремя (20:00)", callback_data="book_ontime")
    builder.button(text="⏳ Позже", callback_data="book_late")
    builder.button(text="❌ Не смогу", callback_data="book_no")
    builder.adjust(1)
    return builder.as_markup()


# ========== ФИНАНСЫ ==========
def admin_pay_kb(user_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=f"conf_{user_id}")
    builder.button(text="❌ Отклонить", callback_data=f"decl_{user_id}")
    builder.adjust(2)
    return builder.as_markup()


def user_pay_now_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Перейти к оплате", callback_data="pay_now")
    return builder.as_markup()


def user_paid_kb(user_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Я оплатил(а)", callback_data=f"check_{user_id}")
    return builder.as_markup()


def profile_kb(debt: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Изменить ник", callback_data="edit_nickname")
    if debt < 0:
        builder.button(text="💳 Оплатить долг", callback_data="profile_pay")
    builder.adjust(1)
    return builder.as_markup()


# ========== АДМИН-МЕНЮ (REPLY) ==========
def admin_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🎲 Новая игра")
    builder.button(text="♻️ Продолжить игру")
    builder.button(text="📋 Игроки")
    builder.button(text="👥 Все пользователи")
    builder.button(text="💰 Должники")
    builder.button(text="📣 Сделать анонс")
    builder.button(text="💸 Разослать счета")
    builder.button(text="📚 История вечеров")
    builder.button(text="❌ Отменить вечер")
    builder.button(text="🏠 В главное меню")
    builder.adjust(2, 3, 2, 2, 1)
    return builder.as_markup(resize_keyboard=True, is_persistent=True)


def game_admin_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Ок")
    builder.button(text="Выставить")
    builder.button(text="Голоса")
    builder.button(text="Фол")
    builder.button(text="Убить")
    builder.button(text="✏️ Редактировать")
    builder.button(text="⏹ Остановить")
    builder.button(text="🏁 Завершить")
    builder.adjust(3, 2, 2, 1)
    return builder.as_markup(resize_keyboard=True, is_persistent=True)


# ========== INLINE КЛАВИАТУРЫ ==========
def evenings_history_kb(evenings: list):
    builder = InlineKeyboardBuilder()
    for date_str, count in evenings:
        builder.button(text=f"📅 {date_str} ({count} чел.)", callback_data=f"hist_{date_str}")
    builder.adjust(1)
    return builder.as_markup()


def split_decision_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="⚡ Поднять всех", callback_data="split:kill_all")
    builder.button(text="🔄 Оставить всех", callback_data="split:keep_all")
    builder.adjust(1)
    return builder.as_markup()


def game_finish_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🏙 Победа города", callback_data="game_end:city")
    builder.button(text="💀 Победа мафии", callback_data="game_end:mafia")
    builder.button(text="⚠️ ППК", callback_data="game_end:ppk")  # НОВАЯ КНОПКА
    builder.button(text="❌ Отмена", callback_data="game_end:cancel")
    builder.adjust(1)
    return builder.as_markup()


def games_list_kb(games: list, prefix: str):
    builder = InlineKeyboardBuilder()
    for game_id, title, number in games:
        if len(title) > 35:
            title = title[:32] + "..."
        builder.button(text=title, callback_data=f"{prefix}:{game_id}:{number}")
    builder.adjust(1)
    return builder.as_markup()


# ========== ДОПОЛНИТЕЛЬНЫЕ УДОБНЫЕ КЛАВИАТУРЫ ==========
def numeric_keyboard(max_buttons: int = 10, row_size: int = 5):
    builder = InlineKeyboardBuilder()
    for i in range(1, max_buttons + 1):
        builder.button(text=str(i), callback_data=f"num_{i}")
    builder.adjust(row_size)
    return builder.as_markup()


def quick_actions_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="🎲 Раздать роли", callback_data="quick_roles")
    builder.button(text="⚡ Показать живых", callback_data="quick_alive")
    builder.button(text="📊 Текущий счёт", callback_data="quick_score")
    builder.button(text="🔄 Сбросить голоса", callback_data="quick_reset_votes")
    builder.adjust(2, 2)
    return builder.as_markup()


def confirmation_kb(action: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да", callback_data=f"confirm_{action}_yes")
    builder.button(text="❌ Нет", callback_data=f"confirm_{action}_no")
    builder.adjust(2)
    return builder.as_markup()


# ========== НОВЫЕ КЛАВИАТУРЫ ДЛЯ РЕЖИМА РЕДАКТИРОВАНИЯ ==========

def edit_slot_selection_kb(slots: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for slot_num, info in slots.items():
        name = info.get("nickname") or info.get("full_name") or f"Слот {slot_num}"
        if len(name) > 15:
            name = name[:12] + "..."
        role = info.get("role", "?")
        if len(role) > 8:
            role = role[:6] + "."
        status_icon = "✅" if info.get("alive", True) else "💀"
        builder.button(
            text=f"{status_icon} {slot_num}. {name} [{role}]",
            callback_data=f"edit_slot_{slot_num}"
        )
    builder.adjust(1)
    builder.button(text="❌ Закрыть", callback_data="edit_close")
    builder.adjust(1)
    return builder.as_markup()


def get_edit_menu_keyboard(slot_num: int, slot_data: dict) -> InlineKeyboardMarkup:
    role = slot_data.get("role", "Не задана")
    team = slot_data.get("team", "—")
    alive = slot_data.get("alive", True)
    status_reason = slot_data.get("status_reason", "Жив")
    pu_mark = slot_data.get("pu_mark", False)
    lh = slot_data.get("night_suspects", [])
    protocol = slot_data.get("will_protocol_raw", "")
    opinion = slot_data.get("will_opinion", "")
    kicked = slot_data.get("kicked", False)

    status_text = "✅ Жив" if alive else f"💀 {status_reason}"
    if kicked:
        status_text = "🚫 Удалён"

    role_display = role if len(role) <= 10 else role[:8] + ".."
    team_display = team if team and len(team) <= 8 else team[:6] + ".." if team else "—"

    builder = InlineKeyboardBuilder()

    builder.button(text=f"🎭 {role_display}", callback_data="edit_role")
    builder.button(text=f"🏳️ {team_display}", callback_data="edit_team")
    builder.button(text=f"📊 {status_text}", callback_data="edit_status")
    pu_text = "👑 ПУ: ✅" if pu_mark else "👑 ПУ: ❌"
    builder.button(text=pu_text, callback_data="edit_pu")
    lh_text = f"📝 ЛХ: {len(lh)}" if lh else "📝 ЛХ: нет"
    protocol_text = "📋 ПР: есть" if protocol else "📋 ПР: нет"
    builder.button(text=lh_text, callback_data="edit_lh")
    builder.button(text=protocol_text, callback_data="edit_protocol")
    opinion_text = "💬 МН: есть" if opinion else "💬 МН: нет"
    builder.button(text=opinion_text, callback_data="edit_opinion")
    builder.button(text="🔄 Очистить", callback_data="edit_clear_all")
    builder.button(text="◀️ Назад", callback_data="edit_back_to_menu")
    builder.button(text="❌ Закрыть", callback_data="edit_close")

    builder.adjust(2, 2, 2, 2, 2)
    return builder.as_markup()


def role_selection_kb(current_role: str = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="👤 Мирный", callback_data="role_set_Мирный")
    builder.button(text="🕵️ Шериф", callback_data="role_set_Шериф")
    builder.button(text="🔪 Мафия", callback_data="role_set_Мафия")
    builder.button(text="👑 Дон", callback_data="role_set_Дон")
    builder.button(text="❓ Не задана", callback_data="role_set_Не задана")
    builder.button(text="◀️ Назад", callback_data="edit_back_to_menu")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def status_selection_kb(current_status: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Жив", callback_data="status_set_alive")
    builder.button(text="💀 Убит ночью", callback_data="status_set_killed")
    builder.button(text="⚖️ Заголосован", callback_data="status_set_voted")
    builder.button(text="🚫 Удалён", callback_data="status_set_kicked")
    builder.button(text="◀️ Назад", callback_data="edit_back_to_menu")
    builder.adjust(1, 1, 1, 1, 1)
    return builder.as_markup()


def pu_confirmation_kb(slot_num: int, slot_name: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=f"✅ Да, назначить {slot_name} ПУ", callback_data="pu_confirm_yes")
    builder.button(text="❌ Нет, отмена", callback_data="edit_back_to_menu")
    builder.adjust(1)
    return builder.as_markup()


def lh_input_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔢 Цифровая клавиатура", callback_data="show_numeric_kb")
    builder.button(text="◀️ Назад", callback_data="edit_back_to_menu")
    builder.adjust(1)
    return builder.as_markup()


def clear_confirmation_kb(slot_num: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⚠️ ДА, ОЧИСТИТЬ ВСЁ", callback_data="clear_confirm_yes")
    builder.button(text="❌ Отмена", callback_data="edit_back_to_menu")
    builder.adjust(1)
    return builder.as_markup()


def numeric_selection_kb(selected: list = None) -> InlineKeyboardMarkup:
    selected = selected or []
    builder = InlineKeyboardBuilder()
    for i in range(1, 6):
        text = f"✅ {i}" if str(i) in selected else str(i)
        builder.button(text=text, callback_data=f"num_toggle_{i}")
    builder.adjust(5)
    for i in range(6, 11):
        text = f"✅ {i}" if str(i) in selected else str(i)
        builder.button(text=text, callback_data=f"num_toggle_{i}")
    builder.adjust(5)
    builder.button(text="❌ Очистить всё", callback_data="numeric_clear")
    builder.button(text="◀️ Назад", callback_data="numeric_back")
    builder.button(text="✅ Готово", callback_data="numeric_done")
    builder.adjust(3)
    return builder.as_markup()


# ========== НОВЫЕ КЛАВИАТУРЫ ДЛЯ СОЗДАНИЯ ИГРЫ ==========

def game_confirm_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="game_confirm_yes")
    builder.button(text="🔄 Перемешать", callback_data="game_confirm_no")
    builder.button(text="✏️ Редактировать", callback_data="game_confirm_edit")
    builder.adjust(2, 1)
    return builder.as_markup()


def players_selection_kb(players: list, action: str, max_select: int, selected: list = None) -> InlineKeyboardMarkup:
    selected = selected or []
    builder = InlineKeyboardBuilder()
    for slot_num, name in players:
        is_selected = slot_num in selected
        prefix = "✅ " if is_selected else "⬜ "
        builder.button(text=f"{prefix}{slot_num}. {name}", callback_data=f"select_{action}_{slot_num}")
    if action == "mafia" and len(selected) == max_select:
        builder.button(text="✅ Продолжить", callback_data="mafia_selection_done")
    builder.adjust(1)
    return builder.as_markup()


# ========== КЛАВИАТУРЫ ДЛЯ УПРАВЛЕНИЯ ФОЛАМИ ==========

def foul_select_kb(slots: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for slot_num, info in slots.items():
        if not info.get("alive", True):
            continue
        name = info.get("nickname") or info.get("full_name") or f"Слот {slot_num}"
        if len(name) > 15:
            name = name[:12] + "..."
        fouls = info.get("fouls", 0)
        foul_icon = "⚠️" * min(fouls, 3) if fouls > 0 else "⚪"
        builder.button(text=f"{slot_num}. {name} [{foul_icon}]", callback_data=f"foul_select_{slot_num}")
    builder.button(text="❌ Отмена", callback_data="foul_cancel")
    builder.adjust(1)
    return builder.as_markup()


def foul_action_kb(slot_num: int, current_fouls: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ +1 фол", callback_data=f"foul_add_{slot_num}")
    if current_fouls > 0:
        builder.button(text="➖ -1 фол", callback_data=f"foul_remove_{slot_num}")
    builder.button(text="📋 Техфол малый (-0.3)", callback_data=f"tech_foul_small_{slot_num}")  # -0.3
    builder.button(text="⚠️ Техфол большой (-0.6)", callback_data=f"tech_foul_big_{slot_num}")  # -0.6
    builder.button(text="🚫 Удалить игрока (-1.0)", callback_data=f"kick_player_{slot_num}")
    builder.button(text="❌ Отмена", callback_data="foul_cancel")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


# ========== КЛАВИАТУРЫ ДЛЯ ВЫСТАВЛЕНИЯ (НОМИНАЦИИ) ==========

def nominate_select_kb(slots: dict, current_nominated: list = None) -> InlineKeyboardMarkup:
    current_nominated = current_nominated or []
    builder = InlineKeyboardBuilder()

    names = {}
    for slot_num, info in slots.items():
        if info.get("alive", True):
            name = info.get("nickname") or info.get("full_name") or f"Слот {slot_num}"
            names[slot_num] = name[:15] if len(name) > 15 else name

    for slot_num in range(1, 11):
        if slot_num in names:
            prefix = "✅ " if slot_num in current_nominated else "⬜ "
            builder.button(text=f"{prefix}{slot_num}. {names[slot_num]}", callback_data=f"nominate_toggle_{slot_num}")

    buttons_count = len(names)
    rows = []
    for i in range(buttons_count):
        if i % 2 == 0:
            rows.append(2)
    if buttons_count % 2 == 1:
        rows[-1] = 1

    if rows:
        builder.adjust(*rows)

    builder.button(text="✅ Подтвердить", callback_data="nominate_confirm")
    builder.button(text="❌ Отмена", callback_data="nominate_cancel")
    builder.adjust(1)
    return builder.as_markup()


# ========== КЛАВИАТУРЫ ДЛЯ ГОЛОСОВАНИЯ ==========

def vote_value_kb(slot_num: int, max_votes: int, remaining_voters: int = None,
                  remaining_candidates: int = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="0", callback_data=f"vote_set_{slot_num}_0")
    limit = min(max_votes, 10)
    split_options = set()
    if remaining_voters and remaining_candidates:
        if remaining_voters == 10 and remaining_candidates == 2:
            split_options.add(5)
        elif remaining_voters == 9 and remaining_candidates == 3:
            split_options.add(3)
        elif remaining_voters == 8 and remaining_candidates == 2:
            split_options.add(4)
        elif remaining_voters == 8 and remaining_candidates == 4:
            split_options.add(2)
        elif remaining_voters == 6 and remaining_candidates == 2:
            split_options.add(3)
        elif remaining_voters == 6 and remaining_candidates == 3:
            split_options.add(2)
        elif remaining_voters == 4 and remaining_candidates == 2:
            split_options.add(2)

    for i in range(1, limit + 1):
        if i in split_options:
            builder.button(text=f"🔴 {i}", callback_data=f"vote_set_{slot_num}_{i}")
        else:
            builder.button(text=str(i), callback_data=f"vote_set_{slot_num}_{i}")

    import math
    rows_count = 1 + math.ceil(limit / 2)
    rows = [1] + [2] * math.ceil(limit / 2)
    builder.adjust(*rows[:rows_count])
    if remaining_voters:
        builder.button(text=f"ℹ️ Осталось голосов: {remaining_voters}", callback_data="vote_info")
    elif max_votes > 10:
        builder.button(text=f"ℹ️ Всего: {max_votes}", callback_data="vote_info")
    builder.adjust(1)
    return builder.as_markup()


# ========== КЛАВИАТУРЫ ДЛЯ РЕДАКТОРА БАЛЛОВ ПОСЛЕ ИГРЫ ==========

def score_editor_player_kb(slots: dict, winning_team: str = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for slot_num, info in slots.items():
        name = info.get("nickname") or info.get("full_name") or f"Слот {slot_num}"
        if len(name) > 12:
            name = name[:10] + ".."
        role = info.get("role", "?")
        if len(role) > 8:
            role = role[:6] + "."
        total = (info.get("base_points", 0) + info.get("bonus_points", 0) +
                 info.get("lh_points", 0) + info.get("will_protocol_points", 0) +
                 info.get("will_opinion_points", 0))
        team = info.get("team")
        team_icon = "🔴" if team == "Красные" else "⚫" if team == "Чёрные" else "⚪"
        builder.button(text=f"{team_icon} {slot_num}. {name} [{role}] — {total:.1f}",
                       callback_data=f"score_edit_{slot_num}")
    builder.button(text="✅ Завершить и сохранить", callback_data="score_finish")
    builder.button(text="❌ Отмена", callback_data="score_cancel")
    builder.adjust(1)
    return builder.as_markup()


def score_type_kb(slot_num: int, current_values: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    bonus = current_values.get("bonus_points", 0)
    protocol = current_values.get("will_protocol_points", 0)
    opinion = current_values.get("will_opinion_points", 0)
    builder.button(text=f"🎲 Доп: {bonus:+.1f}", callback_data=f"score_type_bonus_{slot_num}")
    builder.button(text=f"📋 ПР: {protocol:+.1f}", callback_data=f"score_type_protocol_{slot_num}")
    builder.button(text=f"💬 МН: {opinion:+.1f}", callback_data=f"score_type_opinion_{slot_num}")
    builder.button(text="◀️ Назад к выбору игрока", callback_data="score_back_to_players")
    builder.button(text="✅ Завершить", callback_data="score_finish")
    builder.adjust(1)
    return builder.as_markup()


def score_value_kb(current_value: float = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    pairs = []
    for i in range(1, 9):
        val = i / 10
        pairs.append((f"+{val:.1f}", val, f"-{val:.1f}", -val))
    for plus_text, plus_val, minus_text, minus_val in pairs:
        builder.button(text=plus_text, callback_data=f"score_val_{plus_val}")
        builder.button(text=minus_text, callback_data=f"score_val_{minus_val}")
    builder.button(text="0", callback_data="score_val_0")
    builder.button(text="✏️ Ввести вручную", callback_data="score_manual")
    builder.button(text="◀️ Назад", callback_data="score_back_to_types")
    builder.adjust(*([2] * 8), 2, 1)
    return builder.as_markup()


edit_actions_kb = get_edit_menu_keyboard


# ========== КЛАВИАТУРЫ ДЛЯ УБИЙСТВА ==========

def kill_select_kb(slots: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for slot_num, info in slots.items():
        if not info.get("alive", True):
            continue
        name = info.get("nickname") or info.get("full_name") or f"Слот {slot_num}"
        if len(name) > 15:
            name = name[:12] + "..."
        role = info.get("role", "?")
        if len(role) > 8:
            role = role[:6] + "."
        builder.button(text=f"💀 {slot_num}. {name} [{role}]", callback_data=f"kill_select_{slot_num}")
    builder.button(text="❌ Отмена", callback_data="kill_cancel")
    builder.adjust(2)
    return builder.as_markup()


def kill_lh_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔢 Цифровая клавиатура", callback_data="kill_show_numeric_kb")
    builder.button(text="◀️ Назад", callback_data="kill_back_to_select")
    builder.adjust(1)
    return builder.as_markup()


def kill_protocol_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⏩ Пропустить (без протокола)", callback_data="kill_protocol_skip")
    builder.button(text="◀️ Назад", callback_data="kill_back_to_lh")
    builder.adjust(1)
    return builder.as_markup()


def kill_opinion_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⏩ Пропустить (без мнения)", callback_data="kill_opinion_skip")
    builder.button(text="◀️ Назад", callback_data="kill_back_to_protocol")
    builder.adjust(1)
    return builder.as_markup()


# ========== НОВЫЕ КЛАВИАТУРЫ ДЛЯ ППК ==========

def ppk_team_selection_kb() -> InlineKeyboardMarkup:
    """Выбор победившей команды при ППК."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔴 Красные (ППК)", callback_data="ppk_team_red")
    builder.button(text="⚫ Чёрные (ППК)", callback_data="ppk_team_black")
    builder.button(text="❌ Отмена", callback_data="ppk_cancel")
    builder.adjust(1)
    return builder.as_markup()


def ppk_culprit_selection_kb(slots: dict, team: str) -> InlineKeyboardMarkup:
    """Выбор виновника ППК из указанной команды."""
    builder = InlineKeyboardBuilder()
    for slot_num, info in slots.items():
        if info.get("team") == team and info.get("alive", True):
            name = info.get("nickname") or info.get("full_name") or f"Слот {slot_num}"
            if len(name) > 15:
                name = name[:12] + "..."
            builder.button(text=f"{slot_num}. {name}", callback_data=f"ppk_culprit_{slot_num}")
    builder.button(text="◀️ Назад", callback_data="ppk_back_to_teams")
    builder.adjust(1)
    return builder.as_markup()


def ppk_confirmation_kb(slot_num: int, name: str) -> InlineKeyboardMarkup:
    """Подтверждение назначения виновника ППК."""
    builder = InlineKeyboardBuilder()
    builder.button(text=f"✅ Да, {name} виноват", callback_data="ppk_confirm_yes")
    builder.button(text="❌ Нет, отмена", callback_data="ppk_cancel")
    builder.adjust(1)
    return builder.as_markup()