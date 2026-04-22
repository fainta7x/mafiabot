import os
import time
from typing import Dict, Any, Tuple, Optional, List

from aiogram import Router, F, types, Bot
from aiogram.enums import ParseMode
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

import stats_utils
from database import (
    get_last_games,
    get_user_games,
    get_game_by_id,
    get_game_slots_by_date,
    update_game_slot,
    update_game_outcome,
)
from keyboards import games_list_kb
from pic_profile import create_profile_pic
from game.pic_endgame import create_endgame_pic_summary

router = Router()

TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
os.makedirs(TEMP_DIR, exist_ok=True)


# ======================= УТИЛИТЫ =======================

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
    except Exception as e:
        print(f"[CLEANUP] Error: {e}")


def _parse_bonus_value(raw: str) -> float:
    """Парсит значение: 0.2, 02, 0,2, 2 → 0.2"""
    raw = raw.strip().replace(",", ".")

    if raw.isdigit() or (raw.startswith("-") and raw[1:].isdigit()):
        val = int(raw) / 10.0
        return round(val, 1)

    try:
        val = float(raw)
        return round(val, 1)
    except ValueError:
        return 0.0


def _format_slot_for_kb(slot_num: int, slot: dict) -> str:
    """Форматирует слот для отображения в кнопке."""
    nickname = slot.get("nickname") or slot.get("full_name") or f"Игрок {slot_num}"
    if len(nickname) > 12:
        nickname = nickname[:10] + ".."
    role = slot.get("role") or "?"
    if len(role) > 6:
        role = role[:4] + "."
    base = float(slot.get("base_points") or 0)
    bonus = float(slot.get("bonus_points") or 0)
    lh = float(slot.get("lh_points") or 0)
    pr = float(slot.get("will_protocol_points") or 0)
    mn = float(slot.get("will_opinion_points") or 0)
    dc = float(slot.get("dc_points") or 0)
    total = base + bonus + lh + pr + mn + dc
    return f"{slot_num}. {nickname} [{role}] — {total:+.1f}"


def _get_team_by_role(role: str) -> str:
    """Возвращает команду по роли."""
    if role in ("Мирный", "Шериф"):
        return "Красные"
    elif role in ("Мафия", "Дон"):
        return "Чёрные"
    return ""


# ======================= FSM =======================

class EditGameState(StatesGroup):
    waiting_for_value = State()
    ppk_winning_team = State()
    ppk_culprit_select = State()


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
        await message.answer_document(
            document=doc,
            caption=f"{text}\n\n🕐 Обновлено: {timestamp}",
            parse_mode=ParseMode.MARKDOWN,
        )

        _cleanup_old_files("profile_", keep=10)

    except Exception as e:
        print(f"[PROFILE][ERROR] {e}")
        text = await stats_utils.build_user_stats_text(user_id)
        await message.answer(text)


@router.message(F.text == "📜 Все игры")
async def show_all_games(message: types.Message):
    games = await get_last_games(limit=15)

    if not games:
        await message.answer("Пока нет завершённых игр.")
        return

    buttons_data = []
    for g in games:
        game_id = g["id"]
        date_str = g.get("game_date") or ""
        game_number = g.get("game_number")
        global_game_number = g.get("global_game_number")

        if game_number:
            title = f"Игра №{game_number}"
        else:
            title = "Игра"

        if date_str:
            title += f" ({date_str})"

        if global_game_number:
            title += f" — №{global_game_number}"

        buttons_data.append((game_id, title, game_number or 0))

    kb = games_list_kb(buttons_data, prefix="allgames")
    await message.answer("📜 Выбери игру для просмотра или редактирования:", reply_markup=kb)


@router.message(F.text == "📜 Мои игры")
async def show_my_games(message: types.Message):
    user_id = message.from_user.id
    games = await get_user_games(user_id=user_id, limit=15)

    if not games:
        await message.answer("Пока нет игр с твоим участием.")
        return

    buttons_data = []
    for g in games:
        game_id = g["id"]
        date_str = g.get("game_date") or ""
        game_number = g.get("game_number")
        global_game_number = g.get("global_game_number")

        if game_number:
            title = f"Игра №{game_number}"
        else:
            title = "Игра"

        if date_str:
            title += f" ({date_str})"

        if global_game_number:
            title += f" — №{global_game_number}"

        buttons_data.append((game_id, title, game_number or 0))

    kb = games_list_kb(buttons_data, prefix="mygames")
    await message.answer("📜 Выбери игру:", reply_markup=kb)


# ======================= ПРОТОКОЛ ИГРЫ =======================

async def _get_game_info(game_id: int) -> Tuple[Optional[dict], Optional[str], Optional[dict]]:
    """Возвращает (game, date_str, slots)."""
    game = await get_game_by_id(game_id)
    if not game:
        return None, None, None
    date_str = game.get("game_date") or "-"
    raw_slots = await get_game_slots_by_date(date_str) or {}

    # Фильтруем слоты сразу - оставляем только числовые ключи
    slots = {}
    for key, value in raw_slots.items():
        if isinstance(key, int) and 1 <= key <= 10:
            slots[key] = value
        # Пропускаем _night_kills_order и другие служебные ключи

    return game, date_str, slots


def _build_protocol_text(game: dict, slots: dict, winner_label: str = None) -> str:
    """Строит текст протокола из игры и слотов."""
    date_str = game.get("game_date") or "-"
    game_number = game.get("game_number")
    global_game_number = game.get("global_game_number") or 0
    winner = winner_label or game.get("winner_label") or "Результат не указан"

    if game_number:
        header = f"📑 Протокол игры №{game_number} ({date_str}): {winner}"
    else:
        header = f"📑 Протокол игры ({date_str}): {winner}"

    if global_game_number:
        header += f" — №{global_game_number} по общей истории"

    # Группируем по командам
    reds = []
    blacks = []
    others = []

    for slot_num, slot in slots.items():
        # slots уже отфильтрован, все ключи - числа
        team = slot.get("team")
        if team == "Красные":
            reds.append((slot_num, slot))
        elif team == "Чёрные":
            blacks.append((slot_num, slot))
        else:
            others.append((slot_num, slot))

    reds.sort(key=lambda x: x[0])
    blacks.sort(key=lambda x: x[0])
    others.sort(key=lambda x: x[0])

    def format_player(slot_num: int, slot: dict) -> str:
        name = slot.get("nickname") or slot.get("full_name") or f"Игрок {slot_num}"
        role = slot.get("role") or "Не задана"
        team = slot.get("team") or "—"
        base = float(slot.get("base_points") or 0)
        bonus = float(slot.get("bonus_points") or 0)
        lh = float(slot.get("lh_points") or 0)
        pr = float(slot.get("will_protocol_points") or 0)
        mn = float(slot.get("will_opinion_points") or 0)
        dc = float(slot.get("dc_points") or 0)
        total = base + bonus + lh + pr + mn + dc
        return f"{slot_num}. {name} — {role} ({team}) — Игра {base:+.1f}, Доп {bonus:+.1f}, ЛХ {lh:+.1f}, ПР {pr:+.1f}, МН {mn:+.1f}, ДЦ {dc:+.1f} → {total:+.1f}"

    lines = [header, ""]

    if reds:
        lines.append("🔴 КРАСНЫЕ:")
        for slot_num, slot in reds:
            lines.append(f"  {format_player(slot_num, slot)}")
        lines.append("")

    if blacks:
        lines.append("⚫ ЧЁРНЫЕ:")
        for slot_num, slot in blacks:
            lines.append(f"  {format_player(slot_num, slot)}")
        lines.append("")

    if others:
        lines.append("⚪ БЕЗ КОМАНДЫ:")
        for slot_num, slot in others:
            lines.append(f"  {format_player(slot_num, slot)}")
        lines.append("")

    return "\n".join(lines)


async def _send_protocol(
        target: types.Message | types.CallbackQuery,
        game_id: int,
        game: dict,
        date_str: str,
        slots: dict,
        winner_label: str,
        reply_markup: InlineKeyboardMarkup = None,
):
    """Отправляет протокол игры (текст + картинка)."""
    # Фильтруем слоты - оставляем только числовые ключи
    clean_slots = {}
    night_kills_order = []

    for key, value in slots.items():
        if isinstance(key, int):
            clean_slots[key] = value
        elif key == "_night_kills_order" and isinstance(value, list):
            night_kills_order = value

    if night_kills_order:
        clean_slots["_night_kills_order"] = night_kills_order

    protocol_text = _build_protocol_text(game, clean_slots, winner_label)
    game_number = game.get("game_number") or 0
    global_game_number = game.get("global_game_number") or 0

    if isinstance(target, types.CallbackQuery):
        target = target.message

    try:
        if clean_slots:
            img_path = create_endgame_pic_summary(
                slots=clean_slots,
                game_date=date_str,
                evening_game_number=game_number or 0,
                global_game_number=global_game_number or 0,
                winner_label=winner_label,
            )
            doc = FSInputFile(img_path)
            timestamp = int(time.time())

            await target.answer_document(
                document=doc,
                caption=f"{protocol_text}\n\n🕐 Обновлено: {timestamp}",
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
            _cleanup_old_files("endgame_summary_", keep=10)
        else:
            await target.answer(
                protocol_text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
    except Exception as e:
        print(f"[SEND_PROTOCOL] Error: {e}")
        await target.answer(
            protocol_text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )


# ======================= ОСНОВНОЙ ПРОСМОТР ИГРЫ =======================

@router.callback_query(F.data.startswith(("allgames:", "mygames:")))
async def show_game(callback: types.CallbackQuery):
    """Показываем игру: картинка + протокол + кнопка для входа в редактор."""
    try:
        _, game_id_str, _ = callback.data.split(":", 2)
        game_id = int(game_id_str)
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    game, date_str, slots = await _get_game_info(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    winner_label = game.get("winner_label") or "Результат не указан"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Открыть редактор", callback_data=f"editor_open:{game_id}")],
        [InlineKeyboardButton(text="🔄 Обновить протокол", callback_data=f"refresh_protocol:{game_id}")],
    ])

    await _send_protocol(callback, game_id, game, date_str, slots, winner_label, kb)
    await callback.answer()


@router.callback_query(F.data.startswith("refresh_protocol:"))
async def refresh_protocol(callback: types.CallbackQuery):
    """Обновить протокол."""
    try:
        game_id = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    game, date_str, slots = await _get_game_info(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    winner_label = game.get("winner_label") or "Результат не указан"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Открыть редактор", callback_data=f"editor_open:{game_id}")],
        [InlineKeyboardButton(text="🔄 Обновить протокол", callback_data=f"refresh_protocol:{game_id}")],
    ])

    await _send_protocol(callback, game_id, game, date_str, slots, winner_label, kb)
    await callback.answer()


# ======================= РЕДАКТОР (ОТДЕЛЬНОЕ СООБЩЕНИЕ) =======================

def _build_editor_main_kb(game_id: int) -> InlineKeyboardMarkup:
    """Главное меню редактора."""
    kb = [
        [InlineKeyboardButton(text="✏️ Редактировать игроков", callback_data=f"editor_players:{game_id}")],
        [InlineKeyboardButton(text="🏆 Сменить исход игры", callback_data=f"editor_outcome:{game_id}")],
        [InlineKeyboardButton(text="✅ Подтвердить изменения", callback_data=f"editor_confirm:{game_id}")],
        [InlineKeyboardButton(text="❌ Закрыть редактор", callback_data=f"editor_close:{game_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _build_players_list_kb(game_id: int, slots: dict) -> InlineKeyboardMarkup:
    """Список игроков для выбора редактирования."""
    buttons = []
    for slot_num in sorted([k for k in slots.keys() if isinstance(k, int)]):
        slot = slots[slot_num]
        text = _format_slot_for_kb(slot_num, slot)
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"editor_slot:{game_id}:{slot_num}")])

    buttons.append([InlineKeyboardButton(text="◀️ Назад в меню", callback_data=f"editor_back:{game_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _build_slot_edit_kb(game_id: int, slot_num: int) -> InlineKeyboardMarkup:
    """Меню редактирования одного слота."""
    kb = [
        [InlineKeyboardButton(text="🎭 Роль", callback_data=f"editor_field:role:{game_id}:{slot_num}")],
        [InlineKeyboardButton(text="➕ ДОП", callback_data=f"editor_field:bonus:{game_id}:{slot_num}")],
        [InlineKeyboardButton(text="🔭 ЛХ", callback_data=f"editor_field:lh:{game_id}:{slot_num}")],
        [InlineKeyboardButton(text="📋 ПР", callback_data=f"editor_field:protocol:{game_id}:{slot_num}")],
        [InlineKeyboardButton(text="💬 МН", callback_data=f"editor_field:opinion:{game_id}:{slot_num}")],
        [InlineKeyboardButton(text="💣 ДЦ", callback_data=f"editor_field:dc:{game_id}:{slot_num}")],
        [InlineKeyboardButton(text="👑 ПУ", callback_data=f"editor_field:pu:{game_id}:{slot_num}")],
        [InlineKeyboardButton(text="⚠ Техфолы/Удаление", callback_data=f"editor_fouls:{game_id}:{slot_num}")],
        [InlineKeyboardButton(text="◀️ Назад к списку", callback_data=f"editor_players:{game_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _build_fouls_menu_kb(game_id: int, slot_num: int, slot: dict) -> InlineKeyboardMarkup:
    """Меню управления техфолами и удалением."""
    current_kick = int(slot.get("kick") or 0)
    current_tech = int(slot.get("technical_fouls") or 0)

    kick_text = "✅ Удалён: ДА" if current_kick else "❌ Удалён: НЕТ"

    kb = [
        [InlineKeyboardButton(text=f"📊 Техфолы: {current_tech}/2", callback_data="ignore")],
        [InlineKeyboardButton(text=kick_text, callback_data=f"fouls_kick_{game_id}_{slot_num}")],
        [InlineKeyboardButton(text="🔧 Малый техфол (+1, -0.3 ДЦ)", callback_data=f"fouls_small_{game_id}_{slot_num}")],
        [InlineKeyboardButton(text="🔧 Большой техфол (+1, -0.6 ДЦ)", callback_data=f"fouls_big_{game_id}_{slot_num}")],
        [InlineKeyboardButton(text="🔧 Снять техфол (-1)", callback_data=f"fouls_dec_{game_id}_{slot_num}")],
        [InlineKeyboardButton(text="◀️ Назад к слоту", callback_data=f"editor_slot:{game_id}:{slot_num}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _build_outcome_menu_kb(game_id: int) -> InlineKeyboardMarkup:
    """Меню выбора исхода."""
    kb = [
        [InlineKeyboardButton(text="🔴 Победа города", callback_data=f"editor_outcome_set:city:{game_id}")],
        [InlineKeyboardButton(text="⚫ Победа мафии", callback_data=f"editor_outcome_set:mafia:{game_id}")],
        [InlineKeyboardButton(text="⚠ ППК (с выбором виновника)", callback_data=f"editor_outcome_set:ppk:{game_id}")],
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data=f"editor_back:{game_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _build_ppk_team_kb(game_id: int) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="🔴 Победа города (Красные)", callback_data=f"editor_ppk_team:red:{game_id}")],
        [InlineKeyboardButton(text="⚫ Победа мафии (Чёрные)", callback_data=f"editor_ppk_team:black:{game_id}")],
        [InlineKeyboardButton(text="◀️ Назад к исходу", callback_data=f"editor_outcome:{game_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _build_ppk_culprit_kb(game_id: int, slots: dict, losing_team: str) -> InlineKeyboardMarkup:
    buttons = []
    for slot_num, slot in slots.items():
        if not isinstance(slot_num, int):
            continue
        if slot.get("team") == losing_team:
            name = slot.get("nickname") or slot.get("full_name") or f"Игрок {slot_num}"
            buttons.append([InlineKeyboardButton(text=f"{slot_num}. {name}", callback_data=f"editor_ppk_culprit:{game_id}:{slot_num}")])

    buttons.append([InlineKeyboardButton(text="◀️ Назад к выбору команды", callback_data=f"editor_outcome_set:ppk:{game_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ======================= ОТКРЫТИЕ РЕДАКТОРА =======================

@router.callback_query(F.data.startswith("editor_open:"))
async def editor_open(callback: types.CallbackQuery, state: FSMContext):
    """Открывает редактор в отдельном сообщении."""
    try:
        game_id = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    game, date_str, slots = await _get_game_info(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    winner_label = game.get("winner_label") or "Результат не указан"

    await state.update_data(
        protocol_chat_id=callback.message.chat.id,
        protocol_message_id=callback.message.message_id,
        game_id=game_id
    )

    await callback.message.answer(
        f"✏️ **Редактор игры**\n\n"
        f"📅 Дата: {date_str}\n"
        f"🏆 Текущий исход: {winner_label}\n"
        f"👥 Игроков: {len([k for k in slots.keys() if isinstance(k, int)])}\n\n"
        f"Выбери действие:",
        reply_markup=_build_editor_main_kb(game_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("editor_back:"))
async def editor_back(callback: types.CallbackQuery, state: FSMContext):
    """Возврат в главное меню редактора."""
    try:
        game_id = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    game, date_str, slots = await _get_game_info(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    winner_label = game.get("winner_label") or "Результат не указан"

    await callback.message.edit_text(
        f"✏️ **Редактор игры**\n\n"
        f"📅 Дата: {date_str}\n"
        f"🏆 Текущий исход: {winner_label}\n"
        f"👥 Игроков: {len([k for k in slots.keys() if isinstance(k, int)])}\n\n"
        f"Выбери действие:",
        reply_markup=_build_editor_main_kb(game_id),
    )
    await callback.answer()


# ======================= РЕДАКТИРОВАНИЕ ИГРОКОВ =======================

@router.callback_query(F.data.startswith("editor_players:"))
async def editor_players(callback: types.CallbackQuery):
    """Список игроков для редактирования."""
    try:
        game_id = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    game, date_str, slots = await _get_game_info(game_id)
    if not game or not slots:
        await callback.answer("Нет данных об игре.", show_alert=True)
        return

    await callback.message.edit_text(
        "👥 **Выбери игрока для редактирования:**",
        reply_markup=_build_players_list_kb(game_id, slots),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("editor_slot:"))
async def editor_slot(callback: types.CallbackQuery):
    """Меню редактирования слота."""
    try:
        _, game_id_str, slot_str = callback.data.split(":", 2)
        game_id = int(game_id_str)
        slot_num = int(slot_str)
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    game, date_str, slots = await _get_game_info(game_id)
    if not game or not slots or slot_num not in slots:
        await callback.answer("Слот не найден.", show_alert=True)
        return

    slot = slots[slot_num]
    nickname = slot.get("nickname") or slot.get("full_name") or f"Игрок {slot_num}"
    role = slot.get("role") or "Не задана"
    team = slot.get("team") or "—"
    base = float(slot.get("base_points") or 0)
    bonus = float(slot.get("bonus_points") or 0)
    lh = float(slot.get("lh_points") or 0)
    pr = float(slot.get("will_protocol_points") or 0)
    mn = float(slot.get("will_opinion_points") or 0)
    dc = float(slot.get("dc_points") or 0)
    pu = "✅" if slot.get("pu_mark") else "❌"
    kick = "✅" if slot.get("kick") else "❌"
    tech = int(slot.get("technical_fouls") or 0)

    total = base + bonus + lh + pr + mn + dc

    text = (
        f"🎭 **Слот {slot_num}: {nickname}**\n\n"
        f"Роль: {role}\n"
        f"Команда: {team}\n"
        f"ПУ: {pu} | Удалён: {kick} | Техфолы: {tech}\n\n"
        f"📊 Очки:\n"
        f"  • Игра: {base:+.1f}\n"
        f"  • ДОП: {bonus:+.1f}\n"
        f"  • ЛХ: {lh:+.1f}\n"
        f"  • ПР: {pr:+.1f}\n"
        f"  • МН: {mn:+.1f}\n"
        f"  • ДЦ: {dc:+.1f}\n"
        f"  • ИТОГО: {total:+.1f}"
    )

    await callback.message.edit_text(text, reply_markup=_build_slot_edit_kb(game_id, slot_num))
    await callback.answer()


# ======================= РЕДАКТИРОВАНИЕ ПОЛЕЙ СЛОТА =======================

@router.callback_query(F.data.startswith("editor_field:"))
async def editor_field_entry(callback: types.CallbackQuery, state: FSMContext):
    """Запрос значения для поля."""
    try:
        _, field, game_id_str, slot_str = callback.data.split(":", 3)
        game_id = int(game_id_str)
        slot_num = int(slot_str)
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    await state.set_state(EditGameState.waiting_for_value)
    await state.update_data(field=field, game_id=game_id, slot_num=slot_num)

    prompts = {
        "role": "Введи новую роль (строкой), например: Мирный, Шериф, Мафия, Дон\n\nКоманда изменится автоматически!",
        "bonus": "Введи новое значение ДОП (число):\nПримеры: 0.2, 02, 0,2, 2 (всё это = 0.2)",
        "lh": "Введи новое значение ЛХ (число): +0.3, -0.3, 0",
        "protocol": "Введи новое значение ПР (число): +0.5, -1, 0",
        "opinion": "Введи новое значение МН (число): +0.5, -1, 0",
        "dc": "Введи новое значение ДЦ (число): -1.5, -0.3, 0, +0.5",
        "pu": "ПУ: введи 1 (включить) или 0 (выключить)",
    }

    await callback.message.answer(prompts.get(field, "Введи новое значение:"))
    await callback.answer()


@router.message(EditGameState.waiting_for_value)
async def editor_field_apply(message: types.Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    field = data.get("field")
    game_id = data.get("game_id")
    slot_num = data.get("slot_num")
    edit_chat_id = data.get("protocol_chat_id")
    edit_message_id = data.get("protocol_message_id")

    if field is None or game_id is None or slot_num is None:
        await message.answer("Ошибка состояния, попробуй ещё раз.")
        await state.clear()
        return

    game = await get_game_by_id(game_id)
    if not game:
        await message.answer("Игра не найдена.")
        await state.clear()
        return

    date_str = game.get("game_date") or "-"
    text = message.text.strip()

    try:
        if field == "role":
            await update_game_slot(date_str, slot_num, role=text)
            team = _get_team_by_role(text)
            if team:
                await update_game_slot(date_str, slot_num, team=team)
            await message.answer(f"✅ Роль изменена на: {text}\nКоманда: {team if team else 'не изменилась'}")

        elif field == "bonus":
            val = _parse_bonus_value(text)
            await update_game_slot(date_str, slot_num, bonus_points=val)
            await message.answer(f"✅ ДОП изменён: {val:+.1f}")

        elif field == "lh":
            val = _parse_bonus_value(text)
            await update_game_slot(date_str, slot_num, lh_points=val)
            await message.answer(f"✅ ЛХ изменён: {val:+.1f}")

        elif field == "protocol":
            val = _parse_bonus_value(text)
            await update_game_slot(date_str, slot_num, will_protocol_points=val)
            await message.answer(f"✅ ПР изменён: {val:+.1f}")

        elif field == "opinion":
            val = _parse_bonus_value(text)
            await update_game_slot(date_str, slot_num, will_opinion_points=val)
            await message.answer(f"✅ МН изменён: {val:+.1f}")

        elif field == "dc":
            val = _parse_bonus_value(text)
            await update_game_slot(date_str, slot_num, dc_points=val)
            await message.answer(f"✅ ДЦ изменён: {val:+.1f}")

        elif field == "pu":
            if text not in ("0", "1"):
                await message.answer("Нужно 0 или 1")
                return
            await update_game_slot(date_str, slot_num, pu=1 if text == "1" else 0)
            await message.answer(f"✅ ПУ {'включён' if text == '1' else 'выключен'}")

    except Exception as e:
        print(f"[EDIT_FIELD] Error: {e}")
        await message.answer("Ошибка при обновлении.")

    await state.clear()


# ======================= ТЕХФОЛЫ И УДАЛЕНИЕ =======================

@router.callback_query(F.data == "ignore")
async def ignore_callback(callback: types.CallbackQuery):
    await callback.answer()


@router.callback_query(F.data.startswith("fouls_kick_"))
async def editor_fouls_kick(callback: types.CallbackQuery):
    try:
        parts = callback.data.split("_")
        game_id = int(parts[2])
        slot_num = int(parts[3])
    except Exception as e:
        print(f"[FOULS_KICK] Error: {e}")
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    game, date_str, slots = await _get_game_info(game_id)
    if not game or not slots or slot_num not in slots:
        await callback.answer("Слот не найден.", show_alert=True)
        return

    current = int(slots[slot_num].get("kick") or 0)
    new_val = 0 if current else 1
    await update_game_slot(date_str, slot_num, kick=new_val)

    await callback.answer(f"Удаление {'включено' if new_val else 'выключено'}")

    slots[slot_num]["kick"] = new_val
    await callback.message.edit_text(
        f"⚠ **Техфолы и удаление слота {slot_num}**\n\n"
        f"Малый техфол: -0.3 балла в ДЦ\n"
        f"Большой техфол: -0.6 балла в ДЦ\n"
        f"2 техфола = автоматическое удаление\n"
        f"Удаление: помечает игрока как удалённого из игры",
        reply_markup=_build_fouls_menu_kb(game_id, slot_num, slots[slot_num]),
    )


@router.callback_query(F.data.startswith("fouls_small_"))
async def editor_fouls_tech_small(callback: types.CallbackQuery):
    try:
        parts = callback.data.split("_")
        game_id = int(parts[2])
        slot_num = int(parts[3])
    except Exception as e:
        print(f"[FOULS_SMALL] Error: {e}")
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    game, date_str, slots = await _get_game_info(game_id)
    if not game or not slots or slot_num not in slots:
        await callback.answer("Слот не найден.", show_alert=True)
        return

    current_tech = int(slots[slot_num].get("technical_fouls") or 0)
    current_dc = float(slots[slot_num].get("dc_points") or 0)

    new_tech = current_tech + 1
    new_dc = round(current_dc - 0.3, 1)

    await update_game_slot(date_str, slot_num, technical_fouls=new_tech, dc_points=new_dc)

    if new_tech >= 2:
        await update_game_slot(date_str, slot_num, kick=1)
        await callback.answer(f"⚠️ Игрок удалён за 2 техфола! Штраф -0.3 в ДЦ", show_alert=True)
    else:
        await callback.answer(f"Малый техфол: -0.3 к ДЦ")

    slots[slot_num]["technical_fouls"] = new_tech
    slots[slot_num]["dc_points"] = new_dc
    if new_tech >= 2:
        slots[slot_num]["kick"] = 1

    await callback.message.edit_text(
        f"⚠ **Техфолы и удаление слота {slot_num}**\n\n"
        f"Малый техфол: -0.3 балла в ДЦ\n"
        f"Большой техфол: -0.6 балла в ДЦ\n"
        f"2 техфола = автоматическое удаление\n"
        f"Удаление: помечает игрока как удалённого из игры",
        reply_markup=_build_fouls_menu_kb(game_id, slot_num, slots[slot_num]),
    )


@router.callback_query(F.data.startswith("fouls_big_"))
async def editor_fouls_tech_big(callback: types.CallbackQuery):
    try:
        parts = callback.data.split("_")
        game_id = int(parts[2])
        slot_num = int(parts[3])
    except Exception as e:
        print(f"[FOULS_BIG] Error: {e}")
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    game, date_str, slots = await _get_game_info(game_id)
    if not game or not slots or slot_num not in slots:
        await callback.answer("Слот не найден.", show_alert=True)
        return

    current_tech = int(slots[slot_num].get("technical_fouls") or 0)
    current_dc = float(slots[slot_num].get("dc_points") or 0)

    new_tech = current_tech + 1
    new_dc = round(current_dc - 0.6, 1)

    await update_game_slot(date_str, slot_num, technical_fouls=new_tech, dc_points=new_dc)

    if new_tech >= 2:
        await update_game_slot(date_str, slot_num, kick=1)
        await callback.answer(f"⚠️ Игрок удалён за 2 техфола! Штраф -0.6 в ДЦ", show_alert=True)
    else:
        await callback.answer(f"Большой техфол: -0.6 к ДЦ")

    slots[slot_num]["technical_fouls"] = new_tech
    slots[slot_num]["dc_points"] = new_dc
    if new_tech >= 2:
        slots[slot_num]["kick"] = 1

    await callback.message.edit_text(
        f"⚠ **Техфолы и удаление слота {slot_num}**\n\n"
        f"Малый техфол: -0.3 балла в ДЦ\n"
        f"Большой техфол: -0.6 балла в ДЦ\n"
        f"2 техфола = автоматическое удаление\n"
        f"Удаление: помечает игрока как удалённого из игры",
        reply_markup=_build_fouls_menu_kb(game_id, slot_num, slots[slot_num]),
    )


@router.callback_query(F.data.startswith("fouls_dec_"))
async def editor_fouls_tech_dec(callback: types.CallbackQuery):
    try:
        parts = callback.data.split("_")
        game_id = int(parts[2])
        slot_num = int(parts[3])
    except Exception as e:
        print(f"[FOULS_DEC] Error: {e}")
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    game, date_str, slots = await _get_game_info(game_id)
    if not game or not slots or slot_num not in slots:
        await callback.answer("Слот не найден.", show_alert=True)
        return

    current_tech = int(slots[slot_num].get("technical_fouls") or 0)
    new_tech = max(0, current_tech - 1)

    current_kick = int(slots[slot_num].get("kick") or 0)
    new_kick = 0 if current_kick == 1 and current_tech >= 2 else current_kick

    await update_game_slot(date_str, slot_num, technical_fouls=new_tech, kick=new_kick)
    await callback.answer(f"Техфолы: {current_tech} → {new_tech}")

    slots[slot_num]["technical_fouls"] = new_tech
    slots[slot_num]["kick"] = new_kick

    await callback.message.edit_text(
        f"⚠ **Техфолы и удаление слота {slot_num}**\n\n"
        f"Малый техфол: -0.3 балла в ДЦ\n"
        f"Большой техфол: -0.6 балла в ДЦ\n"
        f"2 техфола = автоматическое удаление\n"
        f"Удаление: помечает игрока как удалённого из игры",
        reply_markup=_build_fouls_menu_kb(game_id, slot_num, slots[slot_num]),
    )


@router.callback_query(F.data.startswith("editor_fouls:"))
async def editor_fouls_menu(callback: types.CallbackQuery):
    """Меню управления техфолами."""
    try:
        parts = callback.data.split(":")
        if len(parts) != 3:
            await callback.answer("Некорректный формат данных.", show_alert=True)
            return
        game_id = int(parts[1])
        slot_num = int(parts[2])
    except Exception as e:
        print(f"[FOULS_MENU] Error: {e}")
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    game, date_str, slots = await _get_game_info(game_id)
    if not game or not slots or slot_num not in slots:
        await callback.answer("Слот не найден.", show_alert=True)
        return

    await callback.message.edit_text(
        f"⚠ **Техфолы и удаление слота {slot_num}**\n\n"
        f"Малый техфол: -0.3 балла в ДЦ\n"
        f"Большой техфол: -0.6 балла в ДЦ\n"
        f"2 техфола = автоматическое удаление\n"
        f"Удаление: помечает игрока как удалённого из игры",
        reply_markup=_build_fouls_menu_kb(game_id, slot_num, slots[slot_num]),
    )
    await callback.answer()


# ======================= РЕДАКТОР ИСХОДА =======================

def _build_outcome_menu_kb(game_id: int) -> InlineKeyboardMarkup:
    """Меню выбора исхода."""
    kb = [
        [InlineKeyboardButton(text="🔴 Победа города", callback_data=f"editor_outcome_set:city:{game_id}")],
        [InlineKeyboardButton(text="⚫ Победа мафии", callback_data=f"editor_outcome_set:mafia:{game_id}")],
        [InlineKeyboardButton(text="⚠ ППК (с выбором виновника)", callback_data=f"editor_outcome_set:ppk:{game_id}")],
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data=f"editor_back:{game_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _build_ppk_team_kb(game_id: int) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="🔴 Победа города (Красные)", callback_data=f"editor_ppk_team:red:{game_id}")],
        [InlineKeyboardButton(text="⚫ Победа мафии (Чёрные)", callback_data=f"editor_ppk_team:black:{game_id}")],
        [InlineKeyboardButton(text="◀️ Назад к исходу", callback_data=f"editor_outcome:{game_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _build_ppk_culprit_kb(game_id: int, slots: dict, losing_team: str) -> InlineKeyboardMarkup:
    buttons = []
    for slot_num, slot in slots.items():
        if not isinstance(slot_num, int):
            continue
        if slot.get("team") == losing_team:
            name = slot.get("nickname") or slot.get("full_name") or f"Игрок {slot_num}"
            buttons.append([InlineKeyboardButton(text=f"{slot_num}. {name}", callback_data=f"editor_ppk_culprit:{game_id}:{slot_num}")])

    buttons.append([InlineKeyboardButton(text="◀️ Назад к выбору команды", callback_data=f"editor_outcome_set:ppk:{game_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data.startswith("editor_outcome:"))
async def editor_outcome(callback: types.CallbackQuery):
    """Меню смены исхода."""
    try:
        game_id = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    game, date_str, slots = await _get_game_info(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    await callback.message.edit_text(
        f"🏆 **Смена исхода игры**\n\n"
        f"Текущий результат: {game.get('winner_label', 'Не указан')}\n\n"
        f"Выбери новый исход:",
        reply_markup=_build_outcome_menu_kb(game_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("editor_outcome_set:"))
async def editor_outcome_set(callback: types.CallbackQuery, state: FSMContext):
    """Установка исхода (город/мафия/ППК)."""
    try:
        _, outcome, game_id_str = callback.data.split(":", 2)
        game_id = int(game_id_str)
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    game, date_str, slots = await _get_game_info(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    if outcome in ("city", "mafia"):
        if outcome == "city":
            winning_team = "Красные"
            winner_label = "Победа города"
        else:
            winning_team = "Чёрные"
            winner_label = "Победа мафии"

        for slot_num, slot in slots.items():
            if not isinstance(slot_num, int):
                continue
            team = slot.get("team")
            base_val = 1 if team == winning_team else 0
            await update_game_slot(date_str, slot_num, base_points=base_val)

        await update_game_outcome(game_id, winner_label=winner_label)

        await callback.answer(f"✅ Исход изменён на: {winner_label}")
        await editor_back(callback, state)
        return

    if outcome == "ppk":
        await state.set_state(EditGameState.ppk_winning_team)
        await state.update_data(game_id=game_id)
        await callback.message.edit_text(
            "⚠ **ППК (Победа противоположной команды)**\n\n"
            "Выбери победившую команду:",
            reply_markup=_build_ppk_team_kb(game_id),
        )
        await callback.answer()
        return


@router.callback_query(EditGameState.ppk_winning_team, F.data.startswith("editor_ppk_team:"))
async def editor_ppk_team(callback: types.CallbackQuery, state: FSMContext):
    """Выбор команды-победителя при ППК."""
    try:
        _, team, game_id_str = callback.data.split(":", 2)
        game_id = int(game_id_str)
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    game, date_str, slots = await _get_game_info(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    if team == "red":
        winning_team = "Красные"
        losing_team = "Чёрные"
    else:
        winning_team = "Чёрные"
        losing_team = "Красные"

    await state.update_data(winning_team=winning_team, losing_team=losing_team, game_id=game_id)
    await state.set_state(EditGameState.ppk_culprit_select)

    await callback.message.edit_text(
        f"⚠ **ППК**\n\n"
        f"Победившая команда: {winning_team}\n\n"
        f"Выбери виновника из команды {losing_team}:",
        reply_markup=_build_ppk_culprit_kb(game_id, slots, losing_team),
    )
    await callback.answer()


@router.callback_query(EditGameState.ppk_culprit_select, F.data.startswith("editor_ppk_culprit:"))
async def editor_ppk_culprit(callback: types.CallbackQuery, state: FSMContext):
    """Выбор виновника ППК и применение штрафа."""
    try:
        _, game_id_str, slot_str = callback.data.split(":", 2)
        game_id = int(game_id_str)
        slot_num = int(slot_str)
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    data = await state.get_data()
    winning_team = data.get("winning_team")
    losing_team = data.get("losing_team")

    game, date_str, slots = await _get_game_info(game_id)
    if not game or not slots or slot_num not in slots:
        await callback.answer("Слот не найден.", show_alert=True)
        return

    culprit = slots[slot_num]
    culprit_name = culprit.get("nickname") or culprit.get("full_name") or f"Игрок {slot_num}"

    # Штраф виновнику: -1.5 к ДЦ
    current_dc = float(culprit.get("dc_points") or 0)
    new_dc = round(current_dc - 1.5, 1)
    await update_game_slot(date_str, slot_num, dc_points=new_dc, ppk=1, kick=1)

    for num, slot in slots.items():
        if not isinstance(num, int):
            continue
        team = slot.get("team")
        base_val = 1 if team == winning_team else 0
        await update_game_slot(date_str, num, base_points=base_val)

    winner_label = f"ППК: {winning_team} (Виновник: {culprit_name})"
    await update_game_outcome(game_id, winner_label=winner_label)

    await state.clear()

    await callback.answer(f"⚠ ППК применена! Виновник: {culprit_name}")
    await editor_back(callback, state)


# ======================= ПОДТВЕРЖДЕНИЕ И ЗАКРЫТИЕ =======================

@router.callback_query(F.data.startswith("editor_confirm:"))
async def editor_confirm(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    """Подтверждение изменений - обновляем исходное сообщение с протоколом."""
    try:
        game_id = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    data = await state.get_data()
    protocol_chat_id = data.get("protocol_chat_id")
    protocol_message_id = data.get("protocol_message_id")

    game, date_str, slots = await _get_game_info(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    winner_label = game.get("winner_label") or "Результат не указан"

    if protocol_chat_id and protocol_message_id:
        try:
            protocol_text = _build_protocol_text(game, slots, winner_label)
            game_number = game.get("game_number") or 0
            global_game_number = game.get("global_game_number") or 0

            if slots:
                img_path = create_endgame_pic_summary(
                    slots=slots,  # slots уже чистый!
                    game_date=date_str,
                    evening_game_number=game_number or 0,
                    global_game_number=global_game_number or 0,
                    winner_label=winner_label,
                )
                doc = FSInputFile(img_path)
                timestamp = int(time.time())

                await bot.edit_message_media(
                    chat_id=protocol_chat_id,
                    message_id=protocol_message_id,
                    media=types.InputMediaDocument(
                        media=doc,
                        caption=f"{protocol_text}\n\n🕐 Обновлено: {timestamp}",
                        parse_mode=ParseMode.HTML,
                    ),
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✏️ Открыть редактор", callback_data=f"editor_open:{game_id}")],
                        [InlineKeyboardButton(text="🔄 Обновить протокол", callback_data=f"refresh_protocol:{game_id}")],
                    ]),
                )
                _cleanup_old_files("endgame_summary_", keep=10)
            else:
                await bot.edit_message_text(
                    chat_id=protocol_chat_id,
                    message_id=protocol_message_id,
                    text=f"{protocol_text}\n\n🕐 Обновлено: {int(time.time())}",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✏️ Открыть редактор", callback_data=f"editor_open:{game_id}")],
                        [InlineKeyboardButton(text="🔄 Обновить протокол", callback_data=f"refresh_protocol:{game_id}")],
                    ]),
                )
        except Exception as e:
            print(f"[CONFIRM] Error: {e}")
            await callback.answer("Ошибка при обновлении протокола", show_alert=True)
            return

    await callback.answer("✅ Изменения сохранены! Протокол обновлён.")

    try:
        await callback.message.delete()
    except Exception:
        pass

    await state.clear()


@router.callback_query(F.data.startswith("editor_close:"))
async def editor_close(callback: types.CallbackQuery, state: FSMContext):
    """Закрыть редактор."""
    await state.clear()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer("Редактор закрыт.")