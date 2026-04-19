from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import keyboards
from .state import GameCreateState
from .text import build_game_state, build_slots_text

router = Router()


# ========== КЛАВИАТУРЫ ДЛЯ РЕДАКТИРОВАНИЯ ==========
def get_role_keyboard(current_role: str = None) -> InlineKeyboardMarkup:
    """Клавиатура выбора роли."""
    buttons = [
        [InlineKeyboardButton(text="👤 Мирный", callback_data="role_Мирный")],
        [InlineKeyboardButton(text="🕵️ Шериф", callback_data="role_Шериф")],
        [InlineKeyboardButton(text="🔪 Мафия", callback_data="role_Мафия")],
        [InlineKeyboardButton(text="👑 Дон", callback_data="role_Дон")],
        [InlineKeyboardButton(text="❓ Не задана", callback_data="role_Не задана")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="edit_back_to_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_team_keyboard(current_team: str = None) -> InlineKeyboardMarkup:
    """Клавиатура выбора команды."""
    buttons = [
        [InlineKeyboardButton(text="🔴 Красные", callback_data="team_Красные")],
        [InlineKeyboardButton(text="⚫ Чёрные", callback_data="team_Чёрные")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="edit_back_to_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_status_keyboard(current_status: str = None) -> InlineKeyboardMarkup:
    """Клавиатура выбора статуса."""
    buttons = [
        [InlineKeyboardButton(text="✅ Жив", callback_data="status_alive")],
        [InlineKeyboardButton(text="💀 Убит ночью", callback_data="status_killed")],
        [InlineKeyboardButton(text="⚖️ Заголосован", callback_data="status_voted")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="edit_back_to_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_edit_menu_keyboard(slot_num: int, slot_data: dict) -> InlineKeyboardMarkup:
    """Главное меню редактирования слота."""
    role = slot_data.get("role", "Не задана")
    team = slot_data.get("team", "—")
    alive = slot_data.get("alive", True)
    status_reason = slot_data.get("status_reason", "Жив")
    pu_mark = slot_data.get("pu_mark", False)
    lh = slot_data.get("night_suspects", [])
    protocol = slot_data.get("will_protocol_raw", "")
    opinion = slot_data.get("will_opinion", "")

    status_text = "✅ Жив" if alive else f"💀 {status_reason}"

    buttons = [
        [InlineKeyboardButton(text=f"👤 Роль: {role}", callback_data="edit_role")],
        [InlineKeyboardButton(text=f"🏳️ Команда: {team}", callback_data="edit_team")],
        [InlineKeyboardButton(text=f"📊 Статус: {status_text}", callback_data="edit_status")],
        [InlineKeyboardButton(text=f"👑 ПУ: {'✅' if pu_mark else '❌'}", callback_data="edit_pu")],
        [InlineKeyboardButton(text=f"📝 ЛХ: {len(lh)} чел.", callback_data="edit_lh")],
        [InlineKeyboardButton(text=f"📋 ПР: {'есть' if protocol else 'нет'}", callback_data="edit_protocol")],
        [InlineKeyboardButton(text=f"💬 МН: {'есть' if opinion else 'нет'}", callback_data="edit_opinion")],
        [InlineKeyboardButton(text="🔄 Очистить всё", callback_data="edit_clear_all")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="edit_close")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_slot_selection_keyboard(slots: dict) -> InlineKeyboardMarkup:
    """Клавиатура выбора слота для редактирования."""
    buttons = []
    row = []
    for slot_num in sorted(slots.keys()):
        info = slots[slot_num]
        name = info.get("nickname") or info.get("full_name") or f"Слот {slot_num}"
        if len(name) > 15:
            name = name[:12] + "..."
        status = "✅" if info.get("alive", True) else "💀"
        row.append(InlineKeyboardButton(text=f"{status}{slot_num}.{name}", callback_data=f"edit_slot_{slot_num}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="edit_close")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ========== ОСНОВНЫЕ ХЕНДЛЕРЫ ==========

@router.message(GameCreateState.editing_slots, F.text == "✏️ Редактировать")
async def enter_edit_mode(message: types.Message, state: FSMContext):
    """Вход в режим редактирования игры."""
    if not await ensure_admin_pm(message):
        return

    data = await state.get_data()
    slots = data.get("slots") or {}

    if not slots:
        await message.answer("Нет активной игры для редактирования.", reply_markup=keyboards.game_admin_menu())
        return

    await state.set_state(GameCreateState.edit_mode_select_slot)
    await message.answer(
        "✏️ **Режим редактирования игры**\n\nВыберите слот для редактирования:",
        reply_markup=get_slot_selection_keyboard(slots)
    )


@router.callback_query(GameCreateState.edit_mode_select_slot, F.data.startswith("edit_slot_"))
async def edit_select_slot(callback: types.CallbackQuery, state: FSMContext):
    """Выбор слота для редактирования."""
    slot_num = int(callback.data.split("_")[-1])

    data = await state.get_data()
    slots = data.get("slots") or {}

    if slot_num not in slots:
        await callback.answer("Слот не найден!", show_alert=True)
        return

    await state.update_data(edit_slot=slot_num)
    await state.set_state(GameCreateState.edit_mode_menu)

    slot_data = slots[slot_num]
    name = slot_data.get("nickname") or slot_data.get("full_name") or f"Слот {slot_num}"

    await callback.message.edit_text(
        f"✏️ **Редактирование слота {slot_num}**\n👤 Игрок: {name}\n\nВыберите параметр для изменения:",
        reply_markup=get_edit_menu_keyboard(slot_num, slot_data)
    )
    await callback.answer()


@router.callback_query(GameCreateState.edit_mode_menu, F.data == "edit_role")
async def edit_role(callback: types.CallbackQuery, state: FSMContext):
    """Редактирование роли."""
    await state.set_state(GameCreateState.edit_mode_role)
    await callback.message.edit_text(
        "🎭 **Выберите роль:**",
        reply_markup=get_role_keyboard()
    )
    await callback.answer()


@router.callback_query(GameCreateState.edit_mode_role, F.data.startswith("role_"))
async def set_role(callback: types.CallbackQuery, state: FSMContext):
    """Установка роли."""
    role = callback.data.split("_")[1]

    data = await state.get_data()
    slots = data.get("slots") or {}
    slot_num = data.get("edit_slot")

    if slot_num and slot_num in slots:
        slots[slot_num]["role"] = role
        # Автоматически ставим команду
        if role in ["Мирный", "Шериф"]:
            slots[slot_num]["team"] = "Красные"
        elif role in ["Мафия", "Дон"]:
            slots[slot_num]["team"] = "Чёрные"
        else:
            slots[slot_num]["team"] = None

        await state.update_data(slots=slots)
        await database.save_current_game_slots(slots)

    await state.set_state(GameCreateState.edit_mode_menu)
    slot_data = slots.get(slot_num, {})
    await callback.message.edit_text(
        f"✏️ **Редактирование слота {slot_num}**\n\nВыберите параметр для изменения:",
        reply_markup=get_edit_menu_keyboard(slot_num, slot_data)
    )
    await callback.answer(f"Роль изменена на {role}")


@router.callback_query(GameCreateState.edit_mode_menu, F.data == "edit_team")
async def edit_team(callback: types.CallbackQuery, state: FSMContext):
    """Редактирование команды."""
    await state.set_state(GameCreateState.edit_mode_menu)
    await callback.message.edit_text(
        "🏳️ **Выберите команду:**",
        reply_markup=get_team_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("team_"))
async def set_team(callback: types.CallbackQuery, state: FSMContext):
    """Установка команды."""
    team = callback.data.split("_")[1]

    data = await state.get_data()
    slots = data.get("slots") or {}
    slot_num = data.get("edit_slot")

    if slot_num and slot_num in slots:
        slots[slot_num]["team"] = team

    await state.update_data(slots=slots)
    await database.save_current_game_slots(slots)

    await state.set_state(GameCreateState.edit_mode_menu)
    slot_data = slots.get(slot_num, {})
    await callback.message.edit_text(
        f"✏️ **Редактирование слота {slot_num}**\n\nВыберите параметр для изменения:",
        reply_markup=get_edit_menu_keyboard(slot_num, slot_data)
    )
    await callback.answer(f"Команда изменена на {team}")


@router.callback_query(GameCreateState.edit_mode_menu, F.data == "edit_status")
async def edit_status(callback: types.CallbackQuery, state: FSMContext):
    """Редактирование статуса (жив/убит)."""
    await callback.message.edit_text(
        "📊 **Выберите статус:**",
        reply_markup=get_status_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("status_"))
async def set_status(callback: types.CallbackQuery, state: FSMContext):
    """Установка статуса."""
    status_type = callback.data.split("_")[1]

    data = await state.get_data()
    slots = data.get("slots") or {}
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
    slot_data = slots.get(slot_num, {})
    await callback.message.edit_text(
        f"✏️ **Редактирование слота {slot_num}**\n\nВыберите параметр для изменения:",
        reply_markup=get_edit_menu_keyboard(slot_num, slot_data)
    )
    await callback.answer(f"Статус изменён")


@router.callback_query(GameCreateState.edit_mode_menu, F.data == "edit_pu")
async def edit_pu(callback: types.CallbackQuery, state: FSMContext):
    """Переключение ПУ."""
    data = await state.get_data()
    slots = data.get("slots") or {}
    slot_num = data.get("edit_slot")

    if slot_num and slot_num in slots:
        # Снимаем ПУ со всех
        for s in slots.values():
            s["pu_mark"] = False
        # Ставим ПУ на выбранный слот
        slots[slot_num]["pu_mark"] = not slots[slot_num].get("pu_mark", False)

    await state.update_data(slots=slots)
    await database.save_current_game_slots(slots)

    slot_data = slots.get(slot_num, {})
    await callback.message.edit_text(
        f"✏️ **Редактирование слота {slot_num}**\n\nВыберите параметр для изменения:",
        reply_markup=get_edit_menu_keyboard(slot_num, slot_data)
    )
    await callback.answer(f"ПУ: {'включён' if slots[slot_num].get('pu_mark') else 'выключен'}")


@router.callback_query(GameCreateState.edit_mode_menu, F.data == "edit_lh")
async def edit_lh(callback: types.CallbackQuery, state: FSMContext):
    """Редактирование ЛХ (подозреваемых)."""
    await state.set_state(GameCreateState.edit_mode_lh)
    await callback.message.edit_text(
        "📝 **Введите номера подозреваемых через пробел**\n\n"
        "Пример: `2 5 7`\n"
        "Или `0` для очистки",
        reply_markup=None
    )
    await callback.answer()


@router.message(GameCreateState.edit_mode_lh)
async def set_lh(message: types.Message, state: FSMContext):
    """Установка ЛХ."""
    if not await ensure_admin_pm(message):
        return

    text = message.text.strip()

    data = await state.get_data()
    slots = data.get("slots") or {}
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
    slot_data = slots.get(slot_num, {})
    await message.answer(
        f"✏️ **Редактирование слота {slot_num}**\n\nВыберите параметр для изменения:",
        reply_markup=get_edit_menu_keyboard(slot_num, slot_data)
    )


@router.callback_query(GameCreateState.edit_mode_menu, F.data == "edit_protocol")
async def edit_protocol(callback: types.CallbackQuery, state: FSMContext):
    """Редактирование ПР (протокола)."""
    await state.set_state(GameCreateState.edit_mode_protocol)
    await callback.message.edit_text(
        "📋 **Введите текст протокола (ПР)**\n\n"
        "Пример: `3 6 7 красные, 1 4 чёрные`\n"
        "Или `нет` для очистки",
        reply_markup=None
    )
    await callback.answer()


@router.message(GameCreateState.edit_mode_protocol)
async def set_protocol(message: types.Message, state: FSMContext):
    """Установка ПР."""
    if not await ensure_admin_pm(message):
        return

    text = message.text.strip()

    data = await state.get_data()
    slots = data.get("slots") or {}
    slot_num = data.get("edit_slot")

    if slot_num and slot_num in slots:
        if text.lower() in ["нет", "no", "0"]:
            slots[slot_num]["will_protocol_raw"] = ""
        else:
            slots[slot_num]["will_protocol_raw"] = text

    await state.update_data(slots=slots)
    await database.save_current_game_slots(slots)

    await state.set_state(GameCreateState.edit_mode_menu)
    slot_data = slots.get(slot_num, {})
    await message.answer(
        f"✏️ **Редактирование слота {slot_num}**\n\nВыберите параметр для изменения:",
        reply_markup=get_edit_menu_keyboard(slot_num, slot_data)
    )


@router.callback_query(GameCreateState.edit_mode_menu, F.data == "edit_opinion")
async def edit_opinion(callback: types.CallbackQuery, state: FSMContext):
    """Редактирование МН (мнения)."""
    await state.set_state(GameCreateState.edit_mode_opinion)
    await callback.message.edit_text(
        "💬 **Введите текст мнения (МН)**\n\n"
        "Пример: `В 12 нет двух мирных`\n"
        "Или `нет` для очистки",
        reply_markup=None
    )
    await callback.answer()


@router.message(GameCreateState.edit_mode_opinion)
async def set_opinion(message: types.Message, state: FSMContext):
    """Установка МН."""
    if not await ensure_admin_pm(message):
        return

    text = message.text.strip()

    data = await state.get_data()
    slots = data.get("slots") or {}
    slot_num = data.get("edit_slot")

    if slot_num and slot_num in slots:
        if text.lower() in ["нет", "no", "0"]:
            slots[slot_num]["will_opinion"] = ""
        else:
            slots[slot_num]["will_opinion"] = text

    await state.update_data(slots=slots)
    await database.save_current_game_slots(slots)

    await state.set_state(GameCreateState.edit_mode_menu)
    slot_data = slots.get(slot_num, {})
    await message.answer(
        f"✏️ **Редактирование слота {slot_num}**\n\nВыберите параметр для изменения:",
        reply_markup=get_edit_menu_keyboard(slot_num, slot_data)
    )


@router.callback_query(GameCreateState.edit_mode_menu, F.data == "edit_clear_all")
async def edit_clear_all(callback: types.CallbackQuery, state: FSMContext):
    """Очистка всех данных слота (кроме ника и слота)."""
    data = await state.get_data()
    slots = data.get("slots") or {}
    slot_num = data.get("edit_slot")

    if slot_num and slot_num in slots:
        # Сохраняем ник и базовую информацию
        nickname = slots[slot_num].get("nickname")
        full_name = slots[slot_num].get("full_name")
        user_id = slots[slot_num].get("user_id")
        username = slots[slot_num].get("username")

        # Очищаем всё
        slots[slot_num] = create_empty_slot(nickname or full_name or f"Слот {slot_num}")
        slots[slot_num].update({
            "user_id": user_id,
            "full_name": full_name,
            "username": username,
            "nickname": nickname,
        })

    await state.update_data(slots=slots)
    await database.save_current_game_slots(slots)

    slot_data = slots.get(slot_num, {})
    await callback.message.edit_text(
        f"✏️ **Редактирование слота {slot_num}**\n\n✅ Все данные очищены!\n\nВыберите параметр для изменения:",
        reply_markup=get_edit_menu_keyboard(slot_num, slot_data)
    )
    await callback.answer("Данные очищены")


@router.callback_query(F.data == "edit_back_to_menu")
async def edit_back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    """Возврат в главное меню редактирования."""
    data = await state.get_data()
    slot_num = data.get("edit_slot")
    slots = data.get("slots") or {}

    await state.set_state(GameCreateState.edit_mode_menu)
    slot_data = slots.get(slot_num, {})
    await callback.message.edit_text(
        f"✏️ **Редактирование слота {slot_num}**\n\nВыберите параметр для изменения:",
        reply_markup=get_edit_menu_keyboard(slot_num, slot_data)
    )
    await callback.answer()


@router.callback_query(F.data == "edit_close")
async def edit_close(callback: types.CallbackQuery, state: FSMContext):
    """Закрытие режима редактирования."""
    await state.set_state(GameCreateState.editing_slots)

    data = await state.get_data()
    slots = data.get("slots") or {}

    await callback.message.delete()
    await callback.message.answer(
        build_game_state(slots, alive_only=False),
        reply_markup=keyboards.game_admin_menu()
    )
    await callback.answer()


# Добавим вспомогательную функцию, если её нет
async def ensure_admin_pm(message: types.Message) -> bool:
    from .slots_router import is_admin_pm
    if not is_admin_pm(message):
        await message.answer("⛔ Только для администраторов.")
        return False
    return True


def create_empty_slot(nickname: str) -> dict:
    from .slots_router import create_empty_slot
    return create_empty_slot(nickname)