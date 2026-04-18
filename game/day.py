from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode

import keyboards
import database
from .state import GameCreateState
from .text import (
    _parse_slots_list,
    build_game_state,
    build_votes_summary,
    build_protocol_text,
)

router = Router()

# =========================================================
# FOULS & VOTES ROUTER — ФОЛЫ, ВЫСТАВЛЕНИЕ, ГОЛОСА, ДОПЫ, ПР/МН
#
# ОГЛАВЛЕНИЕ:
# 0. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# 1. ФОЛЫ
# 2. ВЫСТАВЛЕНИЕ (НОМИНАЦИЯ)
# 3. ГОЛОСОВАНИЕ С ПОПИЛОМ
# 4. РЕШЕНИЕ ПО ВТОРОМУ ПОПИЛУ
# 5. ДОПЫ ("доп")
# 6. БАЛЛЫ ЗА ЗАВЕЩАНИЯ ("пр", "мн")
# =========================================================


# =========================================================
# 0. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =========================================================

def _parse_bonus_value(raw: str) -> float | None:
    """
    Парсим доп и всегда приводим его к шагу 0.1.

    Правила:
    - Целые числа интерпретируем как десятые:
        "1", "01"   -> 0.1
        "2", "02"   -> 0.2
        "-3", "-03" -> -0.3

    - Дроби читаем как есть:
        "0.2", "0,2", ".2", ",2"       -> 0.2
        "-0.3", "-0,3", "-.3", "-,3"   -> -0.3
    """
    s = raw.strip().replace(",", ".")
    if not s:
        return None

    # случаи вида ".2" / "-.3" -> "0.2" / "-0.3"
    if s.startswith(".") or s.startswith("-."):
        s = s.replace(".", "0.", 1)

    try:
        val = float(s)
    except ValueError:
        return None

    # Если нет десятичной точки в исходной строке — считаем, что это целое "в десятых"
    if "." not in s:
        try:
            n = int(s)
        except ValueError:
            return None
        val = n / 10.0

    return round(val, 1)


def _parse_float_value(raw: str) -> float | None:
    """
    Универсальный парсер числа с точкой/запятой (оставлен на всякий случай,
    сейчас ПР/МН тоже используют _parse_bonus_value, как допы).
    """
    s = (raw or "").strip().replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _attach_night_kills_order(slots: dict[int, dict], data: dict) -> None:
    """
    Приклеивает порядок ночных убийств из FSM в slots["_night_kills_order"],
    чтобы build_protocol_text мог нарисовать блок «Убийства».
    """
    night_kills_order: list[int] = data.get("night_kills_order") or []
    if night_kills_order:
        slots["_night_kills_order"] = night_kills_order
    else:
        # На всякий случай чистим служебный ключ, если порядок пуст
        slots.pop("_night_kills_order", None)


async def _update_main_protocol_message(
    message: types.Message,
    state: FSMContext,
    slots: dict[int, dict],
):
    """
    Перерисовать основное сообщение с протоколом игры на основе актуальных slots.
    Ожидает, что в FSM лежат protocol_chat_id, protocol_message_id, winner_label.
    """
    data = await state.get_data()

    # Приклеиваем порядок ночных убийств, если он есть
    _attach_night_kills_order(slots, data)

    protocol_body = build_protocol_text(slots, updated=True)

    protocol_chat_id = data.get("protocol_chat_id")
    protocol_message_id = data.get("protocol_message_id")
    winner_label = data.get("winner_label")

    # Если нет сохранённого сообщения — просто отправим новый протокол,
    # чтобы не терять информацию
    if not protocol_chat_id or not protocol_message_id or winner_label is None:
        print("[PROTO] No stored protocol message, sending new one")
        await message.answer(
            protocol_body,
            reply_markup=keyboards.game_admin_menu(),
            parse_mode=ParseMode.HTML,
        )
        return

    # Вытаскиваем текущие номера игры из "current_*"
    game_date = await database.get_current_game_date() or "-"
    evening_game_number = await database.get_current_game_number() or 1
    global_game_number = await database.get_current_global_game_number() or 1

    header = (
        f"📑 Протокол игры №{evening_game_number} ({game_date}): "
        f"№{global_game_number} по общей истории — {winner_label}"
    )
    full_text = f"{header}\n\n{protocol_body}"

    try:
        print(
            f"[PROTO] Editing message chat_id={protocol_chat_id}, "
            f"message_id={protocol_message_id}"
        )
        await message.bot.edit_message_text(
            chat_id=protocol_chat_id,
            message_id=protocol_message_id,
            text=full_text,
            reply_markup=keyboards.game_admin_menu(),
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        # Логируем ошибку и шлём новый протокол, чтобы ничего не потерять
        print(f"[PROTO] Failed to edit message: {repr(e)}")
        await message.answer(
            full_text,
            reply_markup=keyboards.game_admin_menu(),
            parse_mode=ParseMode.HTML,
        )


# =========================================================
# 1. ФОЛЫ
# =========================================================

@router.message(
    GameCreateState.editing_slots,
    F.text.func(lambda t: (t or "").strip().lower().startswith("фол")),
)
async def ask_fouls(message: types.Message, state: FSMContext):
    await state.set_state(GameCreateState.waiting_fouls)
    await message.answer(
        "Режим фолов.\n"
        "Чтобы ДОБАВИТЬ фол, введи номера слотов через пробел:\n"
        "например: `3 7` — по фолу игрокам 3 и 7.\n\n"
        "Чтобы СНЯТЬ фол, начни со знака минус:\n"
        "`- 3 8` — убрать по фолу с игроков 3 и 8.",
        reply_markup=keyboards.game_admin_menu(),
    )


@router.message(GameCreateState.waiting_fouls)
async def apply_fouls(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}

    text = (message.text or "").strip()
    if not text:
        await message.answer(
            "Пустой ввод. Пример: `3 7` или `- 3 8`.",
            reply_markup=keyboards.game_admin_menu(),
        )
        await state.set_state(GameCreateState.editing_slots)
        return

    mode = "add"
    if text.startswith("-"):
        mode = "remove"
        text = text[1:].strip()

    nums = _parse_slots_list(text)
    if not nums:
        await message.answer(
            "Не получилось распознать номера слотов.\n"
            "Пример: `3 7` или `- 3 8`.",
            reply_markup=keyboards.game_admin_menu(),
        )
        await state.set_state(GameCreateState.editing_slots)
        return

    for n in nums:
        if n not in slots or n < 1 or n > 10:
            continue
        if not slots[n].get("alive", True):
            continue

        fouls = slots[n].get("fouls", 0)
        if mode == "add":
            fouls += 1
        else:
            fouls = max(0, fouls - 1)
        slots[n]["fouls"] = fouls

    await state.update_data(slots=slots)

    game_text = build_game_state(slots, alive_only=False)
    await message.answer(game_text, reply_markup=keyboards.game_admin_menu())
    await state.set_state(GameCreateState.editing_slots)


# =========================================================
# 2. ВЫСТАВЛЕНИЕ (НОМИНАЦИЯ)
# =========================================================

@router.message(
    GameCreateState.editing_slots,
    F.text.func(lambda t: (t or "").strip().lower().startswith("выставить")),
)
async def ask_nominees(message: types.Message, state: FSMContext):
    await state.set_state(GameCreateState.waiting_nominees)
    await message.answer(
        "Введи номера выставленных слотов через пробел.\n"
        "Пример: `1 3 7`",
        reply_markup=keyboards.game_admin_menu(),
    )


@router.message(GameCreateState.waiting_nominees)
async def set_nominees(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}
    nominated_list: list[int] = data.get("nominated_list") or [
        s for s, info in slots.items() if info.get("nominated")
    ]

    nums = _parse_slots_list(message.text or "")
    if not nums:
        await message.answer(
            "Не удалось распознать номера. Пример: `1 3 7`.",
            reply_markup=keyboards.game_admin_menu(),
        )
        await state.set_state(GameCreateState.editing_slots)
        return

    for n in nums:
        if n in slots and 1 <= n <= 10:
            if not slots[n].get("alive", True):
                continue
            slots[n]["nominated"] = True
            slots[n].setdefault("votes", 0)
            if n not in nominated_list:
                nominated_list.append(n)

    await state.update_data(slots=slots, nominated_list=nominated_list, vote_index=0)

    game_text = build_game_state(slots, alive_only=False)
    await message.answer(game_text, reply_markup=keyboards.game_admin_menu())
    await state.set_state(GameCreateState.editing_slots)


# =========================================================
# 3. ГОЛОСОВАНИЕ С ПОПИЛОМ
# =========================================================

@router.message(
    GameCreateState.editing_slots,
    F.text.func(lambda t: (t or "").strip().lower().startswith("голоса")),
)
async def start_votes(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}
    in_split: bool = data.get("in_split", False)
    split_candidates: list[int] = data.get("split_candidates") or []

    # ИСПРАВЛЕНО: логическое and вместо побитового &
    if in_split and split_candidates:
        nominated_list = [
            s for s in split_candidates
            if s in slots and slots[s].get("alive", True)
        ]
        for s, info in slots.items():
            info["nominated"] = (s in nominated_list)
            info["votes"] = 0
    else:
        nominated_list = [
            s for s, info in slots.items()
            if info.get("nominated") and info.get("alive", True)
        ]

    if not nominated_list:
        await message.answer(
            "Сначала нужно выставить живых игроков (кнопка «Выставить»).",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    await state.set_state(GameCreateState.waiting_votes)
    await state.update_data(
        nominated_list=nominated_list,
        vote_index=0,
        slots=slots,
    )

    first_slot = nominated_list[0]
    await message.answer(
        f"Голоса.\nСколько голосов за слот {first_slot}?",
        reply_markup=keyboards.game_admin_menu(),
    )


@router.message(GameCreateState.waiting_votes)
async def collect_votes(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}
    nominated_list: list[int] = data.get("nominated_list") or []
    vote_index: int = data.get("vote_index", 0)
    in_split: bool = data.get("in_split", False)

    if not nominated_list or vote_index >= len(nominated_list):
        await state.set_state(GameCreateState.editing_slots)
        await message.answer(
            "Что-то пошло не так с голосованием. Попробуй начать заново кнопкой «Голоса».",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    text = (message.text or "").strip()
    try:
        votes = int(text)
    except ValueError:
        await message.answer(
            "Нужно ввести число голосов. Пример: 3",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    slot_num = nominated_list[vote_index]
    if slot_num in slots:
        slots[slot_num]["votes"] = max(0, votes)

    vote_index += 1
    await state.update_data(slots=slots, vote_index=vote_index, nominated_list=nominated_list)

    # Если ещё не всех спросили — спрашиваем следующий слот
    if vote_index < len(nominated_list):
        next_slot = nominated_list[vote_index]
        await message.answer(
            f"Сколько голосов за слот {next_slot}?",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    # === все голоса собраны ===
    live_nominated = [
        n for n in nominated_list
        if n in slots and slots[n].get("alive", True)
    ]

    leaders: list[int] = []
    max_votes = 0
    if live_nominated:
        max_votes = max(slots[n]["votes"] for n in live_nominated)
        if max_votes > 0:
            leaders = [n for n in live_nominated if slots[n]["votes"] == max_votes]

    # 1. Один лидер — его заголосовали
    if len(leaders) == 1:
        leader = leaders[0]
        slots[leader]["alive"] = False
        slots[leader]["status_reason"] = "Заголосован"

        for n in live_nominated:
            slots[n]["nominated"] = False
            slots[n]["votes"] = 0

        await state.update_data(
            slots=slots,
            nominated_list=[],
            vote_index=0,
            in_split=False,
            split_candidates=[],
        )

        summary = build_votes_summary(slots)
        game_state = build_game_state(slots, alive_only=False)

        await message.answer(
            summary + "\n\n" + game_state,
            reply_markup=keyboards.game_admin_menu(),
        )
        await state.set_state(GameCreateState.editing_slots)
        return

    # 2. Несколько лидеров с одинаковым max_votes > 0
    if len(leaders) > 1:
        leaders_sorted = sorted(leaders)
        leaders_text = ", ".join(str(n) for n in leaders_sorted)

        if not in_split:
            # Первый попил — объявляем и готовим переголосовку только между лидерами
            for n in live_nominated:
                slots[n]["votes"] = 0

            for s, info in slots.items():
                info["nominated"] = (s in leaders)

            await state.update_data(
                slots=slots,
                nominated_list=leaders_sorted,
                vote_index=0,
                in_split=True,
                split_candidates=leaders_sorted,
            )

            game_state = build_game_state(slots, alive_only=False)
            await message.answer(
                f"ПОПИЛ МЕЖДУ ИГРОКАМИ: {leaders_text}\n"
                f"У каждого оправдательная речь, затем переголосование только между ними.\n\n"
                f"{game_state}",
                reply_markup=keyboards.game_admin_menu(),
            )
            await state.set_state(GameCreateState.editing_slots)
            return
        else:
            # ВТОРОЙ ПОПИЛ — спрашиваем, что делать (поднять всех / оставить всех)
            await state.update_data(
                slots=slots,
                split_candidates=leaders_sorted,
                nominated_list=leaders_sorted,
                vote_index=0,
                in_split=False,
            )

            game_state = build_game_state(slots, alive_only=False)
            await message.answer(
                "Повторный попил: голоса снова поровну.\n"
                f"Игроки: {leaders_text}\n"
                "Что делаем?",
                reply_markup=keyboards.split_decision_keyboard(),
            )
            await state.set_state(GameCreateState.editing_slots)
            return

    # 3. max_votes == 0 или live_nominated пуст — никто не заголосован
    for n in live_nominated:
        slots[n]["nominated"] = False
        slots[n]["votes"] = 0

    await state.update_data(
        slots=slots,
        nominated_list=[],
        vote_index=0,
        in_split=False,
        split_candidates=[],
    )

    game_state = build_game_state(slots, alive_only=False)
    await message.answer(
        "Никто не был заголосован по итогам голосования.\n\n" + game_state,
        reply_markup=keyboards.game_admin_menu(),
    )
    await state.set_state(GameCreateState.editing_slots)


# =========================================================
# 4. РЕШЕНИЕ ПО ВТОРОМУ ПОПИЛУ
# =========================================================

@router.callback_query(F.data == "split:kill_all")
async def split_kill_all(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}
    split_candidates: list[int] = data.get("split_candidates") or []

    live_candidates = [
        n for n in split_candidates
        if n in slots and slots[n].get("alive", True)
    ]

    for n in live_candidates:
        slots[n]["alive"] = False
        slots[n]["status_reason"] = "Заголосован"
        slots[n]["nominated"] = False
        slots[n]["votes"] = 0

    await state.update_data(
        slots=slots,
        nominated_list=[],
        vote_index=0,
        in_split=False,
        split_candidates=[],
    )

    game_state = build_game_state(slots, alive_only=False)

    await callback.message.edit_text(
        "Решение: Поднять всех.\n"
        "Все игроки из попила заголосованы."
    )
    await callback.message.answer(
        game_state,
        reply_markup=keyboards.game_admin_menu(),
    )

    await callback.answer()


@router.callback_query(F.data == "split:keep_all")
async def split_keep_all(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}
    split_candidates: list[int] = data.get("split_candidates") or []

    for n in split_candidates:
        if n in slots:
            slots[n]["nominated"] = False
            slots[n]["votes"] = 0

    await state.update_data(
        slots=slots,
        nominated_list=[],
        vote_index=0,
        in_split=False,
        split_candidates=[],
    )

    game_state = build_game_state(slots, alive_only=False)

    await callback.message.edit_text(
        "Решение: Оставить всех.\n"
        "Никто из попила не заголосovan."
    )
    await callback.message.answer(
        game_state,
        reply_markup=keyboards.game_admin_menu(),
    )

    await callback.answer()


# =========================================================
# 5. ДОПЫ ("доп")
# =========================================================

@router.message(GameCreateState.editing_slots, F.text.regexp(r"^доп\s+"))
async def apply_bonus_points(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    parts = text.split()

    if len(parts) < 3:
        await message.answer(
            "Формат допа: `доп <номер_слота> <доп>`.\n"
            "Примеры: `доп 4 2` (0.2), `доп 4 0,2`, `доп 4 ,2`.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    _, slot_raw, bonus_raw = parts[0], parts[1], parts[2]

    try:
        slot_num = int(slot_raw)
    except ValueError:
        await message.answer(
            "Вторым должно быть число — номер слота.\n"
            "Пример: `доп 4 2`.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    bonus_val = _parse_bonus_value(bonus_raw)
    if bonus_val is None:
        await message.answer(
            "Не удалось разобрать доп. Используй форматы:\n"
            "`доп 4 2` (0.2), `доп 4 -3` (-0.3), `доп 4 0.4`, `доп 4 0,4`, "
            "`доп 4 .5`, `доп 4 ,5`.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}

    if slot_num not in slots:
        await message.answer(
            f"Слот {slot_num} не найден.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    slot = slots[slot_num]

    current_bonus = slot.get("bonus_points", 0.0) or 0.0
    slot["bonus_points"] = round(current_bonus + bonus_val, 1)
    slots[slot_num] = slot

    await state.update_data(slots=slots)

    sign = "+" if bonus_val >= 0 else ""
    await message.answer(
        f"Допы: слот {slot_num} ({sign}{bonus_val} очков). Протокол обновлён 👇",
        reply_markup=keyboards.game_admin_menu(),
    )

    await _update_main_protocol_message(message, state, slots)


# =========================================================
# 6. БАЛЛЫ ЗА ЗАВЕЩАНИЯ ("пр", "мн")
# =========================================================

@router.message(GameCreateState.editing_slots, F.text.regexp(r"^пр\s+"))
async def set_protocol_points(message: types.Message, state: FSMContext):
    """
    Установка балла за ПРОТОКОЛ завещания.
    Формат: 'пр <номер_слота> <балл>' -> will_protocol_points.
    """
    text = (message.text or "").strip()
    parts = text.split()

    if len(parts) < 3:
        await message.answer(
            "Формат: `пр <номер_слота> <балл>`.\n"
            "Примеры: `пр 5 0.2`, `пр 5 0`, `пр 5 -0.1`.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    _, slot_raw, pts_raw = parts[0], parts[1], parts[2]

    try:
        slot_num = int(slot_raw)
    except ValueError:
        await message.answer(
            "Вторым должно быть число — номер слота.\n"
            "Пример: `пр 5 0.2`.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    # ПР парсим как доп, чтобы 2 / 02 / 0.2 / 0,2 / .2 / ,2 => 0.2
    bonus_val = _parse_bonus_value(pts_raw)
    if bonus_val is None:
        await message.answer(
            "Третьим должно быть число — балл.\n"
            "Примеры: `0.2`, `0`, `-0.1`.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}

    if slot_num not in slots:
        await message.answer(
            f"Слот {slot_num} не найден.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    # Для ПР ставим значение, не накапливаем
    slots[slot_num]["will_protocol_points"] = bonus_val
    await state.update_data(slots=slots)

    sign = "+" if bonus_val >= 0 else ""
    await message.answer(
        f"ПР: слот {slot_num} ({sign}{bonus_val} очков). Протокол обновлён 👇",
        reply_markup=keyboards.game_admin_menu(),
    )

    await _update_main_protocol_message(message, state, slots)


@router.message(GameCreateState.editing_slots, F.text.regexp(r"^мн\s+"))
async def set_opinion_points(message: types.Message, state: FSMContext):
    """
    Установка балла за МНЕНИЕ завещания.
    Формат: 'мн <номер_слота> <балл>' -> will_opinion_points.
    """
    text = (message.text or "").strip()
    parts = text.split()

    if len(parts) < 3:
        await message.answer(
            "Формат: `мн <номер_слота> <балл>`.\n"
            "Примеры: `мн 5 0.2`, `мн 5 0`, `мн 5 -0.1`.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    _, slot_raw, pts_raw = parts[0], parts[1], parts[2]

    try:
        slot_num = int(slot_raw)
    except ValueError:
        await message.answer(
            "Вторым должно быть число — номер слота.\n"
            "Пример: `мн 5 0.2`.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    # МН тоже парсим как доп
    bonus_val = _parse_bonus_value(pts_raw)
    if bonus_val is None:
        await message.answer(
            "Третьим должно быть число — балл.\n"
            "Примеры: `0.2`, `0`, `-0.1`.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}

    if slot_num not in slots:
        await message.answer(
            f"Слот {slot_num} не найден.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    slots[slot_num]["will_opinion_points"] = bonus_val
    await state.update_data(slots=slots)

    sign = "+" if bonus_val >= 0 else ""
    await message.answer(
        f"МН: слот {slot_num} ({sign}{bonus_val} очков). Протокол обновлён 👇",
        reply_markup=keyboards.game_admin_menu(),
    )

    await _update_main_protocol_message(message, state, slots)