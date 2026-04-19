import random
from datetime import datetime

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode
from aiogram.types import FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
import database
import keyboards
from .state import GameCreateState
from .text import build_slots_text, build_game_state, build_protocol_text
from .pic_endgame import create_endgame_pic_summary

router = Router()


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def is_admin_pm(message: types.Message) -> bool:
    return message.from_user and message.from_user.id in config.ADMIN_IDS and message.chat.type == "private"


async def ensure_admin_pm(message: types.Message) -> bool:
    if not is_admin_pm(message):
        return False
    return True


async def get_slots(message: types.Message, state: FSMContext, allow_empty: bool = False) -> dict:
    data = await state.get_data()
    slots = data.get("slots") or {}
    if not slots and not allow_empty:
        await message.answer("Слоты пустые. Нажми «🎲 Новая игра», чтобы начать новую партию.",
                             reply_markup=keyboards.game_admin_menu())
    return slots


def parse_slot_num(raw: str, min_slot: int = 1, max_slot: int = 10) -> tuple[bool, int | None, str | None]:
    text = (raw or "").strip()
    if not text.isdigit():
        return False, None, f"Нужно ввести номер слота (число от {min_slot} до {max_slot})."
    num = int(text)
    if num < min_slot or num > max_slot:
        return False, None, f"Номер слота должен быть от {min_slot} до {max_slot}."
    return True, num, None


def create_empty_slot(nickname: str) -> dict:
    """Создаёт пустой слот для игрока."""
    return {
        "user_id": None, "full_name": None, "nickname": nickname, "username": None,
        "status": "Добавлен вручную", "fouls": 0, "alive": True, "status_reason": "Жив",
        "nominated": False, "votes": 0, "night_suspects": [], "role": "Не задана",
        "team": None, "base_points": 0, "bonus_points": 0, "lh_points": 0.0, "pu_mark": False
    }


async def save_slots(state: FSMContext, slots: dict):
    """Сохраняет слоты и метаданные в состояние и БД."""
    # Убеждаемся, что ключи — целые числа
    slots_int = {int(k): v for k, v in slots.items()}
    await state.update_data(slots=slots_int)

    # Сохраняем метаданные вместе со слотами
    data = await state.get_data()
    metadata = {
        "first_night_kill_recorded": data.get("first_night_kill_recorded", False),
        "night_kills_order": data.get("night_kills_order", []),
        "roles_assigned": data.get("roles_assigned", False),
        "winner_label": data.get("winner_label"),
        "winning_team": data.get("winning_team"),
    }
    await database.save_current_game_slots(slots_int, metadata)


async def clear_game_state(state: FSMContext):
    """Полностью очищает состояние игры."""
    await state.clear()
    await database.set_setting("game_active", None)
    await database.set_setting("current_game_slots", None)
    await database.set_setting("current_game_date", None)
    await database.set_setting("current_game_number", None)
    await database.set_setting("current_game_global_number", None)


async def show_game_state_all(message: types.Message, state: FSMContext):
    """Показывает текущее состояние игры."""
    data = await state.get_data()
    slots = data.get("slots") or {}
    print(f"[DIAG] show_game_state_all: slots keys = {list(slots.keys())}")
    if 6 in slots:
        print(f"[DIAG] Слот 6: alive={slots[6].get('alive')}")
    if slots:
        await message.answer(build_game_state(slots, alive_only=False), reply_markup=keyboards.game_admin_menu())


# ========== 1. НОВАЯ ИГРА (ИНТЕРАКТИВНАЯ) ==========
@router.message(F.text == "🎲 Новая игра")
async def start_new_game(message: types.Message, state: FSMContext):
    if not await ensure_admin_pm(message):
        return

    if await database.get_setting("game_active") == "1":
        await message.answer("Уже есть активная игра. Сначала завершите её.", reply_markup=keyboards.game_admin_menu())
        return

    booked = await database.get_booked_players_for_game()
    if not booked:
        await message.answer("На вечер никто не записан.", reply_markup=keyboards.admin_menu())
        return

    # Сохраняем список записанных игроков
    await state.update_data(
        booked_players=booked,
        first_night_kill_recorded=False,
        night_kills_order=[],
        night_killed_slot=None,
        roles_assigned=False,
        winner_label=None,
        winning_team=None,
        nominated_list=[],
        vote_index=0,
        split_candidates=[],
        in_split=False,
        votes_received={},
        remaining_voters=0,
        protocol_chat_id=None,
        protocol_message_id=None
    )

    await show_players_list_for_game(message, state, booked)


async def show_players_list_for_game(message: types.Message, state: FSMContext, booked: list = None):
    """Показывает предварительный список всех 10 слотов."""
    if booked is None:
        data = await state.get_data()
        booked = data.get("booked_players", [])

    players_text = "📋 **Предварительный состав игры (10 слотов):**\n\n"

    for slot_num in range(1, 11):
        if slot_num <= len(booked) and booked[slot_num - 1]:
            user_id, full_name, username, nickname, status = booked[slot_num - 1]
            name = nickname or full_name or f"Игрок {user_id}"
            players_text += f"{slot_num}. ✅ {name}\n"
        else:
            players_text += f"{slot_num}. ⬜ Свободно\n"

    real_players = len([p for p in booked if p and p[3] not in [None, "Свободно", ""] and p[1] not in ["Свободно"]])

    players_text += f"\n👥 **Заполнено слотов:** {real_players}/10\n"

    if real_players < 4:
        players_text += "\n⚠️ **Минимальное количество игроков: 4**\n"
    else:
        players_text += "\n✅ Можно начинать игру!\n"

    players_text += "\nПодтвердите состав или отредактируйте слоты."

    await message.answer(players_text, reply_markup=keyboards.game_confirm_kb(), parse_mode="Markdown")


async def show_current_players_list(message: types.Message, state: FSMContext):
    """Показывает текущий список слотов с инлайн-кнопкой Готово."""
    data = await state.get_data()
    booked = data.get("booked_players", [])

    players_text = "📋 **Текущий состав (10 слотов):**\n\n"

    for slot_num in range(1, 11):
        if slot_num <= len(booked) and booked[slot_num - 1]:
            user_id, full_name, username, nickname, status = booked[slot_num - 1]
            name = nickname or full_name or f"Игрок {user_id}"
            if len(name) > 20:
                name = name[:17] + "..."
            players_text += f"{slot_num}. {name}\n"
        else:
            players_text += f"{slot_num}. ⬜ Свободно\n"

    real_players = len([p for p in booked if p and p[3] not in [None, "Свободно", ""] and p[1] not in ["Свободно"]])
    players_text += f"\n✏️ **Заполнено: {real_players}/10**\n\n"
    players_text += "**Команды:**\n"
    players_text += "• `<номер> <ник>` — заполнить слот\n"
    players_text += "• `очистить <номер>` — очистить слот\n\n"
    players_text += "Когда закончите редактирование — нажмите кнопку **Готово**"

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Готово", callback_data="edit_players_done")
    builder.adjust(1)

    await message.answer(players_text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.callback_query(F.data == "game_confirm_yes")
async def confirm_game_players(callback: types.CallbackQuery, state: FSMContext):
    """Подтверждение состава игроков и переход к раздаче ролей."""
    data = await state.get_data()
    booked = data.get("booked_players", [])

    real_players = []
    for p in booked:
        if p and p[3] not in [None, "Свободно", ""] and p[1] not in ["Свободно"]:
            real_players.append(p)

    if len(real_players) < 4:
        await callback.message.edit_text(
            "❌ **Недостаточно игроков!**\n\n"
            f"Заполнено слотов: {len(real_players)}/10\n"
            "Для игры нужно минимум 4 человека.\n\n"
            "Заполните слоты командой `<номер> <ник>`",
            reply_markup=keyboards.game_confirm_kb()
        )
        await callback.answer()
        return

    random.shuffle(real_players)
    slots = {}
    for i, (user_id, full_name, username, nickname, status) in enumerate(real_players, 1):
        slots[i] = create_empty_slot(nickname)
        slots[i].update({"user_id": user_id, "full_name": full_name, "username": username, "status": status})

    await state.update_data(slots=slots, booked_players=None)
    await save_slots(state, slots)
    await state.update_data(selected_mafia=[])
    await state.set_state(GameCreateState.choosing_mafia)

    await show_players_for_role_selection(callback.message, state, "mafia", 2)
    await callback.answer()


@router.callback_query(F.data == "game_confirm_no")
async def reshuffle_players(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    booked = data.get("booked_players", [])

    if booked:
        random.shuffle(booked)
        await state.update_data(booked_players=booked)

    await show_players_list_for_game(callback.message, state, booked)
    await callback.answer("🔀 Игроки перемешаны!")


@router.callback_query(F.data == "game_confirm_edit")
async def edit_players_list(callback: types.CallbackQuery, state: FSMContext):
    await show_current_players_list(callback.message, state)
    await state.set_state(GameCreateState.editing_players_list)
    await callback.answer()


@router.callback_query(F.data == "edit_players_done")
async def edit_players_done(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    booked = data.get("booked_players", [])

    try:
        await callback.message.delete()
    except Exception:
        pass

    await show_players_list_for_game(callback.message, state, booked)
    await state.set_state(GameCreateState.editing_slots)
    await callback.answer()


@router.message(GameCreateState.editing_players_list, F.text.regexp(r"^\d+\s+"))
async def edit_player_by_number(message: types.Message, state: FSMContext):
    if not await ensure_admin_pm(message):
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❌ Формат: `<номер> <ник>`\nПример: `7 Вепрь`")
        return

    try:
        slot_num = int(parts[0])
    except ValueError:
        await message.answer("❌ Номер должен быть числом.")
        return

    if slot_num < 1 or slot_num > 10:
        await message.answer("❌ Номер слота от 1 до 10.")
        return

    new_nick = parts[1].strip()
    if not new_nick:
        await message.answer("❌ Ник не может быть пустым.")
        return

    data = await state.get_data()
    booked = data.get("booked_players", [])

    user_data = await database.get_user_by_nickname(new_nick)

    while len(booked) < slot_num:
        booked.append((-(len(booked) + 1), "Свободно", None, "Свободно", "Пусто"))

    old_name = booked[slot_num - 1][3] or booked[slot_num - 1][1]

    if user_data:
        user_id, full_name, username, nickname = user_data
        booked[slot_num - 1] = (user_id, full_name, username, nickname, "Добавлен вручную")
        await state.update_data(booked_players=booked)
        await message.answer(f"✅ Слот {slot_num}: {old_name} → {nickname} (найден в БД)")
    else:
        booked[slot_num - 1] = (-slot_num, new_nick, None, new_nick, "Добавлен вручную")
        await state.update_data(booked_players=booked)
        await message.answer(f"⚠️ Слот {slot_num}: {old_name} → {new_nick} (не найден в БД, статистика не сохранится)")

    await show_current_players_list(message, state)


@router.message(GameCreateState.editing_players_list, F.text.regexp(r"^очистить\s+\d+"))
async def clear_player_by_number(message: types.Message, state: FSMContext):
    if not await ensure_admin_pm(message):
        return

    try:
        slot_num = int(message.text.replace("очистить", "").strip())
    except ValueError:
        await message.answer("❌ Формат: `очистить <номер>`\nПример: `очистить 7`")
        return

    if slot_num < 1 or slot_num > 10:
        await message.answer("❌ Номер слота от 1 до 10.")
        return

    data = await state.get_data()
    booked = data.get("booked_players", [])

    if slot_num <= len(booked):
        booked[slot_num - 1] = (-slot_num, "Свободно", None, "Свободно", "Пусто")
        await state.update_data(booked_players=booked)
        await message.answer(f"✅ Слот {slot_num} очищен")
    else:
        await message.answer(f"❌ Слот {slot_num} уже пуст")

    await show_current_players_list(message, state)


# ========== 2. РАЗДАЧА РОЛЕЙ ==========
async def show_players_for_role_selection(message: types.Message, state: FSMContext, role_key: str, count: int):
    data = await state.get_data()
    slots = data.get("slots") or {}

    available = []
    for slot_num, info in slots.items():
        if info.get("alive", True) and info.get("role") == "Не задана":
            name = info.get("nickname") or info.get("full_name") or f"Слот {slot_num}"
            available.append((slot_num, name))

    if len(available) < count:
        await message.answer(f"❌ Недостаточно свободных игроков для выбора {count} {role_key}.")
        return

    role_names = {"mafia": "мафий", "don": "дона", "sheriff": "шерифа"}
    role_name = role_names.get(role_key, role_key)

    text = f"🎭 **Выберите {count} {role_name}**\n\n"
    for slot_num, name in available:
        text += f"• Слот {slot_num}: {name}\n"
    text += f"\nНажмите на игрока, чтобы выбрать."

    await message.answer(text, reply_markup=keyboards.players_selection_kb(available, role_key, count), parse_mode="Markdown")


@router.callback_query(F.data.startswith("select_mafia_"))
async def select_mafia_callback(callback: types.CallbackQuery, state: FSMContext):
    slot_num = int(callback.data.split("_")[2])

    data = await state.get_data()
    selected = data.get("selected_mafia", [])

    if slot_num in selected:
        selected.remove(slot_num)
    else:
        if len(selected) >= 2:
            await callback.answer("Уже выбрано 2 мафии!", show_alert=True)
            return
        selected.append(slot_num)

    await state.update_data(selected_mafia=selected)

    slots = data.get("slots") or {}
    available = []
    for s_num, info in slots.items():
        if info.get("alive", True) and info.get("role") == "Не задана":
            name = info.get("nickname") or info.get("full_name") or f"Слот {s_num}"
            available.append((s_num, name))

    await callback.message.edit_reply_markup(reply_markup=keyboards.players_selection_kb(available, "mafia", 2, selected))

    if len(selected) == 2:
        slots = data.get("slots") or {}
        for m in selected:
            if m in slots:
                slots[m]["role"] = "Мафия"
                slots[m]["team"] = "Чёрные"
        await state.update_data(slots=slots, selected_mafia=None)
        await state.set_state(GameCreateState.choosing_don)
        await show_players_for_role_selection(callback.message, state, "don", 1)

    await callback.answer()


@router.callback_query(F.data.startswith("select_don_"))
async def select_don_callback(callback: types.CallbackQuery, state: FSMContext):
    slot_num = int(callback.data.split("_")[2])

    data = await state.get_data()
    slots = data.get("slots") or {}

    if slot_num in slots:
        slots[slot_num]["role"] = "Дон"
        slots[slot_num]["team"] = "Чёрные"

    await state.update_data(slots=slots)
    await save_slots(state, slots)
    await state.set_state(GameCreateState.choosing_sheriff)
    await show_players_for_role_selection(callback.message, state, "sheriff", 1)
    await callback.answer(f"✅ Дон назначен на слот {slot_num}")


@router.callback_query(F.data.startswith("select_sheriff_"))
async def select_sheriff_callback(callback: types.CallbackQuery, state: FSMContext):
    slot_num = int(callback.data.split("_")[2])

    data = await state.get_data()
    slots = data.get("slots") or {}

    if slot_num in slots:
        slots[slot_num]["role"] = "Шериф"
        slots[slot_num]["team"] = "Красные"

    for s_num, info in slots.items():
        if info.get("role") == "Не задана" and info.get("alive", True):
            info["role"] = "Мирный"
            info["team"] = "Красные"

    await state.update_data(slots=slots, roles_assigned=True)
    await save_slots(state, slots)

    game_date = datetime.now().strftime("%d.%m.%Y")
    await database.set_current_game_date(game_date)

    evening_games = await database.get_games_by_date(game_date)
    evening_num = len(evening_games) + 1
    await database.set_current_game_number(evening_num)

    total_games = await database.get_total_games_count()
    global_num = total_games + 1
    await database.set_current_global_game_number(global_num)

    await database.set_setting("game_active", "1")

    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(
        f"✅ **Игра создана!**\n\n"
        f"🎲 Игра №{evening_num} ({game_date}): №{global_num} по общей истории\n\n"
        f"{build_slots_text(slots)}",
        reply_markup=keyboards.game_admin_menu(),
        parse_mode="Markdown"
    )

    await state.set_state(GameCreateState.editing_slots)
    await callback.answer("✅ Игра готова к старту!")


# ========== 4. ПРОДОЛЖИТЬ ИГРУ ==========
@router.message(F.text == "♻️ Продолжить игру")
async def resume_game(message: types.Message, state: FSMContext):
    if not await ensure_admin_pm(message):
        return

    if await database.get_setting("game_active") != "1":
        await message.answer("Нет активной сохранённой игры.", reply_markup=keyboards.admin_menu())
        return

    slots = await database.load_current_game_slots()
    metadata = await database.load_current_game_metadata()

    if not slots:
        await message.answer("Не удалось найти сохранённые слоты.", reply_markup=keyboards.admin_menu())
        return

    await state.set_state(GameCreateState.editing_slots)
    await state.update_data(
        slots=slots,
        roles_assigned=metadata.get("roles_assigned", False),
        nominated_list=[],
        vote_index=0,
        split_candidates=[],
        in_split=False,
        first_night_kill_recorded=metadata.get("first_night_kill_recorded", False),
        night_kills_order=metadata.get("night_kills_order", []),
        night_killed_slot=None,
        winner_label=metadata.get("winner_label"),
        winning_team=metadata.get("winning_team"),
        protocol_chat_id=None,
        protocol_message_id=None
    )

    await message.answer(f"Продолжаем незавершённую игру.\n\n{build_game_state(slots, alive_only=False)}",
                         reply_markup=keyboards.game_admin_menu())


# ========== 5. ПОКАЗ СОСТОЯНИЯ ==========
@router.message(GameCreateState.editing_slots, F.text == "⏹ Остановить")
async def ask_game_finish_reason(message: types.Message, state: FSMContext):
    if await ensure_admin_pm(message):
        await message.answer("⚠️ **Остановка игры**\n\nВыберите результат:", reply_markup=keyboards.game_finish_keyboard())


@router.message(GameCreateState.editing_slots, F.text.casefold() == "игра")
async def show_game_state_all_handler(message: types.Message, state: FSMContext):
    if await ensure_admin_pm(message):
        await show_game_state_all(message, state)


@router.message(GameCreateState.editing_slots, F.text.casefold() == "игра живые")
async def show_game_state_alive(message: types.Message, state: FSMContext):
    if await ensure_admin_pm(message):
        slots = await get_slots(message, state)
        if slots:
            await message.answer(build_game_state(slots, alive_only=True), reply_markup=keyboards.game_admin_menu())


@router.message(GameCreateState.editing_slots, F.text.casefold() == "ок")
async def ok_show_state(message: types.Message, state: FSMContext):
    if await ensure_admin_pm(message):
        await show_game_state_all(message, state)


# ========== 6. ЗАВЕРШЕНИЕ ИГРЫ И РЕДАКТОР БАЛЛОВ ==========
@router.callback_query(F.data.startswith("game_end:"))
async def handle_game_finish(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    data = await state.get_data()
    slots = data.get("slots") or {}
    action = callback.data.split(":", 1)[1]

    if action == "cancel":
        await clear_game_state(state)
        await callback.message.edit_text("❌ **Игра отменена**\n\nИгра полностью удалена без сохранения.")
        await callback.message.answer("🛠 Админ-панель", reply_markup=keyboards.admin_menu())
        await callback.answer()
        return

    if action == "city":
        winning_team = "Красные"
        winner_label = "Победа города"
    elif action == "mafia":
        winning_team = "Чёрные"
        winner_label = "Победа мафии"
    else:
        await callback.answer("Неизвестное действие", show_alert=True)
        return

    await state.update_data(winning_team=winning_team, winner_label=winner_label)

    for slot in slots.values():
        slot["base_points"] = 1 if slot.get("team") == winning_team else 0

    await save_slots(state, slots)
    await state.set_state(GameCreateState.score_editor_select_player)

    await callback.message.edit_text(
        f"🏆 **Победитель: {winner_label}**\n\n"
        f"🎲 **Редактор баллов**\n\n"
        f"Выберите игрока для редактирования Доп, ПР или МН:\n\n"
        f"🔴 Красные — победа (+1 очко за игру)\n"
        f"⚫ Чёрные — поражение (0 очков за игру)",
        reply_markup=keyboards.score_editor_player_kb(slots, winning_team)
    )
    await callback.answer()


@router.callback_query(GameCreateState.score_editor_select_player, F.data.startswith("score_edit_"))
async def score_editor_select_player(callback: types.CallbackQuery, state: FSMContext):
    slot_num = int(callback.data.split("_")[2])

    data = await state.get_data()
    slots = data.get("slots") or {}

    if slot_num not in slots:
        await callback.answer("Игрок не найден!", show_alert=True)
        return

    slot_data = slots[slot_num]
    name = slot_data.get("nickname") or slot_data.get("full_name") or f"Слот {slot_num}"
    role = slot_data.get("role", "Не задана")
    team = slot_data.get("team", "")
    team_icon = "🔴" if team == "Красные" else "⚫" if team == "Чёрные" else "⚪"

    await state.update_data(score_edit_slot=slot_num)
    await state.set_state(GameCreateState.score_editor_select_type)

    protocol_text = slot_data.get("will_protocol_raw", "")
    opinion_text = slot_data.get("will_opinion", "")

    info_text = (
        f"{team_icon} **Слот {slot_num} - {name}**\n"
        f"Роль: {role}\n\n"
        f"📊 **Текущие баллы:**\n"
        f"  • Игра: {slot_data.get('base_points', 0):+.1f}\n"
        f"  • Доп: {slot_data.get('bonus_points', 0):+.1f}\n"
        f"  • ПР: {slot_data.get('will_protocol_points', 0):+.1f}\n"
        f"  • МН: {slot_data.get('will_opinion_points', 0):+.1f}\n"
        f"  • ЛХ: {slot_data.get('lh_points', 0):+.1f}\n\n"
    )

    if protocol_text:
        info_text += f"📋 **Протокол:** {protocol_text[:100]}...\n\n"
    if opinion_text:
        info_text += f"💬 **Мнение:** {opinion_text[:100]}...\n\n"

    info_text += "Выберите тип баллов для изменения:"

    await callback.message.edit_text(info_text, reply_markup=keyboards.score_type_kb(slot_num, slot_data))
    await callback.answer()


@router.callback_query(GameCreateState.score_editor_select_type, F.data.startswith("score_type_"))
async def score_editor_select_type(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    score_type = parts[2]
    slot_num = int(parts[3])

    data = await state.get_data()
    slots = data.get("slots") or {}

    if slot_num not in slots:
        await callback.answer("Игрок не найден!", show_alert=True)
        return

    current_value = 0.0
    if score_type == "bonus":
        current_value = slots[slot_num].get("bonus_points", 0)
    elif score_type == "protocol":
        current_value = slots[slot_num].get("will_protocol_points", 0)
    elif score_type == "opinion":
        current_value = slots[slot_num].get("will_opinion_points", 0)

    await state.update_data(score_edit_type=score_type, score_edit_slot=slot_num, score_old_value=current_value)
    await state.set_state(GameCreateState.score_editor_select_value)

    type_names = {"bonus": "Доп", "protocol": "ПР", "opinion": "МН"}
    type_name = type_names.get(score_type, score_type)

    await callback.message.edit_text(
        f"📊 **Редактирование {type_name}**\n\n"
        f"Текущее значение: {current_value:+.1f}\n\n"
        f"Выберите новое значение:",
        reply_markup=keyboards.score_value_kb(current_value)
    )
    await callback.answer()


@router.callback_query(GameCreateState.score_editor_select_value, F.data.startswith("score_val_"))
async def score_editor_set_value(callback: types.CallbackQuery, state: FSMContext):
    value = float(callback.data.split("_")[2])

    data = await state.get_data()
    slot_num = data.get("score_edit_slot")
    score_type = data.get("score_edit_type")
    old_value = data.get("score_old_value", 0)
    slots = data.get("slots") or {}

    if slot_num not in slots:
        await callback.answer("Игрок не найден!", show_alert=True)
        return

    if score_type == "bonus":
        slots[slot_num]["bonus_points"] = value
    elif score_type == "protocol":
        slots[slot_num]["will_protocol_points"] = value
    elif score_type == "opinion":
        slots[slot_num]["will_opinion_points"] = value

    await save_slots(state, slots)

    type_names = {"bonus": "Доп", "protocol": "ПР", "opinion": "МН"}
    type_name = type_names.get(score_type, score_type)

    await callback.answer(f"✅ {type_name} изменён: {old_value:+.1f} → {value:+.1f}")

    await state.set_state(GameCreateState.score_editor_select_type)
    slot_data = slots.get(slot_num, {})

    await callback.message.edit_text(
        f"📊 **Редактирование баллов слота {slot_num}**\n\n"
        f"✅ {type_name} установлен: {value:+.1f}\n\n"
        f"Выберите тип баллов для дальнейшего редактирования:",
        reply_markup=keyboards.score_type_kb(slot_num, slot_data)
    )


@router.callback_query(F.data == "score_back_to_players")
async def score_back_to_players(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    slots = data.get("slots") or {}
    winning_team = data.get("winning_team")

    await state.set_state(GameCreateState.score_editor_select_player)

    await callback.message.edit_text(
        f"🏆 **Редактор баллов**\n\n"
        f"Выберите игрока для редактирования Доп, ПР или МН:",
        reply_markup=keyboards.score_editor_player_kb(slots, winning_team)
    )
    await callback.answer()


@router.callback_query(F.data == "score_back_to_types")
async def score_back_to_types(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    slot_num = data.get("score_edit_slot")
    slots = data.get("slots") or {}

    if slot_num not in slots:
        await callback.answer("Игрок не найден!", show_alert=True)
        return

    await state.set_state(GameCreateState.score_editor_select_type)
    slot_data = slots.get(slot_num, {})

    await callback.message.edit_text(
        f"📊 **Редактирование баллов слота {slot_num}**\n\n"
        f"Выберите тип баллов для изменения:",
        reply_markup=keyboards.score_type_kb(slot_num, slot_data)
    )
    await callback.answer()


@router.callback_query(F.data == "score_back_to_values")
async def score_back_to_values(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    old_value = data.get("score_old_value", 0)

    await state.set_state(GameCreateState.score_editor_select_value)

    await callback.message.edit_text(
        f"📊 **Выбор значения**\n\n"
        f"Текущее значение: {old_value:+.1f}\n\n"
        f"Выберите новое значение:",
        reply_markup=keyboards.score_value_kb(old_value)
    )
    await callback.answer()


@router.callback_query(F.data == "score_finish")
async def score_finish(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    slots = data.get("slots") or {}
    winning_team = data.get("winning_team")
    winner_label = data.get("winner_label")

    for slot in slots.values():
        if not slot.get("pu_mark") or slot.get("team") != "Красные":
            slot["lh_points"] = float(slot.get("lh_points") or 0.0)
            continue
        suspects = slot.get("night_suspects") or []
        correct = sum(1 for n in suspects if slots.get(n, {}).get("team") == "Чёрные")
        slot["lh_points"] = [0.0, 0.1, 0.3, 0.6][correct] if correct <= 3 else 0.0

    await database.apply_game_result_to_users(slots, winning_team)

    game_date = await database.get_current_game_date() or "-"
    evening_num = await database.get_current_game_number() or 1
    global_num = await database.get_current_global_game_number() or 1

    protocol_body = build_protocol_text(slots, updated=False, winner_label=winner_label)
    await database.save_game_history(game_date, winner_label, protocol_body, evening_num, global_num)
    await database.save_game_slots_history(game_date, slots)

    try:
        await callback.message.delete()
    except Exception:
        pass

    header = f"📑 Протокол игры №{evening_num} ({game_date}): №{global_num} по общей истории — {winner_label}"
    full_protocol = f"{header}\n\n{protocol_body}"

    await callback.message.answer(full_protocol, reply_markup=keyboards.game_admin_menu(), parse_mode=ParseMode.HTML)

    await state.update_data(slots=slots, protocol_chat_id=None, protocol_message_id=None, winner_label=winner_label)
    await save_slots(state, slots)
    await state.set_state(GameCreateState.editing_slots)

    await callback.answer("✅ Игра сохранена! Нажмите «Завершить игру» для графического протокола.")


@router.callback_query(F.data == "score_cancel")
async def score_cancel(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    slots = data.get("slots") or {}

    await state.set_state(GameCreateState.editing_slots)

    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(
        build_game_state(slots, alive_only=False),
        reply_markup=keyboards.game_admin_menu()
    )
    await callback.answer("Редактирование отменено")


@router.message(F.text == "🏁 Завершить")
async def final_finish_game(message: types.Message, state: FSMContext):
    if not await ensure_admin_pm(message):
        return

    active = await database.get_setting("game_active")
    if active != "1":
        await message.answer("Сейчас нет активной игры.", reply_markup=keyboards.admin_menu())
        return

    data = await state.get_data()
    slots = data.get("slots") or await database.load_current_game_slots()

    if not slots:
        await message.answer("Нет данных об игре.", reply_markup=keyboards.admin_menu())
        await clear_game_state(state)
        return

    game_date = await database.get_current_game_date() or "-"
    evening_num = await database.get_current_game_number() or 1
    global_num = await database.get_current_global_game_number() or 1
    winner_label = data.get("winner_label")

    if winner_label and winner_label != "Игра отменена":
        img_path = create_endgame_pic_summary(slots, game_date, evening_num, global_num, winner_label)
        photo = FSInputFile(img_path)
        await message.answer_photo(photo, caption="Итоговый графический протокол игры 📸")

    await clear_game_state(state)
    await message.answer("✅ Игра полностью завершена. Можно запускать новую.", reply_markup=keyboards.admin_menu())


# ========== 7. РЕЖИМ РЕДАКТИРОВАНИЯ ==========
@router.message(GameCreateState.editing_slots, F.text == "✏️ Редактировать")
async def enter_edit_mode(message: types.Message, state: FSMContext):
    if not await ensure_admin_pm(message):
        return

    data = await state.get_data()
    slots = data.get("slots") or {}

    slots = {int(k): v for k, v in slots.items()}

    if not slots:
        await message.answer("Нет активной игры для редактирования.", reply_markup=keyboards.game_admin_menu())
        return

    await state.set_state(GameCreateState.edit_mode_select_slot)
    await message.answer(
        "✏️ **Режим редактирования игры**\n\nВыберите слот для редактирования:",
        reply_markup=get_slot_selection_keyboard(slots)
    )


# ========== 8. УПРАВЛЕНИЕ ФОЛАМИ ==========
@router.message(GameCreateState.editing_slots, F.text == "Фол")
async def foul_start(message: types.Message, state: FSMContext):
    if not await ensure_admin_pm(message):
        return

    slots = await get_slots(message, state)
    if not slots:
        return

    alive_slots = {k: v for k, v in slots.items() if v.get("alive", True)}

    if not alive_slots:
        await message.answer("❌ Нет живых игроков для начисления фолов.", reply_markup=keyboards.game_admin_menu())
        return

    await state.set_state(GameCreateState.foul_select)
    await message.answer("⚠️ **Управление фолами**\n\nВыберите игрока:", reply_markup=keyboards.foul_select_kb(alive_slots))


@router.callback_query(GameCreateState.foul_select, F.data.startswith("foul_select_"))
async def foul_select_player(callback: types.CallbackQuery, state: FSMContext):
    slot_num = int(callback.data.split("_")[2])

    data = await state.get_data()
    slots = data.get("slots") or {}

    if slot_num not in slots:
        await callback.answer("Игрок не найден!", show_alert=True)
        return

    current_fouls = slots[slot_num].get("fouls", 0)
    name = slots[slot_num].get("nickname") or slots[slot_num].get("full_name") or f"Слот {slot_num}"

    await state.update_data(foul_slot=slot_num)
    await state.set_state(GameCreateState.foul_action)

    await callback.message.edit_text(
        f"⚠️ **Фолы игрока {slot_num} - {name}**\n\n"
        f"Текущее количество фолов: {current_fouls}\n\n"
        f"Выберите действие:",
        reply_markup=keyboards.foul_action_kb(slot_num, current_fouls)
    )
    await callback.answer()


@router.callback_query(GameCreateState.foul_action, F.data.startswith("foul_add_"))
async def foul_add(callback: types.CallbackQuery, state: FSMContext):
    slot_num = int(callback.data.split("_")[2])

    data = await state.get_data()
    slots = data.get("slots") or {}

    if slot_num not in slots:
        await callback.answer("Игрок не найден!", show_alert=True)
        return

    slots[slot_num]["fouls"] = slots[slot_num].get("fouls", 0) + 1
    await save_slots(state, slots)

    await callback.answer(f"✅ Фол добавлен игроку {slot_num}")

    alive_slots = {k: v for k, v in slots.items() if v.get("alive", True)}
    await callback.message.edit_text("⚠️ **Управление фолами**\n\nВыберите игрока:", reply_markup=keyboards.foul_select_kb(alive_slots))
    await state.set_state(GameCreateState.foul_select)


@router.callback_query(GameCreateState.foul_action, F.data.startswith("foul_remove_"))
async def foul_remove(callback: types.CallbackQuery, state: FSMContext):
    slot_num = int(callback.data.split("_")[2])

    data = await state.get_data()
    slots = data.get("slots") or {}

    if slot_num not in slots:
        await callback.answer("Игрок не найден!", show_alert=True)
        return

    current = slots[slot_num].get("fouls", 0)
    if current > 0:
        slots[slot_num]["fouls"] = current - 1
        await save_slots(state, slots)
        await callback.answer(f"✅ Фол снят с игрока {slot_num}")
    else:
        await callback.answer("❌ У игрока нет фолов для снятия!", show_alert=True)

    alive_slots = {k: v for k, v in slots.items() if v.get("alive", True)}
    await callback.message.edit_text("⚠️ **Управление фолами**\n\nВыберите игрока:", reply_markup=keyboards.foul_select_kb(alive_slots))
    await state.set_state(GameCreateState.foul_select)


@router.callback_query(F.data == "foul_cancel")
async def foul_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(GameCreateState.editing_slots)

    data = await state.get_data()
    slots = data.get("slots") or {}

    await callback.message.delete()
    await callback.message.answer(build_game_state(slots, alive_only=False), reply_markup=keyboards.game_admin_menu())
    await callback.answer()


# ========== 9. CATCH-ALL ==========
@router.message(GameCreateState.editing_slots)
async def catch_all_in_game(message: types.Message, state: FSMContext):
    if not await ensure_admin_pm(message):
        return
    slots = await get_slots(message, state)
    if slots:
        await message.answer(build_game_state(slots, alive_only=False), reply_markup=keyboards.game_admin_menu())