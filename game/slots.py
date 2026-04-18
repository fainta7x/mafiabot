import random
from datetime import datetime

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode

import config
import database
import keyboards
from .state import GameCreateState
from .utils import build_slots_text, build_game_state, build_protocol_text

router = Router()

# =========================================================
# SLOTS ROUTER — РАБОТА СО СЛОТАМИ ИГРЫ
#
# Это файл отвечает за:
# - запуск новой игры;
# - продолжение сохранённой игры;
# - ручное редактирование ников и очистку слотов;
# - показ состояния игры;
# - завершение игры и протокол;
# - команды ЛХ и ПУ;
# - обработку любого текста во время игры.
#
# ОГЛАВЛЕНИЕ:
# 0. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# 1. СТАРТ / ПРОДОЛЖЕНИЕ ИГРЫ
# 2. РУЧНОЕ РЕДАКТИРОВАНИЕ НИКОВ
# 3. ОЧИСТКА СЛОТА
# 4. ПОКАЗ СОСТОЯНИЯ ИГРЫ
# 5. ЗАВЕРШЕНИЕ ИГРЫ + ПРОТОКОЛ
# 6. ПОЛНОЕ ЗАВЕРШЕНИЕ ИГРЫ
# 7. КОМАНДЫ ЛХ
# 8. КОМАНДЫ ПУ
# 9. ПРОИЗВОЛЬНЫЙ ТЕКСТ ВО ВРЕМЯ ИГРЫ
# =========================================================


# =========================================================
# 0. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# Здесь лежат общие функции, которые используются в разных
# хендлерах ниже:
#   - проверка, что пишет АДМИН в ЛИЧКУ;
#   - получение/сохранение слотов;
#   - разбор номера слота.
# =========================================================

def _is_admin_pm(message: types.Message) -> bool:
    """
    Проверяем, что сообщение от админа и в личных сообщениях боту.
    """
    return (
        message.from_user
        and message.from_user.id in config.ADMIN_IDS
        and message.chat.type == "private"
    )


async def _ensure_admin_pm(message: types.Message) -> bool:
    """
    Если НЕ админ или НЕ личка — вернёт False, хендлер просто выйдет.
    """
    if not _is_admin_pm(message):
        return False
    return True


async def _get_slots_or_reply(
    message: types.Message,
    state: FSMContext,
    allow_empty: bool = False,
) -> dict[int, dict]:
    """
    Получаем словарь slots из FSM.
    Если слотов нет и allow_empty=False — пишем подсказку и возвращаем {}.
    """
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}

    if not slots and not allow_empty:
        await message.answer(
            "Слоты пустые. Нажми «🎲 Новая игра», чтобы начать новую партию.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return {}

    return slots


def _parse_slot_num(
    raw: str | None,
    min_slot: int = 1,
    max_slot: int = 10,
):
    """
    Разбор номера слота с проверкой диапазона.
    Возвращает кортеж:
      (ok: bool, slot_num: int | None, error_text: str | None)
    """
    text = (raw or "").strip()
    if not text.isdigit():
        return False, None, f"Нужно ввести номер слота (число от {min_slot} до {max_slot})."

    slot_num = int(text)
    if slot_num < min_slot or slot_num > max_slot:
        return False, None, f"Номер слота должен быть от {min_slot} до {max_slot}."

    return True, slot_num, None


async def _save_slots(state: FSMContext, slots: dict[int, dict]):
    """
    Сохраняем slots сразу и в FSM-состоянии, и в базе.
    """
    await state.update_data(slots=slots)
    await database.save_current_game_slots(slots)


# =========================================================
# 1. СТАРТ / ПРОДОЛЖЕНИЕ ИГРЫ
#
# Хендлеры:
#   - start_new_game  — кнопка «🎲 Новая игра»
#   - resume_game     — кнопка «♻️ Продолжить игру»
#
# Здесь:
#   - создаются слоты на основе записавшихся игроков;
#   - выставляются номера игр (за день и глобальный);
#   - поднимается флаг "игра активна" в базе;
#   - можно восстановить игру после перезапуска бота.
# =========================================================

@router.message(F.text == "🎲 Новая игра")
async def start_new_game(message: types.Message, state: FSMContext):
    if not await _ensure_admin_pm(message):
        return

    active_flag = await database.get_setting("game_active")
    if active_flag == "1":
        await message.answer(
            "Уже есть активная игра. Сначала завершите её (кнопкой «Завершить игру»).",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    booked = await database.get_booked_players_for_game()
    if not booked:
        await message.answer(
            "На вечер никто не записан (со статусами «Вовремя» или «Позже») — не из кого собирать игру.",
            reply_markup=keyboards.admin_menu(),
        )
        return

    # === Дата и номера игры ===
    game_date = datetime.now().strftime("%d.%m.%Y")
    await database.set_current_game_date(game_date)

    evening_games = await database.get_games_by_date(game_date)
    evening_game_number = len(evening_games) + 1
    await database.set_current_game_number(evening_game_number)

    total_games = await database.get_total_games_count()
    global_game_number = total_games + 1
    await database.set_current_global_game_number(global_game_number)

    # === Формируем слоты на основе записавшихся игроков ===
    random.shuffle(booked)

    slots: dict[int, dict] = {}
    for i, (user_id, full_name, username, nickname, status) in enumerate(booked, start=1):
        slots[i] = {
            "user_id": user_id,
            "full_name": full_name,
            "nickname": nickname,
            "username": username,
            "status": status,
            "fouls": 0,
            "alive": True,
            "status_reason": "Жив",
            "nominated": False,
            "votes": 0,
            "night_suspects": [],
            "role": "Не задана",
            "team": None,
            "base_points": 0,
            "bonus_points": 0,
            "lh_points": 0.0,
            "pu_mark": False,
        }

    # Сохраняем состояние игры в FSM
    await state.set_state(GameCreateState.editing_slots)
    await state.update_data(
        slots=slots,
        roles_assigned=False,
        nominated_list=[],
        vote_index=0,
        split_candidates=[],
        in_split=False,
        first_night_kill_recorded=False,
        waiting_night_suspects_slot=None,
        night_killed_slot=None,
        winner_label=None,
    )

    # Флаг "игра активна" и сами слоты в базу
    await database.set_setting("game_active", "1")
    await database.save_current_game_slots(slots)

    # Выводим состав игры
    text = build_slots_text(slots)
    header = (
        f"🎲 Начата игра №{evening_game_number} ({game_date}): "
        f"№{global_game_number} по общей истории"
    )
    await message.answer(
        f"{header}\n\n{text}",
        reply_markup=keyboards.game_admin_menu(),
    )


@router.message(F.text == "♻️ Продолжить игру")
async def resume_game(message: types.Message, state: FSMContext):
    """
    Восстановить незавершённую игру из БД (если она есть).
    Работает и после перезапуска бота.
    """
    if not await _ensure_admin_pm(message):
        return

    active_flag = await database.get_setting("game_active")
    if active_flag != "1":
        await message.answer(
            "Нет активной сохранённой игры. Нажмите «🎲 Новая игра», чтобы начать новую.",
            reply_markup=keyboards.admin_menu(),
        )
        return

    slots = await database.load_current_game_slots()
    if not slots:
        await message.answer(
            "Не удалось найти сохранённые слоты игры. Нажмите «🎲 Новая игра», чтобы начать новую.",
            reply_markup=keyboards.admin_menu(),
        )
        return

    # Восстанавливаем состояние FSM
    await state.set_state(GameCreateState.editing_slots)
    await state.update_data(
        slots=slots,
        roles_assigned=False,
        nominated_list=[],
        vote_index=0,
        split_candidates=[],
        in_split=False,
        first_night_kill_recorded=False,
        waiting_night_suspects_slot=None,
        night_killed_slot=None,
        winner_label=None,
    )

    text = build_game_state(slots, alive_only=False)
    await message.answer(
        "Продолжаем незавершённую игру.\n\n" + text,
        reply_markup=keyboards.game_admin_menu(),
    )


# =========================================================
# 2. РУЧНОЕ РЕДАКТИРОВАНИЕ НИКОВ
#
# Хендлеры:
#   - manual_nick_edit — ввод вида: "<номер> <ник>"
#
# Здесь можно:
#   - поменять ник у уже существующего слота;
#   - создать новый слот с ником, если такого слота ещё нет.
# =========================================================

@router.message(GameCreateState.editing_slots, F.text.regexp(r"^\d+\s+"))
async def manual_nick_edit(message: types.Message, state: FSMContext):
    if not await _ensure_admin_pm(message):
        return

    lower = message.text.strip().lower()
    # Игнорируем служебные команды типа "1 ночь", "1 день", "1 жив"
    if lower.endswith(" ночь") or lower.endswith(" день") or lower.endswith(" жив"):
        return

    slots = await _get_slots_or_reply(message, state)
    if not slots:
        return

    # Ожидаем формат: "<номер_слота> <новый_ник>"
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "Формат: <номер_слота> <новый_ник>\nПример: 3 Волк",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    ok, slot_num, err = _parse_slot_num(parts[0])
    if not ok:
        await message.answer(err, reply_markup=keyboards.game_admin_menu())
        return

    new_nick = parts[1].strip()
    if not new_nick:
        await message.answer(
            "Ник не может быть пустым. Пример: 3 Волк",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    # Если слот существует — обновляем ник
    if slot_num in slots:
        slots[slot_num]["nickname"] = new_nick
        action = "обновлён"
    else:
        # Если слота нет — создаём новый «ручной» слот
        slots[slot_num] = {
            "user_id": None,
            "full_name": None,
            "nickname": new_nick,
            "username": None,
            "status": "Добавлен вручную",
            "fouls": 0,
            "alive": True,
            "status_reason": "Жив",
            "nominated": False,
            "votes": 0,
            "night_suspects": [],
            "role": "Не задана",
            "team": None,
            "base_points": 0,
            "bonus_points": 0,
            "lh_points": 0.0,
            "pu_mark": False,
        }
        action = "создан"

    await _save_slots(state, slots)

    text = build_slots_text(slots)
    await message.answer(
        f"Слот {slot_num} {action}, ник: «{new_nick}».\n\n{text}",
        reply_markup=keyboards.game_admin_menu(),
    )


# =========================================================
# 3. ОЧИСТКА СЛОТА
#
# Хендлеры:
#   - ask_clear_slot      — кнопка «🧹 Очистить слот»
#   - clear_slot_handler  — ввод номера слота
#
# Что делает:
#   - сбрасывает фолы, голоса, статус, ЛХ, ПУ и т.п.;
#   - НЕ трогает привязку к игроку, роль и команду.
# =========================================================

@router.message(F.text == "🧹 Очистить слот")
async def ask_clear_slot(message: types.Message, state: FSMContext):
    """
    Запрашиваем у админа номер слота для очистки.
    """
    if not await _ensure_admin_pm(message):
        return

    slots = await _get_slots_or_reply(message, state)
    if not slots:
        return

    await state.set_state(GameCreateState.waiting_clear_slot_number)
    await message.answer(
        "Какой слот очистить? Введите номер от 1 до 10.",
        reply_markup=keyboards.game_admin_menu(),
    )


@router.message(GameCreateState.waiting_clear_slot_number)
async def clear_slot_handler(message: types.Message, state: FSMContext):
    """
    Получаем номер слота, очищаем игровые поля и возвращаемся в режим редактирования.
    Работает даже если слот уже мёртв — можно откатить ошибки.
    """
    if not await _ensure_admin_pm(message):
        return

    ok, slot_num, err = _parse_slot_num(message.text)
    if not ok:
        await message.answer(err + " Попробуй ещё раз.", reply_markup=keyboards.game_admin_menu())
        return

    slots = await _get_slots_or_reply(message, state)
    if not slots:
        await state.set_state(GameCreateState.editing_slots)
        return

    slot = slots.get(slot_num)
    if not slot:
        await message.answer(
            f"Слот {slot_num} пока не занят. Нечего очищать.",
            reply_markup=keyboards.game_admin_menu(),
        )
        await state.set_state(GameCreateState.editing_slots)
        return

    # Очищаем только игровые поля, не трогаем привязку к игроку, роль и команду
    slot.update(
        fouls=0,
        alive=True,
        status_reason="Жив",
        nominated=False,
        votes=0,
        night_suspects=[],
        base_points=0,
        bonus_points=0,
        lh_points=0.0,
        pu_mark=False,
    )
    slots[slot_num] = slot

    await _save_slots(state, slots)

    game_text = build_game_state(slots, alive_only=False)
    await message.answer(
        f"Слот {slot_num} очищен: статус, фолы, голоса, ЛХ и ПУ сброшены.\n\n{game_text}",
        reply_markup=keyboards.game_admin_menu(),
    )

    await state.set_state(GameCreateState.editing_slots)


# =========================================================
# 4. ПОКАЗ СОСТОЯНИЯ ИГРЫ
#
# Хендлеры:
#   - ask_game_finish_reason — текст «остановить игру»
#   - show_game_state_all    — текст «игра»
#   - show_game_state_alive  — текст «игра живые»
#
# Здесь:
#   - спрашиваем, как завершить игру;
#   - показываем все слоты;
#   - показываем только живые слоты.
# =========================================================

@router.message(GameCreateState.editing_slots, F.text.casefold() == "остановить игру")
async def ask_game_finish_reason(message: types.Message, state: FSMContext):
    if not await _ensure_admin_pm(message):
        return
    await message.answer(
        "Как завершить текущую игру?",
        reply_markup=keyboards.game_finish_keyboard(),
    )


@router.message(GameCreateState.editing_slots, F.text.casefold() == "игра")
async def show_game_state_all(message: types.Message, state: FSMContext):
    if not await _ensure_admin_pm(message):
        return

    slots = await _get_slots_or_reply(message, state)
    if not slots:
        return

    text = build_game_state(slots, alive_only=False)
    await message.answer(text, reply_markup=keyboards.game_admin_menu())


@router.message(GameCreateState.editing_slots, F.text.casefold() == "игра живые")
async def show_game_state_alive(message: types.Message, state: FSMContext):
    if not await _ensure_admin_pm(message):
        return

    slots = await _get_slots_or_reply(message, state)
    if not slots:
        return

    text = build_game_state(slots, alive_only=True)
    await message.answer(text, reply_markup=keyboards.game_admin_menu())


# =========================================================
# 5. ЗАВЕРШЕНИЕ ИГРЫ + ПРОТОКОЛ
#
# Хендлеры:
#   - handle_game_finish — callback "game_end:*"
#
# Здесь:
#   - выбирается, кто победил (город/мафия/отмена);
#   - начисляются базовые очки по командам;
#   - автоматически считается ЛХ ПУ по night_suspects;
#   - формируется и сохраняется протокол игры.
# =========================================================

@router.callback_query(F.data.startswith("game_end:"))
async def handle_game_finish(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}

    action = callback.data.split(":", 1)[1]

    # Определяем результат
    if action == "city":
        result_text = "🏙 Игра завершена: Победа города (мирных жителей)."
        winning_team = "Красные"
        winner_label = "Победа города"
    elif action == "mafia":
        result_text = "💀 Игра завершена: Победа мафии."
        winning_team = "Чёрные"
        winner_label = "Победа мафии"
    else:
        result_text = "❌ Игра отменена без подведения итогов."
        winning_team = None
        winner_label = "Игра отменена"

    # Начисляем базовые очки по командам
    if winning_team is not None:
        await database.apply_game_result_to_users(slots, winning_team)
        for slot in slots.values():
            team = slot.get("team")
            if not team:
                slot["base_points"] = 0
            else:
                slot["base_points"] = 1 if team == winning_team else 0
    else:
        for slot in slots.values():
            slot["base_points"] = 0

    # === Расчёт ЛХ для ПУ (по night_suspects и team "Чёрные") ===
    for slot_num, slot in slots.items():
        if not slot.get("pu_mark"):
            # Не ПУ — ЛХ либо уже задан, либо 0
            slot["lh_points"] = float(slot.get("lh_points") or 0.0)
            slots[slot_num] = slot
            continue

        # Для ПУ смотрим, сколько чёрных он угадал
        suspects = slot.get("night_suspects") or []
        correct_blacks = 0

        for n in suspects:
            info = slots.get(n)
            if info and info.get("team") == "Чёрные":
                correct_blacks += 1

        if correct_blacks == 1:
            lh_val = 0.1
        elif correct_blacks == 2:
            lh_val = 0.3
        elif correct_blacks == 3:
            lh_val = 0.6
        else:
            lh_val = 0.0

        slot["lh_points"] = lh_val
        slots[slot_num] = slot

    # Достаём информацию о номерах игры и дате
    game_date = await database.get_current_game_date() or "-"
    evening_game_number = await database.get_current_game_number() or 1
    global_game_number = await database.get_current_global_game_number() or 1

    # Сохраняем историю слотов
    await database.save_game_slots_history(game_date, slots)

    # Формируем протокол
    protocol_body = build_protocol_text(
        slots,
        updated=False,
        winner_label=winner_label,
    )

    await database.save_game_history(
        game_date=game_date,
        winner_label=winner_label,
        protocol_text=protocol_body,
        game_number=evening_game_number,
        global_game_number=global_game_number,
    )

    header = (
        f"📑 Протокол игры №{evening_game_number} ({game_date}): "
        f"№{global_game_number} по общей истории — {winner_label}"
    )
    protocol_text = f"{header}\n\n{protocol_body}"

    # Обновляем сообщение с кнопками и отправляем протокол
    await callback.message.edit_text(result_text)
    protocol_msg = await callback.message.answer(
        protocol_text,
        reply_markup=keyboards.game_admin_menu(),
        parse_mode=ParseMode.HTML,
    )

    # Сохраняем ссылку на сообщение с протоколом
    await state.update_data(
        slots=slots,
        protocol_chat_id=protocol_msg.chat.id,
        protocol_message_id=protocol_msg.message_id,
        winner_label=winner_label,
    )

    await database.save_current_game_slots(slots)
    await state.set_state(GameCreateState.editing_slots)

    await callback.answer()


# =========================================================
# 6. ПОЛНОЕ ЗАВЕРШЕНИЕ ИГРЫ
#
# Хендлеры:
#   - final_finish_game — текст «завершить игру»
#
# Полностью очищает:
#   - FSM-состояние;
#   - флаг "game_active" и текущие слоты/даты/номера в базе.
# =========================================================

@router.message(GameCreateState.editing_slots, F.text.casefold() == "завершить игру")
async def final_finish_game(message: types.Message, state: FSMContext):
    if not await _ensure_admin_pm(message):
        return

    await state.clear()
    await database.set_setting("game_active", None)
    await database.set_setting("current_game_slots", None)
    await database.set_setting("current_game_date", None)
    await database.set_setting("current_game_number", None)
    await database.set_setting("current_game_global_number", None)

    await message.answer(
        "Игра полностью завершена. Можно запускать новую.",
        reply_markup=keyboards.admin_menu(),
    )


# =========================================================
# 7. КОМАНДЫ ЛХ (night_suspects)
#
# Хендлеры:
#   - manual_lh_input — текст вида: "лх <слот> [список слотов]"
#
# Примеры:
#   - "лх 5 1 2 3"  -> для слота 5 подозреваемые [1,2,3]
#   - "лх 5"        -> очищаем подозреваемых для слота 5
#
# Сам ЛХ (0.1 / 0.3 / 0.6) считается в handle_game_finish
# на основе night_suspects и команды игроков.
# =========================================================

@router.message(F.text.regexp(r"^лх\s+"))
async def manual_lh_input(message: types.Message, state: FSMContext):
    if not await _ensure_admin_pm(message):
        return

    slots = await _get_slots_or_reply(message, state)
    if not slots:
        return

    text = (message.text or "").strip().lower()
    parts = text.split()

    if len(parts) < 2:
        await message.answer(
            "Формат: лх <номер_слота> [подозреваемые через пробел]\n"
            "Например: лх 5 1 2 3",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    ok, slot_num, err = _parse_slot_num(parts[1])
    if not ok:
        await message.answer(err, reply_markup=keyboards.game_admin_menu())
        return

    slot = slots.get(slot_num)
    if not slot:
        await message.answer(
            f"Слот {slot_num} пока не занят. Нечего менять.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    suspects_raw = parts[2:]
    suspects: list[int] = []

    for p in suspects_raw:
        p = p.strip()
        if not p:
            continue
        if not p.isdigit():
            continue
        num = int(p)
        if 1 <= num <= 10 and num not in suspects:
            suspects.append(num)

    slot["night_suspects"] = suspects
    slots[slot_num] = slot

    await _save_slots(state, slots)

    if suspects:
        suspects_str = ", ".join(str(x) for x in suspects)
        msg = (
            f"Для слота {slot_num} вручную задан список подозреваемых: {suspects_str}.\n"
            "ЛХ будет автоматически пересчитан при завершении игры."
        )
    else:
        msg = (
            f"Для слота {slot_num} список подозреваемых очищен.\n"
            "ЛХ для этого слота будет 0 при завершении игры."
        )

    game_text = build_game_state(slots, alive_only=False)
    await message.answer(
        f"{msg}\n\n{game_text}",
        reply_markup=keyboards.game_admin_menu(),
    )


# =========================================================
# 8. КОМАНДЫ ПУ (ПРОВЕРЯЮЩИЙ УЛИЦЫ) + ПОДОЗРЕВАЕМЫЕ
#
# Хендлеры:
#   - manual_pu_and_lh_input — текст "пу <слот> [список слотов]"
#
# Примеры:
#   - "пу 4 1 2 3"  -> слот 4 становится ПУ, подозреваемые [1,2,3]
#   - "пу 4"        -> слот 4 ПУ, список подозреваемых очищен
#
# При этом:
#   - ПУ снимается со всех остальных слотов;
#   - night_suspects обновляется для указанного слота.
# =========================================================

@router.message(F.text.regexp(r"^пу\s+"))
async def manual_pu_and_lh_input(message: types.Message, state: FSMContext):
    if not await _ensure_admin_pm(message):
        return

    slots = await _get_slots_or_reply(message, state)
    if not slots:
        return

    text = (message.text or "").strip().lower()
    parts = text.split()

    if len(parts) < 2:
        await message.answer(
            "Формат: пу <номер_слота> [подозреваемые через пробел]\n"
            "Например: пу 4 1 2 3",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    ok, slot_num, err = _parse_slot_num(parts[1])
    if not ok:
        await message.answer(err, reply_markup=keyboards.game_admin_menu())
        return

    slot = slots.get(slot_num)
    if not slot:
        await message.answer(
            f"Слот {slot_num} пока не занят. Нечего менять.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    suspects_raw = parts[2:]
    suspects: list[int] = []

    for p in suspects_raw:
        p = p.strip()
        if not p:
            continue
        if not p.isdigit():
            continue
        num = int(p)
        if 1 <= num <= 10 and num not in suspects:
            suspects.append(num)

    # Снимаем ПУ со всех и назначаем нового
    for s_num, s_info in slots.items():
        s_info["pu_mark"] = (s_num == slot_num)

    slot["night_suspects"] = suspects
    slots[slot_num] = slot

    await _save_slots(state, slots)

    if suspects:
        suspects_str = ", ".join(str(x) for x in suspects)
        msg = (
            f"Слот {slot_num} назначен ПУ.\n"
            f"Подозреваемые для ПУ: {suspects_str}.\n"
            "ЛХ будет автоматически посчитан при завершении игры."
        )
    else:
        msg = (
            f"Слот {slot_num} назначен ПУ.\n"
            "Список подозреваемых очищен, ЛХ пока 0."
        )

    game_text = build_game_state(slots, alive_only=False)
    await message.answer(
        f"{msg}\n\n{game_text}",
        reply_markup=keyboards.game_admin_menu(),
    )


# =========================================================
# 9. ПРОИЗВОЛЬНЫЙ ТЕКСТ ВО ВРЕМЯ ИГРЫ (CATCH-ALL)
#
# Хендлеры:
#   - catch_all_in_game — любое сообщение в состоянии editing_slots,
#                         которое не попало под более специфичные
#                         хендлеры (лх/пу/доп и т.п.)
#
# Здесь:
#   - игнорируем команды, которые должны обрабатываться отдельно;
#   - по любому другому тексту просто показываем текущее состояние игры.
# =========================================================

@router.message(GameCreateState.editing_slots)
async def catch_all_in_game(message: types.Message, state: FSMContext):
    text_raw = (message.text or "").strip().lower()

    # Эти префиксы обрабатываются отдельными хендлерами
    if text_raw.startswith("доп "):
        return

    if text_raw.startswith("лх "):
        return

    if text_raw.startswith("пу "):
        return

    slots = await _get_slots_or_reply(message, state)
    if not slots:
        return

    text = build_game_state(slots, alive_only=False)
    await message.answer(
        text,
        reply_markup=keyboards.game_admin_menu(),
    )