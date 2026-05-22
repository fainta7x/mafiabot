"""
Управление фолами и техфолами
"""
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

import keyboards
from game.state import GameCreateState
from game.text import build_game_state
from game.admin_actions.common import get_slots, save_slots, ensure_judge_pm, ensure_judge_cb

router = Router()


@router.message(GameCreateState.editing_slots, F.text == "Фол")
async def foul_start(message: types.Message, state: FSMContext):
    if not await ensure_judge_pm(message):
        return
    slots = await get_slots(message, state)
    if not slots:
        return
    alive_slots = {k: v for k, v in slots.items() if v.get("alive", True)}
    if not alive_slots:
        await message.answer("❌ Нет живых игроков для начисления фолов.", reply_markup=keyboards.game_admin_menu())
        return
    await state.set_state(GameCreateState.foul_select)
    await message.answer("⚠️ **Управление фолами**\n\nВыберите игрока:", reply_markup=keyboards.foul_select_kb(alive_slots))


@router.callback_query(GameCreateState.foul_select, F.data.startswith("foul_select_"))
async def foul_select_player(callback: CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return
    slot_num = int(callback.data.split("_")[2])
    data = await state.get_data()
    slots = data.get("slots") or {}
    if slot_num not in slots:
        await callback.answer("Игрок не найден!", show_alert=True)
        return
    current_fouls = slots[slot_num].get("fouls", 0)
    name = slots[slot_num].get("nickname") or slots[slot_num].get("full_name") or f"Слот {slot_num}"
    await state.update_data(foul_slot=slot_num)
    await state.set_state(GameCreateState.foul_action)
    await callback.message.edit_text(
        f"⚠️ **Фолы игрока {slot_num} - {name}**\n\nТекущее количество фолов: {current_fouls}\n\nВыберите действие:",
        reply_markup=keyboards.foul_action_kb(slot_num, current_fouls)
    )
    await callback.answer()


@router.callback_query(GameCreateState.foul_action, F.data.startswith("foul_add_"))
async def foul_add(callback: CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return
    slot_num = int(callback.data.split("_")[2])
    data = await state.get_data()
    slots = data.get("slots") or {}
    if slot_num not in slots:
        await callback.answer("Игрок не найден!", show_alert=True)
        return
    current_fouls = slots[slot_num].get("fouls", 0)
    new_fouls = current_fouls + 1
    slots[slot_num]["fouls"] = new_fouls
    await save_slots(state, slots)

    if new_fouls >= 4 and slots[slot_num].get("alive", True):
        slots[slot_num]["alive"] = False
        slots[slot_num]["status_reason"] = "Удалён (4 фола)"
        slots[slot_num]["kicked"] = True
        current_dc = slots[slot_num].get("dc_points", 0.0)
        slots[slot_num]["dc_points"] = round(current_dc - 1.0, 1)
        await save_slots(state, slots)
        name = slots[slot_num].get("nickname") or slots[slot_num].get("full_name") or f"Слот {slot_num}"
        await callback.answer(f"⚠️ Игрок {name} удалён за 4 фола!", show_alert=True)
        game_state = build_game_state(slots, alive_only=False)
        await callback.message.answer(game_state, reply_markup=keyboards.game_admin_menu())
        alive_slots = {k: v for k, v in slots.items() if v.get("alive", True)}
        if alive_slots:
            await callback.message.answer("⚠️ **Управление фолами**\n\nВыберите игрока:", reply_markup=keyboards.foul_select_kb(alive_slots))
            await state.set_state(GameCreateState.foul_select)
        else:
            await state.set_state(GameCreateState.editing_slots)
        return

    await callback.answer(f"✅ Фол добавлен игроку {slot_num}")
    game_state = build_game_state(slots, alive_only=False)
    await callback.message.answer(game_state, reply_markup=keyboards.game_admin_menu())
    alive_slots = {k: v for k, v in slots.items() if v.get("alive", True)}
    await callback.message.answer("⚠️ **Управление фолами**\n\nВыберите игрока:", reply_markup=keyboards.foul_select_kb(alive_slots))
    await state.set_state(GameCreateState.foul_select)


@router.callback_query(GameCreateState.foul_action, F.data.startswith("foul_remove_"))
async def foul_remove(callback: CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return
    slot_num = int(callback.data.split("_")[2])
    data = await state.get_data()
    slots = data.get("slots") or {}
    if slot_num not in slots:
        await callback.answer("Игрок не найден!", show_alert=True)
        return
    current = slots[slot_num].get("fouls", 0)
    if current > 0:
        slots[slot_num]["fouls"] = current - 1
        await save_slots(state, slots)
        await callback.answer(f"✅ Фол снят с игрока {slot_num}")
    else:
        await callback.answer("❌ У игрока нет фолов для снятия!", show_alert=True)
    game_state = build_game_state(slots, alive_only=False)
    await callback.message.answer(game_state, reply_markup=keyboards.game_admin_menu())
    alive_slots = {k: v for k, v in slots.items() if v.get("alive", True)}
    await callback.message.answer("⚠️ **Управление фолами**\n\nВыберите игрока:", reply_markup=keyboards.foul_select_kb(alive_slots))
    await state.set_state(GameCreateState.foul_select)


@router.callback_query(F.data == "foul_cancel")
async def foul_cancel(callback: CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return
    await state.set_state(GameCreateState.editing_slots)
    data = await state.get_data()
    slots = data.get("slots") or {}
    await callback.message.delete()
    await callback.message.answer(build_game_state(slots, alive_only=False), reply_markup=keyboards.game_admin_menu())
    await callback.answer()


@router.callback_query(GameCreateState.foul_action, F.data.startswith("tech_foul_small_"))
async def tech_foul_small(callback: CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return
    slot_num = int(callback.data.split("_")[3])
    data = await state.get_data()
    slots = data.get("slots") or {}
    if slot_num not in slots:
        await callback.answer("Игрок не найден!", show_alert=True)
        return
    tech_fouls = slots[slot_num].get("technical_fouls", [])
    tech_fouls.append("small")
    slots[slot_num]["technical_fouls"] = tech_fouls
    current_dc = slots[slot_num].get("dc_points", 0.0)
    slots[slot_num]["dc_points"] = round(current_dc - 0.3, 1)
    await save_slots(state, slots)
    await callback.answer("✅ Малый техфол (-0.3) добавлен в ДЦ")

    if len(tech_fouls) >= 2 and slots[slot_num].get("alive", True):
        slots[slot_num]["alive"] = False
        slots[slot_num]["status_reason"] = "Удалён (2 техфола)"
        slots[slot_num]["kicked"] = True
        await save_slots(state, slots)
        await callback.answer("⚠️ Игрок удалён за 2 техфола!", show_alert=True)

    game_state = build_game_state(slots, alive_only=False)
    await callback.message.answer(game_state, reply_markup=keyboards.game_admin_menu())
    alive_slots = {k: v for k, v in slots.items() if v.get("alive", True)}
    await callback.message.answer("⚠️ **Управление фолами**\n\nВыберите игрока:", reply_markup=keyboards.foul_select_kb(alive_slots))
    await state.set_state(GameCreateState.foul_select)


@router.callback_query(GameCreateState.foul_action, F.data.startswith("tech_foul_big_"))
async def tech_foul_big(callback: CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return
    slot_num = int(callback.data.split("_")[3])
    data = await state.get_data()
    slots = data.get("slots") or {}
    if slot_num not in slots:
        await callback.answer("Игрок не найден!", show_alert=True)
        return
    tech_fouls = slots[slot_num].get("technical_fouls", [])
    tech_fouls.append("big")
    slots[slot_num]["technical_fouls"] = tech_fouls
    current_dc = slots[slot_num].get("dc_points", 0.0)
    slots[slot_num]["dc_points"] = round(current_dc - 0.6, 1)
    await save_slots(state, slots)
    await callback.answer("✅ Большой техфол (-0.6) добавлен в ДЦ")

    if len(tech_fouls) >= 2 and slots[slot_num].get("alive", True):
        slots[slot_num]["alive"] = False
        slots[slot_num]["status_reason"] = "Удалён (2 техфола)"
        slots[slot_num]["kicked"] = True
        await save_slots(state, slots)
        await callback.answer("⚠️ Игрок удалён за 2 техфола!", show_alert=True)

    game_state = build_game_state(slots, alive_only=False)
    await callback.message.answer(game_state, reply_markup=keyboards.game_admin_menu())
    alive_slots = {k: v for k, v in slots.items() if v.get("alive", True)}
    await callback.message.answer("⚠️ **Управление фолами**\n\nВыберите игрока:", reply_markup=keyboards.foul_select_kb(alive_slots))
    await state.set_state(GameCreateState.foul_select)


@router.callback_query(GameCreateState.foul_action, F.data.startswith("kick_player_"))
async def kick_player(callback: CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return
    slot_num = int(callback.data.split("_")[2])
    data = await state.get_data()
    slots = data.get("slots") or {}
    if slot_num not in slots:
        await callback.answer("Игрок не найден!", show_alert=True)
        return
    slots[slot_num]["alive"] = False
    slots[slot_num]["status_reason"] = "Удалён ведущим"
    slots[slot_num]["kicked"] = True
    current_dc = slots[slot_num].get("dc_points", 0.0)
    slots[slot_num]["dc_points"] = round(current_dc - 1.0, 1)
    await save_slots(state, slots)
    await callback.answer("🚫 Игрок удалён из игры (-1.0 в ДЦ)")
    game_state = build_game_state(slots, alive_only=False)
    await callback.message.answer(game_state, reply_markup=keyboards.game_admin_menu())
    alive_slots = {k: v for k, v in slots.items() if v.get("alive", True)}
    await callback.message.answer("⚠️ **Управление фолами**\n\nВыберите игрока:", reply_markup=keyboards.foul_select_kb(alive_slots))
    await state.set_state(GameCreateState.foul_select)