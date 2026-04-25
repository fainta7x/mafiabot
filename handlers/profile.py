import os
import time
import re
from typing import Dict, Any

from aiogram import Router, F, types
from aiogram.enums import ParseMode
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

import stats_utils
import database
from database import (
    get_last_games,
    get_user_games,
    get_game_by_id,
    get_game_slots_by_date,
    update_game_slot,
    update_game_outcome,
    get_night_kills_order,
    save_night_kills_order,
)
from keyboards import games_list_kb
from pic_profile import create_profile_pic
from game.utils.endgame_pic import create_endgame_pic_summary

router = Router()

TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
os.makedirs(TEMP_DIR, exist_ok=True)


# ======================= ВСПОМОГАТЕЛЬНОЕ =======================

def _cleanup_old_files(prefix: str, keep: int = 10):
    try:
        files = [
            os.path.join(TEMP_DIR, f)
            for f in os.listdir(TEMP_DIR)
            if f.startswith(prefix) and f.endswith(".png")
        ]
        files.sort(key=os.path.getmtime)
        for f in files[:-keep]:
            os.remove(f)
            print(f"[CLEANUP] Removed old file: {f}")
    except Exception as e:
        print(f"[CLEANUP] Error: {e}")


def _build_game_edit_kb(game_id: int, has_changes: bool = False) -> InlineKeyboardMarkup:
    buttons = []
    buttons.append([InlineKeyboardButton(text="👥 Редактировать игроков", callback_data=f"editgame_players:{game_id}")])
    buttons.append([InlineKeyboardButton(text="🏆 Редактировать исход", callback_data=f"editgame_outcome:{game_id}")])
    buttons.append([InlineKeyboardButton(text="📋 Показать актуальный протокол",
                                         callback_data=f"editgame_show_protocol:{game_id}")])

    if has_changes:
        buttons.append([InlineKeyboardButton(text="🔄 Сохранить и обновить протокол",
                                             callback_data=f"editgame_regenerate:{game_id}")])
        buttons.append([InlineKeyboardButton(text="❌ Отмена (есть изменения)",
                                             callback_data=f"editgame_cancel_confirm:{game_id}")])
    else:
        buttons.append([InlineKeyboardButton(text="❌ Закрыть", callback_data=f"editgame_close:{game_id}")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _build_players_edit_kb(game_id: int, slots: Dict[int, dict]) -> InlineKeyboardMarkup:
    buttons = []
    for slot_num in sorted(k for k in slots.keys() if isinstance(k, int)):
        info = slots[slot_num]
        nickname = info.get("nickname") or info.get("full_name") or f"Игрок {slot_num}"
        role = info.get("role") or "Не задана"
        team = info.get("team") or "Без команды"

        base = float(info.get("base_points") or 0)
        bonus = float(info.get("bonus_points") or 0)
        lh = float(info.get("lh_points") or 0)
        pr = float(info.get("will_protocol_points") or 0)
        op = float(info.get("will_opinion_points") or 0)
        dc = float(info.get("dc_points") or 0)
        total = base + bonus + lh + pr + op + dc

        alive = info.get("alive", True)
        status_icon = "✅" if alive else "💀"
        text = f"{status_icon} {slot_num}. {nickname} [{role}] — {team} — {total:+.1f}"
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"editgame_slot:{game_id}:{slot_num}")])

    buttons.append([InlineKeyboardButton(text="⬅️ Назад к меню", callback_data=f"editgame_back:{game_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _build_slot_menu_kb(game_id: int, slot_num: int) -> InlineKeyboardMarkup:
    """Меню редактирования одного слота."""
    kb = [
        [
            InlineKeyboardButton(text="🎭 Роль", callback_data=f"editgame_field:role:{game_id}:{slot_num}"),
            InlineKeyboardButton(text="🏳 Команда", callback_data=f"editgame_field:team:{game_id}:{slot_num}"),
        ],
        [
            InlineKeyboardButton(text="📊 Статус", callback_data=f"editgame_field:status:{game_id}:{slot_num}"),
            InlineKeyboardButton(text="🎲 Очки", callback_data=f"editgame_field:points:{game_id}:{slot_num}"),
        ],
        [
            InlineKeyboardButton(text="📋 ПР (баллы)", callback_data=f"editgame_field:protocol:{game_id}:{slot_num}"),
            InlineKeyboardButton(text="📋 ПР (текст)", callback_data=f"editgame_field:protocol_text:{game_id}:{slot_num}"),
        ],
        [
            InlineKeyboardButton(text="💬 МН (баллы)", callback_data=f"editgame_field:opinion:{game_id}:{slot_num}"),
            InlineKeyboardButton(text="💬 МН (текст)", callback_data=f"editgame_field:opinion_text:{game_id}:{slot_num}"),
        ],
        [
            InlineKeyboardButton(text="👑 ПУ (вкл/выкл)", callback_data=f"editgame_field:pu:{game_id}:{slot_num}"),
            InlineKeyboardButton(text="⚠️ Фолы/Техфолы", callback_data=f"editgame_field:fouls:{game_id}:{slot_num}"),
        ],
        [
            InlineKeyboardButton(text="◀️ Назад к списку", callback_data=f"editgame_players:{game_id}"),
            InlineKeyboardButton(text="📋 Показать протокол", callback_data=f"editgame_show_protocol:{game_id}"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _build_outcome_kb(game_id: int, current_winner: str) -> InlineKeyboardMarkup:
    winner_lower = current_winner.lower() if current_winner else ""
    buttons = []

    check = "✅ " if "город" in winner_lower else ""
    buttons.append(
        [InlineKeyboardButton(text=f"{check}🏙 Победа города", callback_data=f"editgame_set_outcome:{game_id}:city")])

    check = "✅ " if "мафи" in winner_lower else ""
    buttons.append(
        [InlineKeyboardButton(text=f"{check}💀 Победа мафии", callback_data=f"editgame_set_outcome:{game_id}:mafia")])

    check = "✅ " if "ппк" in winner_lower else ""
    buttons.append([InlineKeyboardButton(text=f"{check}⚠️ ППК", callback_data=f"editgame_set_outcome:{game_id}:ppk")])

    buttons.append([InlineKeyboardButton(text="◀️ Назад к меню", callback_data=f"editgame_back:{game_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _build_status_kb(game_id: int, slot_num: int, current_status: dict) -> InlineKeyboardMarkup:
    alive = current_status.get("alive", True)
    status_reason = current_status.get("status_reason", "Жив")
    buttons = []

    check = "✅ " if alive and status_reason == "Жив" else ""
    buttons.append(
        [InlineKeyboardButton(text=f"{check}✅ Жив", callback_data=f"editgame_set_status:{game_id}:{slot_num}:alive")])

    check = "✅ " if not alive and "Убит" in status_reason and "ППК" not in status_reason else ""
    buttons.append([InlineKeyboardButton(text=f"{check}💀 Убит ночью",
                                         callback_data=f"editgame_set_status:{game_id}:{slot_num}:killed")])

    check = "✅ " if not alive and "Заголосован" in status_reason else ""
    buttons.append([InlineKeyboardButton(text=f"{check}⚖️ Заголосован",
                                         callback_data=f"editgame_set_status:{game_id}:{slot_num}:voted")])

    check = "✅ " if not alive and "Удалён ведущим" in status_reason else ""
    buttons.append([InlineKeyboardButton(text=f"{check}🚫 Удалён ведущим",
                                         callback_data=f"editgame_set_status:{game_id}:{slot_num}:kicked")])

    check = "✅ " if not alive and "ППК" in status_reason else ""
    buttons.append([InlineKeyboardButton(text=f"{check}⚠️ Удалён (ППК)",
                                         callback_data=f"editgame_set_status:{game_id}:{slot_num}:ppk")])

    check = "✅ " if not alive and "4 фола" in status_reason else ""
    buttons.append([InlineKeyboardButton(text=f"{check}🚷 Удалён (4 фола)",
                                         callback_data=f"editgame_set_status:{game_id}:{slot_num}:fouls")])

    check = "✅ " if not alive and "2 техфол" in status_reason else ""
    buttons.append([InlineKeyboardButton(text=f"{check}🔧 Удалён (2 техфола)",
                                         callback_data=f"editgame_set_status:{game_id}:{slot_num}:tech")])

    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"editgame_slot:{game_id}:{slot_num}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _build_cancel_confirm_kb(game_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="⚠️ Да, отменить все изменения", callback_data=f"editgame_cancel_yes:{game_id}")],
        [InlineKeyboardButton(text="❌ Нет, продолжить редактирование", callback_data=f"editgame_back:{game_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ======================= FSM ДЛЯ ВВОДА ЗНАЧЕНИЙ =======================

class EditGameState(StatesGroup):
    waiting_for_value = State()


# ======================= Профиль / списки игр =======================

@router.message(F.text == "📊 Статистика")
async def show_user_stats(message: types.Message):
    user_id = message.from_user.id
    try:
        stats_data = await stats_utils.build_user_stats_data(user_id)
        nickname = stats_data.get("nickname") or message.from_user.full_name
        img_path = create_profile_pic(nickname, stats_data)
        text = await stats_utils.build_user_stats_text(user_id)
        doc = FSInputFile(img_path)
        timestamp = int(time.time())
        await message.answer_document(document=doc, caption=f"{text}\n\n🕐 Обновлено: {timestamp}",
                                      parse_mode=ParseMode.MARKDOWN)
        _cleanup_old_files("profile_", keep=10)
    except Exception as e:
        print(f"[PROFILE][ERROR] {e}")
        text = await stats_utils.build_user_stats_text(user_id)
        await message.answer(text)


@router.message(F.text == "📜 Все игры")
async def show_all_games(message: types.Message):
    games = await get_last_games(limit=10)
    if not games:
        await message.answer("Пока нет завершённых игр.")
        return
    buttons_data = []
    for g in games:
        game_id = g["id"]
        date_str = g.get("game_date") or ""
        game_number = g.get("game_number")
        global_game_number = g.get("global_game_number")
        title = f"Игра №{game_number}" if game_number else "Игра"
        if date_str:
            title += f" ({date_str})"
        if global_game_number:
            title += f" — №{global_game_number} по истории"
        buttons_data.append((game_id, title, game_number or 0))
    kb = games_list_kb(buttons_data, prefix="allgames")
    await message.answer("Выбери игру:", reply_markup=kb)


@router.message(F.text == "📜 Мои игры")
async def show_my_games(message: types.Message):
    user_id = message.from_user.id
    games = await get_user_games(user_id=user_id, limit=10)
    if not games:
        await message.answer("Пока нет игр с твоим участием.")
        return
    buttons_data = []
    for g in games:
        game_id = g["id"]
        date_str = g.get("game_date") or ""
        game_number = g.get("game_number")
        global_game_number = g.get("global_game_number")
        title = f"Игра №{game_number}" if game_number else "Игра"
        if date_str:
            title += f" ({date_str})"
        if global_game_number:
            title += f" — №{global_game_number} по истории"
        buttons_data.append((game_id, title, game_number or 0))
    kb = games_list_kb(buttons_data, prefix="mygames")
    await message.answer("Выбери игру:", reply_markup=kb)


# ======================= ПРОТОКОЛ ИГРЫ + КАРТИНКА =======================

async def _send_protocol(message_or_callback, game_id: int, winner_label: str = None):
    game = await get_game_by_id(game_id)
    if not game:
        return False, "Игра не найдена."

    date_str = game.get("game_date") or "-"
    winner_label = winner_label or game.get("winner_label") or "Результат не указан"
    protocol = (game.get("protocol_text") or "").strip()
    game_number = game.get("game_number")
    global_game_number = game.get("global_game_number") or 0

    lines = protocol.splitlines()
    if lines and lines[0].startswith("📑 Протокол"):
        lines = lines[1:]
    protocol_body = "\n".join(lines).lstrip()

    header = f"📑 Протокол игры №{game_number} ({date_str}): {winner_label}"
    if global_game_number:
        header += f" — №{global_game_number} по общей истории"

    text = header
    if protocol_body:
        text += f"\n\n{protocol_body}"

    try:
        slots = await get_game_slots_by_date(date_str, game_number=game_number)
        if slots:
            night_kills_order = await get_night_kills_order(date_str, game_number or 0)
            filtered_order = []
            for slot_num in night_kills_order:
                if slot_num in slots:
                    status_reason = slots[slot_num].get("status_reason", "")
                    if "убит" in status_reason.lower() and "заголосован" not in status_reason.lower():
                        filtered_order.append(slot_num)
            slots["_night_kills_order"] = filtered_order

            img_path = create_endgame_pic_summary(
                slots=slots, game_date=date_str,
                evening_game_number=game_number or 0,
                global_game_number=global_game_number or 0,
                winner_label=winner_label,
            )
            doc = FSInputFile(img_path)
            timestamp = int(time.time())

            if isinstance(message_or_callback, types.CallbackQuery):
                await message_or_callback.message.answer_document(document=doc, caption=None)
                await message_or_callback.message.answer(f"{text}\n\n🕐 Обновлено: {timestamp}",
                                                         parse_mode=ParseMode.HTML)
            else:
                await message_or_callback.answer_document(document=doc, caption=None)
                await message_or_callback.answer(f"{text}\n\n🕐 Обновлено: {timestamp}", parse_mode=ParseMode.HTML)

            _cleanup_old_files("endgame_summary_", keep=10)
            return True, None
        else:
            if isinstance(message_or_callback, types.CallbackQuery):
                await message_or_callback.message.answer(text, parse_mode=ParseMode.HTML)
            else:
                await message_or_callback.answer(text, parse_mode=ParseMode.HTML)
            return True, None
    except Exception as e:
        print(f"[PROTOCOL][ERROR] {e}")
        return False, str(e)


@router.callback_query(F.data.startswith(("allgames:", "mygames:")))
async def show_game_protocol(callback: types.CallbackQuery, state: FSMContext):
    try:
        prefix, game_id_str, game_number_str = callback.data.split(":", 2)
        game_id = int(game_id_str)
    except Exception:
        await callback.answer("Некорректные данные игры.", show_alert=True)
        return

    game = await get_game_by_id(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    date_str = game.get("game_date") or "-"
    winner_label = game.get("winner_label") or "Результат не указан"
    protocol = (game.get("protocol_text") or "").strip()
    game_number = game.get("game_number")
    global_game_number = game.get("global_game_number") or 0

    lines = protocol.splitlines()
    if lines and lines[0].startswith("📑 Протокол"):
        lines = lines[1:]
    protocol_body = "\n".join(lines).lstrip()

    header = f"📑 Протокол игры №{game_number} ({date_str}): {winner_label}"
    if global_game_number:
        header += f" — №{global_game_number} по общей истории"

    text = header
    if protocol_body:
        text += f"\n\n{protocol_body}"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Редактировать игру", callback_data=f"editgame_menu:{game_id}")]
    ])

    try:
        slots = await get_game_slots_by_date(date_str, game_number=game_number)
        if slots:
            night_kills_order = await get_night_kills_order(date_str, game_number or 0)
            filtered_order = []
            for slot_num in night_kills_order:
                if slot_num in slots:
                    status_reason = slots[slot_num].get("status_reason", "")
                    if "убит" in status_reason.lower() and "заголосован" not in status_reason.lower():
                        filtered_order.append(slot_num)
            slots["_night_kills_order"] = filtered_order

            img_path = create_endgame_pic_summary(
                slots=slots, game_date=date_str,
                evening_game_number=game_number or 0,
                global_game_number=global_game_number or 0,
                winner_label=winner_label,
            )
            doc = FSInputFile(img_path)
            timestamp = int(time.time())

            await callback.message.answer_document(document=doc, caption=None)
            await callback.message.answer(f"{text}\n\n🕐 Обновлено: {timestamp}", parse_mode=ParseMode.HTML,
                                          reply_markup=kb)
            _cleanup_old_files("endgame_summary_", keep=10)
        else:
            await callback.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception as e:
        print(f"[GAME_PROTOCOL][ERROR] {e}")
        await callback.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)

    await callback.answer()


# ======================= ГЛАВНОЕ МЕНЮ РЕДАКТИРОВАНИЯ =======================

@router.callback_query(F.data.startswith("editgame_menu:"))
async def editgame_main_menu(callback: types.CallbackQuery, state: FSMContext):
    try:
        game_id = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    await state.clear()
    await state.update_data(game_id=game_id, has_changes=False, temp_slots={}, temp_winner=None)

    await callback.message.edit_text(
        "✏️ **Редактирование игры**\n\nВыберите действие:",
        reply_markup=_build_game_edit_kb(game_id, has_changes=False)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("editgame_back:"))
async def editgame_back(callback: types.CallbackQuery, state: FSMContext):
    try:
        game_id = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    data = await state.get_data()
    has_changes = data.get("has_changes", False)

    await callback.message.edit_text(
        "✏️ **Редактирование игры**\n\nВыберите действие:",
        reply_markup=_build_game_edit_kb(game_id, has_changes=has_changes)
    )
    await callback.answer()


# ======================= ПОКАЗАТЬ АКТУАЛЬНЫЙ ПРОТОКОЛ =======================

@router.callback_query(F.data.startswith("editgame_show_protocol:"))
async def editgame_show_protocol(callback: types.CallbackQuery, state: FSMContext):
    try:
        game_id = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    game = await get_game_by_id(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    date_str = game.get("game_date") or "-"
    game_number = game.get("game_number") or 0
    winner_label = game.get("winner_label") or "Результат не указан"

    slots = await get_game_slots_by_date(date_str, game_number=game_number)
    if not slots:
        await callback.answer("Нет слотов игры.", show_alert=True)
        return

    # ПРИМЕНЯЕМ ВРЕМЕННЫЕ ИЗМЕНЕНИЯ
    data = await state.get_data()
    temp_slots = data.get("temp_slots", {})
    print(f"[DEBUG] temp_slots: {temp_slots}")
    for slot_num, changes in temp_slots.items():
        if slot_num in slots:
            for key, value in changes.items():
                slots[slot_num][key] = value
                print(f"[DEBUG] Applied change: slot {slot_num}, {key}={value}")

    temp_winner = data.get("temp_winner")
    if temp_winner:
        winner_label = temp_winner

    # Собираем только "Убит ночью"
    night_kills_order = []
    for slot_num, info in slots.items():
        if isinstance(slot_num, int):
            status_reason = info.get("status_reason", "")
            if "убит" in status_reason.lower() and "заголосован" not in status_reason.lower():
                night_kills_order.append(slot_num)
    night_kills_order.sort()
    if night_kills_order:
        slots["_night_kills_order"] = night_kills_order

    from game.text import build_protocol_text
    protocol_body = await build_protocol_text(slots, winner_label=winner_label)

    header = f"📑 **АКТУАЛЬНЫЙ ПРОТОКОЛ** (ещё не сохранён)\n\n📑 Протокол игры №{game_number} ({date_str}): {winner_label}"
    text = f"{header}\n\n{protocol_body}"

    try:
        img_path = create_endgame_pic_summary(
            slots=slots, game_date=date_str,
            evening_game_number=game_number or 0,
            global_game_number=game.get("global_game_number") or 0,
            winner_label=winner_label,
        )
        doc = FSInputFile(img_path)
        timestamp = int(time.time())

        await callback.message.answer_document(document=doc, caption=None)
        await callback.message.answer(f"{text}\n\n🕐 Обновлено: {timestamp}", parse_mode=ParseMode.HTML)
        _cleanup_old_files("endgame_summary_", keep=10)
    except Exception as e:
        print(f"[SHOW_PROTOCOL][ERROR] {e}")
        await callback.message.answer(text, parse_mode=ParseMode.HTML)

    await callback.answer()


# ======================= РЕДАКТИРОВАНИЕ ИГРОКОВ =======================

@router.callback_query(F.data.startswith("editgame_players:"))
async def editgame_players(callback: types.CallbackQuery, state: FSMContext):
    try:
        game_id = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    game = await get_game_by_id(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    date_str = game.get("game_date") or "-"
    game_number = game.get("game_number") or 0

    slots = await get_game_slots_by_date(date_str, game_number=game_number)
    if not slots:
        await callback.answer("Нет слотов игры.", show_alert=True)
        return

    data = await state.get_data()
    temp_slots = data.get("temp_slots", {})
    for slot_num, changes in temp_slots.items():
        if slot_num in slots:
            for key, value in changes.items():
                slots[slot_num][key] = value

    night_kills_order = await get_night_kills_order(date_str, game_number)
    filtered_order = []
    for slot_num in night_kills_order:
        if slot_num in slots:
            status_reason = slots[slot_num].get("status_reason", "")
            if "убит" in status_reason.lower() and "заголосован" not in status_reason.lower():
                filtered_order.append(slot_num)
    slots["_night_kills_order"] = filtered_order

    await callback.message.edit_text(
        f"👥 **Редактирование игроков**\nИгра №{game_number} от {date_str}\n\nВыберите слот:",
        reply_markup=_build_players_edit_kb(game_id, slots)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("editgame_slot:"))
async def editgame_slot_menu(callback: types.CallbackQuery, state: FSMContext):
    try:
        _, game_id_str, slot_str = callback.data.split(":", 2)
        game_id = int(game_id_str)
        slot_num = int(slot_str)
    except Exception:
        if callback.id != "0":
            await callback.answer("Некорректные данные.", show_alert=True)
        return

    await state.update_data(has_changes=True)

    game = await get_game_by_id(game_id)
    if not game:
        if callback.id != "0":
            await callback.answer("Игра не найдена.", show_alert=True)
        return

    date_str = game.get("game_date") or "-"
    game_number = game.get("game_number") or 0

    base_slots = await get_game_slots_by_date(date_str, game_number=game_number)
    if not base_slots or slot_num not in base_slots:
        if callback.id != "0":
            await callback.answer("Слот не найден.", show_alert=True)
        return

    data = await state.get_data()
    temp_slots = data.get("temp_slots", {})

    slot = base_slots[slot_num].copy()
    if slot_num in temp_slots:
        slot.update(temp_slots[slot_num])

    nickname = slot.get("nickname") or slot.get("full_name") or f"Игрок {slot_num}"
    role = slot.get("role") or "Не задана"
    team = slot.get("team") or "Без команды"
    alive = slot.get("alive", True)
    status_reason = slot.get("status_reason", "Жив")

    base = float(slot.get("base_points") or 0)
    bonus = float(slot.get("bonus_points") or 0)
    lh = float(slot.get("lh_points") or 0)
    pr = float(slot.get("will_protocol_points") or 0)
    op = float(slot.get("will_opinion_points") or 0)
    dc = float(slot.get("dc_points") or 0)
    total = base + bonus + lh + pr + op + dc
    pu_mark = bool(slot.get("pu_mark"))
    status_text = "✅ Жив" if alive else f"💀 {status_reason}"

    text = (
        f"🎮 **Слот {slot_num}: {nickname}**\n\n"
        f"📋 **Роль:** {role}\n"
        f"🏳️ **Команда:** {team}\n"
        f"📊 **Статус:** {status_text}\n\n"
        f"💰 **Баллы:**\n"
        f"  • Игра: {base:+.1f}\n"
        f"  • Доп: {bonus:+.1f}\n"
        f"  • ЛХ: {lh:+.1f}\n"
        f"  • ПР: {pr:+.1f}\n"
        f"  • МН: {op:+.1f}\n"
        f"  • ДЦ: {dc:+.1f}\n"
        f"  ───────────────\n"
        f"  • **ИТОГО: {total:+.1f}**\n\n"
        f"👑 **ПУ:** {'да' if pu_mark else 'нет'}"
    )

    try:
        await callback.message.edit_text(text, reply_markup=_build_slot_menu_kb(game_id, slot_num),
                                         parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await callback.message.answer(text, reply_markup=_build_slot_menu_kb(game_id, slot_num),
                                      parse_mode=ParseMode.MARKDOWN)

    if callback.id != "0":
        await callback.answer()


# ======================= РЕДАКТИРОВАНИЕ ИСХОДА =======================

@router.callback_query(F.data.startswith("editgame_outcome:"))
async def editgame_outcome(callback: types.CallbackQuery, state: FSMContext):
    try:
        game_id = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    game = await get_game_by_id(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    data = await state.get_data()
    temp_winner = data.get("temp_winner")
    current_winner = temp_winner if temp_winner else game.get("winner_label", "Результат не указан")

    await callback.message.edit_text(
        f"🏆 **Редактирование исхода игры**\n\nТекущий исход: {current_winner}\n\nВыберите новый исход:",
        reply_markup=_build_outcome_kb(game_id, current_winner)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("editgame_set_outcome:"))
async def editgame_set_outcome(callback: types.CallbackQuery, state: FSMContext):
    try:
        _, _, game_id_str, outcome = callback.data.split(":", 3)
        game_id = int(game_id_str)
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    if outcome == "city":
        winner_label = "Победа города"
    elif outcome == "mafia":
        winner_label = "Победа мафии"
    elif outcome == "ppk":
        winner_label = "ППК"
    else:
        await callback.answer("Неизвестный исход.", show_alert=True)
        return

    await state.update_data(temp_winner=winner_label, has_changes=True)
    await callback.answer(f"✅ Исход изменён на: {winner_label} (пока не сохранён)")

    data = await state.get_data()
    has_changes = data.get("has_changes", True)
    await callback.message.edit_text(
        f"✏️ **Редактирование игры**\n\nИсход изменён на: {winner_label}\n\nВыберите действие:",
        reply_markup=_build_game_edit_kb(game_id, has_changes=has_changes)
    )


# ======================= СОХРАНЕНИЕ И ОБНОВЛЕНИЕ ПРОТОКОЛА =======================

@router.callback_query(F.data.startswith("editgame_regenerate:"))
async def editgame_regenerate(callback: types.CallbackQuery, state: FSMContext):
    try:
        game_id = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    game = await get_game_by_id(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    date_str = game.get("game_date") or "-"
    game_number = game.get("game_number") or 0

    data = await state.get_data()
    temp_slots = data.get("temp_slots", {})
    temp_winner = data.get("temp_winner")

    slots = await get_game_slots_by_date(date_str, game_number=game_number)
    if not slots:
        await callback.answer("Нет слотов игры.", show_alert=True)
        return

    # Применяем временные изменения к слотам и сохраняем в БД
    for slot_num, changes in temp_slots.items():
        if slot_num in slots:
            update_params = {}

            # Обрабатываем все возможные поля
            for key, value in changes.items():
                if key == "alive":
                    update_params["alive"] = 1 if value else 0
                elif key == "status_reason":
                    update_params["status_reason"] = value
                elif key == "kicked":
                    update_params["kick"] = 1 if value else 0
                elif key == "ppk":
                    update_params["ppk"] = 1 if value else 0
                elif key == "pu_mark":
                    update_params["pu"] = 1 if value else 0
                elif key == "will_protocol_raw":
                    update_params["will_protocol_raw"] = value
                elif key == "will_opinion":
                    update_params["will_opinion"] = value
                elif key == "role":
                    update_params["role"] = value
                elif key == "team":
                    update_params["team"] = value
                elif key == "base_points":
                    update_params["base_points"] = value
                elif key == "bonus_points":
                    update_params["bonus_points"] = value
                elif key == "lh_points":
                    update_params["lh_points"] = value
                elif key == "dc_points":
                    update_params["dc_points"] = value
                elif key == "will_protocol_points":
                    update_params["will_protocol_points"] = value
                elif key == "will_opinion_points":
                    update_params["will_opinion_points"] = value
                elif key == "fouls":
                    update_params["fouls"] = value
                elif key == "technical_fouls":
                    tech_list = value
                    if isinstance(tech_list, list):
                        update_params["technical_fouls"] = len(tech_list)
                    else:
                        update_params["technical_fouls"] = tech_list
                else:
                    update_params[key] = value

            if update_params:
                await update_game_slot(date_str, slot_num, **update_params)
                print(f"[DEBUG] Saved slot {slot_num}: {update_params}")

    # Сохраняем исход, если изменён
    if temp_winner:
        await update_game_outcome(game_id, temp_winner)

    # Обновляем локальные слоты для генерации протокола
    for slot_num, changes in temp_slots.items():
        if slot_num in slots:
            for key, value in changes.items():
                slots[slot_num][key] = value

    # Собираем только "Убит ночью"
    night_kills_order = []
    for slot_num, info in slots.items():
        if isinstance(slot_num, int):
            status_reason = info.get("status_reason", "")
            if "убит" in status_reason.lower() and "заголосован" not in status_reason.lower():
                night_kills_order.append(slot_num)
    night_kills_order.sort()
    if night_kills_order:
        slots["_night_kills_order"] = night_kills_order
        await save_night_kills_order(date_str, game_number, night_kills_order)

    from game.text import build_protocol_text
    final_winner = temp_winner if temp_winner else game.get("winner_label", "Результат не указан")
    new_protocol_text = await build_protocol_text(slots, winner_label=final_winner)

    import aiosqlite
    async with aiosqlite.connect("mafia_crm.db") as conn:
        await conn.execute("UPDATE game_history SET protocol_text = ? WHERE id = ?", (new_protocol_text, game_id))
        await conn.commit()

    await state.update_data(temp_slots={}, temp_winner=None, has_changes=False)
    await callback.answer("✅ Изменения сохранены! Протокол обновлён.")
    await _send_protocol(callback, game_id, final_winner)


# ======================= ОТМЕНА ИЗМЕНЕНИЙ =======================

@router.callback_query(F.data.startswith("editgame_cancel_confirm:"))
async def editgame_cancel_confirm(callback: types.CallbackQuery, state: FSMContext):
    try:
        game_id = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    await callback.message.edit_text(
        "⚠️ **Вы уверены, что хотите отменить все изменения?**\n\nНесохранённые правки будут потеряны.",
        reply_markup=_build_cancel_confirm_kb(game_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("editgame_cancel_yes:"))
async def editgame_cancel_yes(callback: types.CallbackQuery, state: FSMContext):
    try:
        game_id = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    await state.update_data(temp_slots={}, temp_winner=None, has_changes=False)
    await callback.message.edit_text("✅ Изменения отменены. Возвращайтесь в историю игр.")
    await callback.answer()


@router.callback_query(F.data.startswith("editgame_close:"))
async def editgame_close(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("✅ Редактор закрыт.")
    await callback.answer()


# ======================= ОБРАБОТЧИКИ ПОЛЕЙ РЕДАКТИРОВАНИЯ =======================

def _apply_change_to_temp_slots(state_data: dict, slot_num: int, changes: dict):
    temp_slots = state_data.get("temp_slots", {})
    if slot_num not in temp_slots:
        temp_slots[slot_num] = {}
    temp_slots[slot_num].update(changes)
    return temp_slots


@router.callback_query(F.data.startswith("editgame_field:"))
async def editgame_field_entry(callback: types.CallbackQuery, state: FSMContext):
    try:
        _, field, game_id_str, slot_str = callback.data.split(":", 3)
        game_id = int(game_id_str)
        slot_num = int(slot_str)
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    if field == "status":
        game = await get_game_by_id(game_id)
        if not game:
            await callback.answer("Игра не найдена.", show_alert=True)
            return
        date_str = game.get("game_date") or "-"
        game_number = game.get("game_number") or 0
        slots = await get_game_slots_by_date(date_str, game_number=game_number)
        if not slots or slot_num not in slots:
            await callback.answer("Слот не найден.", show_alert=True)
            return

        data = await state.get_data()
        temp_slots = data.get("temp_slots", {})
        if slot_num in temp_slots:
            slots[slot_num].update(temp_slots[slot_num])

        await callback.message.edit_text(
            f"📊 **Выберите статус для игрока {slot_num}:**",
            reply_markup=_build_status_kb(game_id, slot_num, slots[slot_num])
        )
        await callback.answer()
        return

    if field == "fouls":
        # Перенаправляем на меню фолов
        await editgame_fouls_menu(callback, state)
        return

    # Для всех остальных полей
    await state.set_state(EditGameState.waiting_for_value)
    await state.update_data(has_changes=True, current_field=field, current_slot=slot_num, current_game_id=game_id)

    msgs = {
        "role": "Введи новую роль (строкой), например: Мирный, Шериф, Мафия, Дон.",
        "team": "Введи новую команду (строкой), например: Красные или Чёрные.",
        "points": "Введи очки через пробел: Игра Доп ЛХ ДЦ\nНапример: 1 0.5 0 -0.5",
        "protocol": "Введи новое значение ПР (число, можно с знаком: +0.5, -1):",
        "protocol_text": "📋 Введи текст протокола (ПР):\nПример: 3 6 7 красные, 1 4 чёрные\nИли 'нет' для очистки",
        "opinion": "Введи новое значение МН (число, можно с знаком: +0.5, -1):",
        "opinion_text": "💬 Введи текст мнения (МН):\nПример: В 12 нет двух мирных\nИли 'нет' для очистки",
        "pu": "ПУ: введи 1 чтобы включить или 0 чтобы выключить.",
    }
    await callback.message.answer(msgs.get(field, "Неизвестное поле."))
    await callback.answer()


@router.callback_query(F.data.startswith("editgame_set_status:"))
async def editgame_set_status(callback: types.CallbackQuery, state: FSMContext):
    try:
        data_part = callback.data.replace("editgame_set_status:", "")
        parts = data_part.split(":")
        game_id = int(parts[0])
        slot_num = int(parts[1])
        status_type = parts[2]
    except Exception as e:
        print(f"[DEBUG] Parse error: {e}")
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    alive, status_reason, kick_val, ppk_val = 1, "Жив", 0, 0
    if status_type == "alive":
        alive, status_reason, kick_val = 1, "Жив", 0
    elif status_type == "killed":
        alive, status_reason = 0, "Убит ночью"
    elif status_type == "voted":
        alive, status_reason = 0, "Заголосован"
    elif status_type == "kicked":
        alive, status_reason, kick_val = 0, "Удалён ведущим", 1
    elif status_type == "ppk":
        alive, status_reason, kick_val, ppk_val = 0, "Удалён (ППК)", 1, 1
    elif status_type == "fouls":
        alive, status_reason, kick_val = 0, "Удалён (4 фола)", 1
    elif status_type == "tech":
        alive, status_reason, kick_val = 0, "Удалён (2 техфола)", 1
    else:
        await callback.answer("Неизвестный статус.", show_alert=True)
        return

    data = await state.get_data()
    temp_slots = _apply_change_to_temp_slots(data, slot_num, {
        "alive": alive == 1,
        "status_reason": status_reason,
        "kicked": kick_val == 1,
        "ppk": ppk_val == 1,
    })
    await state.update_data(temp_slots=temp_slots, has_changes=True)

    await callback.answer(f"✅ Статус изменён: {status_reason}")

    await callback.message.edit_text(
        f"✏️ **Редактирование слота {slot_num}**\n\nСтатус изменён на: {status_reason}",
        reply_markup=_build_slot_menu_kb(game_id, slot_num)
    )


@router.callback_query(F.data.startswith("editgame_field:protocol_text:"))
async def editgame_protocol_text_entry(callback: types.CallbackQuery, state: FSMContext):
    try:
        _, field, game_id_str, slot_str = callback.data.split(":", 3)
        game_id = int(game_id_str)
        slot_num = int(slot_str)
    except Exception as e:
        print(f"[DEBUG] Parse error: {e}")
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    await state.set_state(EditGameState.waiting_for_value)
    await state.update_data(
        has_changes=True,
        current_field="protocol_text",
        current_slot=slot_num,
        current_game_id=game_id
    )

    await callback.message.answer("📋 Введи текст протокола (ПР):\nПример: 3 6 7 красные, 1 4 чёрные\nИли 'нет' для очистки")
    await callback.answer()


@router.callback_query(F.data.startswith("editgame_field:opinion_text:"))
async def editgame_opinion_text_entry(callback: types.CallbackQuery, state: FSMContext):
    try:
        _, field, game_id_str, slot_str = callback.data.split(":", 3)
        game_id = int(game_id_str)
        slot_num = int(slot_str)
    except Exception as e:
        print(f"[DEBUG] Parse error: {e}")
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    await state.set_state(EditGameState.waiting_for_value)
    await state.update_data(
        has_changes=True,
        current_field="opinion_text",
        current_slot=slot_num,
        current_game_id=game_id
    )

    await callback.message.answer("💬 Введи текст мнения (МН):\nПример: В 12 нет двух мирных\nИли 'нет' для очистки")
    await callback.answer()


@router.message(EditGameState.waiting_for_value)
async def editgame_field_apply(message: types.Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("current_field")
    game_id = data.get("current_game_id")
    slot_num = data.get("current_slot")

    if field is None or game_id is None or slot_num is None:
        await message.answer("Ошибка состояния, попробуй ещё раз.")
        await state.clear()
        return

    game = await get_game_by_id(int(game_id))
    if not game:
        await message.answer("Игра не найдена.")
        await state.clear()
        return

    text = message.text.strip()
    changes = {}

    try:
        if field == "role":
            changes["role"] = text
            await message.answer("✅ Роль обновлена (будет сохранена после нажатия 'Сохранить').")
        elif field == "team":
            changes["team"] = text
            await message.answer("✅ Команда обновлена (будет сохранена после нажатия 'Сохранить').")
        elif field == "points":
            parts = text.replace(",", ".").split()
            if len(parts) != 4:
                await message.answer("❌ Нужно 4 числа через пробел: Игра Доп ЛХ ДЦ.")
                return
            b, bo, lh, dc = map(float, parts)
            changes["base_points"] = b
            changes["bonus_points"] = bo
            changes["lh_points"] = lh
            changes["dc_points"] = dc
            await message.answer("✅ Очки обновлены (будут сохранены после нажатия 'Сохранить').")
        elif field == "protocol":
            val = float(text.replace(",", "."))
            changes["will_protocol_points"] = val
            await message.answer("✅ ПР обновлён (будет сохранён после нажатия 'Сохранить').")
        elif field == "protocol_text":
            if text.lower() in ("нет", "no", "0"):
                text = ""
            changes["will_protocol_raw"] = text
            await message.answer("✅ Текст ПР сохранён (будет сохранён после нажатия 'Сохранить').")
        elif field == "opinion":
            val = float(text.replace(",", "."))
            changes["will_opinion_points"] = val
            await message.answer("✅ МН обновлено (будет сохранено после нажатия 'Сохранить').")
        elif field == "opinion_text":
            if text.lower() in ("нет", "no", "0"):
                text = ""
            changes["will_opinion"] = text
            await message.answer("✅ Текст МН сохранён (будет сохранён после нажатия 'Сохранить').")
        elif field == "pu":
            if text not in ("0", "1"):
                await message.answer("❌ Нужно 0 или 1.")
                return
            changes["pu_mark"] = text == "1"
            await message.answer("✅ ПУ обновлён (будет сохранён после нажатия 'Сохранить').")
        else:
            await message.answer("❌ Неизвестное поле.")
            await state.clear()
            return

        # Сохраняем изменения во временные слоты
        state_data = await state.get_data()
        temp_slots = state_data.get("temp_slots", {})
        if slot_num not in temp_slots:
            temp_slots[slot_num] = {}
        temp_slots[slot_num].update(changes)

        await state.update_data(
            temp_slots=temp_slots,
            has_changes=True,
            current_field=None,
            current_slot=None,
            current_game_id=None
        )
        await state.set_state(None)

    except Exception as e:
        print(f"[EDIT_GAME][ERROR] {e}")
        await message.answer(f"❌ Ошибка: {e}")
        await state.clear()
        return

    # Отправляем новое сообщение с меню слота
    date_str = game.get("game_date") or "-"
    game_number = game.get("game_number") or 0
    base_slots = await get_game_slots_by_date(date_str, game_number=game_number)

    temp_slots = (await state.get_data()).get("temp_slots", {})
    slot = base_slots[slot_num].copy() if base_slots and slot_num in base_slots else {}
    if slot_num in temp_slots:
        for key, value in temp_slots[slot_num].items():
            slot[key] = value

    nickname = slot.get("nickname") or slot.get("full_name") or f"Игрок {slot_num}"
    role = slot.get("role") or "Не задана"
    team = slot.get("team") or "Без команды"
    alive = slot.get("alive", True)
    status_reason = slot.get("status_reason", "Жив")

    base = float(slot.get("base_points") or 0)
    bonus = float(slot.get("bonus_points") or 0)
    lh = float(slot.get("lh_points") or 0)
    pr = float(slot.get("will_protocol_points") or 0)
    op = float(slot.get("will_opinion_points") or 0)
    dc = float(slot.get("dc_points") or 0)
    total = base + bonus + lh + pr + op + dc
    pu_mark = bool(slot.get("pu_mark"))
    status_text = "✅ Жив" if alive else f"💀 {status_reason}"

    text_msg = (
        f"🎮 **Слот {slot_num}: {nickname}**\n\n"
        f"📋 **Роль:** {role}\n"
        f"🏳️ **Команда:** {team}\n"
        f"📊 **Статус:** {status_text}\n\n"
        f"💰 **Баллы:**\n"
        f"  • Игра: {base:+.1f}\n"
        f"  • Доп: {bonus:+.1f}\n"
        f"  • ЛХ: {lh:+.1f}\n"
        f"  • ПР: {pr:+.1f}\n"
        f"  • МН: {op:+.1f}\n"
        f"  • ДЦ: {dc:+.1f}\n"
        f"  ───────────────\n"
        f"  • **ИТОГО: {total:+.1f}**\n\n"
        f"👑 **ПУ:** {'да' if pu_mark else 'нет'}"
    )

    await message.answer(text_msg, reply_markup=_build_slot_menu_kb(game_id, slot_num), parse_mode=ParseMode.MARKDOWN)


# ======================= УПРАВЛЕНИЕ ФОЛАМИ =======================

@router.callback_query(F.data.startswith("editgame_field:fouls:"))
async def editgame_fouls_menu(callback: types.CallbackQuery, state: FSMContext):
    """Меню редактирования фолов и техфолов"""
    try:
        # Получаем данные из callback
        parts = callback.data.split(":")
        # Формат: editgame_field:fouls:game_id:slot_num
        game_id = int(parts[2])
        slot_num = int(parts[3])

    except Exception as e:
        print(f"[FOULS] Parse error: {e}")
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    game = await get_game_by_id(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    date_str = game.get("game_date") or "-"
    game_number = game.get("game_number") or 0

    slots = await get_game_slots_by_date(date_str, game_number=game_number)
    if not slots or slot_num not in slots:
        await callback.answer("Слот не найден.", show_alert=True)
        return

    # Применяем временные изменения
    data = await state.get_data()
    temp_slots = data.get("temp_slots", {})
    slot = slots[slot_num].copy()
    if slot_num in temp_slots:
        for key, value in temp_slots[slot_num].items():
            slot[key] = value

    fouls = slot.get("fouls", 0)
    tech_fouls = slot.get("technical_fouls", [])
    if isinstance(tech_fouls, int):
        tech_fouls_count = tech_fouls
    else:
        tech_fouls_count = len(tech_fouls)

    text = (
        f"⚠️ **Управление фолами**\n\n"
        f"Слот {slot_num}: {slot.get('nickname') or slot.get('full_name')}\n\n"
        f"📊 Текущие фолы: **{fouls}**\n"
        f"📋 Текущие техфолы: **{tech_fouls_count}**\n\n"
        f"⚡ При 4 фолах → удаление (-1.0 ДЦ)\n"
        f"⚡ При 2 техфолах → удаление\n\n"
        f"Выберите действие:"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"➕ +1 фол (сейчас {fouls})",
                              callback_data=f"editgame_set_fouls:{game_id}:{slot_num}:add")],
        [InlineKeyboardButton(text=f"➖ -1 фол (сейчас {fouls})",
                              callback_data=f"editgame_set_fouls:{game_id}:{slot_num}:remove")],
        [InlineKeyboardButton(text="⚠️ Малый техфол (-0.3 ДЦ)",
                              callback_data=f"editgame_set_fouls:{game_id}:{slot_num}:tech_small")],
        [InlineKeyboardButton(text="⚠️ Большой техфол (-0.6 ДЦ)",
                              callback_data=f"editgame_set_fouls:{game_id}:{slot_num}:tech_big")],
        [InlineKeyboardButton(text="🔧 Снять последний техфол",
                              callback_data=f"editgame_set_fouls:{game_id}:{slot_num}:tech_remove")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"editgame_slot:{game_id}:{slot_num}")],
    ])

    await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    await callback.answer()


@router.callback_query(F.data.startswith("editgame_set_fouls:"))
async def editgame_set_fouls(callback: types.CallbackQuery, state: FSMContext):
    """Устанавливает фолы/техфолы игроку"""
    try:
        # Формат: editgame_set_fouls:game_id:slot_num:action
        parts = callback.data.split(":")
        game_id = int(parts[1])
        slot_num = int(parts[2])
        action = parts[3]

        print(f"[FOULS] game_id={game_id}, slot_num={slot_num}, action={action}")

    except Exception as e:
        print(f"[FOULS] Parse error: {e}")
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    game = await get_game_by_id(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    date_str = game.get("game_date") or "-"
    game_number = game.get("game_number") or 0

    slots = await get_game_slots_by_date(date_str, game_number=game_number)
    if not slots or slot_num not in slots:
        await callback.answer("Слот не найден.", show_alert=True)
        return

    data = await state.get_data()
    temp_slots = data.get("temp_slots", {})

    slot = slots[slot_num].copy()
    if slot_num in temp_slots:
        for key, value in temp_slots[slot_num].items():
            slot[key] = value

    changes = {}
    message_text = ""

    try:
        if action == "add":
            new_fouls = slot.get("fouls", 0) + 1
            changes["fouls"] = new_fouls
            message_text = f"✅ +1 фол. Всего: {new_fouls}"

            if new_fouls >= 4:
                changes["alive"] = False
                changes["status_reason"] = "Удалён (4 фола)"
                changes["kicked"] = True
                current_dc = slot.get("dc_points", 0.0)
                changes["dc_points"] = round(current_dc - 1.0, 1)
                message_text = f"⚠️ Игрок удалён за 4 фола! -1.0 ДЦ"

        elif action == "remove":
            new_fouls = max(0, slot.get("fouls", 0) - 1)
            changes["fouls"] = new_fouls
            message_text = f"✅ -1 фол. Всего: {new_fouls}"

        elif action == "tech_small":
            tech_list = slot.get("technical_fouls", [])
            if isinstance(tech_list, int):
                tech_list = []
            tech_list.append("small")
            changes["technical_fouls"] = tech_list
            current_dc = slot.get("dc_points", 0.0)
            changes["dc_points"] = round(current_dc - 0.3, 1)

            if len(tech_list) >= 2:
                changes["alive"] = False
                changes["status_reason"] = "Удалён (2 техфола)"
                changes["kicked"] = True
                message_text = f"⚠️ Игрок удалён за 2 техфола! -0.3 ДЦ"
            else:
                message_text = f"✅ Малый техфол добавлен (-0.3 ДЦ)"

        elif action == "tech_big":
            tech_list = slot.get("technical_fouls", [])
            if isinstance(tech_list, int):
                tech_list = []
            tech_list.append("big")
            changes["technical_fouls"] = tech_list
            current_dc = slot.get("dc_points", 0.0)
            changes["dc_points"] = round(current_dc - 0.6, 1)

            if len(tech_list) >= 2:
                changes["alive"] = False
                changes["status_reason"] = "Удалён (2 техфола)"
                changes["kicked"] = True
                message_text = f"⚠️ Игрок удалён за 2 техфола! -0.6 ДЦ"
            else:
                message_text = f"✅ Большой техфол добавлен (-0.6 ДЦ)"

        elif action == "tech_remove":
            tech_list = slot.get("technical_fouls", [])
            if isinstance(tech_list, int):
                tech_list = []
            if tech_list:
                removed = tech_list.pop()
                changes["technical_fouls"] = tech_list
                current_dc = slot.get("dc_points", 0.0)
                if removed == "small":
                    changes["dc_points"] = round(current_dc + 0.3, 1)
                else:
                    changes["dc_points"] = round(current_dc + 0.6, 1)
                message_text = "✅ Техфол снят"
            else:
                await callback.answer("Нет техфолов для снятия", show_alert=True)
                return
        else:
            await callback.answer("Неизвестное действие", show_alert=True)
            return

    except Exception as e:
        print(f"[FOULS] Error: {e}")
        await callback.answer(f"Ошибка: {e}", show_alert=True)
        return

    # Сохраняем изменения во временные слоты
    if slot_num not in temp_slots:
        temp_slots[slot_num] = {}
    temp_slots[slot_num].update(changes)
    await state.update_data(temp_slots=temp_slots, has_changes=True)

    await callback.answer(message_text, show_alert=False)

    # Обновляем меню фолов
    await editgame_fouls_menu(callback, state)