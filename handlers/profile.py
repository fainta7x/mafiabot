import os
import time
from typing import Dict, Any

from aiogram import Router, F, types
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
)
from keyboards import games_list_kb
from pic_profile import create_profile_pic
from game.pic_endgame import create_endgame_pic_summary

router = Router()

TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
os.makedirs(TEMP_DIR, exist_ok=True)


# ======================= ВСПОМОГАТЕЛЬНОЕ =======================

def _cleanup_old_files(prefix: str, keep: int = 10):
    """Удаляет старые файлы с указанным префиксом, оставляя только keep последних."""
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


def _build_edit_game_kb(game_id: int) -> InlineKeyboardMarkup:
    """Клавиатура под протоколом."""
    kb = [
        [
            InlineKeyboardButton(
                text="✏️ Редактировать игру",
                callback_data=f"editgame:{game_id}",
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _build_slots_kb(game_id: int, slots: Dict[int, dict]) -> InlineKeyboardMarkup:
    """Клавиатура со списком слотов для редактирования."""
    buttons = []
    for slot_num in sorted(k for k in slots.keys() if isinstance(k, int)):
        info = slots[slot_num]
        nickname = info.get("nickname") or info.get("full_name") or f"Игрок {slot_num}"
        role = info.get("role") or "Не задана"
        team = info.get("team") or "Без команды"
        base = float(info.get("base_points") or 0)
        bonus = float(info.get("bonus_points") or 0)
        lh = float(info.get("lh_points") or 0)
        dc = float(info.get("dc_points") or 0)
        total = base + bonus + lh + dc

        text = f"{slot_num}. {nickname} [{role}] — {team} — {total:+.1f}"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=text,
                    callback_data=f"editgame_slot:{game_id}:{slot_num}",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="⬅️ Закрыть редактор",
                callback_data=f"editgame_close:{game_id}",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _build_slot_menu_kb(game_id: int, slot_num: int) -> InlineKeyboardMarkup:
    """Меню редактирования одного слота."""
    kb = [
        [
            InlineKeyboardButton(
                text="🎭 Роль",
                callback_data=f"editgame_field:role:{game_id}:{slot_num}",
            ),
            InlineKeyboardButton(
                text="🏳 Команда",
                callback_data=f"editgame_field:team:{game_id}:{slot_num}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🎲 Очки (игра/доп/ЛХ/ДЦ)",
                callback_data=f"editgame_field:points:{game_id}:{slot_num}",
            )
        ],
        [
            InlineKeyboardButton(
                text="📋 ПР (баллы)",
                callback_data=f"editgame_field:protocol:{game_id}:{slot_num}",
            ),
            InlineKeyboardButton(
                text="💬 МН (баллы)",
                callback_data=f"editgame_field:opinion:{game_id}:{slot_num}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="👑 ПУ (вкл/выкл)",
                callback_data=f"editgame_field:pu:{game_id}:{slot_num}",
            )
        ],
        [
            InlineKeyboardButton(
                text="⬅️ Назад к списку игроков",
                callback_data=f"editgame:{game_id}",
            )
        ],
        [
            InlineKeyboardButton(
                text="✅ Перерисовать протокол",
                callback_data=f"editgame_redraw:{game_id}",
            )
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


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
        await message.answer_document(
            document=doc,
            caption=f"{text}\n\n🕐 Обновлено: {timestamp}",
            parse_mode=ParseMode.MARKDOWN,
        )

        _cleanup_old_files("profile_", keep=10)

    except Exception as e:
        print(f"[PROFILE][ERROR] Failed to send profile image for {user_id}: {e}")
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

        if game_number:
            title = f"Игра №{game_number}"
        else:
            title = "Игра"

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

        if game_number:
            title = f"Игра №{game_number}"
        else:
            title = "Игра"

        if date_str:
            title += f" ({date_str})"

        if global_game_number:
            title += f" — №{global_game_number} по истории"

        buttons_data.append((game_id, title, game_number or 0))

    kb = games_list_kb(buttons_data, prefix="mygames")
    await message.answer("Выбери игру:", reply_markup=kb)


# ======================= ПРОТОКОЛ ИГРЫ + КАРТИНКА =======================

@router.callback_query(F.data.startswith(("allgames:", "mygames:")))
async def show_game_protocol(callback: types.CallbackQuery, state: FSMContext):
    """
    callback.data: allgames:{game_id}:{game_number} или mygames:{game_id}:{game_number}
    """
    try:
        prefix, game_id_str, game_number_str = callback.data.split(":", 2)
        game_id = int(game_id_str)
        _ = int(game_number_str)
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

    # Убираем шапку, если вдруг она попала в protocol_text
    lines = protocol.splitlines()
    if lines and lines[0].startswith("📑 Протокол"):
        lines = lines[1:]
    protocol_body = "\n".join(lines).lstrip()

    # Шапка
    if game_number:
        header = f"📑 Протокол игры №{game_number} ({date_str}): {winner_label}"
    else:
        header = f"📑 Протокол игры ({date_str}): {winner_label}"

    if global_game_number:
        header += f" — №{global_game_number} по общей истории"

    text = header
    if protocol_body:
        text += f"\n\n{protocol_body}"

    kb_under_protocol = _build_edit_game_kb(game_id)

    try:
        slots = await get_game_slots_by_date(date_str)

        if slots:
            img_path = create_endgame_pic_summary(
                slots=slots,
                game_date=date_str,
                evening_game_number=game_number or 0,
                global_game_number=global_game_number or 0,
                winner_label=winner_label,
            )
            print(f"[GAME_PROTOCOL] Generated protocol image for game_id={game_id}: {img_path}")

            doc = FSInputFile(img_path)
            timestamp = int(time.time())
            await callback.message.answer_document(
                document=doc,
                caption=f"{text}\n\n🕐 Обновлено: {timestamp}",
                parse_mode=ParseMode.HTML,
                reply_markup=kb_under_protocol,
            )

            _cleanup_old_files("endgame_summary_", keep=10)
        else:
            await callback.message.answer(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=kb_under_protocol,
            )

    except Exception as e:
        print(f"[GAME_PROTOCOL][ERROR] Failed to send image for game_id={game_id}: {e}")
        await callback.message.answer(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=kb_under_protocol,
        )

    await callback.answer()


# ======================= РЕДАКТОР ИГРЫ =======================

@router.callback_query(F.data.startswith("editgame_close:"))
async def editgame_close(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Редактор закрыт.")


@router.callback_query(F.data.startswith("editgame:"))
async def editgame_open(callback: types.CallbackQuery, state: FSMContext):
    """
    Открывает список слотов для редактирования.
    callback.data: editgame:{game_id}
    """
    try:
        _, game_id_str = callback.data.split(":", 1)
        game_id = int(game_id_str)
    except Exception:
        await callback.answer("Некорректные данные игры.", show_alert=True)
        return

    game = await get_game_by_id(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    date_str = game.get("game_date") or "-"
    slots = await get_game_slots_by_date(date_str)
    if not slots:
        await callback.answer("У этой игры нет сохранённых слотов.", show_alert=True)
        return

    kb = _build_slots_kb(game_id, slots)
    await callback.message.answer(
        f"✏️ Редактирование игры от {date_str}\nВыбери слот:",
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("editgame_slot:"))
async def editgame_slot_menu(callback: types.CallbackQuery, state: FSMContext):
    """
    Меню редактирования одного слота.
    data: editgame_slot:{game_id}:{slot_num}
    """
    try:
        _, game_id_str, slot_str = callback.data.split(":", 2)
        game_id = int(game_id_str)
        slot_num = int(slot_str)
    except Exception:
        await callback.answer("Некорректные данные слота.", show_alert=True)
        return

    game = await get_game_by_id(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    date_str = game.get("game_date") or "-"
    slots = await get_game_slots_by_date(date_str)
    if not slots or slot_num not in slots:
        await callback.answer("Слот не найден.", show_alert=True)
        return

    slot = slots[slot_num]
    nickname = slot.get("nickname") or slot.get("full_name") or f"Игрок {slot_num}"
    role = slot.get("role") or "Не задана"
    team = slot.get("team") or "Без команды"

    base = float(slot.get("base_points") or 0)
    bonus = float(slot.get("bonus_points") or 0)
    lh = float(slot.get("lh_points") or 0)
    dc = float(slot.get("dc_points") or 0)
    pr = float(slot.get("will_protocol_points") or 0)
    op = float(slot.get("will_opinion_points") or 0)
    pu_mark = bool(slot.get("pu_mark"))

    text = (
        f"Слот {slot_num}: {nickname}\n"
        f"Роль: {role}\n"
        f"Команда: {team}\n"
        f"Игра: {base:+.1f}, Доп: {bonus:+.1f}, ЛХ: {lh:+.1f}, ДЦ: {dc:+.1f}\n"
        f"ПР: {pr:+.1f}, МН: {op:+.1f}\n"
        f"ПУ: {'да' if pu_mark else 'нет'}"
    )

    kb = _build_slot_menu_kb(game_id, slot_num)
    await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


# ----------- обработчики изменения полей -----------

@router.callback_query(F.data.startswith("editgame_field:"))
async def editgame_field_entry(callback: types.CallbackQuery, state: FSMContext):
    """
    Запрос значения для поля.
    data: editgame_field:{field}:{game_id}:{slot_num}
    """
    try:
        _, field, game_id_str, slot_str = callback.data.split(":", 3)
        game_id = int(game_id_str)
        slot_num = int(slot_str)
    except Exception:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    await state.set_state(EditGameState.waiting_for_value)
    await state.update_data(field=field, game_id=game_id, slot_num=slot_num)

    if field == "role":
        msg = "Введи новую роль (строкой), например: Красный, Дон мафии, Шериф."
    elif field == "team":
        msg = "Введи новую команду (строкой), например: Красные или Чёрные."
    elif field == "points":
        msg = "Введи очки через пробел: Игра Доп ЛХ ДЦ\nНапример: 1 0.5 0 -0.5"
    elif field == "protocol":
        msg = "Введи новое значение ПР (число, можно с знаком: +0.5, -1):"
    elif field == "opinion":
        msg = "Введи новое значение МН (число, можно с знаком: +0.5, -1):"
    elif field == "pu":
        msg = "ПУ: введи 1 чтобы включить или 0 чтобы выключить."
    else:
        await callback.answer("Неизвестное поле.", show_alert=True)
        await state.clear()
        return

    await callback.message.answer(msg)
    await callback.answer()


@router.message(EditGameState.waiting_for_value)
async def editgame_field_apply(message: types.Message, state: FSMContext):
    data: Dict[str, Any] = await state.get_data()
    field = data.get("field")
    game_id = data.get("game_id")
    slot_num = data.get("slot_num")

    if field is None or game_id is None or slot_num is None:
        await message.answer("Внутренняя ошибка состояния, попробуй ещё раз.")
        await state.clear()
        return

    game = await get_game_by_id(int(game_id))
    if not game:
        await message.answer("Игра не найдена.")
        await state.clear()
        return

    date_str = game.get("game_date") or "-"
    text = message.text.strip()

    try:
        if field == "role":
            await update_game_slot(date_str, slot_num, role=text)
            await message.answer("Роль обновлена.")

        elif field == "team":
            await update_game_slot(date_str, slot_num, team=text)
            await message.answer("Команда обновлена.")

        elif field == "points":
            parts = text.replace(",", ".").split()
            if len(parts) != 4:
                await message.answer("Нужно 4 числа через пробел: Игра Доп ЛХ ДЦ. Попробуй ещё раз.")
                return
            b, bo, lh, dc = map(float, parts)
            await update_game_slot(
                date_str,
                slot_num,
                base_points=b,
                bonus_points=bo,
                lh_points=lh,
                dc_points=dc,
            )
            await message.answer("Очки обновлены.")

        elif field == "protocol":
            val = float(text.replace(",", "."))
            await update_game_slot(date_str, slot_num, will_protocol_points=val)
            await message.answer("ПР обновлён.")

        elif field == "opinion":
            val = float(text.replace(",", "."))
            await update_game_slot(date_str, slot_num, will_opinion_points=val)
            await message.answer("МН обновлено.")

        elif field == "pu":
            if text not in ("0", "1"):
                await message.answer("Нужно 0 или 1. Попробуй ещё раз.")
                return
            pu_val = 1 if text == "1" else 0
            await update_game_slot(date_str, slot_num, pu=pu_val)
            await message.answer("ПУ обновлён.")
        else:
            await message.answer("Неизвестное поле.")
    except Exception as e:
        print(f"[EDIT_GAME][ERROR] {e}")
        await message.answer("Ошибка при обновлении. См. логи бота.")

    await state.clear()

    # После изменения — покажем снова меню слота
    fake_callback = types.CallbackQuery(
        id="0",
        from_user=message.from_user,
        chat_instance="",
        message=message,
        data=f"editgame_slot:{game_id}:{slot_num}",
    )
    # Вызовем обработчик напрямую
    await editgame_slot_menu(fake_callback, state)


# ----------- перерисовка протокола -----------

@router.callback_query(F.data.startswith("editgame_redraw:"))
async def editgame_redraw(callback: types.CallbackQuery, state: FSMContext):
    """
    Перерисовывает картинку протокола после правок.
    data: editgame_redraw:{game_id}
    """
    try:
        _, game_id_str = callback.data.split(":", 1)
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
    game_number = game.get("game_number") or 0
    global_game_number = game.get("global_game_number") or 0

    lines = protocol.splitlines()
    if lines and lines[0].startswith("📑 Протокол"):
        lines = lines[1:]
    protocol_body = "\n".join(lines).lstrip()

    header = f"📑 Протокол игры №{game_number or '?'} ({date_str}): {winner_label}"
    if global_game_number:
        header += f" — №{global_game_number} по общей истории"

    text = header
    if protocol_body:
        text += f"\n\n{protocol_body}"

    kb_under_protocol = _build_edit_game_kb(game_id)

    try:
        slots = await get_game_slots_by_date(date_str)
        if not slots:
            await callback.answer("Нет слотов игры, нечего перерисовывать.", show_alert=True)
            return

        img_path = create_endgame_pic_summary(
            slots=slots,
            game_date=date_str,
            evening_game_number=game_number or 0,
            global_game_number=global_game_number or 0,
            winner_label=winner_label,
        )
        print(f"[GAME_REDRAW] Regenerated protocol image for game_id={game_id}: {img_path}")

        doc = FSInputFile(img_path)
        timestamp = int(time.time())
        await callback.message.answer_document(
            document=doc,
            caption=f"{text}\n\n🕐 Обновлено: {timestamp}",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_under_protocol,
        )
        _cleanup_old_files("endgame_summary_", keep=10)

    except Exception as e:
        print(f"[GAME_REDRAW][ERROR] Failed to redraw image for game_id={game_id}: {e}")
        await callback.message.answer(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=kb_under_protocol,
        )

    await callback.answer()