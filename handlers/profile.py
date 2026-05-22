import os
import time
import re
from typing import Dict, Any, List, Tuple
from collections import defaultdict

from aiogram import Router, F, types
from aiogram.enums import ParseMode
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

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
    get_elo,
    get_players_elo_rating,
    get_user_by_id,
)
from keyboards import games_list_kb
from pic_profile import create_profile_pic
from game.utils.endgame_pic import create_endgame_pic_summary

router = Router()

TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from typing import Callable, Awaitable


# --- ЗАЩИТА РЕДАКТОРА ---
async def check_is_editor(user_id: int) -> bool:
    """Проверяет права на редактирование (админ/судья)"""

    # 1. Проверяем через твою базу данных, назначен ли человек судьей
    is_judge = await database.is_game_judge(user_id)
    if is_judge:
        return True

    # 2. Главные админы (создатель бота).
    # Впиши сюда свой Telegram ID, чтобы у тебя всегда был доступ,
    # даже если ты забыл назначить себя судьей через меню бота.
    admin_ids = [123456789]  # <-- Удали 123456789 и впиши свои цифры!

    if user_id in admin_ids:
        return True

    return False


class EditorProtectionMiddleware(BaseMiddleware):
    """Мидлварь, которая блокирует ВСЕ действия редактора для обычных игроков"""

    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: Dict[str, Any]
    ) -> Any:
        user_id = None
        is_edit_action = False

        # Перехватываем нажатия на инлайн-кнопки редактора
        if isinstance(event, types.CallbackQuery) and event.data and event.data.startswith("editgame_"):
            user_id = event.from_user.id
            is_edit_action = True

        # Перехватываем текстовый ввод (когда бот просит ввести очки или фолы)
        elif isinstance(event, types.Message):
            state = data.get("state")
            if state:
                curr_state = await state.get_state()
                if curr_state and curr_state.startswith("EditGame"):
                    user_id = event.from_user.id
                    is_edit_action = True

        # Если это действие редактора — проверяем права
        if is_edit_action and user_id:
            if not await check_is_editor(user_id):
                if isinstance(event, types.CallbackQuery):
                    await event.answer("⛔ Доступ запрещен. Только администраторы и судьи могут редактировать игры.",
                                       show_alert=True)
                elif isinstance(event, types.Message):
                    await event.answer("⛔ У вас нет прав для редактирования.")
                return  # Жёстко прерываем выполнение!

        return await handler(event, data)


# Подключаем охранника к роутеру
router.callback_query.middleware(EditorProtectionMiddleware())
router.message.middleware(EditorProtectionMiddleware())


# -------------------------

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
    buttons.append([InlineKeyboardButton(text="✏️ Изменить номер/дату", callback_data=f"editgame_metadata:{game_id}")])
    buttons.append([InlineKeyboardButton(text="🗑 Удалить игру", callback_data=f"editgame_delete_confirm:{game_id}")])

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
    kb = [
        [
            InlineKeyboardButton(text="🎭 Роль", callback_data=f"editgame_field:role:{game_id}:{slot_num}"),
            InlineKeyboardButton(text="📊 Статус", callback_data=f"editgame_field:status:{game_id}:{slot_num}"),
        ],
        [
            InlineKeyboardButton(text="🎲 Очки", callback_data=f"editgame_field:points:{game_id}:{slot_num}"),
            InlineKeyboardButton(text="⚠️ Фолы/Техфолы", callback_data=f"editgame_field:fouls:{game_id}:{slot_num}"),
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
            InlineKeyboardButton(text="👤 Заменить игрока", callback_data=f"editgame_replace_init:{game_id}:{slot_num}")
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
    waiting_for_replacement = State()  # Состояние для замены игрока

class EditGameMetadataState(StatesGroup):
    waiting_for_new_number = State()
    waiting_for_new_date = State()


# ======================= НОВЫЕ ФУНКЦИИ ДЛЯ НАВИГАЦИИ ПО ИГРАМ =======================

async def get_all_game_dates() -> List[Tuple[str, int]]:
    """Возвращает список дат, в которые были игры, и количество игр в эту дату"""
    async with database.get_db() as conn:
        async with conn.execute("""
            SELECT game_date, COUNT(*) as games_count
            FROM game_history
            GROUP BY game_date
            ORDER BY 
                CASE 
                    WHEN LENGTH(game_date) = 5 THEN substr(game_date, 4, 2) || substr(game_date, 1, 2)
                    ELSE substr(game_date, 7, 4) || substr(game_date, 4, 2) || substr(game_date, 1, 2)
                END ASC
        """) as cur:
            return await cur.fetchall()


def get_games_by_date_kb(dates: List[Tuple[str, int]], prefix: str) -> InlineKeyboardMarkup:
    """Клавиатура для выбора даты (с красивым отображением)"""
    builder = []
    for date_str, count in dates:
        # Конвертируем ISO дату в ДД.ММ.ГГГГ только для ТЕКСТА на кнопке
        display_date = database.format_date_to_user(date_str)

        builder.append([InlineKeyboardButton(
            text=f"📅 {display_date} ({count} игр)",
            callback_data=f"{prefix}_date:{date_str}"  # Внутри остается 2026-05-13 для поиска
        )])
    builder.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_games_menu")])
    return InlineKeyboardMarkup(inline_keyboard=builder)


def get_games_by_date_inline_kb(games: List[Dict], date_str: str, prefix: str) -> InlineKeyboardMarkup:
    """Клавиатура для выбора игры из конкретной даты"""
    builder = []
    for game in games:
        game_id = game["id"]
        game_number = game.get("game_number", "?")
        winner = game.get("winner_label", "")
        winner_icon = "🏙" if "город" in winner.lower() else "💀" if "мафи" in winner.lower() else "⚠️"
        builder.append([InlineKeyboardButton(
            text=f"🎮 №{game_number} {winner_icon}",
            callback_data=f"{prefix}_game:{game_id}"
        )])
    builder.append([InlineKeyboardButton(text="◀️ Назад к датам", callback_data=f"{prefix}_back_to_dates")])
    builder.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="close_games")])
    return InlineKeyboardMarkup(inline_keyboard=builder)


# ======================= ОСНОВНЫЕ ХЕНДЛЕРЫ =======================

@router.message(F.text == "📊 Статистика")
async def show_user_stats(message: types.Message):
    user_id = message.from_user.id
    try:
        stats_data = await stats_utils.build_user_stats_data(user_id)
        nickname = stats_data.get("nickname") or message.from_user.full_name

        elo = await get_elo(user_id)
        stats_data["elo"] = elo

        img_path = create_profile_pic(nickname, stats_data)
        text = await stats_utils.build_user_stats_text(user_id)

        text = f"🏆 **Рейтинг Эло: {elo}**\n\n{text}"

        doc = FSInputFile(img_path)
        timestamp = int(time.time())
        await message.answer_document(document=doc, caption=f"{text}\n\n🕐 Обновлено: {timestamp}",
                                      parse_mode=ParseMode.MARKDOWN)
        _cleanup_old_files("profile_", keep=10)
    except Exception as e:
        print(f"[PROFILE][ERROR] {e}")
        text = await stats_utils.build_user_stats_text(user_id)
        elo = await get_elo(user_id)
        text = f"🏆 **Рейтинг Эло: {elo}**\n\n{text}"
        await message.answer(text)


# ======================= ВСЕ ИГРЫ (НОВАЯ ЛОГИКА) =======================

@router.message(F.text == "📜 Все игры")
async def show_all_games_dates(message: types.Message):
    """Показывает список дат, в которые были игры"""
    dates = await get_all_game_dates()
    if not dates:
        await message.answer("📭 Пока нет завершённых игр.")
        return

    kb = get_games_by_date_kb(dates, "allgames")
    await message.answer("📅 **Выберите дату,** чтобы посмотреть игры этого вечера:", reply_markup=kb,
                         parse_mode=ParseMode.MARKDOWN)


@router.callback_query(F.data.startswith("allgames_date:"))
async def show_games_by_date(callback: types.CallbackQuery):
    """Показывает игры за выбранную дату"""
    date_str = callback.data.split(":", 1)[1]

    # Получаем игры за эту дату
    async with database.get_db() as conn:
        async with conn.execute("""
                                SELECT id, game_date, game_number, winner_label
                                FROM game_history
                                WHERE game_date = ?
                                ORDER BY game_number
                                """, (date_str,)) as cur:
            games = await cur.fetchall()

    games_list = [{"id": g[0], "game_date": g[1], "game_number": g[2], "winner_label": g[3]} for g in games]

    if not games_list:
        await callback.answer("Нет игр за эту дату", show_alert=True)
        return

    kb = get_games_by_date_inline_kb(games_list, date_str, "allgames")
    await callback.message.edit_text(
        f"📅 **Игры за {date_str}:**\n\nВыберите игру для просмотра протокола:",
        reply_markup=kb,
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()


@router.callback_query(F.data.startswith("allgames_game:"))
async def show_game_by_id(callback: types.CallbackQuery):
    """Показывает протокол выбранной игры"""
    game_id = int(callback.data.split(":", 1)[1])

    game = await get_game_by_id(game_id)
    if not game:
        await callback.answer("Игра не найдена", show_alert=True)
        return

    date_str = game.get("game_date") or "-"
    winner_label = game.get("winner_label") or "Результат не указан"
    game_number = game.get("game_number")
    global_game_number = game.get("global_game_number") or 0
    judge_id = game.get("judge_id")

    judge_name = None
    if judge_id:
        user_info = await get_user_by_id(judge_id)
        if user_info:
            _, full_name, username, nickname = user_info
            judge_name = nickname or full_name or username

    slots = await get_game_slots_by_date(date_str, game_number=game_number)
    if not slots:
        await callback.answer("Нет слотов игры", show_alert=True)
        return

    night_kills_order = await get_night_kills_order(date_str, game_number or 0)
    filtered_order = []
    for slot_num in night_kills_order:
        if slot_num in slots:
            status_reason = slots[slot_num].get("status_reason", "")
            if "убит" in status_reason.lower() and "заголосован" not in status_reason.lower():
                filtered_order.append(slot_num)
    slots["_night_kills_order"] = filtered_order

    from game.text import build_protocol_text
    protocol_body = await build_protocol_text(slots, winner_label=winner_label)

    header = f"📑 Протокол игры №{game_number} ({date_str}): {winner_label}"
    if global_game_number:
        header += f" — №{global_game_number} по общей истории"

    if judge_name:
        full_text = f"{header}\n\n<b>Судья:</b> {judge_name}\n\n{protocol_body}"
    else:
        full_text = f"{header}\n\n{protocol_body}"

    # --- ПРАВИЛЬНАЯ ПРОВЕРКА ПРАВ И СБОРКА КНОПОК ---
    is_editor = await check_is_editor(callback.from_user.id)
    kb_buttons = []

    if is_editor:
        kb_buttons.append(
            [InlineKeyboardButton(text="✏️ Редактировать игру", callback_data=f"editgame_menu:{game_id}")])

    kb_buttons.append([InlineKeyboardButton(text="◀️ Назад к дате", callback_data=f"allgames_date:{date_str}")])
    kb_buttons.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="close_games")])

    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    # -------------------------------------------------

    timestamp = int(time.time())

    try:
        img_path = create_endgame_pic_summary(
            slots=slots, game_date=date_str,
            evening_game_number=game_number or 0,
            global_game_number=global_game_number or 0,
            winner_label=winner_label,
            judge_name=judge_name,
        )
        doc = FSInputFile(img_path)

        await callback.message.answer_document(document=doc, caption=None)
        await callback.message.answer(
            f"{full_text}\n\n🕐 Обновлено: {timestamp}",
            parse_mode=ParseMode.HTML,
            reply_markup=kb
        )
        _cleanup_old_files("endgame_summary_", keep=10)
    except Exception as e:
        print(f"[GAME_PROTOCOL][ERROR] {e}")
        await callback.message.answer(
            f"{full_text}\n\n🕐 Обновлено: {timestamp}",
            parse_mode=ParseMode.HTML,
            reply_markup=kb
        )

    await callback.answer()


# ======================= МОИ ИГРЫ (НОВАЯ ЛОГИКА) =======================

@router.message(F.text == "📜 Мои игры")
async def show_my_games_dates(message: types.Message):
    """Показывает список дат, в которые пользователь играл"""
    user_id = message.from_user.id

    async with database.get_db() as conn:
        async with conn.execute("""
                                SELECT DISTINCT g.game_date, COUNT(*) as games_count
                                FROM game_history g
                                         JOIN game_slots_history s
                                              ON g.game_date = s.game_date AND g.game_number = s.game_number
                                WHERE s.user_id = ?
                                GROUP BY g.game_date
                                ORDER BY g.game_date DESC
                                """, (user_id,)) as cur:
            dates = await cur.fetchall()

    if not dates:
        await message.answer("📭 У вас пока нет сыгранных игр.")
        return

    kb = get_games_by_date_kb(dates, "mygames")
    await message.answer("📅 **Выберите дату,** чтобы посмотреть ваши игры в этот вечер:", reply_markup=kb,
                         parse_mode=ParseMode.MARKDOWN)


@router.callback_query(F.data.startswith("mygames_date:"))
async def show_my_games_by_date(callback: types.CallbackQuery):
    """Показывает игры пользователя за выбранную дату"""
    date_str = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id

    async with database.get_db() as conn:
        async with conn.execute("""
                                SELECT DISTINCT g.id, g.game_date, g.game_number, g.winner_label
                                FROM game_history g
                                         JOIN game_slots_history s
                                              ON g.game_date = s.game_date AND g.game_number = s.game_number
                                WHERE s.user_id = ?
                                  AND g.game_date = ?
                                ORDER BY g.game_number
                                """, (user_id, date_str)) as cur:
            games = await cur.fetchall()

    games_list = [{"id": g[0], "game_date": g[1], "game_number": g[2], "winner_label": g[3]} for g in games]

    if not games_list:
        await callback.answer("Нет ваших игр за эту дату", show_alert=True)
        return

    kb = get_games_by_date_inline_kb(games_list, date_str, "mygames")
    await callback.message.edit_text(
        f"📅 **Ваши игры за {date_str}:**\n\nВыберите игру для просмотра протокола:",
        reply_markup=kb,
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mygames_game:"))
async def show_my_game_by_id(callback: types.CallbackQuery):
    """Показывает протокол выбранной игры пользователя"""
    game_id = int(callback.data.split(":", 1)[1])

    game = await get_game_by_id(game_id)
    if not game:
        await callback.answer("Игра не найдена", show_alert=True)
        return

    date_str = game.get("game_date") or "-"
    winner_label = game.get("winner_label") or "Результат не указан"
    game_number = game.get("game_number")
    global_game_number = game.get("global_game_number") or 0
    judge_id = game.get("judge_id")

    judge_name = None
    if judge_id:
        user_info = await get_user_by_id(judge_id)
        if user_info:
            _, full_name, username, nickname = user_info
            judge_name = nickname or full_name or username

    slots = await get_game_slots_by_date(date_str, game_number=game_number)
    if not slots:
        await callback.answer("Нет слотов игры", show_alert=True)
        return

    night_kills_order = await get_night_kills_order(date_str, game_number or 0)
    filtered_order = []
    for slot_num in night_kills_order:
        if slot_num in slots:
            status_reason = slots[slot_num].get("status_reason", "")
            if "убит" in status_reason.lower() and "заголосован" not in status_reason.lower():
                filtered_order.append(slot_num)
    slots["_night_kills_order"] = filtered_order

    from game.text import build_protocol_text
    protocol_body = await build_protocol_text(slots, winner_label=winner_label)

    header = f"📑 Протокол игры №{game_number} ({date_str}): {winner_label}"
    if global_game_number:
        header += f" — №{global_game_number} по общей истории"

    if judge_name:
        full_text = f"{header}\n\n<b>Судья:</b> {judge_name}\n\n{protocol_body}"
    else:
        full_text = f"{header}\n\n{protocol_body}"

    # --- ПРАВИЛЬНАЯ ПРОВЕРКА ПРАВ И СБОРКА КНОПОК ---
    is_editor = await check_is_editor(callback.from_user.id)
    kb_buttons = []

    if is_editor:
        kb_buttons.append(
            [InlineKeyboardButton(text="✏️ Редактировать игру", callback_data=f"editgame_menu:{game_id}")])

    kb_buttons.append([InlineKeyboardButton(text="◀️ Назад к дате", callback_data=f"mygames_date:{date_str}")])
    kb_buttons.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="close_games")])

    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    # -------------------------------------------------

    timestamp = int(time.time())

    try:
        img_path = create_endgame_pic_summary(
            slots=slots, game_date=date_str,
            evening_game_number=game_number or 0,
            global_game_number=global_game_number or 0,
            winner_label=winner_label,
            judge_name=judge_name,
        )
        doc = FSInputFile(img_path)

        await callback.message.answer_document(document=doc, caption=None)
        await callback.message.answer(
            f"{full_text}\n\n🕐 Обновлено: {timestamp}",
            parse_mode=ParseMode.HTML,
            reply_markup=kb
        )
        _cleanup_old_files("endgame_summary_", keep=10)
    except Exception as e:
        print(f"[GAME_PROTOCOL][ERROR] {e}")
        await callback.message.answer(
            f"{full_text}\n\n🕐 Обновлено: {timestamp}",
            parse_mode=ParseMode.HTML,
            reply_markup=kb
        )

    await callback.answer()


@router.callback_query(F.data == "back_to_games_menu")
async def back_to_games_menu(callback: types.CallbackQuery):
    """Возврат к списку дат"""
    dates = await get_all_game_dates()
    if not dates:
        await callback.message.edit_text("📭 Пока нет завершённых игр.")
        await callback.answer()
        return

    kb = get_games_by_date_kb(dates, "allgames")
    try:
        await callback.message.edit_text(
            "📅 **Выберите дату,** чтобы посмотреть игры этого вечера:",
            reply_markup=kb,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception:
        # Игнорируем ошибку "message is not modified"
        pass
    await callback.answer()


@router.callback_query(F.data == "close_games")
async def close_games(callback: types.CallbackQuery):
    """Закрывает окно с играми"""
    await callback.message.delete()
    await callback.answer()


@router.callback_query(F.data.startswith("allgames_back_to_dates"))
async def allgames_back_to_dates(callback: types.CallbackQuery):
    """Возврат к списку дат из allgames"""
    dates = await get_all_game_dates()
    if not dates:
        await callback.message.edit_text("📭 Пока нет завершённых игр.")
        await callback.answer()
        return

    kb = get_games_by_date_kb(dates, "allgames")
    await callback.message.edit_text(
        "📅 **Выберите дату,** чтобы посмотреть игры этого вечера:",
        reply_markup=kb,
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mygames_back_to_dates"))
async def mygames_back_to_dates(callback: types.CallbackQuery):
    """Возврат к списку дат из mygames"""
    user_id = callback.from_user.id

    async with database.get_db() as conn:
        async with conn.execute("""
                                SELECT DISTINCT g.game_date, COUNT(*) as games_count
                                FROM game_history g
                                         JOIN game_slots_history s
                                              ON g.game_date = s.game_date AND g.game_number = s.game_number
                                WHERE s.user_id = ?
                                GROUP BY g.game_date
                                ORDER BY g.game_date DESC
                                """, (user_id,)) as cur:
            dates = await cur.fetchall()

    if not dates:
        await callback.message.edit_text("📭 У вас пока нет сыгранных игр.")
        await callback.answer()
        return

    kb = get_games_by_date_kb(dates, "mygames")
    await callback.message.edit_text(
        "📅 **Выберите дату,** чтобы посмотреть ваши игры в этот вечер:",
        reply_markup=kb,
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()


# ======================= ОСТАЛЬНЫЕ ФУНКЦИИ (MVP, РЕЙТИНГ, РЕДАКТИРОВАНИЕ) =======================

async def get_mvp() -> tuple:
    async with database.get_db() as conn:
        async with conn.execute("""
                                SELECT u.nickname,
                                       u.full_name,
                                       COALESCE(SUM(s.bonus_points + s.lh_points + s.will_protocol_points +
                                                    s.will_opinion_points + s.dc_points), 0) as total_bonus
                                FROM game_slots_history s
                                         JOIN users u ON s.user_id = u.user_id
                                GROUP BY s.user_id
                                HAVING total_bonus > 0
                                ORDER BY total_bonus DESC
                                LIMIT 1
                                """) as cur:
            row = await cur.fetchone()
            if row:
                name = row[0] or row[1] or "Неизвестный"
                return name, round(row[2], 1)
    return None, 0


async def get_best_by_role(role_name: str) -> tuple:
    async with database.get_db() as conn:
        async with conn.execute("""
                                SELECT u.nickname,
                                       u.full_name,
                                       COALESCE(SUM(s.bonus_points + s.lh_points + s.will_protocol_points +
                                                    s.will_opinion_points + s.dc_points), 0) as total_bonus
                                FROM game_slots_history s
                                         JOIN users u ON s.user_id = u.user_id
                                WHERE s.role = ?
                                GROUP BY s.user_id
                                HAVING total_bonus > 0
                                ORDER BY total_bonus DESC
                                LIMIT 1
                                """, (role_name,)) as cur:
            row = await cur.fetchone()
            if row:
                name = row[0] or row[1] or "Неизвестный"
                return name, round(row[2], 1)
    return None, 0


@router.message(F.text == "🏆 Рейтинг")
async def show_rating(message: types.Message):
    """Показывает общий рейтинг игроков по Эло + MVP + лучшие по ролям с пагинацией"""

    # Получаем всех игроков с Эло
    rating = await get_players_elo_rating(limit=100)

    if not rating:
        await message.answer("📊 Пока нет данных для рейтинга Эло.")
        return

    rating = [p for p in rating if p["games_played"] > 0]

    if not rating:
        await message.answer("📊 Пока нет игроков, сыгравших хотя бы одну игру.")
        return

    # Сохраняем кэш в боте
    if not hasattr(message.bot, "rating_cache"):
        message.bot.rating_cache = {}
    message.bot.rating_cache[message.chat.id] = rating

    # Показываем первую страницу
    await show_rating_page(message, 0, rating)


def build_compact_rating_page(players: list, page: int, total_pages: int, total_players: int, mvp_data: tuple,
                              roles_data: dict) -> str:
    """Генерирует компактный и красивый текст для страницы рейтинга."""
    lines = [
        f"🏆 **РЕЙТИНГ ЭЛО** • Страница {page}/{total_pages}",
        f"👥 Всего игроков: {total_players}\n",
        "```"  # Начинаем моноширинный блок для основного рейтинга
    ]

    for p in players:
        pos = p["place"]
        name = p["nickname"] or "Неизвестный"
        elo = p["elo"]
        games = p["games_played"]
        wins = p["games_won"]
        winrate = int((wins / games * 100)) if games > 0 else 0

        icon = f"{pos:2}."
        name_pad = name[:12].ljust(12)
        games_pad = f"{games:>2}"
        wins_pad = f"{wins:>2}"
        win_pad = f"{winrate:>3}"

        lines.append(f"{icon} {name_pad} • {elo} ⚜️ | Игр: {games_pad} | Побед: {wins_pad} ({win_pad}%)")

    lines.append("```\n")

    # Показываем номинации только на первой странице
    if page == 1:
        mvp_name, mvp_score = mvp_data
        if mvp_name and mvp_score > 0:
            lines.append(f"🌟 **MVP (Общий Доп):** {mvp_name} (+{mvp_score})\n")

        if roles_data:
            lines.append("🎭 **Лучшие по ролям:**")
            lines.append("```")  # Открываем второй моноширинный блок для ролей

            # Строгий порядок ролей
            for role_name in ["Мирный", "Шериф", "Мафия", "Дон"]:
                if role_name in roles_data:
                    name, score = roles_data[role_name]

                    # Выравнивание: Роль (6 символов), Имя (12 символов)
                    role_pad = role_name.ljust(6)
                    name_pad = name[:12].ljust(12)
                    score_pad = f"+{score:.1f}"

                    lines.append(f"{role_pad} | {name_pad} | {score_pad}")

            lines.append("```")

    return "\n".join(lines)


async def show_rating_page(message: types.Message, page: int, rating: list):
    """Показывает конкретную страницу рейтинга (Новое сообщение)"""
    page_size = 10
    total_players = len(rating)
    total_pages = (total_players + page_size - 1) // page_size
    start_idx = page * page_size
    end_idx = min(start_idx + page_size, total_players)
    current_page_players = rating[start_idx:end_idx]

    # Подгружаем номинации только для 1 страницы
    mvp_data = await get_mvp() if page == 0 else (None, 0)
    roles_data = {}
    if page == 0:
        for role_name in ["Мирный", "Шериф", "Мафия", "Дон"]:
            best_name, best_bonus = await get_best_by_role(role_name)
            if best_name and best_bonus > 0:
                # Теперь мы сохраняем и имя, и баллы!
                roles_data[role_name] = (best_name, best_bonus)

    text = build_compact_rating_page(
        players=current_page_players,
        page=page + 1,
        total_pages=total_pages,
        total_players=total_players,
        mvp_data=mvp_data,
        roles_data=roles_data
    )

    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.button(text="◀️ Назад", callback_data=f"rating_page:{page - 1}")
    if page < total_pages - 1:
        builder.button(text="Вперед ▶️", callback_data=f"rating_page:{page + 1}")

    builder.button(text="ℹ️ Как считается рейтинг?", callback_data="rating_rules")
    builder.button(text="❌ Закрыть", callback_data="rating_close")

    if page > 0 and page < total_pages - 1:
        builder.adjust(2, 1, 1)
    else:
        builder.adjust(1, 1, 1)

    await message.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=builder.as_markup())


async def show_rating_page_from_callback(callback: types.CallbackQuery, page: int, rating: list):
    """Показывает страницу рейтинга (Редактирование сообщения по кнопке)"""
    page_size = 10
    total_players = len(rating)
    total_pages = (total_players + page_size - 1) // page_size
    start_idx = page * page_size
    end_idx = min(start_idx + page_size, total_players)
    current_page_players = rating[start_idx:end_idx]

    mvp_data = await get_mvp() if page == 0 else (None, 0)
    roles_data = {}
    if page == 0:
        for role_name in ["Мирный", "Шериф", "Мафия", "Дон"]:
            best_name, best_bonus = await get_best_by_role(role_name)
            if best_name and best_bonus > 0:
                # Теперь мы сохраняем и имя, и баллы!
                roles_data[role_name] = (best_name, best_bonus)

    text = build_compact_rating_page(
        players=current_page_players,
        page=page + 1,
        total_pages=total_pages,
        total_players=total_players,
        mvp_data=mvp_data,
        roles_data=roles_data
    )

    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.button(text="◀️ Назад", callback_data=f"rating_page:{page - 1}")
    if page < total_pages - 1:
        builder.button(text="Вперед ▶️", callback_data=f"rating_page:{page + 1}")

    builder.button(text="ℹ️ Как считается рейтинг?", callback_data="rating_rules")
    builder.button(text="❌ Закрыть", callback_data="rating_close")

    if page > 0 and page < total_pages - 1:
        builder.adjust(2, 1, 1)
    else:
        builder.adjust(1, 1, 1)

    await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("rating_page:"))
async def rating_page_callback(callback: types.CallbackQuery):
    """Обработчик переключения страниц рейтинга"""
    page = int(callback.data.split(":")[1])

    if not hasattr(callback.bot, "rating_cache") or callback.message.chat.id not in callback.bot.rating_cache:
        await callback.answer("Данные устарели, нажмите '🏆 Рейтинг' заново", show_alert=True)
        return

    rating = callback.bot.rating_cache[callback.message.chat.id]
    await show_rating_page_from_callback(callback, page, rating)


async def show_rating_page_from_callback(callback: types.CallbackQuery, page: int, rating: list):
    """Показывает страницу рейтинга (Редактирование сообщения по кнопке)"""
    page_size = 10
    total_players = len(rating)
    total_pages = (total_players + page_size - 1) // page_size
    start_idx = page * page_size
    end_idx = min(start_idx + page_size, total_players)
    current_page_players = rating[start_idx:end_idx]

    mvp_data = await get_mvp() if page == 0 else (None, 0)
    roles_data = {}
    if page == 0:
        for role_name in ["Мирный", "Шериф", "Мафия", "Дон"]:
            best_name, best_bonus = await get_best_by_role(role_name)
            if best_name and best_bonus > 0:
                roles_data[role_name] = best_name

    text = build_compact_rating_page(
        players=current_page_players,
        page=page + 1,
        total_pages=total_pages,
        total_players=total_players,
        mvp_data=mvp_data,
        roles_data=roles_data
    )

    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.button(text="◀️ Назад", callback_data=f"rating_page:{page - 1}")
    if page < total_pages - 1:
        builder.button(text="Вперед ▶️", callback_data=f"rating_page:{page + 1}")

    builder.button(text="ℹ️ Как считается рейтинг?", callback_data="rating_rules")
    builder.button(text="❌ Закрыть", callback_data="rating_close")

    if page > 0 and page < total_pages - 1:
        builder.adjust(2, 1, 1)
    else:
        builder.adjust(1, 1, 1)

    await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "rating_rules")
async def rating_rules_callback(callback: types.CallbackQuery):
    """Показывает всплывающее окно с правилами рейтинга"""
    rules = (
        "🏆 ФОРМУЛА ЭЛО:\n"
        "1. За сильных соперников дают больше.\n"
        "2. Баланс: Красным сложнее (получают больше, теряют меньше).\n"
        "3. Допы: дают плюс к Эло.\n"
        "4. Carry: если 'тащил', теряешь меньше."
    )
    await callback.answer(rules, show_alert=True)


@router.callback_query(F.data == "rating_close")
async def rating_close(callback: types.CallbackQuery):
    """Закрывает окно с рейтингом"""
    await callback.message.delete()
    await callback.answer()


@router.message(F.text == "🏆 Рейтинг (старый)")
async def show_old_rating(message: types.Message):
    rating = await database.get_players_rating(limit=30)

    if not rating:
        await message.answer("📊 Пока нет данных для рейтинга.")
        return

    text = "🏆 **ОБЩИЙ РЕЙТИНГ ИГРОКОВ (по баллам)**\n\n"

    for p in rating[:15]:
        if p["place"] == 1:
            medal = "🥇"
        elif p["place"] == 2:
            medal = "🥈"
        elif p["place"] == 3:
            medal = "🥉"
        else:
            medal = f"{p['place']}."

        name = p["nickname"] or p["full_name"]
        winrate = round(p["games_won"] / p["games_played"] * 100, 1) if p["games_played"] > 0 else 0

        text += f"{medal} **{name}**\n"
        text += f"   🎮 Игр: {p['games_played']} | 🏆 Побед: {p['games_won']} ({winrate}%)\n"
        text += f"   ⭐ Средний балл: {p['avg_points']:.2f}\n"
        text += f"   💰 Всего баллов: {p['total_points']:.1f}\n\n"

    await message.answer(text, parse_mode="Markdown")


# ======================= ОСТАЛЬНЫЕ ХЕНДЛЕРЫ РЕДАКТИРОВАНИЯ =======================

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
        prefix, game_id_str = callback.data.split(":", 1)
        game_id = int(game_id_str)
    except Exception as e:
        print(f"[GAME_PROTOCOL][ERROR] Parse error: {e}")
        await callback.answer("Некорректные данные игры.", show_alert=True)
        return

    game = await get_game_by_id(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    date_str = game.get("game_date") or "-"
    winner_label = game.get("winner_label") or "Результат не указан"
    game_number = game.get("game_number")
    global_game_number = game.get("global_game_number") or 0
    judge_id = game.get("judge_id")

    judge_name = None
    if judge_id:
        user_info = await get_user_by_id(judge_id)
        if user_info:
            _, full_name, username, nickname = user_info
            judge_name = nickname or full_name or username

    slots = await get_game_slots_by_date(date_str, game_number=game_number)
    if not slots:
        await callback.answer("Нет слотов игры.", show_alert=True)
        return

    night_kills_order = await get_night_kills_order(date_str, game_number or 0)
    filtered_order = []
    for slot_num in night_kills_order:
        if slot_num in slots:
            status_reason = slots[slot_num].get("status_reason", "")
            if "убит" in status_reason.lower() and "заголосован" not in status_reason.lower():
                filtered_order.append(slot_num)
    slots["_night_kills_order"] = filtered_order

    from game.text import build_protocol_text
    protocol_body = await build_protocol_text(slots, winner_label=winner_label)

    header = f"📑 Протокол игры №{game_number} ({date_str}): {winner_label}"
    if global_game_number:
        header += f" — №{global_game_number} по общей истории"

    if judge_name:
        full_text = f"{header}\n\n<b>Судья:</b> {judge_name}\n\n{protocol_body}"
    else:
        full_text = f"{header}\n\n{protocol_body}"

    # --- ПРАВИЛЬНАЯ ПРОВЕРКА ПРАВ И СБОРКА КНОПОК ---
    is_editor = await check_is_editor(callback.from_user.id)
    kb_buttons = []

    if is_editor:
        kb_buttons.append(
            [InlineKeyboardButton(text="✏️ Редактировать игру", callback_data=f"editgame_menu:{game_id}")])

    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons) if kb_buttons else None
    # -------------------------------------------------

    timestamp = int(time.time())

    try:
        img_path = create_endgame_pic_summary(
            slots=slots, game_date=date_str,
            evening_game_number=game_number or 0,
            global_game_number=global_game_number or 0,
            winner_label=winner_label,
            judge_name=judge_name,
        )
        doc = FSInputFile(img_path)

        await callback.message.answer_document(document=doc, caption=None)
        await callback.message.answer(f"{full_text}\n\n🕐 Обновлено: {timestamp}", parse_mode=ParseMode.HTML,
                                      reply_markup=kb)
        _cleanup_old_files("endgame_summary_", keep=10)
    except Exception as e:
        print(f"[GAME_PROTOCOL][ERROR] {e}")
        await callback.message.answer(f"{full_text}\n\n🕐 Обновлено: {timestamp}", parse_mode=ParseMode.HTML,
                                      reply_markup=kb)

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

    judge_id = game.get("judge_id")
    judge_name = None
    if judge_id:
        user_info = await get_user_by_id(judge_id)
        if user_info:
            _, full_name, username, nickname = user_info
            judge_name = nickname or full_name or username

    try:
        img_path = create_endgame_pic_summary(
            slots=slots, game_date=date_str,
            evening_game_number=game_number or 0,
            global_game_number=game.get("global_game_number") or 0,
            winner_label=winner_label,
            judge_name=judge_name,
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
        # Формат: editgame_set_outcome:game_id:outcome
        parts = callback.data.split(":")
        game_id = int(parts[1])
        outcome = parts[2]
    except Exception as e:
        print(f"[EDITGAME] Parse error: {e}")
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

    date_str = game.get("game_date")
    game_number = game.get("game_number")

    data = await state.get_data()
    temp_slots = data.get("temp_slots", {})
    temp_winner = data.get("temp_winner") or game.get("winner_label")

    slots = await get_game_slots_by_date(date_str, game_number=game_number)
    if not slots:
        await callback.answer("Нет слотов игры.", show_alert=True)
        return

    # --- ЛОГИКА ПЕРЕСЧЕТА БАЛЛОВ ЗА ПОБЕДУ ---
    winning_team = "Красные" if "город" in temp_winner.lower() else "Чёрные" if "мафи" in temp_winner.lower() else None

    # Применяем изменения из temp_slots и сразу пересчитываем base_points
    for slot_num, info in slots.items():
        # Применяем правки из редактора
        if slot_num in temp_slots:
            info.update(temp_slots[slot_num])

        # Пересчет base_points за победу
        if winning_team and info.get("team") == winning_team:
            info["base_points"] = 1.0
        else:
            info["base_points"] = 0.0

        # Сохраняем слот в БД
        update_params = {
            "alive": 1 if info.get("alive") else 0,
            "status_reason": info.get("status_reason"),
            "kick": 1 if info.get("kicked") else 0,
            "ppk": 1 if info.get("ppk") else 0,
            "pu": 1 if info.get("pu_mark") else 0,
            "role": info.get("role"),
            "team": info.get("team"),
            "base_points": info["base_points"],
            "bonus_points": float(info.get("bonus_points", 0)),
            "lh_points": float(info.get("lh_points", 0)),
            "dc_points": float(info.get("dc_points", 0)),
            "will_protocol_points": float(info.get("will_protocol_points", 0)),
            "will_opinion_points": float(info.get("will_opinion_points", 0)),
            "fouls": info.get("fouls", 0)
        }
        await update_game_slot(date_str, game_number, slot_num, **update_params)

    # Обновляем исход игры
    await update_game_outcome(game_id, temp_winner)

    # Пересчитываем ночные убийства
    night_kills_order = []
    for slot_num, info in slots.items():
        if isinstance(slot_num, int):
            if "убит" in info.get("status_reason", "").lower():
                night_kills_order.append(slot_num)
    await save_night_kills_order(date_str, game_number, night_kills_order)
    slots["_night_kills_order"] = night_kills_order

    # Обновляем протокол текстом
    from game.text import build_protocol_text
    new_protocol_text = await build_protocol_text(slots, winner_label=temp_winner)

    async with database.get_db() as conn:
        await conn.execute("UPDATE game_history SET protocol_text = ? WHERE id = ?", (new_protocol_text, game_id))
        await conn.commit()

    # Пересчет общей статистики игроков (чтобы рейтинг обновился с учетом новых очков)
    await database.recalc_all_stats()

    await state.update_data(temp_slots={}, temp_winner=None, has_changes=False)
    await callback.answer("✅ Изменения сохранены! Баллы пересчитаны.")
    await _send_protocol(callback, game_id, temp_winner)


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
        await editgame_fouls_menu(callback, state)
        return

    await state.set_state(EditGameState.waiting_for_value)
    await state.update_data(has_changes=True, current_field=field, current_slot=slot_num, current_game_id=game_id)

    msgs = {
        "role": "🎭 Введи новую роль (например: Мирный, Шериф, Мафия, Дон).\n🏳 Команда (Красные/Чёрные) установится автоматически.",
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

    await callback.message.answer(
        "📋 Введи текст протокола (ПР):\nПример: 3 6 7 красные, 1 4 чёрные\nИли 'нет' для очистки")
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
            role_lower = text.lower()

            # Умное определение команды по роли
            if "мир" in role_lower or "шер" in role_lower:
                team = "Красные"
            elif "маф" in role_lower or "дон" in role_lower:
                team = "Чёрные"
            else:
                team = "Без команды"

            # Делаем первую букву заглавной, если это стандартная роль
            if role_lower in ["мирный", "шериф", "мафия", "дон"]:
                changes["role"] = text.capitalize()
            else:
                changes["role"] = text

            changes["team"] = team
            await message.answer(
                f"✅ Роль обновлена на **{changes['role']}**.\n🏳 Команда автоматически изменена на **{team}** (сохранится после нажатия 'Сохранить').")

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
    try:
        parts = callback.data.split(":")
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
    try:
        parts = callback.data.split(":")
        game_id = int(parts[1])
        slot_num = int(parts[2])
        action = parts[3]
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
            tech_value = slot.get("technical_fouls", [])
            message_text = "✅ Техфол снят"

            # Обработка разных форматов
            if isinstance(tech_value, list):
                # Новый формат: список ["small", "big"]
                if tech_value:
                    removed = tech_value.pop()
                    changes["technical_fouls"] = tech_value
                    current_dc = slot.get("dc_points", 0.0)
                    if removed == "small":
                        changes["dc_points"] = round(current_dc + 0.3, 1)
                    elif removed == "big":
                        changes["dc_points"] = round(current_dc + 0.6, 1)
                    else:
                        changes["dc_points"] = round(current_dc + 0.3, 1)
                else:
                    await callback.answer("Нет техфолов для снятия", show_alert=True)
                    return

            elif isinstance(tech_value, int):
                # Старый формат: просто число
                if tech_value > 0:
                    new_tech = tech_value - 1
                    changes["technical_fouls"] = new_tech
                    current_dc = slot.get("dc_points", 0.0)
                    changes["dc_points"] = round(current_dc + 0.3, 1)
                else:
                    await callback.answer("Нет техфолов для снятия", show_alert=True)
                    return
            else:
                await callback.answer("Нет техфолов для снятия", show_alert=True)
                return

            # Если техфолов стало меньше 2, снимаем удаление
            tech_count = 0
            if isinstance(changes.get("technical_fouls", tech_value), list):
                tech_count = len(changes.get("technical_fouls", tech_value))
            elif isinstance(changes.get("technical_fouls", tech_value), int):
                tech_count = changes.get("technical_fouls", tech_value)
            else:
                tech_count = 0

            if tech_count < 2 and slot.get("kicked", False):
                changes["kicked"] = False
                changes["alive"] = True
                changes["status_reason"] = "Жив"
                message_text += " (удаление снято)"
        else:
            await callback.answer("Неизвестное действие", show_alert=True)
            return

    except Exception as e:
        print(f"[FOULS] Error: {e}")
        await callback.answer(f"Ошибка: {e}", show_alert=True)
        return

    if slot_num not in temp_slots:
        temp_slots[slot_num] = {}
    temp_slots[slot_num].update(changes)
    await state.update_data(temp_slots=temp_slots, has_changes=True)

    await callback.answer(message_text, show_alert=False)
    await editgame_fouls_menu(callback, state)


@router.message(F.text == "🏆 Рейтинг (старый)")
async def show_old_rating(message: types.Message):
    rating = await database.get_players_rating(limit=30)

    if not rating:
        await message.answer("📊 Пока нет данных для рейтинга.")
        return

    text = "🏆 **ОБЩИЙ РЕЙТИНГ ИГРОКОВ (по баллам)**\n\n"

    for p in rating[:15]:
        if p["place"] == 1:
            medal = "🥇"
        elif p["place"] == 2:
            medal = "🥈"
        elif p["place"] == 3:
            medal = "🥉"
        else:
            medal = f"{p['place']}."

        name = p["nickname"] or p["full_name"]
        winrate = round(p["games_won"] / p["games_played"] * 100, 1) if p["games_played"] > 0 else 0

        text += f"{medal} **{name}**\n"
        text += f"   🎮 Игр: {p['games_played']} | 🏆 Побед: {p['games_won']} ({winrate}%)\n"
        text += f"   ⭐ Средний балл: {p['avg_points']:.2f}\n"
        text += f"   💰 Всего баллов: {p['total_points']:.1f}\n\n"

    await message.answer(text, parse_mode="Markdown")


@router.callback_query(F.data.startswith("editgame_metadata:"))
async def editgame_metadata_menu(callback: types.CallbackQuery, state: FSMContext):
    """Меню выбора: изменить номер или дату"""
    try:
        game_id = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    await state.update_data(edit_game_id=game_id)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔢 Изменить номер игры", callback_data=f"editgame_change_number:{game_id}")],
        [InlineKeyboardButton(text="📅 Изменить дату", callback_data=f"editgame_change_date:{game_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"editgame_back:{game_id}")]
    ])

    await callback.message.edit_text(
        "✏️ **Изменение метаданных игры**\n\nВыберите, что хотите изменить:",
        reply_markup=kb,
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()


@router.callback_query(F.data.startswith("editgame_change_number:"))
async def editgame_change_number_start(callback: types.CallbackQuery, state: FSMContext):
    """Начало изменения номера игры"""
    try:
        game_id = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    game = await get_game_by_id(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    current_number = game.get("game_number", "?")
    await state.update_data(edit_game_id=game_id, current_number=current_number)
    await state.set_state(EditGameMetadataState.waiting_for_new_number)

    await callback.message.edit_text(
        f"🔢 **Изменение номера игры**\n\n"
        f"Текущий номер: **{current_number}**\n\n"
        f"Введите новый номер игры (целое число, например: 1, 2, 3...):\n\n"
        f"⚠️ Внимание: номер игры в рамках одного вечера должен быть уникальным!",
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()


@router.message(EditGameMetadataState.waiting_for_new_number)
async def editgame_change_number_apply(message: types.Message, state: FSMContext):
    """Применение нового номера игры"""
    data = await state.get_data()
    game_id = data.get("edit_game_id")

    if not game_id:
        await message.answer("❌ Ошибка: игра не найдена. Попробуйте снова.")
        await state.clear()
        return

    try:
        new_number = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите целое число (например: 1, 2, 3...)")
        return

    if new_number < 1:
        await message.answer("❌ Номер игры должен быть больше 0")
        return

    game = await get_game_by_id(game_id)
    if not game:
        await message.answer("❌ Игра не найдена")
        await state.clear()
        return

    old_number = game.get("game_number")
    old_date = game.get("game_date")

    # Обновляем номер игры в game_history
    async with database.get_db() as conn:
        await conn.execute("""
                           UPDATE game_history
                           SET game_number = ?
                           WHERE id = ?
                           """, (new_number, game_id))

        # Обновляем номер игры в game_slots_history с флагом редактора
        await conn.execute("""
                           UPDATE game_slots_history
                           SET game_number = ?, updated_by_editor = 1
                           WHERE game_date = ?
                             AND game_number = ?
                           """, (new_number, old_date, old_number))

        await conn.commit()

    await message.answer(
        f"✅ Номер игры изменён с **{old_number}** на **{new_number}**\n\n"
        f"⚠️ Если в этот вечер был другой игрок с таким же номером, возможны конфликты.",
        parse_mode=ParseMode.MARKDOWN
    )

    await state.clear()

    # Возвращаемся в меню редактирования
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Вернуться в редактор", callback_data=f"editgame_menu:{game_id}")]
    ])
    await message.answer("Вернуться в редактор:", reply_markup=kb)


@router.callback_query(F.data.startswith("editgame_change_date:"))
async def editgame_change_date_start(callback: types.CallbackQuery, state: FSMContext):
    """Начало изменения даты игры"""
    try:
        game_id = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    game = await get_game_by_id(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    current_date = game.get("game_date", "?")
    await state.update_data(edit_game_id=game_id, current_date=current_date)
    await state.set_state(EditGameMetadataState.waiting_for_new_date)

    await callback.message.edit_text(
        f"📅 **Изменение даты игры**\n\n"
        f"Текущая дата: **{current_date}**\n\n"
        f"Введите новую дату в формате **ДД.ММ** или **ДД.ММ.ГГГГ**\n"
        f"Примеры: `01.05`, `24.04.2026`\n\n"
        f"⚠️ Внимание: формат **ДД.ММ** преобразуется в текущий год.",
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()


@router.message(EditGameMetadataState.waiting_for_new_date)
async def editgame_change_date_apply(message: types.Message, state: FSMContext):
    """Применение новой даты игры"""
    data = await state.get_data()
    game_id = data.get("edit_game_id")

    if not game_id:
        await message.answer("❌ Ошибка: игра не найдена. Попробуйте снова.")
        await state.clear()
        return

    import re
    new_date = message.text.strip()

    # Проверка формата ДД.ММ или ДД.ММ.ГГГГ
    if re.match(r'^\d{2}\.\d{2}$', new_date):
        # Добавляем текущий год
        from datetime import datetime
        new_date = f"{new_date}.{datetime.now().year}"
    elif not re.match(r'^\d{2}\.\d{2}\.\d{4}$', new_date):
        await message.answer("❌ Неверный формат даты. Используйте ДД.ММ или ДД.ММ.ГГГГ")
        return

    game = await get_game_by_id(game_id)
    if not game:
        await message.answer("❌ Игра не найдена")
        await state.clear()
        return

    old_date = game.get("game_date")
    old_number = game.get("game_number")

    # Обновляем дату игры в game_history
    async with database.get_db() as conn:
        await conn.execute("""
                           UPDATE game_history
                           SET game_date = ?
                           WHERE id = ?
                           """, (new_date, game_id))

        # Обновляем дату игры в game_slots_history с флагом редактора
        await conn.execute("""
                           UPDATE game_slots_history
                           SET game_date = ?, updated_by_editor = 1
                           WHERE game_date = ?
                             AND game_number = ?
                           """, (new_date, old_date, old_number))

        await conn.commit()

    await message.answer(
        f"✅ Дата игры изменена с **{old_date}** на **{new_date}**",
        parse_mode=ParseMode.MARKDOWN
    )

    await state.clear()

    # Возвращаемся в меню редактирования
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Вернуться в редактор", callback_data=f"editgame_menu:{game_id}")]
    ])
    await message.answer("Вернуться в редактор:", reply_markup=kb)


# ======================= УДАЛЕНИЕ ИГРЫ =======================

@router.callback_query(F.data.startswith("editgame_delete_confirm:"))
async def editgame_delete_confirm(callback: types.CallbackQuery, state: FSMContext):
    """Подтверждение удаления игры"""
    try:
        game_id = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    game = await get_game_by_id(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    await state.update_data(delete_game_id=game_id)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚠️ ДА, УДАЛИТЬ ИГРУ", callback_data=f"editgame_delete_yes:{game_id}")],
        [InlineKeyboardButton(text="❌ Нет, отмена", callback_data=f"editgame_back:{game_id}")]
    ])

    await callback.message.edit_text(
        f"⚠️ **УДАЛЕНИЕ ИГРЫ**\n\n"
        f"Вы уверены, что хотите удалить игру?\n\n"
        f"📅 Дата: {game.get('game_date')}\n"
        f"🎮 Номер: {game.get('game_number')}\n"
        f"🏆 Победитель: {game.get('winner_label')}\n\n"
        f"❗️ Это действие НЕЛЬЗЯ отменить!\n"
        f"❗️ Статистика игроков будет пересчитана.\n\n"
        f"Введите **ДА, УДАЛИТЬ** для подтверждения:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data.startswith("editgame_delete_yes:"))
async def editgame_delete_yes(callback: types.CallbackQuery, state: FSMContext):
    """Полное удаление игры"""
    try:
        game_id = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    game = await get_game_by_id(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    date_str = game.get("game_date")
    game_number = game.get("game_number")

    # Удаляем слоты игры
    async with database.get_db() as conn:
        await conn.execute("""
                           DELETE
                           FROM game_slots_history
                           WHERE game_date = ?
                             AND game_number = ?
                           """, (date_str, game_number))

        # Удаляем запись об игре
        await conn.execute("DELETE FROM game_history WHERE id = ?", (game_id,))

        await conn.commit()

    # Пересчитываем статистику игроков
    await database.recalc_all_stats()

    await callback.message.edit_text(
        f"✅ **Игра удалена!**\n\n"
        f"📅 Дата: {date_str}\n"
        f"🎮 Номер: {game_number}\n\n"
        f"Статистика игроков пересчитана.",
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()

# ======================= ЗАМЕНА ИГРОКА В СЛОТЕ =======================

@router.callback_query(F.data.startswith("editgame_replace_init:"))
async def editgame_replace_init(callback: types.CallbackQuery, state: FSMContext):
    try:
        _, game_id_str, slot_str = callback.data.split(":")
        game_id = int(game_id_str)
        slot_num = int(slot_str)
    except Exception:
        await callback.answer("Ошибка данных.", show_alert=True)
        return

    await state.set_state(EditGameState.waiting_for_replacement)
    await state.update_data(replace_game_id=game_id, replace_slot=slot_num, has_changes=True)

    await callback.message.answer(
        f"👤 **Замена игрока в слоте {slot_num}**\n\n"
        f"Введите **никнейм** игрока, которого нужно посадить на этот слот.\n\n"
        f"*(Если игрока нет в базе, он будет записан как 'Гость' без сохранения статистики)*",
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()


@router.message(EditGameState.waiting_for_replacement)
async def editgame_replace_apply(message: types.Message, state: FSMContext):
    data = await state.get_data()
    game_id = data.get("replace_game_id")
    slot_num = data.get("replace_slot")

    if not game_id or not slot_num:
        await message.answer("Ошибка состояния. Попробуйте снова.")
        await state.clear()
        return

    new_player_name = message.text.strip()
    new_user = await database.get_user_by_nickname(new_player_name)

    # Проверка на наличие профиля
    if not new_user:
        new_user_id = None
        display_name = "Гость (без профиля)"
    else:
        new_user_id = new_user[0]
        display_name = new_user[3] or new_user[1]

    game = await get_game_by_id(game_id)
    if not game:
        await message.answer("❌ Игра не найдена.")
        await state.set_state(None)
        return

    date_str = game.get("game_date")
    game_number = game.get("game_number")

    # 1. Меняем ID пользователя в истории слотов (Если Гость - пишем NULL)
    async with database.get_db() as conn:
        await conn.execute(
            "UPDATE game_slots_history SET user_id = ?, updated_by_editor = 1 WHERE game_date = ? AND game_number = ? AND slot_num = ?",
            (new_user_id, date_str, game_number, slot_num)
        )
        await conn.commit()

    # 2. Глобально пересчитываем статистику
    await database.recalc_all_stats()

    # 3. Очищаем временные изменения для этого слота в редакторе, чтобы подтянулось новое имя
    temp_slots = data.get("temp_slots", {})
    if slot_num in temp_slots:
        del temp_slots[slot_num]
        await state.update_data(temp_slots=temp_slots)

    await state.set_state(None)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Вернуться к списку игроков", callback_data=f"editgame_players:{game_id}")]
    ])

    await message.answer(
        f"✅ Слот **{slot_num}** успешно обновлен!\n"
        f"Теперь на нем играет: **{display_name}**.\n\n"
        f"Статистика пересчитана автоматически.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )
