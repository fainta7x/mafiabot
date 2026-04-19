from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode

import keyboards
import database
from .state import GameCreateState
from .text import _parse_slots_list, build_game_state, build_votes_summary, build_protocol_text

router = Router()


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def _parse_bonus_value(raw: str) -> float | None:
    """Парсит доп, ПР, МН с шагом 0.1. Поддерживает целые (2→0.2) и дроби (0.2, .2)."""
    s = raw.strip().replace(",", ".")
    if not s:
        return None

    if s.startswith(".") or s.startswith("-."):
        s = s.replace(".", "0.", 1)

    try:
        val = float(s)
    except ValueError:
        return None

    if "." not in s:  # целое число → десятые
        try:
            val = int(s) / 10.0
        except ValueError:
            return None

    return round(val, 1)


def _attach_night_kills_order(slots: dict, data: dict) -> None:
    """Добавляет порядок ночных убийств в slots для протокола."""
    kills = data.get("night_kills_order") or []
    if kills:
        slots["_night_kills_order"] = kills
    else:
        slots.pop("_night_kills_order", None)


async def _update_protocol(message: types.Message, state: FSMContext, slots: dict):
    """Обновляет основное сообщение с протоколом игры."""
    data = await state.get_data()
    _attach_night_kills_order(slots, data)

    protocol = build_protocol_text(slots, updated=True)
    chat_id = data.get("protocol_chat_id")
    msg_id = data.get("protocol_message_id")
    winner = data.get("winner_label")

    if not chat_id or not msg_id or winner is None:
        await message.answer(protocol, reply_markup=keyboards.game_admin_menu(), parse_mode=ParseMode.HTML)
        return

    game_date = await database.get_current_game_date() or "-"
    evening_num = await database.get_current_game_number() or 1
    global_num = await database.get_current_global_game_number() or 1

    full_text = f"📑 Протокол игры №{evening_num} ({game_date}): №{global_num} по общей истории — {winner}\n\n{protocol}"

    try:
        await message.bot.edit_message_text(full_text, chat_id=chat_id, message_id=msg_id,
                                            reply_markup=keyboards.game_admin_menu(), parse_mode=ParseMode.HTML)
    except Exception as e:
        print(f"[PROTO] Edit failed: {e}")
        await message.answer(full_text, reply_markup=keyboards.game_admin_menu(), parse_mode=ParseMode.HTML)


def _clear_nominations(slots: dict, candidates: list[int] = None):
    """Сбрасывает статус номинации и голоса у указанных слотов (или у всех)."""
    targets = candidates if candidates is not None else slots.keys()
    for n in targets:
        if n in slots:
            slots[n]["nominated"] = False
            slots[n]["votes"] = 0


# ========== 1. ФОЛЫ ==========
@router.message(GameCreateState.editing_slots, F.text.func(lambda t: (t or "").strip().lower().startswith("фол")))
async def ask_fouls(message: types.Message, state: FSMContext):
    await state.set_state(GameCreateState.waiting_fouls)
    await message.answer(
        "Режим фолов.\nДОБАВИТЬ: `3 7`\nСНЯТЬ: `- 3 8`",
        reply_markup=keyboards.game_admin_menu()
    )


@router.message(GameCreateState.waiting_fouls)
async def apply_fouls(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots = data.get("slots") or {}
    text = (message.text or "").strip()

    if not text:
        await message.answer("Пустой ввод.", reply_markup=keyboards.game_admin_menu())
        await state.set_state(GameCreateState.editing_slots)
        return

    mode, text = ("remove", text[1:].strip()) if text.startswith("-") else ("add", text)
    nums = _parse_slots_list(text)

    for n in nums:
        if n in slots and slots[n].get("alive", True):
            slots[n]["fouls"] = max(0, (slots[n].get("fouls", 0) + (1 if mode == "add" else -1)))

    await state.update_data(slots=slots)
    await message.answer(build_game_state(slots, alive_only=False), reply_markup=keyboards.game_admin_menu())
    await state.set_state(GameCreateState.editing_slots)


# ========== 2. ВЫСТАВЛЕНИЕ ==========
@router.message(GameCreateState.editing_slots, F.text.func(lambda t: (t or "").strip().lower().startswith("выставить")))
async def ask_nominees(message: types.Message, state: FSMContext):
    await state.set_state(GameCreateState.waiting_nominees)
    await message.answer("Введи номера выставленных слотов через пробел.\nПример: `1 3 7`",
                         reply_markup=keyboards.game_admin_menu())


@router.message(GameCreateState.waiting_nominees)
async def set_nominees(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots = data.get("slots") or {}
    nums = _parse_slots_list(message.text or "")

    if not nums:
        await message.answer("Не удалось распознать номера.", reply_markup=keyboards.game_admin_menu())
        await state.set_state(GameCreateState.editing_slots)
        return

    nominated = []
    for n in nums:
        if n in slots and slots[n].get("alive", True):
            slots[n]["nominated"] = True
            slots[n].setdefault("votes", 0)
            nominated.append(n)

    await state.update_data(slots=slots, nominated_list=nominated, vote_index=0)
    await message.answer(build_game_state(slots, alive_only=False), reply_markup=keyboards.game_admin_menu())
    await state.set_state(GameCreateState.editing_slots)


# ========== 3. ГОЛОСОВАНИЕ ==========
@router.message(GameCreateState.editing_slots, F.text.func(lambda t: (t or "").strip().lower().startswith("голоса")))
async def start_votes(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots = data.get("slots") or {}
    in_split = data.get("in_split", False)
    split_candidates = data.get("split_candidates") or []

    if in_split and split_candidates:
        nominated = [s for s in split_candidates if s in slots and slots[s].get("alive", True)]
        for s in slots:
            slots[s]["nominated"] = s in nominated
            slots[s]["votes"] = 0
    else:
        nominated = [s for s, info in slots.items() if info.get("nominated") and info.get("alive", True)]

    if not nominated:
        await message.answer("Сначала нужно выставить живых игроков (кнопка «Выставить»).",
                             reply_markup=keyboards.game_admin_menu())
        return

    await state.update_data(nominated_list=nominated, vote_index=0, slots=slots)
    await state.set_state(GameCreateState.waiting_votes)
    await message.answer(f"Голоса.\nСколько голосов за слот {nominated[0]}?", reply_markup=keyboards.game_admin_menu())


@router.message(GameCreateState.waiting_votes)
async def collect_votes(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots = data.get("slots") or {}
    nominated = data.get("nominated_list") or []
    idx = data.get("vote_index", 0)
    in_split = data.get("in_split", False)

    if not nominated or idx >= len(nominated):
        await state.set_state(GameCreateState.editing_slots)
        await message.answer("Ошибка голосования. Начните заново кнопкой «Голоса».",
                             reply_markup=keyboards.game_admin_menu())
        return

    try:
        votes = int((message.text or "").strip())
    except ValueError:
        await message.answer("Нужно ввести число голосов. Пример: 3", reply_markup=keyboards.game_admin_menu())
        return

    slot = nominated[idx]
    if slot in slots:
        slots[slot]["votes"] = max(0, votes)

    idx += 1
    await state.update_data(slots=slots, vote_index=idx)

    if idx < len(nominated):
        await message.answer(f"Сколько голосов за слот {nominated[idx]}?", reply_markup=keyboards.game_admin_menu())
        return

    # Подведение итогов
    alive_nominated = [n for n in nominated if n in slots and slots[n].get("alive", True)]
    max_votes = max((slots[n]["votes"] for n in alive_nominated), default=0)
    leaders = [n for n in alive_nominated if slots[n]["votes"] == max_votes] if max_votes > 0 else []

    if len(leaders) == 1:
        # Один лидер — заголосован
        leader = leaders[0]
        slots[leader].update({"alive": False, "status_reason": "Заголосован"})
        _clear_nominations(slots, alive_nominated)
        await state.update_data(slots=slots, nominated_list=[], vote_index=0, in_split=False, split_candidates=[])

        await message.answer(
            build_votes_summary(slots) + "\n\n" + build_game_state(slots, alive_only=False),
            reply_markup=keyboards.game_admin_menu()
        )
        await state.set_state(GameCreateState.editing_slots)

    elif len(leaders) > 1:
        leaders_text = ", ".join(map(str, sorted(leaders)))

        if not in_split:
            # Первый попил
            _clear_nominations(slots)
            for s in leaders:
                slots[s]["nominated"] = True
            await state.update_data(slots=slots, nominated_list=leaders, vote_index=0, in_split=True,
                                    split_candidates=leaders)
            await message.answer(
                f"ПОПИЛ МЕЖДУ: {leaders_text}\nОправдательные речи, затем переголосование.\n\n{build_game_state(slots, alive_only=False)}",
                reply_markup=keyboards.game_admin_menu()
            )
        else:
            # Второй попил
            await state.update_data(slots=slots, split_candidates=leaders, nominated_list=leaders, vote_index=0,
                                    in_split=False)
            await message.answer(
                f"Повторный попил: голоса снова поровну.\nИгроки: {leaders_text}\nЧто делаем?",
                reply_markup=keyboards.split_decision_keyboard()
            )
        await state.set_state(GameCreateState.editing_slots)

    else:
        # Никто не заголосован
        _clear_nominations(slots, alive_nominated)
        await state.update_data(slots=slots, nominated_list=[], vote_index=0, in_split=False, split_candidates=[])
        await message.answer(
            f"Никто не заголосован.\n\n{build_game_state(slots, alive_only=False)}",
            reply_markup=keyboards.game_admin_menu()
        )
        await state.set_state(GameCreateState.editing_slots)


# ========== 4. РЕШЕНИЕ ПО ВТОРОМУ ПОПИЛУ ==========
async def _handle_split_decision(callback: types.CallbackQuery, state: FSMContext, kill: bool):
    data = await state.get_data()
    slots = data.get("slots") or {}
    candidates = data.get("split_candidates") or []

    alive = [n for n in candidates if n in slots and slots[n].get("alive", True)]

    if kill:
        for n in alive:
            slots[n].update({"alive": False, "status_reason": "Заголосован"})

    _clear_nominations(slots, candidates)
    await state.update_data(slots=slots, nominated_list=[], vote_index=0, in_split=False, split_candidates=[])

    action = "заголосованы" if kill else "не заголосованы"
    await callback.message.edit_text(
        f"Решение: {'Поднять всех' if kill else 'Оставить всех'}.\nВсе игроки из попила {action}.")
    await callback.message.answer(build_game_state(slots, alive_only=False), reply_markup=keyboards.game_admin_menu())
    await callback.answer()


@router.callback_query(F.data == "split:kill_all")
async def split_kill_all(callback: types.CallbackQuery, state: FSMContext):
    await _handle_split_decision(callback, state, kill=True)


@router.callback_query(F.data == "split:keep_all")
async def split_keep_all(callback: types.CallbackQuery, state: FSMContext):
    await _handle_split_decision(callback, state, kill=False)


# ========== 5. ДОПЫ, ПР, МН ==========
async def _apply_score(message: types.Message, state: FSMContext, cmd: str, field: str, is_cumulative: bool = True):
    """Общая функция для доп/пр/мн."""
    parts = (message.text or "").strip().split()
    if len(parts) < 3:
        await message.answer(f"Формат: `{cmd} <номер_слота> <значение>`.\nПример: `{cmd} 4 2` (0.2)",
                             reply_markup=keyboards.game_admin_menu())
        return

    try:
        slot_num = int(parts[1])
    except ValueError:
        await message.answer(f"Номер слота должен быть числом. Пример: `{cmd} 4 2`",
                             reply_markup=keyboards.game_admin_menu())
        return

    val = _parse_bonus_value(parts[2])
    if val is None:
        await message.answer(f"Не удалось разобрать значение. Примеры: `2`, `0.2`, `-0.3`",
                             reply_markup=keyboards.game_admin_menu())
        return

    data = await state.get_data()
    slots = data.get("slots") or {}

    if slot_num not in slots:
        await message.answer(f"Слот {slot_num} не найден.", reply_markup=keyboards.game_admin_menu())
        return

    current = slots[slot_num].get(field, 0.0) or 0.0
    slots[slot_num][field] = round(current + val, 1) if is_cumulative else val

    await state.update_data(slots=slots)
    sign = "+" if val >= 0 else ""
    await message.answer(f"{cmd.upper()}: слот {slot_num} ({sign}{val} очков). Протокол обновлён 👇",
                         reply_markup=keyboards.game_admin_menu())
    await _update_protocol(message, state, slots)


@router.message(GameCreateState.editing_slots, F.text.regexp(r"^доп\s+"))
async def apply_bonus_points(message: types.Message, state: FSMContext):
    await _apply_score(message, state, "доп", "bonus_points", is_cumulative=True)


@router.message(GameCreateState.editing_slots, F.text.regexp(r"^пр\s+"))
async def set_protocol_points(message: types.Message, state: FSMContext):
    await _apply_score(message, state, "пр", "will_protocol_points", is_cumulative=False)


@router.message(GameCreateState.editing_slots, F.text.regexp(r"^мн\s+"))
async def set_opinion_points(message: types.Message, state: FSMContext):
    await _apply_score(message, state, "мн", "will_opinion_points", is_cumulative=False)