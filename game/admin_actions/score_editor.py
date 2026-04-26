"""
Редактор баллов после игры
"""
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery

import database
import keyboards
from game.state import GameCreateState
from game.text import build_protocol_text, build_game_state
from game.admin_actions.common import save_slots, clear_game_state, ensure_judge_cb

router = Router()


# ======================= НОВАЯ ЛОГИКА ЭЛО =======================

STARTING_ELO = 1500
K_FACTOR = 32
BONUS_TO_ELO_RATIO = 10  # 0.1 доп. балла = 1 очко Эло
MIN_TEAM_SIZE_FOR_CARRY = 2


def expected_score(player_elo: float, opponent_elo: float) -> float:
    """Ожидаемый результат по формуле Эло"""
    return 1 / (1 + 10 ** ((opponent_elo - player_elo) / 400))


def get_role_coefficient(team: str, is_win: bool) -> float:
    """Ролевой коэффициент"""
    if is_win:
        return 1.2 if team == "Красные" else 0.9
    else:
        return 0.9 if team == "Красные" else 1.1


def calculate_carry_modifier(player_elo: float, team_elos: list, is_win: bool) -> float:
    """Carry-модификатор"""
    if len(team_elos) < MIN_TEAM_SIZE_FOR_CARRY:
        return 1.0

    team_avg = sum(team_elos) / len(team_elos)
    diff = player_elo - team_avg
    normalized = min(1.0, max(-1.0, diff / 200))

    if is_win:
        if diff > 0:
            bonus = normalized * 0.3
            return 1 + bonus
        else:
            penalty = abs(normalized) * 0.2
            return 1 - penalty
    else:
        if diff > 0:
            penalty = normalized * 0.4
            return 1 - penalty
        else:
            relief = abs(normalized) * 0.2
            return 1 + relief


def calculate_bonus_elo_impact(slot: dict) -> float:
    """Рассчитывает влияние доп. баллов на Эло"""
    total_bonus = (
        slot.get("bonus_points", 0) +
        slot.get("lh_points", 0) +
        slot.get("will_protocol_points", 0) +
        slot.get("will_opinion_points", 0) +
        slot.get("dc_points", 0)
    )
    return total_bonus * BONUS_TO_ELO_RATIO


async def calculate_all_elo_changes(slots: dict, winning_team: str) -> dict:
    """
    Рассчитывает новое Эло для всех игроков в игре
    Возвращает словарь {slot_num: {"old_elo": int, "new_elo": int, "total_delta": int}}
    """
    # Собираем игроков с их текущим Эло
    players = []
    for slot_num, slot in slots.items():
        if slot.get("user_id") and slot.get("user_id") > 0:
            user_id = slot["user_id"]
            current_elo = await database.get_elo(user_id)
            players.append({
                "slot_num": slot_num,
                "user_id": user_id,
                "team": slot.get("team"),
                "current_elo": current_elo,
                "bonus_points": slot.get("bonus_points", 0),
                "lh_points": slot.get("lh_points", 0),
                "will_protocol_points": slot.get("will_protocol_points", 0),
                "will_opinion_points": slot.get("will_opinion_points", 0),
                "dc_points": slot.get("dc_points", 0),
            })

    if len(players) < 4:
        return {}

    # Разделяем по командам
    red_players = [p for p in players if p["team"] == "Красные"]
    black_players = [p for p in players if p["team"] == "Чёрные"]

    if not red_players or not black_players:
        return {}

    red_elos = [p["current_elo"] for p in red_players]
    black_elos = [p["current_elo"] for p in black_players]

    result = {}

    for player in players:
        is_win = (player["team"] == winning_team)
        old_elo = player["current_elo"]

        # Соперники
        opponent_elos = black_elos if player["team"] == "Красные" else red_elos
        opponent_avg = sum(opponent_elos) / len(opponent_elos)

        # Ожидаемый результат
        expected = expected_score(old_elo, opponent_avg)
        actual = 1.0 if is_win else 0.0

        # Базовая дельта
        raw_delta = K_FACTOR * (actual - expected)

        # Модификаторы
        role_mod = get_role_coefficient(player["team"], is_win)
        team_elos = red_elos if player["team"] == "Красные" else black_elos
        carry_mod = calculate_carry_modifier(old_elo, team_elos, is_win)

        # Игровая дельта
        game_delta = int(round(raw_delta * role_mod * carry_mod))

        # Бонусная дельта (доп. баллы)
        bonus_impact = calculate_bonus_elo_impact(player)
        bonus_delta = int(round(bonus_impact))

        # Общая дельта
        total_delta = game_delta + bonus_delta
        new_elo = old_elo + total_delta

        result[player["slot_num"]] = {
            "old_elo": old_elo,
            "new_elo": new_elo,
            "game_delta": game_delta,
            "bonus_delta": bonus_delta,
            "total_delta": total_delta,
            "is_win": is_win
        }

    return result


async def update_elo_after_game(slots: dict, winning_team: str):
    """
    Обновляет Эло всех игроков после завершения игры
    """
    print("[ELO] Начинаем расчёт Эло...")

    elo_changes = await calculate_all_elo_changes(slots, winning_team)

    for slot_num, change in elo_changes.items():
        user_id = slots[slot_num].get("user_id")
        if not user_id:
            continue

        await database.update_elo(user_id, change["total_delta"])
        await database.update_player_stats(user_id, slots[slot_num].get("team"), change["is_win"])
        await database.update_player_statuses(user_id)

        # Сохраняем изменение Эло и новое Эло в историю слота
        slots[slot_num]["elo_change"] = change["total_delta"]
        slots[slot_num]["new_elo"] = change["new_elo"]  # Правильное новое Эло

        print(f"[ELO] {slots[slot_num].get('nickname')}: {change['old_elo']} → {change['new_elo']} ({change['total_delta']:+d})")


# ========== ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ДЛЯ УСТАНОВКИ КОМАНДЫ ПО РОЛИ ==========
def _fix_team_by_role(slot: dict) -> None:
    """Принудительно устанавливает команду по роли, если team не задана."""
    if slot.get("team"):
        return

    role = slot.get("role", "")
    role_lower = role.lower()

    if "мирный" in role_lower or "шериф" in role_lower:
        slot["team"] = "Красные"
    elif "мафия" in role_lower or "дон" in role_lower:
        slot["team"] = "Чёрные"
    else:
        slot["team"] = None


def _fix_all_teams_by_role(slots: dict) -> None:
    """Применяет исправление команд для всех слотов."""
    for slot_num, slot in slots.items():
        old_team = slot.get("team")
        _fix_team_by_role(slot)
        if old_team != slot.get("team"):
            print(f"[DEBUG] Слот {slot_num}: команда изменена с '{old_team}' на '{slot.get('team')}' (роль: {slot.get('role')})")


def _debug_print_slots(slots: dict, title: str = "DEBUG") -> None:
    """Отладочный вывод всех слотов."""
    print(f"\n[DEBUG] {title}:")
    for slot_num in sorted([k for k in slots.keys() if isinstance(k, int)]):
        info = slots[slot_num]
        print(f"  Слот {slot_num}: роль={info.get('role')}, команда={info.get('team')}, имя={info.get('nickname')}")


# ========== ОСНОВНЫЕ ХЕНДЛЕРЫ ==========

@router.callback_query(F.data.startswith("game_end:"))
async def handle_game_finish(callback: CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
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
        await state.update_data(winning_team=winning_team, winner_label=winner_label)
        for slot in slots.values():
            slot["base_points"] = 1 if slot.get("team") == winning_team else 0
        await save_slots(state, slots)
        await state.set_state(GameCreateState.score_editor_select_player)
        await callback.message.edit_text(
            f"🏆 **Победитель: {winner_label}**\n\n🎲 **Редактор баллов**\n\nВыберите игрока для редактирования Доп, ПР или МН:\n\n🔴 Красные — победа (+1 очко за игру)\n⚫ Чёрные — поражение (0 очков за игру)",
            reply_markup=keyboards.score_editor_player_kb(slots, winning_team)
        )
        await callback.answer()
        return

    elif action == "mafia":
        winning_team = "Чёрные"
        winner_label = "Победа мафии"
        await state.update_data(winning_team=winning_team, winner_label=winner_label)
        for slot in slots.values():
            slot["base_points"] = 1 if slot.get("team") == winning_team else 0
        await save_slots(state, slots)
        await state.set_state(GameCreateState.score_editor_select_player)
        await callback.message.edit_text(
            f"🏆 **Победитель: {winner_label}**\n\n🎲 **Редактор баллов**\n\nВыберите игрока для редактирования Доп, ПР или МН:\n\n⚫ Чёрные — победа (+1 очко за игру)\n🔴 Красные — поражение (0 очков за игру)",
            reply_markup=keyboards.score_editor_player_kb(slots, winning_team)
        )
        await callback.answer()
        return

    elif action == "ppk":
        await state.set_state(GameCreateState.ppk_team_select)
        await callback.message.edit_text(
            "⚠️ **ППК (Победа Противоположной Команды)**\n\nКакая команда одержала победу?",
            reply_markup=keyboards.ppk_team_selection_kb()
        )
        await callback.answer()
        return


@router.callback_query(GameCreateState.score_editor_select_player, F.data.startswith("score_edit_"))
async def score_editor_select_player(callback: CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return
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
    info_text = f"{team_icon} **Слот {slot_num} - {name}**\nРоль: {role}\n\n📊 **Текущие баллы:**\n  • Игра: {slot_data.get('base_points', 0):+.1f}\n  • Доп: {slot_data.get('bonus_points', 0):+.1f}\n  • ПР: {slot_data.get('will_protocol_points', 0):+.1f}\n  • МН: {slot_data.get('will_opinion_points', 0):+.1f}\n  • ЛХ: {slot_data.get('lh_points', 0):+.1f}\n\n"
    if protocol_text:
        info_text += f"📋 **Протокол:** {protocol_text[:100]}...\n\n"
    if opinion_text:
        info_text += f"💬 **Мнение:** {opinion_text[:100]}...\n\n"
    info_text += "Выберите тип баллов для изменения:"
    await callback.message.edit_text(info_text, reply_markup=keyboards.score_type_kb(slot_num, slot_data))
    await callback.answer()


@router.callback_query(GameCreateState.score_editor_select_type, F.data.startswith("score_type_"))
async def score_editor_select_type(callback: CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return
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
        f"📊 **Редактирование {type_name}**\n\nТекущее значение: {current_value:+.1f}\n\nВыберите новое значение:",
        reply_markup=keyboards.score_value_kb(current_value)
    )
    await callback.answer()


@router.callback_query(GameCreateState.score_editor_select_value, F.data.startswith("score_val_"))
async def score_editor_set_value(callback: CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return
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
        f"📊 **Редактирование баллов слота {slot_num}**\n\n✅ {type_name} установлен: {value:+.1f}\n\nВыберите тип баллов для дальнейшего редактирования:",
        reply_markup=keyboards.score_type_kb(slot_num, slot_data)
    )


@router.callback_query(F.data == "score_back_to_players")
async def score_back_to_players(callback: CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return
    data = await state.get_data()
    slots = data.get("slots") or {}
    winning_team = data.get("winning_team")
    await state.set_state(GameCreateState.score_editor_select_player)
    await callback.message.edit_text(
        f"🏆 **Редактор баллов**\n\nВыберите игрока для редактирования Доп, ПР или МН:",
        reply_markup=keyboards.score_editor_player_kb(slots, winning_team)
    )
    await callback.answer()


@router.callback_query(F.data == "score_back_to_types")
async def score_back_to_types(callback: CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return
    data = await state.get_data()
    slot_num = data.get("score_edit_slot")
    slots = data.get("slots") or {}
    if slot_num not in slots:
        await callback.answer("Игрок не найден!", show_alert=True)
        return
    await state.set_state(GameCreateState.score_editor_select_type)
    slot_data = slots.get(slot_num, {})
    await callback.message.edit_text(
        f"📊 **Редактирование баллов слота {slot_num}**\n\nВыберите тип баллов для изменения:",
        reply_markup=keyboards.score_type_kb(slot_num, slot_data)
    )
    await callback.answer()


@router.callback_query(F.data == "score_back_to_values")
async def score_back_to_values(callback: CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return
    data = await state.get_data()
    old_value = data.get("score_old_value", 0)
    await state.set_state(GameCreateState.score_editor_select_value)
    await callback.message.edit_text(
        f"📊 **Выбор значения**\n\nТекущее значение: {old_value:+.1f}\n\nВыберите новое значение:",
        reply_markup=keyboards.score_value_kb(old_value)
    )
    await callback.answer()


@router.callback_query(F.data == "score_finish")
async def score_finish(callback: CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return

    data = await state.get_data()
    game_saved = data.get("game_saved", False)

    if game_saved:
        await callback.answer("⚠️ Игра уже сохранена! Не нажимайте дважды.", show_alert=True)
        return

    await state.update_data(game_saved=True)

    slots = data.get("slots") or {}
    winning_team = data.get("winning_team")
    winner_label = data.get("winner_label")

    _debug_print_slots(slots, "СЛОТЫ ДО ИСПРАВЛЕНИЯ")

    _fix_all_teams_by_role(slots)

    _debug_print_slots(slots, "СЛОТЫ ПОСЛЕ ИСПРАВЛЕНИЯ")

    # Расчёт ЛХ для ПУ
    for slot in slots.values():
        if not slot.get("pu_mark") or slot.get("team") != "Красные":
            slot["lh_points"] = float(slot.get("lh_points") or 0.0)
            continue
        suspects = slot.get("night_suspects") or []
        correct = sum(1 for n in suspects if slots.get(n, {}).get("team") == "Чёрные")
        slot["lh_points"] = [0.0, 0.1, 0.3, 0.6][correct] if correct <= 3 else 0.0

    # Сохраняем результаты в БД (без Эло пока)
    await database.apply_game_result_to_users(slots, winning_team)
    game_date = await database.get_current_game_date() or "-"
    evening_num = await database.get_current_game_number() or 1
    global_num = await database.get_current_global_game_number() or 1

    # ========== РАСЧЁТ ЭЛО (ДО сохранения истории, чтобы new_elo было в слотах) ==========
    await update_elo_after_game(slots, winning_team)
    # ====================================================================================

    # Сохраняем в историю (уже с elo_change и new_elo)
    protocol_body = await build_protocol_text(slots, updated=False, winner_label=winner_label)
    await database.save_game_history(game_date, winner_label, protocol_body, evening_num, global_num)
    await database.save_game_slots_history(game_date, slots, game_number=evening_num)

    night_kills_order = data.get("night_kills_order", [])
    if night_kills_order:
        await database.save_night_kills_order(game_date, evening_num, night_kills_order)

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
async def score_cancel(callback: CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return
    data = await state.get_data()
    slots = data.get("slots") or {}
    await state.update_data(game_saved=False)
    await state.set_state(GameCreateState.editing_slots)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(build_game_state(slots, alive_only=False), reply_markup=keyboards.game_admin_menu())
    await callback.answer("Редактирование отменено")