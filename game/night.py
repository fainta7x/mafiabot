from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext

import keyboards
from .state import GameCreateState
from .text import _parse_slots_list, build_game_state, build_roles_summary

router = Router()


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
async def _get_slot_or_error(message: types.Message, state: FSMContext, slot_num: int, action: str) -> tuple[
    dict | None, dict | None]:
    """Проверяет существование и живость слота. Возвращает (slots, slot) или (None, None) при ошибке."""
    data = await state.get_data()
    slots = data.get("slots") or {}

    if slot_num not in slots:
        await message.answer(f"Слота №{slot_num} нет в текущем списке.", reply_markup=keyboards.game_admin_menu())
        return None, None

    slot = slots[slot_num]
    if not slot.get("alive", True) and action == "kill":
        await message.answer(f"Слот {slot_num} уже не в игре.", reply_markup=keyboards.game_admin_menu())
        return None, None

    return slots, slot


async def _save_will_text(message: types.Message, state: FSMContext, field: str, next_state, prompt: str):
    """Общая функция для сохранения текста завещания (протокол или мнение)."""
    data = await state.get_data()
    slots = data.get("slots") or {}
    will_slot = data.get("will_slot")

    if will_slot is None or will_slot not in slots:
        await state.set_state(GameCreateState.editing_slots)
        await message.answer("Что-то пошло не так с записью завещания.", reply_markup=keyboards.game_admin_menu())
        return

    text = (message.text or "").strip()
    slots[will_slot][field] = "" if text.lower() in {"нет", "no", "0"} else text

    await state.update_data(slots=slots)
    await state.set_state(next_state)
    await message.answer(prompt.format(will_slot), reply_markup=keyboards.game_admin_menu())


async def _assign_roles(slots: dict, mafia_slots: list, don_slot: int, sheriff_slot: int) -> dict:
    """Назначает роли всем слотам."""
    for info in slots.values():
        info["role"] = "Мирный"
        info["team"] = "Красные"

    for m in mafia_slots:
        slots[m].update({"role": "Мафия", "team": "Чёрные"})

    if don_slot:
        slots[don_slot].update({"role": "Дон", "team": "Чёрные"})

    slots[sheriff_slot].update({"role": "Шериф", "team": "Красные"})
    return slots


# ========== 1. НОЧНОЙ ВЫСТРЕЛ ==========
@router.message(GameCreateState.editing_slots, F.text.func(lambda t: (t or "").strip().lower().startswith("убить")))
async def ask_night_kill_slot(message: types.Message, state: FSMContext):
    await state.set_state(GameCreateState.waiting_kill_slot)
    await message.answer("Кого убили ночью?\nВведи номер слота (например: `5`).",
                         reply_markup=keyboards.game_admin_menu())


@router.message(GameCreateState.waiting_kill_slot)
async def handle_night_kill_slot(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots = data.get("slots") or {}
    night_kills = data.get("night_kills_order") or []

    try:
        slot_num = int((message.text or "").strip())
    except ValueError:
        await message.answer("Нужно ввести номер слота (одно число). Пример: `5`.",
                             reply_markup=keyboards.game_admin_menu())
        return

    slots, slot = await _get_slot_or_error(message, state, slot_num, "kill")
    if slots is None:
        return

    # Помечаем убитым
    slot["alive"] = False
    slot["status_reason"] = "Убит ночью"

    # Первый убитый — ПУ
    first_night = data.get("first_night_kill_recorded", False)
    if not first_night:
        for info in slots.values():
            info["pu_mark"] = False
        slot["pu_mark"] = True

    if slot_num not in night_kills:
        night_kills.append(slot_num)

    await state.update_data(slots=slots, night_kills_order=night_kills, first_night_kill_recorded=True)

    game_state = build_game_state(slots, alive_only=False)
    await message.answer(f"Слот {slot_num} убит ночью.\n\n{game_state}", reply_markup=keyboards.game_admin_menu())

    if not first_night:
        await state.update_data(night_killed_slot=slot_num)
        await state.set_state(GameCreateState.waiting_night_suspects)
        await message.answer(
            "У первого убитого ночью есть право назвать ДО 3 подозрительных игроков (ЛХ).\n\n"
            "Введи номера слотов через пробел (например: `2 5 7`).\nЕсли никого — отправь `0`.",
            reply_markup=keyboards.game_admin_menu()
        )
    else:
        # Для непервого убитого — сразу завещание
        await state.update_data(will_slot=slot_num)
        await state.set_state(GameCreateState.waiting_will_protocol)
        await message.answer(
            f"Слот {slot_num} может оставить завещание.\n\n"
            "Сначала ПРОТОКОЛ (только цвета/версии).\n"
            "Примеры:\n  3 6 7 красные, 1 4 чёрные\n"
            "Отправь текст протокола или напиши `нет`.",
            reply_markup=keyboards.game_admin_menu()
        )


@router.message(GameCreateState.waiting_night_suspects)
async def handle_night_suspects(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots = data.get("slots") or {}
    killed = data.get("night_killed_slot")

    if killed is None or killed not in slots:
        await state.set_state(GameCreateState.editing_slots)
        await message.answer("Ошибка записи подозреваемых.", reply_markup=keyboards.game_admin_menu())
        return

    text = (message.text or "").strip()
    suspects = [] if text == "0" else [n for n in _parse_slots_list(text) if n in slots and n != killed][:3]

    slots[killed]["night_suspects"] = suspects
    await state.update_data(slots=slots, night_killed_slot=None)
    await state.set_state(GameCreateState.editing_slots)

    msg = f"Слот {killed} перед смертью назвал {', '.join(map(str, suspects))}." if suspects else f"Слот {killed} никого не назвал."
    game_state = build_game_state(slots, alive_only=False)
    await message.answer(msg + "\n\n" + game_state, reply_markup=keyboards.game_admin_menu())

    # Завещание для ПУ
    await state.update_data(will_slot=killed)
    await state.set_state(GameCreateState.waiting_will_protocol)
    await message.answer(
        f"Слот {killed} может оставить завещание.\n\n"
        "Сначала ПРОТОКОЛ. Отправь текст или напиши `нет`.",
        reply_markup=keyboards.game_admin_menu()
    )


# ========== ЗАВЕЩАНИЯ ==========
@router.message(GameCreateState.waiting_will_protocol)
async def handle_will_protocol(message: types.Message, state: FSMContext):
    await _save_will_text(
        message, state, "will_protocol_raw", GameCreateState.waiting_will_opinion,
        f"Теперь МНЕНИЕ слота {{}}.\nОтправь текст мнения или напиши `нет`."
    )


@router.message(GameCreateState.waiting_will_opinion)
async def handle_will_opinion(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots = data.get("slots") or {}
    will_slot = data.get("will_slot")

    if will_slot is None or will_slot not in slots:
        await state.set_state(GameCreateState.editing_slots)
        await message.answer("Ошибка записи мнения.", reply_markup=keyboards.game_admin_menu())
        return

    text = (message.text or "").strip()
    slots[will_slot]["will_opinion"] = "" if text.lower() in {"нет", "no", "0"} else text

    await state.update_data(slots=slots, will_slot=None)
    await state.set_state(GameCreateState.editing_slots)

    game_state = build_game_state(slots, alive_only=False)
    await message.answer(f"Завещание слота {will_slot} сохранено.\n\n{game_state}",
                         reply_markup=keyboards.game_admin_menu())


# ========== 2. РАЗДАЧА РОЛЕЙ ==========
@router.message(GameCreateState.editing_slots, F.text.func(lambda t: (t or "").strip().lower().startswith("ок")))
async def handle_ok(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots = data.get("slots") or {}

    if not slots:
        await message.answer("Слоты пустые, делать нечего.", reply_markup=keyboards.game_admin_menu())
        return

    if not data.get("roles_assigned", False):
        if len(slots) < 4:
            await message.answer("Для классической раздачи нужно минимум 4 игрока.",
                                 reply_markup=keyboards.game_admin_menu())
            return

        await state.set_state(GameCreateState.choosing_mafia)
        await message.answer(
            "Шаг 1. Введи НОМЕРА двух мафий (через пробел или запятую).\nПример: `2 7`.",
            reply_markup=keyboards.game_admin_menu()
        )
    else:
        await message.answer(build_game_state(slots, alive_only=False), reply_markup=keyboards.game_admin_menu())


@router.message(GameCreateState.choosing_mafia)
async def choose_mafia(message: types.Message, state: FSMContext):
    slots = (await state.get_data()).get("slots") or {}
    numbers = _parse_slots_list(message.text or "")

    if len(numbers) != 2 or numbers[0] == numbers[1]:
        await message.answer("Нужно указать РОВНО два разных номера слотов.\nПример: `2 7`.",
                             reply_markup=keyboards.game_admin_menu())
        return

    for n in numbers:
        if n not in slots:
            await message.answer(f"Слот №{n} не найден.", reply_markup=keyboards.game_admin_menu())
            return

    await state.update_data(mafia_slots=numbers)
    await state.set_state(GameCreateState.choosing_don)
    await message.answer(f"Мафия: слоты {numbers[0]} и {numbers[1]}.\n\nШаг 2. Введи номер ДОНА (отличный от мафии).",
                         reply_markup=keyboards.game_admin_menu())


@router.message(GameCreateState.choosing_don)
async def choose_don(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots = data.get("slots") or {}
    mafia = data.get("mafia_slots", [])
    numbers = _parse_slots_list(message.text or "")

    if len(numbers) != 1:
        await message.answer("Нужно указать ОДИН номер слота для дона.\nПример: `5`.",
                             reply_markup=keyboards.game_admin_menu())
        return

    don = numbers[0]
    if don not in slots or don in mafia:
        await message.answer(f"Слот {don} не найден или совпадает с мафией. Укажи другой.",
                             reply_markup=keyboards.game_admin_menu())
        return

    await state.update_data(don_slot=don)
    await state.set_state(GameCreateState.choosing_sheriff)
    await message.answer(f"Дон: слот {don}.\n\nШаг 3. Введи номер ШЕРИФА (не мафия и не дон).",
                         reply_markup=keyboards.game_admin_menu())


@router.message(GameCreateState.choosing_sheriff)
async def choose_sheriff(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots = data.get("slots") or {}
    mafia = data.get("mafia_slots", [])
    don = data.get("don_slot")
    numbers = _parse_slots_list(message.text or "")

    if len(numbers) != 1:
        await message.answer("Нужно указать ОДИН номер слота для шерифа.\nПример: `4`.",
                             reply_markup=keyboards.game_admin_menu())
        return

    sheriff = numbers[0]
    if sheriff not in slots or sheriff in mafia or sheriff == don:
        await message.answer("Шериф должен быть отдельным игроком (не мафия и не дон).",
                             reply_markup=keyboards.game_admin_menu())
        return

    slots = await _assign_roles(slots, mafia, don, sheriff)
    await state.update_data(slots=slots, roles_assigned=True)
    await state.set_state(GameCreateState.editing_slots)
    await message.answer(build_roles_summary(slots), reply_markup=keyboards.game_admin_menu())