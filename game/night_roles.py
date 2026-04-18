from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext

import keyboards
from .state import GameCreateState
from .utils import _parse_slots_list, build_game_state, build_roles_summary

router = Router()


# ===== НОЧНОЙ ВЫСТРЕЛ: "УБИТЬ" =====

@router.message(GameCreateState.editing_slots, F.text.casefold() == "убить")
async def ask_night_kill_slot(message: types.Message, state: FSMContext):
    await state.set_state(GameCreateState.waiting_kill_slot)
    await message.answer(
        "Кого убили ночью?\n"
        "Введи номер слота (например: `5`).",
        reply_markup=keyboards.game_admin_menu(),
    )


@router.message(GameCreateState.waiting_kill_slot)
async def handle_night_kill_slot(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}
    first_night_kill_recorded: bool = data.get("first_night_kill_recorded", False)

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

    # помечаем как убитого ночью
    slot["alive"] = False
    slot["status_reason"] = "Убит ночью"

    # если это первое ночное убийство — отмечаем ПУ
    if not first_night_kill_recorded:
        # на всякий случай сбросим ПУ у всех
        for info in slots.values():
            info["pu_mark"] = False
        slot["pu_mark"] = True

    await state.update_data(slots=slots)

    game_state = build_game_state(slots, alive_only=False)
    await message.answer(
        f"Слот {slot_num} убит ночью.\n\n{game_state}",
        reply_markup=keyboards.game_admin_menu(),
    )

    if not first_night_kill_recorded:
        # запоминаем, кто первый убит ночью, и даём назвать подозреваемых
        await state.update_data(
            first_night_kill_recorded=True,
            night_killed_slot=slot_num,
        )
        await state.set_state(GameCreateState.waiting_night_suspects)
        await message.answer(
            "У первого убитого ночью есть право назвать ДО 3 подозрительных игроков.\n\n"
            "Введи номера слотов через пробел (например: `2 5 7`).\n"
            "Если он никого не называет — просто отправь `0`.",
            reply_markup=keyboards.game_admin_menu(),
        )
    else:
        await state.set_state(GameCreateState.editing_slots)


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

    # сохраняем трёх (или меньше) подозреваемых у первого убитого ночью
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


# ===== МАСТЕР РАЗДАЧИ РОЛЕЙ =====

@router.message(GameCreateState.editing_slots, F.text.casefold() == "ок")
async def handle_ok(message: types.Message, state: FSMContext):
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

    numbers = _parse_slots_list(message.text)
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

    numbers = _parse_slots_list(message.text)
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

    numbers = _parse_slots_list(message.text)
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

    # сначала всем ставим мирных
    for slot_num, info in slots.items():
        info["role"] = "Мирный"
        info["team"] = "Красные"

    # мафия
    for m in mafia_slots:
        slots[m]["role"] = "Мафия"
        slots[m]["team"] = "Чёрные"

    # дон
    if don_slot is not None:
        slots[don_slot]["role"] = "Дон"
        slots[don_slot]["team"] = "Чёрные"

    # шериф
    slots[sheriff_slot]["role"] = "Шериф"
    slots[sheriff_slot]["team"] = "Красные"

    await state.update_data(slots=slots, roles_assigned=True)

    summary = build_roles_summary(slots)

    await message.answer(
        summary,
        reply_markup=keyboards.game_admin_menu(),
    )
    await state.set_state(GameCreateState.editing_slots)