from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
import database
import keyboards
from .state import GameCreateState
from .text import build_game_state

router = Router()


# ========== КЛАВИАТУРЫ ==========
def get_slot_selection_kb(slots: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for slot_num, info in slots.items():
        name = info.get("nickname") or info.get("full_name") or f"Слот {slot_num}"
        if len(name) > 15:
            name = name[:12] + "..."
        role = info.get("role", "?")
        if len(role) > 8:
            role = role[:6] + "."
        status_icon = "✅" if info.get("alive", True) else "💀"
        builder.button(
            text=f"{status_icon} {slot_num}. {name} [{role}]",
            callback_data=f"edit_slot_{slot_num}"
        )
    builder.button(text="❌ Закрыть", callback_data="edit_close")
    builder.adjust(1)
    return builder.as_markup()


def get_edit_menu_kb(slot_num: int, slot_data: dict) -> InlineKeyboardMarkup:
    role = slot_data.get("role", "Не задана")
    team = slot_data.get("team", "—")
    alive = slot_data.get("alive", True)
    status_reason = slot_data.get("status_reason", "Жив")
    pu_mark = slot_data.get("pu_mark", False)
    lh = slot_data.get("night_suspects", [])
    protocol = slot_data.get("will_protocol_raw", "")
    opinion = slot_data.get("will_opinion", "")

    status_text = "✅ Жив" if alive else f"💀 {status_reason}"

    role_display = role if len(role) <= 10 else role[:8] + ".."
    team_display = team if team and len(team) <= 8 else team[:6] + ".." if team else "—"

    builder = InlineKeyboardBuilder()

    builder.button(text=f"🎭 Роль: {role_display}", callback_data="edit_role")
    builder.button(text=f"🏳️ Команда: {team_display}", callback_data="edit_team")
    builder.button(text=f"📊 Статус: {status_text}", callback_data="edit_status")
    pu_text = "👑 ПУ: ✅" if pu_mark else "👑 ПУ: ❌"
    builder.button(text=pu_text, callback_data="edit_pu")
    lh_text = f"📝 ЛХ: {len(lh)}" if lh else "📝 ЛХ: нет"
    protocol_text = "📋 ПР: есть" if protocol else "📋 ПР: нет"
    builder.button(text=lh_text, callback_data="edit_lh")
    builder.button(text=protocol_text, callback_data="edit_protocol")
    opinion_text = "💬 МН: есть" if opinion else "💬 МН: нет"
    builder.button(text=opinion_text, callback_data="edit_opinion")
    builder.button(text="🔄 Очистить всё", callback_data="edit_clear_all")
    builder.button(text="◀️ Назад", callback_data="edit_back_to_slots")
    builder.button(text="❌ Закрыть", callback_data="edit_close")

    builder.adjust(2, 2, 2, 2, 1, 1)
    return builder.as_markup()


def get_role_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="👤 Мирный", callback_data="role_set_Мирный")
    builder.button(text="🕵️ Шериф", callback_data="role_set_Шериф")
    builder.button(text="🔪 Мафия", callback_data="role_set_Мафия")
    builder.button(text="👑 Дон", callback_data="role_set_Дон")
    builder.button(text="❓ Не задана", callback_data="role_set_Не задана")
    builder.button(text="◀️ Назад", callback_data="edit_back_to_menu")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def get_team_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔴 Красные", callback_data="team_set_Красные")
    builder.button(text="⚫ Чёрные", callback_data="team_set_Чёрные")
    builder.button(text="◀️ Назад", callback_data="edit_back_to_menu")
    builder.adjust(1)
    return builder.as_markup()


def get_status_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Жив", callback_data="status_set_alive")
    builder.button(text="💀 Убит ночью", callback_data="status_set_killed")
    builder.button(text="⚖️ Заголосован", callback_data="status_set_voted")
    builder.button(text="◀️ Назад", callback_data="edit_back_to_menu")
    builder.adjust(1)
    return builder.as_markup()


def get_pu_kb(slot_num: int, slot_name: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=f"✅ Да, назначить {slot_name} ПУ", callback_data="pu_confirm_yes")
    builder.button(text="❌ Нет, отмена", callback_data="edit_back_to_menu")
    builder.adjust(1)
    return builder.as_markup()


def get_clear_kb(slot_num: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⚠️ ДА, ОЧИСТИТЬ ВСЁ", callback_data="clear_confirm_yes")
    builder.button(text="❌ Отмена", callback_data="edit_back_to_menu")
    builder.adjust(1)
    return builder.as_markup()


# ========== ХЕНДЛЕРЫ ==========
@router.message(GameCreateState.editing_slots, F.text == "✏️ Редактировать")
async def enter_edit_mode(message: types.Message, state: FSMContext):
    if message.from_user.id not in config.ADMIN_IDS:
        return

    data = await state.get_data()
    slots = data.get("slots") or {}
    slots = {int(k): v for k, v in slots.items()}

    if not slots:
        await message.answer("Нет активной игры.")
        return

    await state.update_data(slots=slots)
    await state.set_state(GameCreateState.edit_mode_select_slot)
    await message.answer(
        "✏️ **Режим редактирования**\n\nВыберите слот:",
        reply_markup=get_slot_selection_kb(slots)
    )


@router.callback_query(GameCreateState.edit_mode_select_slot, F.data.startswith("edit_slot_"))
async def edit_select_slot(callback: types.CallbackQuery, state: FSMContext):
    slot_num = int(callback.data.split("_")[-1])

    data = await state.get_data()
    slots = data.get("slots") or {}
    slots = {int(k): v for k, v in slots.items()}

    if slot_num not in slots:
        await callback.answer("Слот не найден!")
        return

    await state.update_data(edit_slot=slot_num)
    await state.set_state(GameCreateState.edit_mode_menu)

    await callback.message.edit_text(
        f"✏️ **Редактирование слота {slot_num}**\n👤 {slots[slot_num].get('nickname', 'Без имени')}\n\nВыберите действие:",
        reply_markup=get_edit_menu_kb(slot_num, slots[slot_num])
    )
    await callback.answer()


@router.callback_query(GameCreateState.edit_mode_menu, F.data == "edit_role")
async def edit_role(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(GameCreateState.edit_mode_role)
    await callback.message.edit_text("🎭 **Выберите роль:**", reply_markup=get_role_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("role_set_"))
async def set_role(callback: types.CallbackQuery, state: FSMContext):
    role = callback.data.split("_")[-1]

    data = await state.get_data()
    slots = data.get("slots") or {}
    slots = {int(k): v for k, v in slots.items()}
    slot_num = data.get("edit_slot")

    if slot_num and slot_num in slots:
        slots[slot_num]["role"] = role
        if role in ["Мирный", "Шериф"]:
            slots[slot_num]["team"] = "Красные"
        elif role in ["Мафия", "Дон"]:
            slots[slot_num]["team"] = "Чёрные"
        else:
            slots[slot_num]["team"] = None

        await state.update_data(slots=slots)
        await database.save_current_game_slots(slots)

    await state.set_state(GameCreateState.edit_mode_menu)
    await callback.message.edit_text(
        f"✏️ **Редактирование слота {slot_num}**\n\n✅ Роль изменена на {role}\n\nВыберите действие:",
        reply_markup=get_edit_menu_kb(slot_num, slots.get(slot_num, {}))
    )
    await callback.answer(f"Роль изменена на {role}")


@router.callback_query(GameCreateState.edit_mode_menu, F.data == "edit_team")
async def edit_team(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(GameCreateState.edit_mode_menu)
    await callback.message.edit_text("🏳️ **Выберите команду:**", reply_markup=get_team_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("team_set_"))
async def set_team(callback: types.CallbackQuery, state: FSMContext):
    team = callback.data.split("_")[-1]

    data = await state.get_data()
    slots = data.get("slots") or {}
    slots = {int(k): v for k, v in slots.items()}
    slot_num = data.get("edit_slot")

    if slot_num and slot_num in slots:
        slots[slot_num]["team"] = team
        await state.update_data(slots=slots)
        await database.save_current_game_slots(slots)

    await state.set_state(GameCreateState.edit_mode_menu)
    await callback.message.edit_text(
        f"✏️ **Редактирование слота {slot_num}**\n\n✅ Команда изменена на {team}\n\nВыберите действие:",
        reply_markup=get_edit_menu_kb(slot_num, slots.get(slot_num, {}))
    )
    await callback.answer(f"Команда изменена на {team}")


@router.callback_query(GameCreateState.edit_mode_menu, F.data == "edit_status")
async def edit_status(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(GameCreateState.edit_mode_status)
    await callback.message.edit_text("📊 **Выберите статус:**", reply_markup=get_status_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("status_set_"))
async def set_status(callback: types.CallbackQuery, state: FSMContext):
    status_type = callback.data.split("_")[-1]

    data = await state.get_data()
    slots = data.get("slots") or {}
    slots = {int(k): v for k, v in slots.items()}
    slot_num = data.get("edit_slot")

    if slot_num and slot_num in slots:
        if status_type == "alive":
            slots[slot_num]["alive"] = True
            slots[slot_num]["status_reason"] = "Жив"
        elif status_type == "killed":
            slots[slot_num]["alive"] = False
            slots[slot_num]["status_reason"] = "Убит ночью"
        elif status_type == "voted":
            slots[slot_num]["alive"] = False
            slots[slot_num]["status_reason"] = "Заголосован"

        await state.update_data(slots=slots)
        await database.save_current_game_slots(slots)

    await state.set_state(GameCreateState.edit_mode_menu)
    await callback.message.edit_text(
        f"✏️ **Редактирование слота {slot_num}**\n\n✅ Статус изменён\n\nВыберите действие:",
        reply_markup=get_edit_menu_kb(slot_num, slots.get(slot_num, {}))
    )
    await callback.answer("Статус изменён")


@router.callback_query(GameCreateState.edit_mode_menu, F.data == "edit_pu")
async def edit_pu(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    slot_num = data.get("edit_slot")
    slots = data.get("slots") or {}
    slots = {int(k): v for k, v in slots.items()}
    name = slots.get(slot_num, {}).get("nickname", f"Слот {slot_num}")

    await state.set_state(GameCreateState.edit_mode_pu)
    await callback.message.edit_text(
        f"👑 **Назначение ПУ**\n\nНазначить {name} ПУ?\n⚠️ ПУ может быть только один!",
        reply_markup=get_pu_kb(slot_num, name)
    )
    await callback.answer()


@router.callback_query(F.data == "pu_confirm_yes")
async def pu_confirm(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    slots = data.get("slots") or {}
    slots = {int(k): v for k, v in slots.items()}
    slot_num = data.get("edit_slot")

    if slot_num and slot_num in slots:
        for s in slots.values():
            s["pu_mark"] = False
        slots[slot_num]["pu_mark"] = True
        await state.update_data(slots=slots)
        await database.save_current_game_slots(slots)

    await state.set_state(GameCreateState.edit_mode_menu)
    await callback.message.edit_text(
        f"✏️ **Редактирование слота {slot_num}**\n\n✅ ПУ назначен\n\nВыберите действие:",
        reply_markup=get_edit_menu_kb(slot_num, slots.get(slot_num, {}))
    )
    await callback.answer("ПУ назначен")


@router.callback_query(GameCreateState.edit_mode_menu, F.data == "edit_lh")
async def edit_lh(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(GameCreateState.edit_mode_lh)
    await callback.message.edit_text(
        "📝 **Введите номера подозреваемых через пробел**\n\n"
        "Пример: `2 5 7`\nИли `0` для очистки",
        reply_markup=None
    )
    await callback.answer()


@router.message(GameCreateState.edit_mode_lh)
async def set_lh(message: types.Message, state: FSMContext):
    if message.from_user.id not in config.ADMIN_IDS:
        return

    text = message.text.strip()

    data = await state.get_data()
    slots = data.get("slots") or {}
    slots = {int(k): v for k, v in slots.items()}
    slot_num = data.get("edit_slot")

    if text == "0":
        suspects = []
    else:
        suspects = [int(x) for x in text.split() if x.isdigit() and 1 <= int(x) <= 10]

    if slot_num and slot_num in slots:
        slots[slot_num]["night_suspects"] = list(dict.fromkeys(suspects))
        await state.update_data(slots=slots)
        await database.save_current_game_slots(slots)

    await state.set_state(GameCreateState.edit_mode_menu)
    await message.answer(
        f"✏️ **Редактирование слота {slot_num}**\n\n✅ ЛХ установлены\n\nВыберите действие:",
        reply_markup=get_edit_menu_kb(slot_num, slots.get(slot_num, {}))
    )


@router.callback_query(GameCreateState.edit_mode_menu, F.data == "edit_protocol")
async def edit_protocol(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(GameCreateState.edit_mode_protocol)
    await callback.message.edit_text(
        "📋 **Введите текст протокола (ПР)**\n\n"
        "Пример: `3 6 7 красные, 1 4 чёрные`\nИли `нет` для очистки",
        reply_markup=None
    )
    await callback.answer()


@router.message(GameCreateState.edit_mode_protocol)
async def set_protocol(message: types.Message, state: FSMContext):
    if message.from_user.id not in config.ADMIN_IDS:
        return

    text = message.text.strip()
    if text.lower() in ["нет", "no", "0"]:
        text = ""

    data = await state.get_data()
    slots = data.get("slots") or {}
    slots = {int(k): v for k, v in slots.items()}
    slot_num = data.get("edit_slot")

    if slot_num and slot_num in slots:
        slots[slot_num]["will_protocol_raw"] = text
        await state.update_data(slots=slots)
        await database.save_current_game_slots(slots)

    await state.set_state(GameCreateState.edit_mode_menu)
    await message.answer(
        f"✏️ **Редактирование слота {slot_num}**\n\n✅ Протокол сохранён\n\nВыберите действие:",
        reply_markup=get_edit_menu_kb(slot_num, slots.get(slot_num, {}))
    )


@router.callback_query(GameCreateState.edit_mode_menu, F.data == "edit_opinion")
async def edit_opinion(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(GameCreateState.edit_mode_opinion)
    await callback.message.edit_text(
        "💬 **Введите текст мнения (МН)**\n\n"
        "Пример: `В 12 нет двух мирных`\nИли `нет` для очистки",
        reply_markup=None
    )
    await callback.answer()


@router.message(GameCreateState.edit_mode_opinion)
async def set_opinion(message: types.Message, state: FSMContext):
    if message.from_user.id not in config.ADMIN_IDS:
        return

    text = message.text.strip()
    if text.lower() in ["нет", "no", "0"]:
        text = ""

    data = await state.get_data()
    slots = data.get("slots") or {}
    slots = {int(k): v for k, v in slots.items()}
    slot_num = data.get("edit_slot")

    if slot_num and slot_num in slots:
        slots[slot_num]["will_opinion"] = text
        await state.update_data(slots=slots)
        await database.save_current_game_slots(slots)

    await state.set_state(GameCreateState.edit_mode_menu)
    await message.answer(
        f"✏️ **Редактирование слота {slot_num}**\n\n✅ Мнение сохранено\n\nВыберите действие:",
        reply_markup=get_edit_menu_kb(slot_num, slots.get(slot_num, {}))
    )


@router.callback_query(GameCreateState.edit_mode_menu, F.data == "edit_clear_all")
async def edit_clear_all(callback: types.CallbackQuery, state: FSMContext):
    slot_num = callback.data.split("_")[-1]
    await state.set_state(GameCreateState.edit_mode_confirm_clear)
    await callback.message.edit_text(
        f"⚠️ **Очистка слота {slot_num}**\n\nВы уверены? Это действие НЕЛЬЗЯ отменить!",
        reply_markup=get_clear_kb(int(slot_num))
    )
    await callback.answer()


@router.callback_query(F.data == "clear_confirm_yes")
async def clear_confirm(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    slots = data.get("slots") or {}
    slots = {int(k): v for k, v in slots.items()}
    slot_num = data.get("edit_slot")

    if slot_num and slot_num in slots:
        nickname = slots[slot_num].get("nickname")
        slots[slot_num] = {
            "user_id": None, "full_name": None, "nickname": nickname, "username": None,
            "status": "Добавлен вручную", "fouls": 0, "alive": True, "status_reason": "Жив",
            "nominated": False, "votes": 0, "night_suspects": [], "role": "Не задана",
            "team": None, "base_points": 0, "bonus_points": 0, "lh_points": 0.0, "pu_mark": False,
            "will_protocol_raw": "", "will_opinion": ""
        }
        await state.update_data(slots=slots)
        await database.save_current_game_slots(slots)

    await state.set_state(GameCreateState.edit_mode_menu)
    await callback.message.edit_text(
        f"✏️ **Редактирование слота {slot_num}**\n\n✅ Все данные очищены!\n\nВыберите действие:",
        reply_markup=get_edit_menu_kb(slot_num, slots.get(slot_num, {}))
    )
    await callback.answer("Данные очищены")


@router.callback_query(F.data == "edit_back_to_slots")
async def back_to_slots(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    slots = data.get("slots") or {}
    slots = {int(k): v for k, v in slots.items()}

    await state.set_state(GameCreateState.edit_mode_select_slot)
    await callback.message.edit_text("✏️ **Выберите слот:**", reply_markup=get_slot_selection_kb(slots))
    await callback.answer()


@router.callback_query(F.data == "edit_back_to_menu")
async def back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    slot_num = data.get("edit_slot")
    slots = data.get("slots") or {}
    slots = {int(k): v for k, v in slots.items()}

    await state.set_state(GameCreateState.edit_mode_menu)
    await callback.message.edit_text(
        f"✏️ **Редактирование слота {slot_num}**\n\nВыберите действие:",
        reply_markup=get_edit_menu_kb(slot_num, slots.get(slot_num, {}))
    )
    await callback.answer()


@router.callback_query(F.data == "edit_close")
async def edit_close(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(GameCreateState.editing_slots)

    data = await state.get_data()
    slots = data.get("slots") or {}

    await callback.message.delete()
    await callback.message.answer(
        build_game_state(slots, alive_only=False),
        reply_markup=keyboards.game_admin_menu()
    )
    await callback.answer()