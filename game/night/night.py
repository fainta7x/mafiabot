from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext

import keyboards
from game.state import GameCreateState
from game.text import _parse_slots_list, build_game_state
from game.admin_actions.common import get_slots, save_slots, ensure_judge_pm

router = Router()


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

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


# ========== УБИЙСТВО (ИНТЕРАКТИВНОЕ) ==========

@router.message(GameCreateState.editing_slots, F.text == "Убить")
async def kill_start(message: types.Message, state: FSMContext):
    """Начало убийства — выбор игрока."""
    if not await ensure_judge_pm(message):
        return

    slots = await get_slots(message, state)
    if not slots:
        return

    alive_slots = {k: v for k, v in slots.items() if v.get("alive", True)}

    if not alive_slots:
        await message.answer("❌ Нет живых игроков для убийства.", reply_markup=keyboards.game_admin_menu())
        return

    await state.set_state(GameCreateState.kill_select)
    await message.answer(
        "💀 **Убийство игрока**\n\n"
        "Выберите игрока, который будет убит:",
        reply_markup=keyboards.kill_select_kb(alive_slots)
    )


@router.callback_query(GameCreateState.kill_select, F.data.startswith("kill_select_"))
async def kill_select_player(callback: types.CallbackQuery, state: FSMContext):
    """Выбор игрока для убийства."""
    try:
        slot_num = int(callback.data.split("_")[2])
    except (IndexError, ValueError):
        await callback.answer("Некорректный номер игрока!", show_alert=True)
        return

    data = await state.get_data()
    slots = data.get("slots") or {}
    first_night = data.get("first_night_kill_recorded", False)

    # Проверяем существование слота
    if slot_num not in slots:
        await callback.answer("Игрок не найден!", show_alert=True)
        return

    # Проверяем, жив ли игрок
    if not slots[slot_num].get("alive", True):
        await callback.answer("Этот игрок уже мёртв!", show_alert=True)
        return

    name = slots[slot_num].get("nickname") or slots[slot_num].get("full_name") or f"Слот {slot_num}"

    # Сохраняем выбранный слот
    await state.update_data(kill_slot=slot_num)

    # Если это первое убийство — запрашиваем ЛХ
    if not first_night:
        await state.set_state(GameCreateState.kill_lh)
        await callback.message.edit_text(
            f"💀 **Убийство игрока {slot_num} ({name})**\n\n"
            f"👑 Это ПЕРВОЕ убийство! Игрок становится ПУ (первоубиенным).\n\n"
            f"📝 **Введите номера подозреваемых (ЛХ) через пробел**\n\n"
            f"Пример: `2 5 7`\n"
            f"Или `0` для очистки\n\n"
            f"Этот игрок может назвать ДО 3 подозрительных игроков.",
            reply_markup=keyboards.kill_lh_kb()
        )
    else:
        # Не первое убийство — сразу переходим к протоколу
        await state.set_state(GameCreateState.kill_protocol)
        await callback.message.edit_text(
            f"💀 **Убийство игрока {slot_num} ({name})**\n\n"
            f"📋 **Введите текст протокола (ПР)**\n\n"
            f"Пример: `3 6 7 красные, 1 4 чёрные`\n"
            f"Или `нет` для очистки",
            reply_markup=keyboards.kill_protocol_kb()
        )

    await callback.answer()


@router.callback_query(GameCreateState.kill_lh, F.data == "kill_show_numeric_kb")
async def kill_show_numeric(callback: types.CallbackQuery, state: FSMContext):
    """Показывает цифровую клавиатуру для ЛХ."""
    data = await state.get_data()
    selected = data.get("kill_temp_selected_numbers", [])

    await callback.message.edit_text(
        "🔢 **Выберите номера подозреваемых (ЛХ)**\n\n"
        "Нажимайте на номера, чтобы выбрать/отменить.\n"
        "Можно выбрать до 3 подозреваемых.\n"
        "После выбора нажмите «Готово».",
        reply_markup=keyboards.numeric_selection_kb(selected)
    )
    await callback.answer()


@router.callback_query(GameCreateState.kill_lh, F.data == "kill_back_to_select")
async def kill_back_to_select(callback: types.CallbackQuery, state: FSMContext):
    """Возврат к выбору игрока."""
    data = await state.get_data()
    slots = data.get("slots") or {}
    alive_slots = {k: v for k, v in slots.items() if v.get("alive", True)}

    await state.set_state(GameCreateState.kill_select)
    await callback.message.edit_text(
        "💀 **Убийство игрока**\n\nВыберите игрока, который будет убит:",
        reply_markup=keyboards.kill_select_kb(alive_slots)
    )
    await callback.answer()


@router.message(GameCreateState.kill_lh)
async def kill_set_lh(message: types.Message, state: FSMContext):
    """Установка ЛХ для первого убитого (ПУ)."""
    if not await ensure_judge_pm(message):
        return

    text = message.text.strip()

    data = await state.get_data()
    slots = data.get("slots") or {}
    slot_num = data.get("kill_slot")

    if slot_num is None or slot_num not in slots:
        await message.answer("Ошибка: не выбран игрок для убийства. Начните заново.",
                             reply_markup=keyboards.game_admin_menu())
        await state.set_state(GameCreateState.editing_slots)
        return

    if text == "0":
        suspects = []
    else:
        suspects = [int(x) for x in text.split() if x.isdigit() and 1 <= int(x) <= 10]
        if len(suspects) > 3:
            await message.answer("❌ Можно указать не более 3 подозреваемых!", reply_markup=keyboards.kill_lh_kb())
            return

    # Сохраняем ЛХ
    slots[slot_num]["night_suspects"] = list(dict.fromkeys(suspects))
    await state.update_data(slots=slots)
    await save_slots(state, slots)

    await state.set_state(GameCreateState.kill_protocol)

    suspects_str = ", ".join(map(str, suspects)) if suspects else "очищен"
    await message.answer(
        f"✅ ЛХ установлены: [{suspects_str}]\n\n"
        f"📋 **Введите текст протокола (ПР)**\n\n"
        f"Пример: `3 6 7 красные, 1 4 чёрные`\n"
        f"Или нажмите кнопку ниже, чтобы пропустить",
        reply_markup=keyboards.kill_protocol_kb()
    )


@router.callback_query(GameCreateState.kill_protocol, F.data == "kill_back_to_lh")
async def kill_back_to_lh(callback: types.CallbackQuery, state: FSMContext):
    """Возврат к вводу ЛХ (только для первого убитого)."""
    data = await state.get_data()
    slot_num = data.get("kill_slot")
    slots = data.get("slots") or {}
    first_night = data.get("first_night_kill_recorded", False)

    if slot_num is None or slot_num not in slots:
        await callback.answer("Ошибка: слот не найден!", show_alert=True)
        return

    if first_night:
        await callback.answer("Это уже не первое убийство, ЛХ не нужны!", show_alert=True)
        return

    name = slots[slot_num].get("nickname") or slots[slot_num].get("full_name") or f"Слот {slot_num}"

    await state.set_state(GameCreateState.kill_lh)
    await callback.message.edit_text(
        f"💀 **Убийство игрока {slot_num} ({name})**\n\n"
        f"👑 Это ПЕРВОЕ убийство! Игрок становится ПУ (первоубиенным).\n\n"
        f"📝 **Введите номера подозреваемых (ЛХ) через пробел**\n\n"
        f"Пример: `2 5 7`\n"
        f"Или `0` для очистки",
        reply_markup=keyboards.kill_lh_kb()
    )
    await callback.answer()


@router.callback_query(GameCreateState.kill_protocol, F.data == "kill_back_to_select")
async def kill_protocol_back_to_select(callback: types.CallbackQuery, state: FSMContext):
    """Возврат к выбору игрока из протокола."""
    data = await state.get_data()
    slots = data.get("slots") or {}
    alive_slots = {k: v for k, v in slots.items() if v.get("alive", True)}

    await state.set_state(GameCreateState.kill_select)
    await callback.message.edit_text(
        "💀 **Убийство игрока**\n\nВыберите игрока, который будет убит:",
        reply_markup=keyboards.kill_select_kb(alive_slots)
    )
    await callback.answer()


@router.message(GameCreateState.kill_protocol)
async def kill_set_protocol(message: types.Message, state: FSMContext):
    """Установка протокола для убитого."""
    if not await ensure_judge_pm(message):
        return

    text = message.text.strip()
    if text.lower() in ["нет", "no", "0"]:
        text = ""

    data = await state.get_data()
    slots = data.get("slots") or {}
    slot_num = data.get("kill_slot")

    if slot_num is None or slot_num not in slots:
        await message.answer("Ошибка: не выбран игрок для убийства.", reply_markup=keyboards.game_admin_menu())
        await state.set_state(GameCreateState.editing_slots)
        return

    slots[slot_num]["will_protocol_raw"] = text
    await state.update_data(slots=slots)
    await save_slots(state, slots)

    await state.set_state(GameCreateState.kill_opinion)

    await message.answer(
        f"✅ Протокол сохранён\n\n"
        f"💬 **Введите текст мнения (МН)**\n\n"
        f"Пример: `В 12 нет двух мирных`\n"
        f"Или нажмите кнопку ниже, чтобы пропустить",
        reply_markup=keyboards.kill_opinion_kb()
    )


@router.callback_query(GameCreateState.kill_opinion, F.data == "kill_back_to_protocol")
async def kill_back_to_protocol(callback: types.CallbackQuery, state: FSMContext):
    """Возврат к вводу протокола."""
    data = await state.get_data()
    slot_num = data.get("kill_slot")
    slots = data.get("slots") or {}

    if slot_num is None or slot_num not in slots:
        await callback.answer("Ошибка: слот не найден!", show_alert=True)
        return

    name = slots[slot_num].get("nickname") or slots[slot_num].get("full_name") or f"Слот {slot_num}"

    await state.set_state(GameCreateState.kill_protocol)
    await callback.message.edit_text(
        f"💀 **Убийство игрока {slot_num} ({name})**\n\n"
        f"📋 **Введите текст протокола (ПР)**\n\n"
        f"Пример: `3 6 7 красные, 1 4 чёрные`\n"
        f"Или `нет` для очистки",
        reply_markup=keyboards.kill_protocol_kb()
    )
    await callback.answer()


@router.callback_query(GameCreateState.kill_opinion, F.data == "kill_back_to_select")
async def kill_opinion_back_to_select(callback: types.CallbackQuery, state: FSMContext):
    """Возврат к выбору игрока из мнения."""
    data = await state.get_data()
    slots = data.get("slots") or {}
    alive_slots = {k: v for k, v in slots.items() if v.get("alive", True)}

    await state.set_state(GameCreateState.kill_select)
    await callback.message.edit_text(
        "💀 **Убийство игрока**\n\nВыберите игрока, который будет убит:",
        reply_markup=keyboards.kill_select_kb(alive_slots)
    )
    await callback.answer()


@router.message(GameCreateState.kill_opinion)
async def kill_set_opinion(message: types.Message, state: FSMContext):
    """Установка мнения и завершение убийства."""
    if not await ensure_judge_pm(message):
        return

    text = message.text.strip()
    if text.lower() in ["нет", "no", "0"]:
        text = ""

    data = await state.get_data()
    slots = data.get("slots") or {}
    slot_num = data.get("kill_slot")
    night_kills = data.get("night_kills_order", [])
    first_night = data.get("first_night_kill_recorded", False)

    if slot_num is None or slot_num not in slots:
        await message.answer("Ошибка: не выбран игрок для убийства.", reply_markup=keyboards.game_admin_menu())
        await state.set_state(GameCreateState.editing_slots)
        return

    # Сохраняем мнение
    slots[slot_num]["will_opinion"] = text

    # Помечаем игрока как убитого
    slots[slot_num]["alive"] = False
    slots[slot_num]["status_reason"] = "Убит ночью"

    # Если это первое убийство — назначаем ПУ
    if not first_night:
        for info in slots.values():
            info["pu_mark"] = False
        slots[slot_num]["pu_mark"] = True
        await state.update_data(first_night_kill_recorded=True, night_killed_slot=slot_num)
    else:
        # Убеждаемся, что у непервого убитого нет ЛХ
        slots[slot_num]["night_suspects"] = []

    # Добавляем в порядок убийств
    if slot_num not in night_kills:
        night_kills.append(slot_num)

    await state.update_data(slots=slots, night_kills_order=night_kills)
    await save_slots(state, slots)

    # Очищаем временные данные
    await state.update_data(kill_slot=None)
    await state.set_state(GameCreateState.editing_slots)

    name = slots[slot_num].get("nickname") or slots[slot_num].get("full_name") or f"Слот {slot_num}"

    # Формируем сообщение
    if not first_night:
        suspects = slots[slot_num].get("night_suspects", [])
        suspects_str = ", ".join(map(str, suspects)) if suspects else "нет"
        await message.answer(
            f"✅ **Игрок {slot_num} ({name}) убит!** (ПУ)\n\n"
            f"• ЛХ: {suspects_str}\n"
            f"• ПР: {slots[slot_num].get('will_protocol_raw', '—')[:100]}\n"
            f"• МН: {text if text else '—'}\n\n"
            f"{build_game_state(slots, alive_only=False)}",
            reply_markup=keyboards.game_admin_menu()
        )
    else:
        await message.answer(
            f"✅ **Игрок {slot_num} ({name}) убит!**\n\n"
            f"• ПР: {slots[slot_num].get('will_protocol_raw', '—')[:100]}\n"
            f"• МН: {text if text else '—'}\n\n"
            f"{build_game_state(slots, alive_only=False)}",
            reply_markup=keyboards.game_admin_menu()
        )


@router.callback_query(F.data == "kill_cancel")
async def kill_cancel(callback: types.CallbackQuery, state: FSMContext):
    """Отмена убийства."""
    await state.set_state(GameCreateState.editing_slots)

    data = await state.get_data()
    slots = data.get("slots") or {}

    await callback.message.delete()
    await callback.message.answer(
        build_game_state(slots, alive_only=False),
        reply_markup=keyboards.game_admin_menu()
    )
    await callback.answer("Убийство отменено")


# ========== ЦИФРОВАЯ КЛАВИАТУРА ДЛЯ ЛХ ПРИ УБИЙСТВЕ ==========

@router.callback_query(GameCreateState.kill_lh, F.data.startswith("num_toggle_"))
async def kill_numeric_toggle(callback: types.CallbackQuery, state: FSMContext):
    """Включение/выключение номера в выбранных для ЛХ убитого."""
    num = callback.data.split("_")[2]

    data = await state.get_data()
    selected = data.get("kill_temp_selected_numbers", [])

    if num in selected:
        selected.remove(num)
    else:
        if len(selected) >= 3:
            await callback.answer("Можно выбрать не более 3 подозреваемых!", show_alert=True)
            return
        selected.append(num)

    selected.sort(key=int)
    await state.update_data(kill_temp_selected_numbers=selected)

    await callback.message.edit_reply_markup(
        reply_markup=keyboards.numeric_selection_kb(selected)
    )
    await callback.answer()


@router.callback_query(GameCreateState.kill_lh, F.data == "numeric_done")
async def kill_numeric_done(callback: types.CallbackQuery, state: FSMContext):
    """Подтверждение выбора номеров для ЛХ убитого."""
    data = await state.get_data()
    selected = data.get("kill_temp_selected_numbers", [])
    slot_num = data.get("kill_slot")
    slots = data.get("slots") or {}

    # Очищаем временные данные
    await state.update_data(kill_temp_selected_numbers=[])

    if slot_num is None or slot_num not in slots:
        await callback.answer("Ошибка: слот не найден!", show_alert=True)
        return

    suspects = [int(x) for x in selected] if selected else []
    if len(suspects) > 3:
        await callback.answer("Можно выбрать не более 3 подозреваемых!", show_alert=True)
        return

    slots[slot_num]["night_suspects"] = list(dict.fromkeys(suspects))
    await state.update_data(slots=slots)
    await save_slots(state, slots)

    await state.set_state(GameCreateState.kill_protocol)

    suspects_str = ", ".join(selected) if selected else "очищен"
    await callback.message.edit_text(
        f"✅ ЛХ установлены: [{suspects_str}]\n\n"
        f"📋 **Введите текст протокола (ПР)**\n\n"
        f"Пример: `3 6 7 красные, 1 4 чёрные`\n"
        f"Или `нет` для очистки",
        reply_markup=keyboards.kill_protocol_kb()
    )
    await callback.answer()


@router.callback_query(GameCreateState.kill_lh, F.data == "numeric_clear")
async def kill_numeric_clear(callback: types.CallbackQuery, state: FSMContext):
    """Очистка всех выбранных номеров."""
    await state.update_data(kill_temp_selected_numbers=[])
    await callback.message.edit_reply_markup(
        reply_markup=keyboards.numeric_selection_kb([])
    )
    await callback.answer("Все номера очищены")


@router.callback_query(GameCreateState.kill_lh, F.data == "numeric_back")
async def kill_numeric_back(callback: types.CallbackQuery, state: FSMContext):
    """Возврат к вводу ЛХ."""
    await state.update_data(kill_temp_selected_numbers=[])
    await state.set_state(GameCreateState.kill_lh)

    data = await state.get_data()
    slot_num = data.get("kill_slot")
    slots = data.get("slots") or {}

    if slot_num is None or slot_num not in slots:
        await callback.answer("Ошибка: слот не найден!", show_alert=True)
        return

    name = slots[slot_num].get("nickname") or slots[slot_num].get("full_name") or f"Слот {slot_num}"

    await callback.message.edit_text(
        f"💀 **Убийство игрока {slot_num} ({name})**\n\n"
        f"👑 Это ПЕРВОЕ убийство! Игрок становится Проверяющим Улицы (ПУ).\n\n"
        f"📝 **Введите номера подозреваемых (ЛХ) через пробел**\n\n"
        f"Пример: `2 5 7`\n"
        f"Или `0` для очистки",
        reply_markup=keyboards.kill_lh_kb()
    )
    await callback.answer()


@router.callback_query(GameCreateState.kill_protocol, F.data == "kill_protocol_skip")
async def kill_protocol_skip(callback: types.CallbackQuery, state: FSMContext):
    """Пропуск протокола."""
    data = await state.get_data()
    slots = data.get("slots") or {}
    slot_num = data.get("kill_slot")

    if slot_num is None or slot_num not in slots:
        await callback.answer("Ошибка: слот не найден!", show_alert=True)
        return

    slots[slot_num]["will_protocol_raw"] = ""
    await state.update_data(slots=slots)
    await save_slots(state, slots)

    await state.set_state(GameCreateState.kill_opinion)

    # Удаляем сообщение с клавиатурой
    try:
        await callback.message.delete()
    except Exception:
        pass

    name = slots[slot_num].get("nickname") or slots[slot_num].get("full_name") or f"Слот {slot_num}"

    await callback.message.answer(
        f"⏩ Протокол пропущен (оставлен пустым)\n\n"
        f"💬 **Введите текст мнения (МН)**\n\n"
        f"Пример: `В 12 нет двух мирных`\n"
        f"Или нажмите кнопку ниже, чтобы пропустить",
        reply_markup=keyboards.kill_opinion_kb()
    )
    await callback.answer()


@router.callback_query(GameCreateState.kill_opinion, F.data == "kill_opinion_skip")
async def kill_opinion_skip(callback: types.CallbackQuery, state: FSMContext):
    """Пропуск мнения и завершение убийства."""
    data = await state.get_data()
    slots = data.get("slots") or {}
    slot_num = data.get("kill_slot")
    night_kills = data.get("night_kills_order", [])
    first_night = data.get("first_night_kill_recorded", False)

    if slot_num is None or slot_num not in slots:
        await callback.answer("Ошибка: слот не найден!", show_alert=True)
        return

    slots[slot_num]["will_opinion"] = ""

    # Помечаем игрока как убитого
    slots[slot_num]["alive"] = False
    slots[slot_num]["status_reason"] = "Убит ночью"

    # Если это первое убийство — назначаем ПУ
    if not first_night:
        for info in slots.values():
            info["pu_mark"] = False
        slots[slot_num]["pu_mark"] = True
        await state.update_data(first_night_kill_recorded=True, night_killed_slot=slot_num)
    else:
        # Убеждаемся, что у непервого убитого нет ЛХ
        slots[slot_num]["night_suspects"] = []

    # Добавляем в порядок убийств
    if slot_num not in night_kills:
        night_kills.append(slot_num)

    await state.update_data(slots=slots, night_kills_order=night_kills)
    await save_slots(state, slots)

    # Очищаем временные данные
    await state.update_data(kill_slot=None)
    await state.set_state(GameCreateState.editing_slots)

    name = slots[slot_num].get("nickname") or slots[slot_num].get("full_name") or f"Слот {slot_num}"

    # Удаляем сообщение с клавиатурой
    try:
        await callback.message.delete()
    except Exception:
        pass

    # Отправляем новое сообщение с обычной клавиатурой
    if not first_night:
        suspects = slots[slot_num].get("night_suspects", [])
        suspects_str = ", ".join(map(str, suspects)) if suspects else "нет"
        await callback.message.answer(
            f"✅ **Игрок {slot_num} ({name}) убит!** (ПУ)\n\n"
            f"• ЛХ: {suspects_str}\n"
            f"• ПР: пропущен\n"
            f"• МН: пропущен\n\n"
            f"{build_game_state(slots, alive_only=False)}",
            reply_markup=keyboards.game_admin_menu()
        )
    else:
        await callback.message.answer(
            f"✅ **Игрок {slot_num} ({name}) убит!**\n\n"
            f"• ПР: пропущен\n"
            f"• МН: пропущен\n\n"
            f"{build_game_state(slots, alive_only=False)}",
            reply_markup=keyboards.game_admin_menu()
        )

    await callback.answer()