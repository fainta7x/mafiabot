from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder

import keyboards
import database
from game.state import GameCreateState
from game.text import build_game_state, build_protocol_text
from game.admin_actions.common import get_slots, save_slots, ensure_judge_pm

router = Router()


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def _parse_bonus_value(raw: str) -> float | None:
    s = raw.strip().replace(",", ".")
    if not s:
        return None
    if s.startswith(".") or s.startswith("-."):
        s = s.replace(".", "0.", 1)
    try:
        val = float(s)
    except ValueError:
        return None
    if "." not in s:
        try:
            val = int(s) / 10.0
        except ValueError:
            return None
    return round(val, 1)


def _attach_night_kills_order(slots: dict, data: dict) -> None:
    kills = data.get("night_kills_order") or []
    if kills:
        slots["_night_kills_order"] = kills
    else:
        slots.pop("_night_kills_order", None)


async def _update_protocol(message: types.Message, state: FSMContext, slots: dict):
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


# ========== 1. ВЫСТАВЛЕНИЕ (ИНТЕРАКТИВНОЕ) ==========
@router.message(GameCreateState.editing_slots, F.text == "Выставить")
async def nominate_start(message: types.Message, state: FSMContext):
    if not await ensure_judge_pm(message):
        return

    slots = await get_slots(message, state)
    if not slots:
        return

    alive_slots = {k: v for k, v in slots.items() if v.get("alive", True)}
    if not alive_slots:
        await message.answer("❌ Нет живых игроков для выставления.", reply_markup=keyboards.game_admin_menu())
        return

    data = await state.get_data()
    current_nominated = data.get("nominated_list", [])

    await state.set_state(GameCreateState.nominate_select)
    await message.answer(
        "⚖️ **Выставление игроков**\n\n"
        "Нажимайте на игроков, чтобы добавить/убрать из списка.\n"
        "После выбора нажмите **«Подтвердить»**.",
        reply_markup=keyboards.nominate_select_kb(alive_slots, current_nominated)
    )


@router.callback_query(GameCreateState.nominate_select, F.data.startswith("nominate_toggle_"))
async def nominate_toggle(callback: types.CallbackQuery, state: FSMContext):
    slot_num = int(callback.data.split("_")[2])

    data = await state.get_data()
    slots = data.get("slots") or {}
    nominated = data.get("nominated_list", [])

    if slot_num not in slots or not slots[slot_num].get("alive", True):
        await callback.answer("Этого игрока уже нельзя выставить!", show_alert=True)
        return

    if slot_num in nominated:
        nominated.remove(slot_num)
        await callback.answer(f"❌ Игрок {slot_num} убран из списка")
    else:
        nominated.append(slot_num)
        await callback.answer(f"✅ Игрок {slot_num} добавлен в список")

    await state.update_data(nominated_list=nominated)

    alive_slots = {k: v for k, v in slots.items() if v.get("alive", True)}
    await callback.message.edit_reply_markup(reply_markup=keyboards.nominate_select_kb(alive_slots, nominated))


@router.callback_query(GameCreateState.nominate_select, F.data == "nominate_confirm")
async def nominate_confirm(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    slots = data.get("slots") or {}
    nominated = data.get("nominated_list", [])

    # Сначала очищаем все старые номинации
    for slot in slots.values():
        slot["nominated"] = False
        slot["votes"] = 0

    # Затем отмечаем выбранных
    for slot_num in nominated:
        if slot_num in slots and slots[slot_num].get("alive", True):
            slots[slot_num]["nominated"] = True

    await state.update_data(slots=slots, nominated_list=nominated, vote_index=0)
    await save_slots(state, slots)

    # Отвечаем на callback ДО того, как редактировать сообщение
    await callback.answer(f"✅ Выставлено {len(nominated)} игроков")

    # Удаляем сообщение с клавиатурой выставления
    try:
        await callback.message.delete()
    except Exception:
        pass

    # Отправляем новое сообщение с результатом
    if nominated:
        nominated_names = []
        for slot_num in nominated:
            name = slots[slot_num].get("nickname") or slots[slot_num].get("full_name") or f"Слот {slot_num}"
            nominated_names.append(f"{slot_num}. {name}")
        await callback.message.answer(
            f"⚖️ **Выставленные игроки:**\n\n" + "\n".join(nominated_names),
            reply_markup=keyboards.game_admin_menu()
        )
    else:
        await callback.message.answer(
            f"⚖️ **Выставление**\n\nНикто не выставлен.",
            reply_markup=keyboards.game_admin_menu()
        )

    # Показываем состояние игры
    await callback.message.answer(
        build_game_state(slots, alive_only=False),
        reply_markup=keyboards.game_admin_menu()
    )

    await state.set_state(GameCreateState.editing_slots)


@router.callback_query(GameCreateState.nominate_select, F.data == "nominate_cancel")
async def nominate_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(GameCreateState.editing_slots)
    data = await state.get_data()
    slots = data.get("slots") or {}
    await callback.message.delete()
    await callback.message.answer(build_game_state(slots, alive_only=False), reply_markup=keyboards.game_admin_menu())
    await callback.answer("Выставление отменено")


# ========== 2. ГОЛОСОВАНИЕ (ИНТЕРАКТИВНОЕ) ==========
@router.message(GameCreateState.editing_slots, F.text == "Голоса")
async def votes_start(message: types.Message, state: FSMContext):
    if not await ensure_judge_pm(message):
        return

    data = await state.get_data()
    slots = data.get("slots") or {}

    # Берём порядок из nominated_list (сохраняет порядок выставления)
    nominated = []
    for slot_num in data.get("nominated_list", []):
        if slot_num in slots and slots[slot_num].get("alive", True):
            nominated.append(slot_num)

    if not nominated:
        await message.answer("❌ Сначала нужно выставить игроков (кнопка «Выставить»).",
                             reply_markup=keyboards.game_admin_menu())
        return

    alive_count = sum(1 for info in slots.values() if info.get("alive", True))

    nominated_names = []
    for s in nominated:
        name = slots[s].get("nickname") or slots[s].get("full_name") or f"Слот {s}"
        nominated_names.append((s, name))

    await state.update_data(
        nominated_list=nominated,
        nominated_names=nominated_names,
        vote_index=0,
        votes_received={},
        remaining_voters=alive_count
    )
    await state.set_state(GameCreateState.vote_collect)

    first_slot, first_name = nominated_names[0]
    remaining_candidates = len(nominated)

    await message.answer(
        f"🗳️ **Голосование**\n\n"
        f"Всего живых игроков: {alive_count}\n\n"
        f"Сколько голосов за игрока {first_slot} ({first_name})?\n\n"
        f"🔴 — вариант может привести к попилу",
        reply_markup=keyboards.vote_value_kb(first_slot, alive_count, alive_count, remaining_candidates)
    )


@router.callback_query(GameCreateState.vote_collect, F.data.startswith("vote_set_"))
async def vote_set(callback: types.CallbackQuery, state: FSMContext):
    try:
        parts = callback.data.split("_")
        slot_num = int(parts[2])
        votes = int(parts[3])

        data = await state.get_data()
        nominated = data.get("nominated_list", [])
        nominated_names = data.get("nominated_names", [])
        idx = data.get("vote_index", 0)
        votes_received = data.get("votes_received", {})
        remaining_voters = data.get("remaining_voters", 0)

        if votes > remaining_voters:
            await callback.answer(f"❌ Не может быть больше {remaining_voters} голосов!", show_alert=True)
            return

        votes_received[slot_num] = votes
        remaining_voters -= votes
        idx += 1

        await state.update_data(votes_received=votes_received, vote_index=idx, remaining_voters=remaining_voters)

        # Отвечаем на callback сразу, чтобы не было timeout
        try:
            await callback.answer()
        except Exception:
            pass

        if idx == len(nominated):
            await process_vote_results(callback.message, state, votes_received, nominated)

        elif idx == len(nominated) - 1:
            last_slot, last_name = nominated_names[idx]
            remaining_votes = remaining_voters
            votes_received[last_slot] = remaining_votes

            await callback.message.edit_text(
                f"🗳️ **Голосование**\n\n"
                f"Осталось голосующих: {remaining_voters}\n\n"
                f"Автоматический подсчёт:\n"
                f"За игрока {last_slot} ({last_name}) отдано {remaining_votes} голосов (все оставшиеся)."
            )

            await process_vote_results(callback.message, state, votes_received, nominated)

        else:
            next_slot, next_name = nominated_names[idx]
            remaining_candidates = len(nominated) - idx
            await callback.message.edit_text(
                f"🗳️ **Голосование**\n\n"
                f"Осталось голосующих: {remaining_voters}\n\n"
                f"Сколько голосов за игрока {next_slot} ({next_name})?\n\n"
                f"🔴 — вариант может привести к попилу",
                reply_markup=keyboards.vote_value_kb(next_slot, remaining_voters, remaining_voters, remaining_candidates)
            )

    except Exception as e:
        print(f"[VOTE_SET] Error: {e}")
        try:
            await callback.answer("Произошла ошибка", show_alert=True)
        except Exception:
            pass


async def process_vote_results(message: types.Message, state: FSMContext, votes_received: dict, nominated: list):
    data = await state.get_data()
    slots = data.get("slots") or {}
    in_split = data.get("in_split", False)
    alive_count = sum(1 for info in slots.values() if info.get("alive", True))

    def get_name(slot):
        return slots[slot].get("nickname") or slots[slot].get("full_name") or f"Слот {slot}"

    max_votes = max(votes_received.values())
    leaders = [s for s, v in votes_received.items() if v == max_votes]

    if len(leaders) == 1:
        leader = leaders[0]
        slots[leader].update({"alive": False, "status_reason": "Заголосован"})

        for s in nominated:
            if s in slots:
                slots[s]["nominated"] = False
                slots[s]["votes"] = 0

        await state.update_data(slots=slots, nominated_list=[], vote_index=0, in_split=False, split_candidates=[])
        await save_slots(state, slots)

        leader_name = get_name(leader)

        results_text = "📊 **Распределение голосов:**\n"
        for s in nominated:
            votes = votes_received.get(s, 0)
            name = get_name(s)
            results_text += f"  • {s}. {name}: {votes} голосов\n"

        await message.edit_text(
            f"🗳️ **Результат голосования**\n\n"
            f"{results_text}\n"
            f"🏆 **Заголосован:** {leader_name} (слот {leader})\n"
            f"Голосов: {max_votes} из {alive_count}\n\n"
            f"{build_game_state(slots, alive_only=False)}"
        )
        await state.set_state(GameCreateState.editing_slots)

    elif len(leaders) > 1:
        leaders_text = ", ".join(f"{s} ({get_name(s)})" for s in sorted(leaders))

        if not in_split:
            for s in leaders:
                if s in slots:
                    slots[s]["nominated"] = True
                    slots[s]["votes"] = 0
            for s in nominated:
                if s not in leaders and s in slots:
                    slots[s]["nominated"] = False

            new_nominated_names = [(s, get_name(s)) for s in leaders]

            await state.update_data(
                slots=slots,
                nominated_list=leaders,
                nominated_names=new_nominated_names,
                vote_index=0,
                in_split=True,
                split_candidates=leaders,
                votes_received={},
                remaining_voters=alive_count
            )

            first_leader = leaders[0]
            first_name = get_name(first_leader)
            remaining_candidates = len(leaders)

            await message.edit_text(
                f"🗳️ **ПОПИЛ!**\n\n"
                f"Голоса разделились между: {leaders_text}\n"
                f"**Переголосование только между ними!**\n\n"
                f"Сколько голосов за игрока {first_leader} ({first_name})?\n\n"
                f"🔴 — вариант может привести к попилу",
                reply_markup=keyboards.vote_value_kb(first_leader, alive_count, alive_count, remaining_candidates)
            )
            await state.set_state(GameCreateState.vote_collect)
        else:
            await state.update_data(slots=slots, split_candidates=leaders, nominated_list=leaders, in_split=False)
            await message.edit_text(
                f"🗳️ **ПОВТОРНЫЙ ПОПИЛ!**\n\n"
                f"Голоса снова разделились между: {leaders_text}\n\n"
                f"Что делаем?",
                reply_markup=keyboards.split_decision_keyboard()
            )
            await state.set_state(GameCreateState.editing_slots)

    else:
        for s in nominated:
            if s in slots:
                slots[s]["nominated"] = False
                slots[s]["votes"] = 0
        await state.update_data(slots=slots, nominated_list=[], vote_index=0, in_split=False, split_candidates=[])
        await save_slots(state, slots)
        await message.edit_text(
            f"🗳️ **Результат**\n\n❌ Никто не заголосован.\n\n{build_game_state(slots, alive_only=False)}"
        )
        await state.set_state(GameCreateState.editing_slots)


# ========== 3. РЕШЕНИЕ ПО ВТОРОМУ ПОПИЛУ ==========
async def handle_split_decision(callback: types.CallbackQuery, state: FSMContext, kill: bool):
    data = await state.get_data()
    slots = data.get("slots") or {}
    candidates = data.get("split_candidates") or []

    if kill:
        for n in candidates:
            if n in slots and slots[n].get("alive", True):
                slots[n].update({"alive": False, "status_reason": "Заголосован"})
                slots[n]["nominated"] = False
                slots[n]["votes"] = 0
        await callback.message.edit_text(f"⚡ **Решение: Поднять всех**\n\nИгроки {', '.join(map(str, candidates))} заголосованы.")
    else:
        for slot_num, info in slots.items():
            info["nominated"] = False
            info["votes"] = 0
        await callback.message.edit_text(f"🔄 **Решение: Оставить всех**\n\nНикто не заголосован.")

    await state.update_data(
        slots=slots,
        nominated_list=[],
        vote_index=0,
        in_split=False,
        split_candidates=[],
        votes_received={},
        remaining_voters=0
    )
    await save_slots(state, slots)
    await callback.message.answer(build_game_state(slots, alive_only=False), reply_markup=keyboards.game_admin_menu())
    await callback.answer()


@router.callback_query(F.data == "split:kill_all")
async def split_kill_all(callback: types.CallbackQuery, state: FSMContext):
    await handle_split_decision(callback, state, kill=True)


@router.callback_query(F.data == "split:keep_all")
async def split_keep_all(callback: types.CallbackQuery, state: FSMContext):
    await handle_split_decision(callback, state, kill=False)


# ========== 4. ДОПЫ, ПР, МН ==========
async def _apply_score(message: types.Message, state: FSMContext, cmd: str, field: str, is_cumulative: bool = True):
    parts = (message.text or "").strip().split()
    if len(parts) < 3:
        await message.answer(f"Формат: `{cmd} <номер_слота> <значение>`.\nПример: `{cmd} 4 2` (0.2)", reply_markup=keyboards.game_admin_menu())
        return

    try:
        slot_num = int(parts[1])
    except ValueError:
        await message.answer(f"Номер слота должен быть числом. Пример: `{cmd} 4 2`", reply_markup=keyboards.game_admin_menu())
        return

    val = _parse_bonus_value(parts[2])
    if val is None:
        await message.answer(f"Не удалось разобрать значение. Примеры: `2`, `0.2`, `-0.3`", reply_markup=keyboards.game_admin_menu())
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
    await message.answer(f"{cmd.upper()}: слот {slot_num} ({sign}{val} очков). Протокол обновлён 👇", reply_markup=keyboards.game_admin_menu())
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