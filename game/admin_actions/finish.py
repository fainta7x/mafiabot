"""
Завершение игры и сохранение протокола
"""
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile
from game.state import GameCreateState

import config
import database
import keyboards
from game.utils.endgame_pic import create_endgame_pic_summary
from game.admin_actions.common import clear_game_state, ensure_judge_pm, get_slots
from game.text import build_game_state

router = Router()


@router.message(F.text == "♻️ Продолжить игру")
async def resume_game(message: types.Message, state: FSMContext):
    if not await ensure_judge_pm(message):
        return

    # Проверяем флаг активной игры
    if await database.get_setting("game_active") != "1":
        rm = keyboards.admin_menu() if message.from_user.id in config.ADMIN_IDS else keyboards.judge_menu()
        await message.answer("Нет активной сохранённой игры.", reply_markup=rm)
        return

    # Загружаем слоты и метаданные
    slots = await database.load_current_game_slots()
    metadata = await database.load_current_game_metadata()

    if not slots:
        rm = keyboards.admin_menu() if message.from_user.id in config.ADMIN_IDS else keyboards.judge_menu()
        await message.answer("Не удалось найти сохранённые слоты.", reply_markup=rm)
        return

    # Преобразуем ключи слотов в int, если они ещё не int
    slots_int = {}
    for k, v in slots.items():
        try:
            slots_int[int(k)] = v
        except (ValueError, TypeError):
            slots_int[k] = v

    # Очищаем текущее состояние перед загрузкой нового
    await state.clear()

    # Устанавливаем состояние
    await state.set_state(GameCreateState.editing_slots)

    # Загружаем данные в состояние
    await state.update_data(
        slots=slots_int,
        roles_assigned=metadata.get("roles_assigned", False) if metadata else False,
        nominated_list=[],
        vote_index=0,
        split_candidates=[],
        in_split=False,
        first_night_kill_recorded=metadata.get("first_night_kill_recorded", False) if metadata else False,
        night_kills_order=metadata.get("night_kills_order", []) if metadata else [],
        night_killed_slot=None,
        winner_label=metadata.get("winner_label") if metadata else None,
        winning_team=metadata.get("winning_team") if metadata else None,
        protocol_chat_id=None,
        protocol_message_id=None,
    )

    # Отправляем сообщение о продолжении игры
    await message.answer(
        f"♻️ **Продолжаем незавершённую игру!**\n\n{build_game_state(slots_int, alive_only=False)}",
        reply_markup=keyboards.game_admin_menu()
    )


@router.message(F.text == "🏁 Завершить")
async def final_finish_game(message: types.Message, state: FSMContext):
    if not await ensure_judge_pm(message):
        return
    active = await database.get_setting("game_active")
    if active != "1":
        rm = keyboards.admin_menu() if message.from_user.id in config.ADMIN_IDS else keyboards.judge_menu()
        await message.answer("Сейчас нет активной игры.", reply_markup=rm)
        return
    data = await state.get_data()
    slots = data.get("slots") or await database.load_current_game_slots()
    if not slots:
        rm = keyboards.admin_menu() if message.from_user.id in config.ADMIN_IDS else keyboards.judge_menu()
        await message.answer("Нет данных об игре.", reply_markup=rm)
        await clear_game_state(state)
        return
    night_kills_order = data.get("night_kills_order") or data.get("_night_kills_order") or []
    if night_kills_order:
        slots["_night_kills_order"] = night_kills_order
    game_date = await database.get_current_game_date() or "-"
    evening_num = await database.get_current_game_number() or 1
    global_num = await database.get_current_global_game_number() or 1
    winner_label = data.get("winner_label")
    if winner_label and winner_label != "Игра отменена":
        img_path = create_endgame_pic_summary(slots, game_date, evening_num, global_num, winner_label)
        photo = FSInputFile(img_path)
        await message.answer_photo(photo, caption="Итоговый графический протокол игры 📸")
    await clear_game_state(state)
    rm = keyboards.admin_menu() if message.from_user.id in config.ADMIN_IDS else keyboards.judge_menu()
    await message.answer("✅ Игра полностью завершена. Можно запускать новую.", reply_markup=rm)


@router.message(GameCreateState.editing_slots, F.text == "⏹ Остановить")
async def ask_game_finish_reason(message: types.Message, state: FSMContext):
    if not await ensure_judge_pm(message):
        return
    await message.answer("⚠️ **Остановка игры**\n\nВыберите результат:", reply_markup=keyboards.game_finish_keyboard())


@router.message(GameCreateState.editing_slots, F.text.casefold() == "игра")
async def show_game_state_all_handler(message: types.Message, state: FSMContext):
    if not await ensure_judge_pm(message):
        return
    from game.admin_actions.common import show_game_state_all
    await show_game_state_all(message, state)


@router.message(GameCreateState.editing_slots, F.text.casefold() == "игра живые")
async def show_game_state_alive(message: types.Message, state: FSMContext):
    if not await ensure_judge_pm(message):
        return
    slots = await get_slots(message, state)
    if slots:
        await message.answer(build_game_state(slots, alive_only=True), reply_markup=keyboards.game_admin_menu())


@router.message(GameCreateState.editing_slots, F.text.casefold() == "ок")
async def ok_show_state(message: types.Message, state: FSMContext):
    if not await ensure_judge_pm(message):
        return
    from game.admin_actions.common import show_game_state_all
    await show_game_state_all(message, state)


@router.message(GameCreateState.editing_slots, F.text == "✏️ Редактировать")
async def enter_edit_mode(message: types.Message, state: FSMContext):
    if not await ensure_judge_pm(message):
        return

    data = await state.get_data()
    slots = data.get("slots") or {}
    slots = {int(k): v for k, v in slots.items()}

    if not slots:
        await message.answer("Нет активной игры для редактирования.", reply_markup=keyboards.game_admin_menu())
        return

    await state.set_state(GameCreateState.edit_mode_select_slot)

    # Используем клавиатуру из edit_router
    from game.edit_router import get_slot_selection_kb
    await message.answer(
        "✏️ **Режим редактирования**\n\nВыберите слот для редактирования:",
        reply_markup=get_slot_selection_kb(slots)
    )