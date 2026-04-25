"""
Общие функции для всех admin_actions
"""
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

import config
import database
import keyboards
from game.text import build_game_state
from game.state import GameCreateState


async def get_slots(message: Message, state: FSMContext, allow_empty: bool = False) -> dict:
    """Возвращает слоты из FSM-состояния. Если слотов нет, пробует загрузить из БД."""
    data = await state.get_data()
    slots = data.get("slots") or {}

    # Если слотов нет, но игра активна в БД - пробуем загрузить
    if not slots and not allow_empty:
        game_active = await database.get_setting("game_active")
        if game_active == "1":
            # Пробуем загрузить игру из БД
            loaded_slots = await database.load_current_game_slots()
            if loaded_slots:
                # Преобразуем ключи в int
                slots = {}
                for k, v in loaded_slots.items():
                    try:
                        slots[int(k)] = v
                    except (ValueError, TypeError):
                        slots[k] = v

                # Загружаем метаданные
                metadata = await database.load_current_game_metadata()
                if metadata:
                    await state.update_data(
                        slots=slots,
                        roles_assigned=metadata.get("roles_assigned", False),
                        first_night_kill_recorded=metadata.get("first_night_kill_recorded", False),
                        night_kills_order=metadata.get("night_kills_order", []),
                        winner_label=metadata.get("winner_label"),
                        winning_team=metadata.get("winning_team"),
                    )
                else:
                    await state.update_data(slots=slots)

                await state.set_state(GameCreateState.editing_slots)

                # Отправляем сообщение, что игра загружена
                judge_name = await database.get_current_game_judge_name()
                await message.answer(
                    f"♻️ **Игра загружена из базы данных!**\n\n{build_game_state(slots, alive_only=False, judge_name=judge_name)}",
                    reply_markup=keyboards.game_admin_menu()
                )
                return slots

    if not slots and not allow_empty:
        await message.answer(
            "Слоты пустые. Нажмите «🎲 Новая игра», чтобы начать новую партию.",
            reply_markup=keyboards.game_admin_menu()
        )
    return slots


async def save_slots(state: FSMContext, slots: dict):
    """Сохраняет слоты и метаданные в состояние и БД."""
    slots_int = {int(k): v for k, v in slots.items()}
    await state.update_data(slots=slots_int)

    data = await state.get_data()
    metadata = {
        "first_night_kill_recorded": data.get("first_night_kill_recorded", False),
        "night_kills_order": data.get("night_kills_order", []),
        "roles_assigned": data.get("roles_assigned", False),
        "winner_label": data.get("winner_label"),
        "winning_team": data.get("winning_team"),
    }
    await database.save_current_game_slots(slots_int, metadata)


async def clear_game_state(state: FSMContext):
    """Полностью очищает состояние игры."""
    await state.clear()
    await database.set_setting("game_active", None)
    await database.set_setting("current_game_slots", None)
    await database.set_setting("current_game_date", None)
    await database.set_setting("current_game_number", None)
    await database.set_setting("current_game_global_number", None)


async def show_game_state_all(message: Message, state: FSMContext):
    """Показывает текущее состояние игры (для ведущего)."""
    data = await state.get_data()
    slots = data.get("slots") or {}

    # Если слотов нет, пробуем загрузить
    if not slots:
        slots = await get_slots(message, state, allow_empty=False)

    if slots:
        judge_name = await database.get_current_game_judge_name()
        await message.answer(
            build_game_state(slots, alive_only=False, judge_name=judge_name),
            reply_markup=keyboards.game_admin_menu()
        )


def create_empty_slot(nickname: str) -> dict:
    return {
        "user_id": None,
        "full_name": None,
        "nickname": nickname,
        "username": None,
        "status": "Добавлен вручную",
        "fouls": 0,
        "alive": True,
        "status_reason": "Жив",
        "nominated": False,
        "votes": 0,
        "night_suspects": [],
        "role": "Не задана",
        "team": None,
        "base_points": 0,
        "bonus_points": 0,
        "lh_points": 0.0,
        "pu_mark": False,
        "kicked": False,
        "ppk": False,
        "technical_fouls": [],
        "dc_points": 0.0,
    }


async def ensure_judge_pm(message: Message) -> bool:
    """Проверка прав судьи или администратора"""
    if not message.from_user or message.chat.type != "private":
        return False
    user_id = message.from_user.id
    if user_id in config.ADMIN_IDS:
        return True
    if await database.is_game_judge(user_id):
        return True
    await message.answer("❌ У вас нет прав судьи.")
    return False


async def ensure_judge_cb(callback: CallbackQuery) -> bool:
    """Проверка прав судьи для callback"""
    user_id = callback.from_user.id
    if user_id in config.ADMIN_IDS:
        return True
    if await database.is_game_judge(user_id):
        return True
    await callback.answer("❌ У вас нет прав судьи.", show_alert=True)
    return False