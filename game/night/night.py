from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext

import database
import keyboards
from game.state import GameCreateState
from game.text import build_game_state
from game.admin_actions.common import get_slots, save_slots, ensure_judge_pm

router = Router()


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

    if slot_num not in slots:
        await callback.answer("Игрок не найден!", show_alert=True)
        return

    if not slots[slot_num].get("alive", True):
        await callback.answer("Этот игрок уже мёртв!", show_alert=True)
        return

    name = slots[slot_num].get("nickname") or slots[slot_num].get("full_name") or f"Слот {slot_num}"
    await state.update_data(kill_slot=slot_num)

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
    if not await ensure_judge_pm(message): return
    text = message.text.strip()
    data = await state.get_data()
    slots = data.get("slots") or {}
    slot_num = data.get("kill_slot")

    if slot_num is None or slot_num not in slots:
        await message.answer("Ошибка: не выбран игрок для убийства.", reply_markup=keyboards.game_admin_menu())
        await state.set_state(GameCreateState.editing_slots)
        return

    if text == "0":
        suspects = []
    else:
        suspects = [int(x) for x in text.split() if x.isdigit() and 1 <= int(x) <= 10]
        if len(suspects) > 3:
            await message.answer("❌ Можно указать не более 3 подозреваемых!", reply_markup=keyboards.kill_lh_kb())
            return

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
    if not await ensure_judge_pm(message): return
    text = message.text.strip()
    if text.lower() in ["нет", "no", "0"]: text = ""

    data = await state.get_data()
    slots = data.get("slots") or {}
    slot_num = data.get("kill_slot")

    if slot_num is None or slot_num not in slots:
        await message.answer("Ошибка: не выбран игрок.", reply_markup=keyboards.game_admin_menu())
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
    data = await state.get_data()
    slots = data.get("slots") or {}
    alive_slots = {k: v for k, v in slots.items() if v.get("alive", True)}
    await state.set_state(GameCreateState.kill_select)
    await callback.message.edit_text(
        "💀 **Убийство игрока**\n\nВыберите игрока, который будет убит:",
        reply_markup=keyboards.kill_select_kb(alive_slots)
    )
    await callback.answer()


# ========== ФИНАЛИЗАЦИЯ УБИЙСТВА (С ЗАКРЫТИЕМ СТАВОК) ==========

async def _finalize_kill(message_or_call, state: FSMContext, opinion_text: str = ""):
    """Общая логика завершения убийства и закрытия ставок"""
    data = await state.get_data()
    slots = data.get("slots") or {}
    slot_num = data.get("kill_slot")
    night_kills = data.get("night_kills_order", [])
    first_night = data.get("first_night_kill_recorded", False)

    if slot_num is None or slot_num not in slots:
        if isinstance(message_or_call, types.CallbackQuery):
            await message_or_call.answer("Ошибка: слот не найден!", show_alert=True)
        return

    slots[slot_num]["will_opinion"] = opinion_text
    slots[slot_num]["alive"] = False
    slots[slot_num]["status_reason"] = "Убит ночью"

    if not first_night:
        for info in slots.values():
            info["pu_mark"] = False
        slots[slot_num]["pu_mark"] = True
        await state.update_data(first_night_kill_recorded=True, night_killed_slot=slot_num)

        # ========== ЗАКРЫТИЕ СТАВОК ==========
        game_id = data.get("current_game_id")
        if game_id:
            bet = await database.get_active_bet(game_id)
            if bet:
                await database.close_bet(bet["id"])
                msg = "🛑 **Прием ставок на эту игру ЗАКРЫТ!** (объявлен ПУ)"
                if isinstance(message_or_call, types.CallbackQuery):
                    await message_or_call.message.answer(msg)
                else:
                    await message_or_call.answer(msg)
        # =====================================
    else:
        slots[slot_num]["night_suspects"] = []

    if slot_num not in night_kills:
        night_kills.append(slot_num)

    await state.update_data(slots=slots, night_kills_order=night_kills)
    await save_slots(state, slots)

    await state.update_data(kill_slot=None)
    await state.set_state(GameCreateState.editing_slots)

    name = slots[slot_num].get("nickname") or slots[slot_num].get("full_name") or f"Слот {slot_num}"

    try:
        if isinstance(message_or_call, types.CallbackQuery):
            await message_or_call.message.delete()
    except Exception:
        pass

    suspects_str = ", ".join(map(str, slots[slot_num].get("night_suspects", []))) if slots[slot_num].get(
        "night_suspects") else "нет"
    protocol_str = slots[slot_num].get('will_protocol_raw', '—')
    if not protocol_str: protocol_str = "пропущен"

    op_str = opinion_text if opinion_text else "пропущен"

    status_tag = "(ПУ)" if not first_night else ""
    lh_line = f"• ЛХ: {suspects_str}\n" if not first_night else ""

    text = (
        f"✅ **Игрок {slot_num} ({name}) убит!** {status_tag}\n\n"
        f"{lh_line}"
        f"• ПР: {protocol_str[:100]}\n"
        f"• МН: {op_str[:100]}\n\n"
        f"{build_game_state(slots, alive_only=False)}"
    )

    if isinstance(message_or_call, types.CallbackQuery):
        await message_or_call.message.answer(text, reply_markup=keyboards.game_admin_menu())
        await message_or_call.answer()
    else:
        await message_or_call.answer(text, reply_markup=keyboards.game_admin_menu())


@router.message(GameCreateState.kill_opinion)
async def kill_set_opinion(message: types.Message, state: FSMContext):
    if not await ensure_judge_pm(message): return
    text = message.text.strip()
    if text.lower() in ["нет", "no", "0"]: text = ""
    await _finalize_kill(message, state, text)


@router.callback_query(GameCreateState.kill_opinion, F.data == "kill_opinion_skip")
async def kill_opinion_skip(callback: types.CallbackQuery, state: FSMContext):
    await _finalize_kill(callback, state, "")


@router.callback_query(GameCreateState.kill_protocol, F.data == "kill_protocol_skip")
async def kill_protocol_skip(callback: types.CallbackQuery, state: FSMContext):
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

    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(
        f"⏩ Протокол пропущен (оставлен пустым)\n\n"
        f"💬 **Введите текст мнения (МН)**\n\n"
        f"Пример: `В 12 нет двух мирных`\n"
        f"Или нажмите кнопку ниже, чтобы пропустить",
        reply_markup=keyboards.kill_opinion_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "kill_cancel")
async def kill_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(GameCreateState.editing_slots)
    data = await state.get_data()
    slots = data.get("slots") or {}
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(build_game_state(slots, alive_only=False), reply_markup=keyboards.game_admin_menu())
    await callback.answer("Убийство отменено")


# ========== ЦИФРОВАЯ КЛАВИАТУРА ДЛЯ ЛХ ПРИ УБИЙСТВЕ ==========

@router.callback_query(GameCreateState.kill_lh, F.data.startswith("num_toggle_"))
async def kill_numeric_toggle(callback: types.CallbackQuery, state: FSMContext):
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
    await callback.message.edit_reply_markup(reply_markup=keyboards.numeric_selection_kb(selected))
    await callback.answer()


@router.callback_query(GameCreateState.kill_lh, F.data == "numeric_done")
async def kill_numeric_done(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("kill_temp_selected_numbers", [])
    slot_num = data.get("kill_slot")
    slots = data.get("slots") or {}

    await state.update_data(kill_temp_selected_numbers=[])

    if slot_num is None or slot_num not in slots:
        await callback.answer("Ошибка: слот не найден!", show_alert=True)
        return

    suspects = [int(x) for x in selected] if selected else []
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
    await state.update_data(kill_temp_selected_numbers=[])
    await callback.message.edit_reply_markup(reply_markup=keyboards.numeric_selection_kb([]))
    await callback.answer("Все номера очищены")


@router.callback_query(GameCreateState.kill_lh, F.data == "numeric_back")
async def kill_numeric_back(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(kill_temp_selected_numbers=[])
    await state.set_state(GameCreateState.kill_lh)
    data = await state.get_data()
    slot_num = data.get("kill_slot")
    slots = data.get("slots") or {}

    if slot_num is None or slot_num not in slots:
        await callback.answer("Ошибка!", show_alert=True)
        return

    name = slots[slot_num].get("nickname") or slots[slot_num].get("full_name") or f"Слот {slot_num}"
    await callback.message.edit_text(
        f"💀 **Убийство игрока {slot_num} ({name})**\n\n"
        f"👑 Это ПЕРВОЕ убийство! Игрок становится ПУ.\n\n"
        f"📝 **Введите номера подозреваемых (ЛХ) через пробел**\n\n"
        f"Пример: `2 5 7`\n"
        f"Или `0` для очистки",
        reply_markup=keyboards.kill_lh_kb()
    )
    await callback.answer()