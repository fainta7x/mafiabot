from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
import database
import keyboards
from .state import GameCreateState
from .text import build_game_state
from game.admin_actions.common import ensure_judge_pm, ensure_judge_cb, get_slots, save_slots

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
    kicked = slot_data.get("kicked", False)
    tech_fouls = len(slot_data.get("technical_fouls", []))

    status_text = "✅ Жив" if alive else f"💀 {status_reason}"
    if kicked:
        status_text = "🚫 Удалён"

    role_display = role if len(role) <= 10 else role[:8] + ".."
    team_display = team if team and len(team) <= 8 else team[:6] + ".." if team else "—"

    builder = InlineKeyboardBuilder()

    builder.button(text=f"🎭 Роль: {role_display}", callback_data="edit_role")
    builder.button(text=f"🏳️ Команда: {team_display}", callback_data="edit_team")
    builder.button(text=f"📊 Статус: {status_text}", callback_data="edit_status")
    pu_text = "👑 ПУ: ✅" if pu_mark else "👑 ПУ: ❌"
    builder.button(text=pu_text, callback_data="edit_pu")
    lh_text = f"📝 ЛХ: {len(lh)}" if lh else "📝 ЛХ: нет"
    builder.button(text=lh_text, callback_data="edit_lh")

    # Разделяем ПР и МН на баллы и текст
    protocol_points = slot_data.get("will_protocol_points", 0)
    opinion_points = slot_data.get("will_opinion_points", 0)
    builder.button(text=f"📋 ПР баллы: {protocol_points:+.1f}", callback_data="edit_protocol_points")
    builder.button(text=f"📋 ПР текст: {'есть' if protocol else 'нет'}", callback_data="edit_protocol_text")
    builder.button(text=f"💬 МН баллы: {opinion_points:+.1f}", callback_data="edit_opinion_points")
    builder.button(text=f"💬 МН текст: {'есть' if opinion else 'нет'}", callback_data="edit_opinion_text")

    fouls_text = f"⚠️ Техфолы: {tech_fouls}/2"
    builder.button(text=fouls_text, callback_data=f"edit_fouls_{slot_num}")
    builder.button(text="🔄 Очистить всё", callback_data="edit_clear_all")
    builder.button(text="◀️ Назад", callback_data="edit_back_to_slots")
    builder.button(text="❌ Закрыть", callback_data="edit_close")

    builder.adjust(2, 2, 2, 2, 2, 1, 1)
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
    if not await ensure_judge_pm(message):
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
    if not await ensure_judge_cb(callback):
        return

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
    if not await ensure_judge_cb(callback):
        return
    await state.set_state(GameCreateState.edit_mode_role)
    await callback.message.edit_text("🎭 **Выберите роль:**", reply_markup=get_role_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("role_set_"))
async def set_role(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return

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
    if not await ensure_judge_cb(callback):
        return
    await state.set_state(GameCreateState.edit_mode_menu)
    await callback.message.edit_text("🏳️ **Выберите команду:**", reply_markup=get_team_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("team_set_"))
async def set_team(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return

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
    if not await ensure_judge_cb(callback):
        return
    await state.set_state(GameCreateState.edit_mode_status)
    await callback.message.edit_text("📊 **Выберите статус:**", reply_markup=get_status_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("status_set_"))
async def set_status(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return

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
    if not await ensure_judge_cb(callback):
        return

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
    if not await ensure_judge_cb(callback):
        return

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
    if not await ensure_judge_cb(callback):
        return
    await state.set_state(GameCreateState.edit_mode_lh)
    await callback.message.edit_text(
        "📝 **Введите номера подозреваемых через пробел**\n\n"
        "Пример: `2 5 7`\nИли `0` для очистки",
        reply_markup=None
    )
    await callback.answer()


@router.message(GameCreateState.edit_mode_lh)
async def set_lh(message: types.Message, state: FSMContext):
    if not await ensure_judge_pm(message):
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


# ========== РЕДАКТИРОВАНИЕ ПР (баллы и текст) ==========
@router.callback_query(GameCreateState.edit_mode_menu, F.data == "edit_protocol_points")
async def edit_protocol_points(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return
    await state.set_state(GameCreateState.edit_mode_points)
    await state.update_data(edit_field="will_protocol_points", edit_field_name="ПР")
    await callback.message.edit_text(
        "📊 **Введите новое значение ПР (баллы)**\n\n"
        "Пример: `+0.5`, `-1`, `0.2`\n"
        "Или `0` для обнуления",
        reply_markup=None
    )
    await callback.answer()


@router.callback_query(GameCreateState.edit_mode_menu, F.data == "edit_protocol_text")
async def edit_protocol_text(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return
    await state.set_state(GameCreateState.edit_mode_protocol)
    await state.update_data(edit_field="will_protocol_raw", edit_field_name="текст ПР")
    await callback.message.edit_text(
        "📋 **Введите текст протокола (ПР)**\n\n"
        "Пример: `3 6 7 красные, 1 4 чёрные`\n"
        "Или `нет` для очистки",
        reply_markup=None
    )
    await callback.answer()


# ========== РЕДАКТИРОВАНИЕ МН (баллы и текст) ==========
@router.callback_query(GameCreateState.edit_mode_menu, F.data == "edit_opinion_points")
async def edit_opinion_points(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return
    await state.set_state(GameCreateState.edit_mode_points)
    await state.update_data(edit_field="will_opinion_points", edit_field_name="МН")
    await callback.message.edit_text(
        "💬 **Введите новое значение МН (баллы)**\n\n"
        "Пример: `+0.5`, `-1`, `0.2`\n"
        "Или `0` для обнуления",
        reply_markup=None
    )
    await callback.answer()


@router.callback_query(GameCreateState.edit_mode_menu, F.data == "edit_opinion_text")
async def edit_opinion_text(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return
    await state.set_state(GameCreateState.edit_mode_opinion)
    await state.update_data(edit_field="will_opinion", edit_field_name="текст МН")
    await callback.message.edit_text(
        "💬 **Введите текст мнения (МН)**\n\n"
        "Пример: `В 12 нет двух мирных`\n"
        "Или `нет` для очистки",
        reply_markup=None
    )
    await callback.answer()


# ========== ОБЩИЙ ХЕНДЛЕР ДЛЯ ВВОДА ЗНАЧЕНИЙ ==========
@router.message(GameCreateState.edit_mode_points)
async def set_points_value(message: types.Message, state: FSMContext):
    if not await ensure_judge_pm(message):
        return

    data = await state.get_data()
    field = data.get("edit_field")
    field_name = data.get("edit_field_name")
    slot_num = data.get("edit_slot")

    if slot_num is None:
        await message.answer("Ошибка: не выбран слот.")
        await state.set_state(GameCreateState.edit_mode_menu)
        return

    data_state = await state.get_data()
    slots = data_state.get("slots") or {}
    slots = {int(k): v for k, v in slots.items()}

    if slot_num not in slots:
        await message.answer("Слот не найден!")
        await state.set_state(GameCreateState.edit_mode_menu)
        return

    text = message.text.strip()
    try:
        value = float(text.replace(",", "."))
    except ValueError:
        await message.answer("❌ Введите число (например: 0.5, -1, 0.2)")
        return

    slots[slot_num][field] = value
    await state.update_data(slots=slots)
    await database.save_current_game_slots(slots)

    await state.set_state(GameCreateState.edit_mode_menu)
    await message.answer(
        f"✏️ **Редактирование слота {slot_num}**\n\n"
        f"✅ {field_name} изменён на {value:+.1f}\n\n"
        f"Выберите действие:",
        reply_markup=get_edit_menu_kb(slot_num, slots[slot_num])
    )


# ========== ОБЩИЙ ХЕНДЛЕР ДЛЯ ВВОДА ТЕКСТА ==========
@router.message(GameCreateState.edit_mode_protocol)
async def set_protocol_text_value(message: types.Message, state: FSMContext):
    if not await ensure_judge_pm(message):
        return

    data = await state.get_data()
    slot_num = data.get("edit_slot")

    if slot_num is None:
        await message.answer("Ошибка: не выбран слот.")
        await state.set_state(GameCreateState.edit_mode_menu)
        return

    data_state = await state.get_data()
    slots = data_state.get("slots") or {}
    slots = {int(k): v for k, v in slots.items()}

    if slot_num not in slots:
        await message.answer("Слот не найден!")
        await state.set_state(GameCreateState.edit_mode_menu)
        return

    text = message.text.strip()
    if text.lower() in ["нет", "no", "0"]:
        text = ""

    slots[slot_num]["will_protocol_raw"] = text
    await state.update_data(slots=slots)
    await database.save_current_game_slots(slots)

    await state.set_state(GameCreateState.edit_mode_menu)
    await message.answer(
        f"✏️ **Редактирование слота {slot_num}**\n\n"
        f"✅ Текст ПР сохранён\n\n"
        f"Выберите действие:",
        reply_markup=get_edit_menu_kb(slot_num, slots[slot_num])
    )


@router.message(GameCreateState.edit_mode_opinion)
async def set_opinion_text_value(message: types.Message, state: FSMContext):
    if not await ensure_judge_pm(message):
        return

    data = await state.get_data()
    slot_num = data.get("edit_slot")

    if slot_num is None:
        await message.answer("Ошибка: не выбран слот.")
        await state.set_state(GameCreateState.edit_mode_menu)
        return

    data_state = await state.get_data()
    slots = data_state.get("slots") or {}
    slots = {int(k): v for k, v in slots.items()}

    if slot_num not in slots:
        await message.answer("Слот не найден!")
        await state.set_state(GameCreateState.edit_mode_menu)
        return

    text = message.text.strip()
    if text.lower() in ["нет", "no", "0"]:
        text = ""

    slots[slot_num]["will_opinion"] = text
    await state.update_data(slots=slots)
    await database.save_current_game_slots(slots)

    await state.set_state(GameCreateState.edit_mode_menu)
    await message.answer(
        f"✏️ **Редактирование слота {slot_num}**\n\n"
        f"✅ Текст МН сохранён\n\n"
        f"Выберите действие:",
        reply_markup=get_edit_menu_kb(slot_num, slots[slot_num])
    )


@router.callback_query(GameCreateState.edit_mode_menu, F.data == "edit_clear_all")
async def edit_clear_all(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return

    data = await state.get_data()
    slot_num = data.get("edit_slot")
    await state.set_state(GameCreateState.edit_mode_confirm_clear)
    await callback.message.edit_text(
        f"⚠️ **Очистка слота {slot_num}**\n\nВы уверены? Это действие НЕЛЬЗЯ отменить!",
        reply_markup=get_clear_kb(int(slot_num))
    )
    await callback.answer()


@router.callback_query(F.data == "clear_confirm_yes")
async def clear_confirm(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return

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
    if not await ensure_judge_cb(callback):
        return

    data = await state.get_data()
    slots = data.get("slots") or {}
    slots = {int(k): v for k, v in slots.items()}

    await state.set_state(GameCreateState.edit_mode_select_slot)
    await callback.message.edit_text("✏️ **Выберите слот:**", reply_markup=get_slot_selection_kb(slots))
    await callback.answer()


@router.callback_query(F.data == "edit_back_to_menu")
async def back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return

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
    if not await ensure_judge_cb(callback):
        return

    await state.set_state(GameCreateState.editing_slots)

    data = await state.get_data()
    slots = data.get("slots") or {}

    await callback.message.delete()
    await callback.message.answer(
        build_game_state(slots, alive_only=False),
        reply_markup=keyboards.game_admin_menu()
    )
    await callback.answer()


# ========== УПРАВЛЕНИЕ ТЕХФОЛАМИ В РЕЖИМЕ РЕДАКТИРОВАНИЯ ==========

async def refresh_fouls_menu(message: types.Message, state: FSMContext, slot_num: int):
    """Обновляет меню техфолов без создания фейкового callback"""
    data = await state.get_data()
    slots = data.get("slots") or {}
    slots = {int(k): v for k, v in slots.items()}

    if slot_num not in slots:
        return

    slot = slots[slot_num]
    current_kick = slot.get("kicked", False)
    current_tech = len(slot.get("technical_fouls", []))

    builder = InlineKeyboardBuilder()

    kick_status = "✅ Удалён" if current_kick else "❌ Не удалён"
    builder.button(text=f"🚫 {kick_status}", callback_data=f"fouls_kick_{slot_num}")
    builder.button(text="⚠️ Малый техфол (+1, -0.3 ДЦ)", callback_data=f"fouls_small_{slot_num}")
    builder.button(text="⚠️ Большой техфол (+1, -0.6 ДЦ)", callback_data=f"fouls_big_{slot_num}")
    if current_tech > 0:
        builder.button(text="🔧 Снять техфол (-1)", callback_data=f"fouls_dec_{slot_num}")
    builder.button(text="◀️ Назад", callback_data="edit_back_to_menu")
    builder.adjust(1)

    await message.edit_text(
        f"⚠️ **Управление техфолами и удалением**\n\n"
        f"Слот {slot_num}: {slot.get('nickname') or slot.get('full_name') or 'Без имени'}\n\n"
        f"Текущее состояние:\n"
        f"• Техфолы: {current_tech}/2\n"
        f"• Удалён: {'Да' if current_kick else 'Нет'}\n\n"
        f"Малый техфол: -0.3 к ДЦ\n"
        f"Большой техфол: -0.6 к ДЦ\n"
        f"2 техфола = автоматическое удаление",
        reply_markup=builder.as_markup()
    )


@router.callback_query(GameCreateState.edit_mode_menu, F.data.startswith("edit_fouls_"))
async def edit_fouls_menu(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return

    slot_num = int(callback.data.split("_")[2])
    await refresh_fouls_menu(callback.message, state, slot_num)
    await callback.answer()


@router.callback_query(F.data.startswith("fouls_kick_"))
async def edit_fouls_toggle_kick(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return

    slot_num = int(callback.data.split("_")[2])
    data = await state.get_data()
    slots = data.get("slots") or {}
    slots = {int(k): v for k, v in slots.items()}

    if slot_num not in slots:
        await callback.answer("Слот не найден!", show_alert=True)
        return

    current = slots[slot_num].get("kicked", False)
    new_val = not current
    slots[slot_num]["kicked"] = new_val

    if new_val:
        slots[slot_num]["alive"] = False
        slots[slot_num]["status_reason"] = "Удалён"
    else:
        tech_count = len(slots[slot_num].get("technical_fouls", []))
        if tech_count < 2:
            slots[slot_num]["alive"] = True
            slots[slot_num]["status_reason"] = "Жив"

    await save_slots(state, slots)
    await callback.answer(f"Удаление {'включено' if new_val else 'выключено'}")

    await refresh_fouls_menu(callback.message, state, slot_num)


@router.callback_query(F.data.startswith("fouls_small_"))
async def edit_fouls_small(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return

    slot_num = int(callback.data.split("_")[2])
    data = await state.get_data()
    slots = data.get("slots") or {}
    slots = {int(k): v for k, v in slots.items()}

    if slot_num not in slots:
        await callback.answer("Слот не найден!", show_alert=True)
        return

    tech_fouls = slots[slot_num].get("technical_fouls", [])
    tech_fouls.append("small")
    slots[slot_num]["technical_fouls"] = tech_fouls

    current_dc = slots[slot_num].get("dc_points", 0.0)
    slots[slot_num]["dc_points"] = round(current_dc - 0.3, 1)

    if len(tech_fouls) >= 2:
        slots[slot_num]["kicked"] = True
        slots[slot_num]["alive"] = False
        slots[slot_num]["status_reason"] = "Удалён (2 техфола)"
        await callback.answer("⚠️ Игрок удалён за 2 техфола! -0.3 к ДЦ", show_alert=True)
    else:
        await callback.answer("✅ Малый техфол добавлен (-0.3 к ДЦ)")

    await save_slots(state, slots)
    await refresh_fouls_menu(callback.message, state, slot_num)


@router.callback_query(F.data.startswith("fouls_big_"))
async def edit_fouls_big(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return

    slot_num = int(callback.data.split("_")[2])
    data = await state.get_data()
    slots = data.get("slots") or {}
    slots = {int(k): v for k, v in slots.items()}

    if slot_num not in slots:
        await callback.answer("Слот не найден!", show_alert=True)
        return

    tech_fouls = slots[slot_num].get("technical_fouls", [])
    tech_fouls.append("big")
    slots[slot_num]["technical_fouls"] = tech_fouls

    current_dc = slots[slot_num].get("dc_points", 0.0)
    slots[slot_num]["dc_points"] = round(current_dc - 0.6, 1)

    if len(tech_fouls) >= 2:
        slots[slot_num]["kicked"] = True
        slots[slot_num]["alive"] = False
        slots[slot_num]["status_reason"] = "Удалён (2 техфола)"
        await callback.answer("⚠️ Игрок удалён за 2 техфола! -0.6 к ДЦ", show_alert=True)
    else:
        await callback.answer("✅ Большой техфол добавлен (-0.6 к ДЦ)")

    await save_slots(state, slots)
    await refresh_fouls_menu(callback.message, state, slot_num)


@router.callback_query(F.data.startswith("fouls_dec_"))
async def edit_fouls_dec(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return

    slot_num = int(callback.data.split("_")[2])
    data = await state.get_data()
    slots = data.get("slots") or {}
    slots = {int(k): v for k, v in slots.items()}

    if slot_num not in slots:
        await callback.answer("Слот не найден!", show_alert=True)
        return

    tech_fouls = slots[slot_num].get("technical_fouls", [])
    if tech_fouls:
        removed = tech_fouls.pop()
        slots[slot_num]["technical_fouls"] = tech_fouls

        current_dc = slots[slot_num].get("dc_points", 0.0)
        if removed == "small":
            slots[slot_num]["dc_points"] = round(current_dc + 0.3, 1)
        elif removed == "big":
            slots[slot_num]["dc_points"] = round(current_dc + 0.6, 1)

        if len(tech_fouls) < 2 and slots[slot_num].get("kicked", False):
            slots[slot_num]["kicked"] = False
            slots[slot_num]["alive"] = True
            slots[slot_num]["status_reason"] = "Жив"

        await save_slots(state, slots)
        await callback.answer("✅ Техфол снят")
    else:
        await callback.answer("Нет техфолов для снятия", show_alert=True)

    await refresh_fouls_menu(callback.message, state, slot_num)