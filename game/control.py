import random
from datetime import datetime

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode
from aiogram.types import FSInputFile

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


async def save_slots(state: FSMContext, slots: dict):
    await state.update_data(slots=slots)
    await database.save_current_game_slots(slots)


def create_empty_slot(nickname: str) -> dict:
    return {
        "user_id": None, "full_name": None, "nickname": nickname, "username": None,
        "status": "Добавлен вручную", "fouls": 0, "alive": True, "status_reason": "Жив",
        "nominated": False, "votes": 0, "night_suspects": [], "role": "Не задана",
        "team": None, "base_points": 0, "bonus_points": 0, "lh_points": 0.0, "pu_mark": False
    }


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
    slots = await get_slots(message, state)
    if slots:
        await message.answer(build_game_state(slots, alive_only=False), reply_markup=keyboards.game_admin_menu())


# ========== 1. СТАРТ / ПРОДОЛЖЕНИЕ ==========
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

    # Дата и номера
    game_date = datetime.now().strftime("%d.%m.%Y")
    await database.set_current_game_date(game_date)

    evening_games = await database.get_games_by_date(game_date)
    evening_num = len(evening_games) + 1
    await database.set_current_game_number(evening_num)

    total_games = await database.get_total_games_count()
    global_num = total_games + 1
    await database.set_current_global_game_number(global_num)

    # Создание слотов
    random.shuffle(booked)
    slots = {}
    for i, (user_id, full_name, username, nickname, status) in enumerate(booked, 1):
        slots[i] = create_empty_slot(nickname)
        slots[i].update({"user_id": user_id, "full_name": full_name, "username": username, "status": status})

    # Состояние FSM
    await state.set_state(GameCreateState.editing_slots)
    await state.update_data(
        slots=slots, roles_assigned=False, nominated_list=[], vote_index=0,
        split_candidates=[], in_split=False, first_night_kill_recorded=False,
        night_killed_slot=None, winner_label=None, protocol_chat_id=None, protocol_message_id=None
    )

    await database.set_setting("game_active", "1")
    await save_slots(state, slots)

    await message.answer(
        f"🎲 Начата игра №{evening_num} ({game_date}): №{global_num} по общей истории\n\n{build_slots_text(slots)}",
        reply_markup=keyboards.game_admin_menu()
    )


@router.message(F.text == "♻️ Продолжить игру")
async def resume_game(message: types.Message, state: FSMContext):
    if not await ensure_admin_pm(message):
        return

    if await database.get_setting("game_active") != "1":
        await message.answer("Нет активной сохранённой игры.", reply_markup=keyboards.admin_menu())
        return

    slots = await database.load_current_game_slots()
    if not slots:
        await message.answer("Не удалось найти сохранённые слоты.", reply_markup=keyboards.admin_menu())
        return

    await state.set_state(GameCreateState.editing_slots)
    await state.update_data(
        slots=slots, roles_assigned=False, nominated_list=[], vote_index=0,
        split_candidates=[], in_split=False, first_night_kill_recorded=False,
        night_killed_slot=None, winner_label=None, protocol_chat_id=None, protocol_message_id=None
    )

    await message.answer(f"Продолжаем незавершённую игру.\n\n{build_game_state(slots, alive_only=False)}",
                         reply_markup=keyboards.game_admin_menu())


# ========== 2. РЕДАКТИРОВАНИЕ НИКОВ ==========
@router.message(GameCreateState.editing_slots, F.text.regexp(r"^\d+\s+"))
async def manual_nick_edit(message: types.Message, state: FSMContext):
    if not await ensure_admin_pm(message):
        return

    lower = message.text.strip().lower()
    if lower.endswith((" ночь", " день", " жив")):
        return

    slots = await get_slots(message, state)
    if not slots:
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Формат: <номер_слота> <новый_ник>\nПример: 3 Волк",
                             reply_markup=keyboards.game_admin_menu())
        return

    ok, slot_num, err = parse_slot_num(parts[0])
    if not ok:
        await message.answer(err, reply_markup=keyboards.game_admin_menu())
        return

    new_nick = parts[1].strip()
    if not new_nick:
        await message.answer("Ник не может быть пустым.", reply_markup=keyboards.game_admin_menu())
        return

    if slot_num in slots:
        slots[slot_num]["nickname"] = new_nick
        action = "обновлён"
    else:
        slots[slot_num] = create_empty_slot(new_nick)
        action = "создан"

    await save_slots(state, slots)
    await message.answer(f"Слот {slot_num} {action}, ник: «{new_nick}».\n\n{build_slots_text(slots)}",
                         reply_markup=keyboards.game_admin_menu())


# ========== 3. ОЧИСТКА СЛОТА ==========
@router.message(F.text == "🧹 Очистить слот")
async def ask_clear_slot(message: types.Message, state: FSMContext):
    if not await ensure_admin_pm(message):
        return
    if not await get_slots(message, state):
        return
    await state.set_state(GameCreateState.waiting_clear_slot_number)
    await message.answer("Какой слот очистить? Введите номер от 1 до 10.", reply_markup=keyboards.game_admin_menu())


@router.message(GameCreateState.waiting_clear_slot_number)
async def clear_slot_handler(message: types.Message, state: FSMContext):
    if not await ensure_admin_pm(message):
        return

    ok, slot_num, err = parse_slot_num(message.text)
    if not ok:
        await message.answer(err + " Попробуй ещё раз.", reply_markup=keyboards.game_admin_menu())
        return

    slots = await get_slots(message, state)
    if not slots:
        await state.set_state(GameCreateState.editing_slots)
        return

    if slot_num not in slots:
        await message.answer(f"Слот {slot_num} не занят.", reply_markup=keyboards.game_admin_menu())
        await state.set_state(GameCreateState.editing_slots)
        return

    slot = slots[slot_num]
    slot.update(fouls=0, alive=True, status_reason="Жив", nominated=False, votes=0,
                night_suspects=[], base_points=0, bonus_points=0, lh_points=0.0, pu_mark=False)

    await save_slots(state, slots)
    await message.answer(f"Слот {slot_num} очищен.\n\n{build_game_state(slots, alive_only=False)}",
                         reply_markup=keyboards.game_admin_menu())
    await state.set_state(GameCreateState.editing_slots)


# ========== 4. ПОКАЗ СОСТОЯНИЯ ==========
@router.message(GameCreateState.editing_slots, F.text == "⏹ Остановить")
async def ask_game_finish_reason(message: types.Message, state: FSMContext):
    if await ensure_admin_pm(message):
        await message.answer("Как завершить текущую игру?", reply_markup=keyboards.game_finish_keyboard())


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


# ========== 5. ЗАВЕРШЕНИЕ ИГРЫ (callback) ==========
@router.callback_query(F.data.startswith("game_end:"))
async def handle_game_finish(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    data = await state.get_data()
    slots = data.get("slots") or {}
    action = callback.data.split(":", 1)[1]

    # Определяем результат
    if action == "city":
        result_text, winning_team, winner_label = "🏙 Игра завершена: Победа города.", "Красные", "Победа города"
    elif action == "mafia":
        result_text, winning_team, winner_label = "💀 Игра завершена: Победа мафии.", "Чёрные", "Победа мафии"
    else:
        result_text, winning_team, winner_label = "❌ Игра отменена без подведения итогов.", None, "Игра отменена"

    # Начисление очков
    if winning_team:
        await database.apply_game_result_to_users(slots, winning_team)
        for slot in slots.values():
            slot["base_points"] = 1 if slot.get("team") == winning_team else 0
    else:
        for slot in slots.values():
            slot["base_points"] = 0

    # Расчёт ЛХ для ПУ
    for slot in slots.values():
        if not slot.get("pu_mark") or slot.get("team") != "Красные":
            slot["lh_points"] = float(slot.get("lh_points") or 0.0)
            continue

        suspects = slot.get("night_suspects") or []
        correct = sum(1 for n in suspects if slots.get(n, {}).get("team") == "Чёрные")
        slot["lh_points"] = [0.0, 0.1, 0.3, 0.6][correct] if correct <= 3 else 0.0

    # Номера игры
    game_date = await database.get_current_game_date() or "-"
    evening_num = await database.get_current_game_number() or 1
    global_num = await database.get_current_global_game_number() or 1

    # Сохранение протокола
    protocol_body = build_protocol_text(slots, updated=False, winner_label=winner_label)
    await database.save_game_history(game_date, winner_label, protocol_body, evening_num, global_num)

    header = f"📑 Протокол игры №{evening_num} ({game_date}): №{global_num} по общей истории — {winner_label}"
    await callback.message.edit_text(result_text)
    protocol_msg = await callback.message.answer(f"{header}\n\n{protocol_body}",
                                                 reply_markup=keyboards.game_admin_menu(), parse_mode=ParseMode.HTML)

    await state.update_data(slots=slots, protocol_chat_id=protocol_msg.chat.id,
                            protocol_message_id=protocol_msg.message_id, winner_label=winner_label)
    await save_slots(state, slots)
    await state.set_state(GameCreateState.editing_slots)
    await callback.answer()


# ========== 6. ПОЛНОЕ ЗАВЕРШЕНИЕ ==========
@router.message(F.text == "🏁 Завершить")
async def final_finish_game(message: types.Message, state: FSMContext):
    if not await ensure_admin_pm(message):
        return

    if await database.get_setting("game_active") != "1":
        await message.answer("Сейчас нет активной игры.", reply_markup=keyboards.admin_menu())
        return

    # Получаем слоты
    data = await state.get_data()
    slots = data.get("slots") or await database.load_current_game_slots() or {}

    game_date = await database.get_current_game_date() or "-"
    evening_num = await database.get_current_game_number() or 1
    global_num = await database.get_current_global_game_number() or 1
    winner_label = data.get("winner_label") or await database.get_last_winner_label()

    # Графический протокол
    if slots:
        img_path = create_endgame_pic_summary(slots, game_date, evening_num, global_num, winner_label)
        await message.answer_photo(FSInputFile(img_path), caption="Итоговый графический протокол игры 📸")

    # Сохраняем историю слотов
    if slots:
        await database.save_game_slots_history(game_date, slots)

    # Очистка
    await clear_game_state(state)
    await message.answer("Игра полностью завершена. Можно запускать новую.", reply_markup=keyboards.admin_menu())


# ========== 7. ЛХ ==========
@router.message(F.text.regexp(r"^лх\s+"))
async def manual_lh_input(message: types.Message, state: FSMContext):
    if not await ensure_admin_pm(message):
        return

    slots = await get_slots(message, state)
    if not slots:
        return

    parts = (message.text or "").strip().lower().split()
    if len(parts) < 2:
        await message.answer("Формат: лх <номер_слота> [подозреваемые]\nПример: лх 5 1 2 3",
                             reply_markup=keyboards.game_admin_menu())
        return

    ok, slot_num, err = parse_slot_num(parts[1])
    if not ok:
        await message.answer(err, reply_markup=keyboards.game_admin_menu())
        return

    if slot_num not in slots:
        await message.answer(f"Слот {slot_num} не занят.", reply_markup=keyboards.game_admin_menu())
        return

    suspects = [int(p) for p in parts[2:] if p.isdigit() and 1 <= int(p) <= 10]
    slots[slot_num]["night_suspects"] = list(dict.fromkeys(suspects))

    await save_slots(state, slots)
    suspects_str = ", ".join(map(str, suspects)) if suspects else "очищен"
    await message.answer(
        f"Слот {slot_num}: подозреваемые [{suspects_str}].\n\n{build_game_state(slots, alive_only=False)}",
        reply_markup=keyboards.game_admin_menu())


# ========== 8. ПУ ==========
@router.message(F.text.regexp(r"^пу\s+"))
async def manual_pu_input(message: types.Message, state: FSMContext):
    if not await ensure_admin_pm(message):
        return

    slots = await get_slots(message, state)
    if not slots:
        return

    parts = (message.text or "").strip().lower().split()
    if len(parts) < 2:
        await message.answer("Формат: пу <номер_слота> [подозреваемые]\nПример: пу 4 1 2 3",
                             reply_markup=keyboards.game_admin_menu())
        return

    ok, slot_num, err = parse_slot_num(parts[1])
    if not ok:
        await message.answer(err, reply_markup=keyboards.game_admin_menu())
        return

    if slot_num not in slots:
        await message.answer(f"Слот {slot_num} не занят.", reply_markup=keyboards.game_admin_menu())
        return

    suspects = [int(p) for p in parts[2:] if p.isdigit() and 1 <= int(p) <= 10]

    # Назначаем ПУ
    for s in slots.values():
        s["pu_mark"] = False
    slots[slot_num]["pu_mark"] = True
    slots[slot_num]["night_suspects"] = list(dict.fromkeys(suspects))

    await save_slots(state, slots)
    suspects_str = ", ".join(map(str, suspects)) if suspects else "очищен"
    await message.answer(
        f"Слот {slot_num} назначен ПУ. Подозреваемые: [{suspects_str}].\n\n{build_game_state(slots, alive_only=False)}",
        reply_markup=keyboards.game_admin_menu())


# ========== 9. РЕЖИМ РЕДАКТИРОВАНИЯ (НОВЫЕ КОМАНДЫ) ==========

@router.message(GameCreateState.editing_slots, F.text == "✏️ Редактировать")
async def enter_edit_mode(message: types.Message, state: FSMContext):
    """Вход в режим редактирования."""
    if not await ensure_admin_pm(message):
        return

    slots = await get_slots(message, state)
    if not slots:
        return

    await message.answer(
        "✏️ **Режим редактирования**\n\n"
        "Используйте команды:\n\n"
        "• `роль <номер> <роль>` — Мирный/Шериф/Мафия/Дон\n"
        "• `команда <номер> <Красные/Чёрные>`\n"
        "• `статус <номер> <жив/убит/заголосован>`\n"
        "• `пу <номер>` — назначить ПУ\n"
        "• `лх <номер> <номера>` — подозреваемые\n"
        "• `пр <номер> <текст>` — протокол\n"
        "• `мн <номер> <текст>` — мнение\n"
        "• `очки <номер> <баллы>` — установить очки\n"
        "• `очистить <номер>` — сбросить всё\n\n"
        "Примеры:\n"
        "`роль 4 Шериф`\n"
        "`лх 5 2 7`\n"
        "`пр 3 5 6 красные 2 чёрные`",
        reply_markup=keyboards.game_admin_menu(),
        parse_mode="Markdown"
    )


@router.message(GameCreateState.editing_slots, F.text.regexp(r"^роль\s+\d+\s+\S+"))
async def edit_role_command(message: types.Message, state: FSMContext):
    if not await ensure_admin_pm(message):
        return

    parts = message.text.strip().split(maxsplit=2)
    if len(parts) < 3:
        return

    ok, slot_num, err = parse_slot_num(parts[1])
    if not ok:
        await message.answer(err)
        return

    role = parts[2].capitalize()
    valid = ["Мирный", "Шериф", "Мафия", "Дон", "Не задана"]
    if role not in valid:
        await message.answer(f"Доступные роли: {', '.join(valid)}")
        return

    slots = await get_slots(message, state)
    if not slots or slot_num not in slots:
        return

    slots[slot_num]["role"] = role
    if role in ["Мирный", "Шериф"]:
        slots[slot_num]["team"] = "Красные"
    elif role in ["Мафия", "Дон"]:
        slots[slot_num]["team"] = "Чёрные"

    await save_slots(state, slots)
    await message.answer(f"✅ Слот {slot_num}: роль → {role}")
    await show_game_state_all(message, state)


@router.message(GameCreateState.editing_slots, F.text.regexp(r"^команда\s+\d+\s+\S+"))
async def edit_team_command(message: types.Message, state: FSMContext):
    if not await ensure_admin_pm(message):
        return

    parts = message.text.strip().split(maxsplit=2)
    if len(parts) < 3:
        return

    ok, slot_num, err = parse_slot_num(parts[1])
    if not ok:
        await message.answer(err)
        return

    team = parts[2].capitalize()
    if team not in ["Красные", "Чёрные"]:
        await message.answer("Доступные команды: Красные, Чёрные")
        return

    slots = await get_slots(message, state)
    if not slots or slot_num not in slots:
        return

    slots[slot_num]["team"] = team
    await save_slots(state, slots)
    await message.answer(f"✅ Слот {slot_num}: команда → {team}")
    await show_game_state_all(message, state)


@router.message(GameCreateState.editing_slots, F.text.regexp(r"^статус\s+\d+\s+\S+"))
async def edit_status_command(message: types.Message, state: FSMContext):
    if not await ensure_admin_pm(message):
        return

    parts = message.text.strip().split(maxsplit=2)
    if len(parts) < 3:
        return

    ok, slot_num, err = parse_slot_num(parts[1])
    if not ok:
        await message.answer(err)
        return

    status = parts[2].lower()
    slots = await get_slots(message, state)
    if not slots or slot_num not in slots:
        return

    if status == "жив":
        slots[slot_num]["alive"] = True
        slots[slot_num]["status_reason"] = "Жив"
    elif status == "убит":
        slots[slot_num]["alive"] = False
        slots[slot_num]["status_reason"] = "Убит ночью"
    elif status == "заголосован":
        slots[slot_num]["alive"] = False
        slots[slot_num]["status_reason"] = "Заголосован"
    else:
        await message.answer("Доступные статусы: жив, убит, заголосован")
        return

    await save_slots(state, slots)
    await message.answer(f"✅ Слот {slot_num}: статус → {status}")
    await show_game_state_all(message, state)


@router.message(GameCreateState.editing_slots, F.text.regexp(r"^пу\s+\d+$"))
async def edit_pu_command(message: types.Message, state: FSMContext):
    if not await ensure_admin_pm(message):
        return

    parts = message.text.strip().split()
    if len(parts) < 2:
        return

    ok, slot_num, err = parse_slot_num(parts[1])
    if not ok:
        await message.answer(err)
        return

    slots = await get_slots(message, state)
    if not slots or slot_num not in slots:
        return

    # Снимаем ПУ со всех
    for s in slots.values():
        s["pu_mark"] = False
    slots[slot_num]["pu_mark"] = True

    await save_slots(state, slots)
    await message.answer(f"✅ Слот {slot_num} назначен ПУ")
    await show_game_state_all(message, state)


@router.message(GameCreateState.editing_slots, F.text.regexp(r"^пр\s+\d+\s+"))
async def edit_protocol_command(message: types.Message, state: FSMContext):
    if not await ensure_admin_pm(message):
        return

    parts = message.text.strip().split(maxsplit=2)
    if len(parts) < 3:
        return

    ok, slot_num, err = parse_slot_num(parts[1])
    if not ok:
        await message.answer(err)
        return

    protocol_text = parts[2].strip()
    if protocol_text.lower() == "нет":
        protocol_text = ""

    slots = await get_slots(message, state)
    if not slots or slot_num not in slots:
        return

    slots[slot_num]["will_protocol_raw"] = protocol_text
    await save_slots(state, slots)
    await message.answer(f"✅ Слот {slot_num}: ПР сохранён")
    await show_game_state_all(message, state)


@router.message(GameCreateState.editing_slots, F.text.regexp(r"^мн\s+\d+\s+"))
async def edit_opinion_command(message: types.Message, state: FSMContext):
    if not await ensure_admin_pm(message):
        return

    parts = message.text.strip().split(maxsplit=2)
    if len(parts) < 3:
        return

    ok, slot_num, err = parse_slot_num(parts[1])
    if not ok:
        await message.answer(err)
        return

    opinion_text = parts[2].strip()
    if opinion_text.lower() == "нет":
        opinion_text = ""

    slots = await get_slots(message, state)
    if not slots or slot_num not in slots:
        return

    slots[slot_num]["will_opinion"] = opinion_text
    await save_slots(state, slots)
    await message.answer(f"✅ Слот {slot_num}: МН сохранён")
    await show_game_state_all(message, state)


@router.message(GameCreateState.editing_slots, F.text.regexp(r"^очки\s+\d+\s+-?\d+\.?\d*"))
async def edit_points_command(message: types.Message, state: FSMContext):
    if not await ensure_admin_pm(message):
        return

    parts = message.text.strip().split()
    if len(parts) < 3:
        return

    ok, slot_num, err = parse_slot_num(parts[1])
    if not ok:
        await message.answer(err)
        return

    try:
        points = float(parts[2])
    except ValueError:
        await message.answer("Очки должны быть числом (например: 0.5, -0.2)")
        return

    slots = await get_slots(message, state)
    if not slots or slot_num not in slots:
        return

    slots[slot_num]["base_points"] = points
    await save_slots(state, slots)
    await message.answer(f"✅ Слот {slot_num}: очки → {points}")
    await show_game_state_all(message, state)


@router.message(GameCreateState.editing_slots, F.text.regexp(r"^очистить\s+\d+$"))
async def edit_clear_command(message: types.Message, state: FSMContext):
    if not await ensure_admin_pm(message):
        return

    parts = message.text.strip().split()
    if len(parts) < 2:
        return

    ok, slot_num, err = parse_slot_num(parts[1])
    if not ok:
        await message.answer(err)
        return

    slots = await get_slots(message, state)
    if not slots or slot_num not in slots:
        return

    # Сохраняем ник и базовую информацию
    nickname = slots[slot_num].get("nickname")
    full_name = slots[slot_num].get("full_name")
    user_id = slots[slot_num].get("user_id")
    username = slots[slot_num].get("username")

    # Очищаем всё
    slots[slot_num] = create_empty_slot(nickname or full_name or f"Слот {slot_num}")
    slots[slot_num].update({
        "user_id": user_id,
        "full_name": full_name,
        "username": username,
        "nickname": nickname,
    })

    await save_slots(state, slots)
    await message.answer(f"✅ Слот {slot_num}: полностью очищен")
    await show_game_state_all(message, state)


# ========== 10. CATCH-ALL ==========
@router.message(GameCreateState.editing_slots)
async def catch_all_in_game(message: types.Message, state: FSMContext):
    if not await ensure_admin_pm(message):
        return
    slots = await get_slots(message, state)
    if slots:
        await message.answer(build_game_state(slots, alive_only=False), reply_markup=keyboards.game_admin_menu())