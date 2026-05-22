"""
ППК (Победа Противоположной Команды)
"""
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

import keyboards
from game.state import GameCreateState
from game.admin_actions.common import save_slots, ensure_judge_cb

router = Router()


@router.callback_query(GameCreateState.ppk_team_select, F.data.startswith("ppk_team_"))
async def ppk_select_team(callback: CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return
    team = callback.data.split("_")[2]
    if team == "red":
        winning_team = "Красные"
        winner_label = "ППК: Победа красных"
    else:
        winning_team = "Чёрные"
        winner_label = "ППК: Победа чёрных"
    await state.update_data(ppk_winning_team=winning_team, ppk_winner_label=winner_label)
    await state.set_state(GameCreateState.ppk_culprit_select)
    data = await state.get_data()
    slots = data.get("slots") or {}
    await callback.message.edit_text(
        f"⚠️ **ППК**\n\nПобедившая команда: {winning_team}\n\nКто виноват в поражении (выберите игрока из проигравшей команды):",
        reply_markup=keyboards.ppk_culprit_selection_kb(slots, "Красные" if team == "black" else "Чёрные")
    )
    await callback.answer()


@router.callback_query(GameCreateState.ppk_culprit_select, F.data.startswith("ppk_culprit_"))
async def ppk_select_culprit(callback: CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return
    slot_num = int(callback.data.split("_")[2])
    data = await state.get_data()
    slots = data.get("slots") or {}
    if slot_num not in slots:
        await callback.answer("Игрок не найден!", show_alert=True)
        return
    slot_data = slots[slot_num]
    name = slot_data.get("nickname") or slot_data.get("full_name") or f"Слот {slot_num}"
    await state.update_data(ppk_culprit_slot=slot_num)
    await state.set_state(GameCreateState.ppk_confirm)
    await callback.message.edit_text(
        f"⚠️ **ППК**\n\nВы уверены, что {name} (слот {slot_num}) является виновником?\n\nЕму будет начислен штраф -1.5 балла.",
        reply_markup=keyboards.ppk_confirmation_kb(slot_num, name)
    )
    await callback.answer()


@router.callback_query(GameCreateState.ppk_confirm, F.data == "ppk_confirm_yes")
async def ppk_confirm(callback: CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return
    data = await state.get_data()
    slots = data.get("slots") or {}
    slot_num = data.get("ppk_culprit_slot")
    winning_team = data.get("ppk_winning_team")
    winner_label = data.get("ppk_winner_label")
    culprit_name = None
    if slot_num and slot_num in slots:
        culprit_name = slots[slot_num].get("nickname") or slots[slot_num].get("full_name") or f"Слот {slot_num}"
        current_dc = slots[slot_num].get("dc_points", 0.0)
        slots[slot_num]["dc_points"] = round(current_dc - 1.5, 1)
        slots[slot_num]["ppk"] = True
        slots[slot_num]["alive"] = False
        slots[slot_num]["status_reason"] = "Удалён (ППК)"
        slots[slot_num]["kicked"] = True

    for slot in slots.values():
        if slot.get("team") == winning_team:
            slot["base_points"] = 1
        else:
            slot["base_points"] = 0

    if culprit_name:
        winner_label = f"ППК: {winning_team} (Виновник: {culprit_name})"

    await state.update_data(winning_team=winning_team, winner_label=winner_label, slots=slots)
    await save_slots(state, slots)
    await state.set_state(GameCreateState.score_editor_select_player)
    await callback.message.edit_text(
        f"🏆 **{winner_label}**\n\n🎲 **Редактор баллов**\n\nВыберите игрока для редактирования Доп, ПР или МН:",
        reply_markup=keyboards.score_editor_player_kb(slots, winning_team)
    )
    await callback.answer()


@router.callback_query(F.data == "ppk_cancel")
async def ppk_cancel(callback: CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return
    await state.set_state(GameCreateState.editing_slots)
    await callback.message.delete()
    await callback.message.answer("❌ ППК отменена. Игра продолжается.", reply_markup=keyboards.game_admin_menu())
    await callback.answer()


@router.callback_query(F.data == "ppk_back_to_teams")
async def ppk_back_to_teams(callback: CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return
    await state.set_state(GameCreateState.ppk_team_select)
    await callback.message.edit_text(
        "⚠️ **ППК (Победа Противоположной Команды)**\n\nКакая команда одержала победу?",
        reply_markup=keyboards.ppk_team_selection_kb()
    )
    await callback.answer()