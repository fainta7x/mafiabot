from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext

import keyboards
from .state import GameCreateState
from .text import _parse_slots_list, build_game_state, build_roles_summary

router = Router()

# =========================================================
# NIGHTS & ROLES ROUTER — НОЧНОЙ ВЫСТРЕЛ, ЗАВЕЩАНИЯ И РАЗДАЧА РОЛЕЙ
#
# ОГЛАВЛЕНИЕ:
# 1. НОЧНОЙ ВЫСТРЕЛ ("убить") + ПОДОЗРЕВАЕМЫЕ ПЕРВОГО УБИТЫХ + ЗАВЕЩАНИЯ
# 2. МАСТЕР РАЗДАЧИ РОЛЕЙ ("ок", выбор мафий, дона, шерифа)
# =========================================================


# =========================================================
# 1. НОЧНОЙ ВЫСТРЕЛ: "УБИТЬ" + ПОДОЗРЕВАЕМЫЕ + ЗАВЕЩАНИЯ
# =========================================================

@router.message(
    GameCreateState.editing_slots,
    F.text.func(lambda t: (t or "").strip().lower().startswith("убить")),
)
async def ask_night_kill_slot(message: types.Message, state: FSMContext):
    await state.set_state(GameCreateState.waiting_kill_slot)
    await message.answer(
        "Кого убили ночью?\n"
        "Введи номер слота (например: `5`).",
        reply_markup=keyboards.game_admin_menu(),
    )


async def _start_will_for_slot(message: types.Message, state: FSMContext, slot_num: int):
    """
    Старт записи завещания для ночного убитого:
    сначала ПРОТОКОЛ (текст), затем МНЕНИЕ (текст).
    Баллы ПР/МН выставляются позже вручную командами 'пр' и 'мн'.
    """
    await state.update_data(will_slot=slot_num)
    await state.set_state(GameCreateState.waiting_will_protocol)
    await message.answer(
        f"Слот {slot_num} может оставить завещание.\n\n"
        "Сначала ПРОТОКОЛ (только цвета/версии).\n"
        "Примеры:\n"
        "  3 6 7 красные, 1 4 чёрные\n"
        "  1 красный 4 чёрный\n"
        "  3 красный, 5 чёрный, 2 дон, 4 шериф\n\n"
        "Отправь текст протокола или напиши `нет`, если без протокола.",
        reply_markup=keyboards.game_admin_menu(),
    )


@router.message(GameCreateState.waiting_kill_slot)
async def handle_night_kill_slot(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}
    first_night_kill_recorded: bool = data.get("first_night_kill_recorded", False)
    night_kills_order: list[int] = data.get("night_kills_order") or []

    text = (message.text or "").strip()
    try:
        slot_num = int(text)
    except ValueError:
        await message.answer(
            "Нужно ввести номер слота (одно число). Пример: `5`.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    if slot_num not in slots:
        await message.answer(
            f"Слота №{slot_num} нет в текущем списке.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    slot = slots[slot_num]
    if not slot.get("alive", True):
        await message.answer(
            f"Слот {slot_num} уже не в игре.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    # Помечаем как убитого ночью
    slot["alive"] = False
    slot["status_reason"] = "Убит ночью"

    # Если это первое ночное убийство — отмечаем ПУ
    if not first_night_kill_recorded:
        # На всякий случай сбросим ПУ у всех
        for info in slots.values():
            info["pu_mark"] = False
        slot["pu_mark"] = True

    # Добавляем в порядок ночных убийств
    if slot_num not in night_kills_order:
        night_kills_order.append(slot_num)

    await state.update_data(slots=slots, night_kills_order=night_kills_order)

    game_state = build_game_state(slots, alive_only=False)
    await message.answer(
        f"Слот {slot_num} убит ночью.\n\n{game_state}",
        reply_markup=keyboards.game_admin_menu(),
    )

    if not first_night_kill_recorded:
        # Запоминаем, кто первый убит ночью, и даём назвать подозреваемых (ЛХ)
        await state.update_data(
            first_night_kill_recorded=True,
            night_killed_slot=slot_num,
        )
        await state.set_state(GameCreateState.waiting_night_suspects)
        await message.answer(
            "У первого убитого ночью есть право назвать ДО 3 подозрительных игроков (ЛХ).\n\n"
            "Введи номера слотов через пробел (например: `2 5 7`).\n"
            "Если он никого не называет — просто отправь `0`.",
            reply_markup=keyboards.game_admin_menu(),
        )
    else:
        # Не ПУ — сразу переходим к завещанию (протокол + мнение)
        await _start_will_for_slot(message, state, slot_num)


@router.message(GameCreateState.waiting_night_suspects)
async def handle_night_suspects(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}
    killed_slot: int | None = data.get("night_killed_slot")

    if killed_slot is None or killed_slot not in slots:
        await state.set_state(GameCreateState.editing_slots)
        await message.answer(
            "Что-то пошло не так с записью подозрительных игроков.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    text = (message.text or "").strip()

    if text == "0":
        suspects: list[int] = []
    else:
        nums = _parse_slots_list(text)
        suspects = [
            n for n in nums
            if n in slots and n != killed_slot
        ][:3]

    # Сохраняем до трёх подозреваемых у первого убитого ночью
    slots[killed_slot]["night_suspects"] = suspects

    await state.update_data(
        slots=slots,
        night_killed_slot=None,
    )
    await state.set_state(GameCreateState.editing_slots)

    if suspects:
        suspects_text = ", ".join(str(n) for n in suspects)
        msg = (
            f"Слот {killed_slot} перед смертью назвал подозрительных игроков: {suspects_text}.\n"
            "Информация сохранена."
        )
    else:
        msg = (
            f"Слот {killed_slot} никого не назвал.\n"
            "Информация сохранена."
        )

    game_state = build_game_state(slots, alive_only=False)

    await message.answer(
        msg + "\n\n" + game_state,
        reply_markup=keyboards.game_admin_menu(),
    )

    # После ЛХ ПУ может оставить завещание (протокол + мнение)
    await _start_will_for_slot(message, state, killed_slot)


# === ЗАВЕЩАНИЯ: ПРОТОКОЛ И МНЕНИЕ (ТЕКСТЫ) ===

@router.message(GameCreateState.waiting_will_protocol)
async def handle_will_protocol(message: types.Message, state: FSMContext):
    """
    Принимаем текст ПРОТОКОЛА завещания для ночного убитого.
    Только текст; баллы ПР ставятся позже через команду 'пр'.
    """
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}
    will_slot: int | None = data.get("will_slot")

    if will_slot is None or will_slot not in slots:
        await state.set_state(GameCreateState.editing_slots)
        await message.answer(
            "Что-то пошло не так с записью завещания (протокола).",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    text = (message.text or "").strip()

    if text.lower() in {"нет", "no", "0"}:
        slots[will_slot]["will_protocol_raw"] = ""
    else:
        slots[will_slot]["will_protocol_raw"] = text

    await state.update_data(slots=slots)
    await state.set_state(GameCreateState.waiting_will_opinion)

    await message.answer(
        f"Теперь МНЕНИЕ слота {will_slot}.\n"
        "Пример: `В 12 нет двух мирных`, `6 мафия по речи`.\n\n"
        "Отправь текст мнения или напиши `нет`, если без мнения.",
        reply_markup=keyboards.game_admin_menu(),
    )


@router.message(GameCreateState.waiting_will_opinion)
async def handle_will_opinion(message: types.Message, state: FSMContext):
    """
    Принимаем текст МНЕНИЯ завещания для ночного убитого.
    Только текст; баллы МН ставятся позже через команду 'мн'.
    """
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}
    will_slot: int | None = data.get("will_slot")

    if will_slot is None or will_slot not in slots:
        await state.set_state(GameCreateState.editing_slots)
        await message.answer(
            "Что-то пошло не так с записью завещания (мнения).",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    text = (message.text or "").strip()

    if text.lower() in {"нет", "no", "0"}:
        slots[will_slot]["will_opinion"] = ""
    else:
        slots[will_slot]["will_opinion"] = text

    await state.update_data(slots=slots, will_slot=None)
    await state.set_state(GameCreateState.editing_slots)

    game_state = build_game_state(slots, alive_only=False)
    await message.answer(
        f"Завещание слота {will_slot} сохранено.\n\n" + game_state,
        reply_markup=keyboards.game_admin_menu(),
    )


# =========================================================
# 2. МАСТЕР РАЗДАЧИ РОЛЕЙ
# =========================================================

@router.message(
    GameCreateState.editing_slots,
    F.text.func(lambda t: (t or "").strip().lower().startswith("ок")),
)
async def handle_ok(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    print(f"[HANDLE_OK] state={current_state}, text={repr(message.text)}")

    data = await state.get_data()
    roles_assigned = data.get("roles_assigned", False)
    slots: dict[int, dict] = data.get("slots") or {}

    if not slots:
        await message.answer(
            "Слоты пустые, делать нечего.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    if not roles_assigned:
        if len(slots) < 4:
            await message.answer(
                "Для классической раздачи (2 мафии, дон, шериф) нужно минимум 4 игрока.",
                reply_markup=keyboards.game_admin_menu(),
            )
            return

        await state.set_state(GameCreateState.choosing_mafia)
        await message.answer(
            "Шаг 1.\n"
            "Введи НОМЕРА двух мафий (через пробел или запятую).\n"
            "Например: `2 7`.",
            reply_markup=keyboards.game_admin_menu(),
        )
    else:
        text = build_game_state(slots, alive_only=False)
        await message.answer(text, reply_markup=keyboards.game_admin_menu())


@router.message(GameCreateState.choosing_mafia)
async def choose_mafia(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}

    numbers = _parse_slots_list(message.text or "")
    if len(numbers) != 2:
        await message.answer(
            "Нужно указать РОВНО два разных номера слотов для мафии.\n"
            "Пример: `2 7`.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    for n in numbers:
        if n not in slots or n < 1 or n > 10:
            await message.answer(
                f"Слот №{n} не найден. Используй существующие слоты от 1 до 10.",
                reply_markup=keyboards.game_admin_menu(),
            )
            return

    mafia1, mafia2 = numbers
    if mafia1 == mafia2:
        await message.answer(
            "Нужно указать ДВА РАЗНЫХ слота для мафии.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    data["mafia_slots"] = numbers
    await state.update_data(data)

    await state.set_state(GameCreateState.choosing_don)
    await message.answer(
        f"Мафия: слоты {mafia1} и {mafia2}.\n\n"
        "Шаг 2.\n"
        "Введи номер ДОНа (отличный от мафии).",
        reply_markup=keyboards.game_admin_menu(),
    )


@router.message(GameCreateState.choosing_don)
async def choose_don(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}

    mafia_slots: list[int] = data.get("mafia_slots", [])

    numbers = _parse_slots_list(message.text or "")
    if len(numbers) != 1:
        await message.answer(
            "Нужно указать ОДИН номер слота для дона.\n"
            "Пример: `5`.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    don_slot = numbers[0]

    if don_slot not in slots or don_slot < 1 or don_slot > 10:
        await message.answer(
            f"Слот №{don_slot} не найден. Используй существующие слоты от 1 до 10.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    if don_slot in mafia_slots:
        await message.answer(
            "Дон не может совпадать с мафией. Укажи другой слот.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    data["don_slot"] = don_slot
    await state.update_data(data)

    await state.set_state(GameCreateState.choosing_sheriff)
    await message.answer(
        f"Дон: слот {don_slot}.\n\n"
        "Шаг 3.\n"
        "Введи номер ШЕРИФА (не мафия и не дон).",
        reply_markup=keyboards.game_admin_menu(),
    )


@router.message(GameCreateState.choosing_sheriff)
async def choose_sheriff(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}
    mafia_slots: list[int] = data.get("mafia_slots", [])
    don_slot: int | None = data.get("don_slot")

    numbers = _parse_slots_list(message.text or "")
    if len(numbers) != 1:
        await message.answer(
            "Нужно указать ОДИН номер слота для шерифа.\n"
            "Пример: `4`.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    sheriff_slot = numbers[0]

    if sheriff_slot not in slots or sheriff_slot < 1 or sheriff_slot > 10:
        await message.answer(
            f"Слот №{sheriff_slot} не найден. Используй существующие слоты от 1 до 10.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    if sheriff_slot in mafia_slots or sheriff_slot == don_slot:
        await message.answer(
            "Шериф должен быть отдельным игроком (не мафия и не дон). Укажи другой слот.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    # Сначала всем ставим мирных
    for slot_num, info in slots.items():
        info["role"] = "Мирный"
        info["team"] = "Красные"

    # Мафия
    for m in mafia_slots:
        slots[m]["role"] = "Мафия"
        slots[m]["team"] = "Чёрные"

    # Дон
    if don_slot is not None:
        slots[don_slot]["role"] = "Дон"
        slots[don_slot]["team"] = "Чёрные"

    # Шериф
    slots[sheriff_slot]["role"] = "Шериф"
    slots[sheriff_slot]["team"] = "Красные"

    await state.update_data(slots=slots, roles_assigned=True)

    summary = build_roles_summary(slots)

    await message.answer(
        summary,
        reply_markup=keyboards.game_admin_menu(),
    )
    await state.set_state(GameCreateState.editing_slots)