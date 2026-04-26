"""
Создание новой игры - раздача ролей
"""
import random
import asyncio
import json
from datetime import datetime, timedelta

from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode

import config
import database
import keyboards
from game.state import GameCreateState
from game.text import build_slots_text, build_game_state
from game.admin_actions.common import save_slots, clear_game_state, create_empty_slot, ensure_judge_pm, ensure_judge_cb

router = Router()


async def get_current_game_date() -> str:
    """
    Возвращает дату для текущей игры.
    Если вечер ещё не архивирован -> используем текущую пятницу.
    Если вечер уже архивирован -> используем следующую пятницу.
    """
    # Проверяем, архивирован ли текущий вечер
    is_archived = await database.get_setting("evening_archived") == "1"

    from handlers.booking import get_next_friday
    current_friday = get_next_friday()

    if is_archived:
        # Если вечер архивирован -> берём следующую пятницу
        now = datetime.utcnow()
        days_ahead = 4 - now.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        next_friday = (now + timedelta(days=days_ahead)).strftime("%d.%m.%Y")
        return next_friday
    else:
        return current_friday


async def show_players_list_for_game(message: types.Message, state: FSMContext, booked: list | None = None):
    """Показывает предварительный список всех 10 слотов + выбор судьи."""
    if booked is None:
        data = await state.get_data()
        booked = data.get("booked_players", []) or []

    judge_id = await database.get_current_game_judge_id()
    judge_name = await database.get_current_game_judge_name()

    # Получаем список всех игроков (включая тех, кто может быть судьёй)
    all_players = []
    for p in booked:
        if p and p[3] not in [None, "Свободно", ""]:
            all_players.append(p)

    lines = [f"📋 Предварительный состав игры (10 слотов):\n"]

    # Отображение судьи
    if judge_name:
        lines.append(f"⚖️ **Судья:** {judge_name}")
    else:
        lines.append(f"⚖️ **Судья:** не выбран")
    lines.append("")

    for slot_num in range(1, 11):
        if slot_num <= len(booked) and booked[slot_num - 1]:
            user_id, full_name, username, nickname, status = booked[slot_num - 1]
            name = nickname or full_name or f"Игрок {user_id}"
            lines.append(f"{slot_num}. ✅ {name}")
        else:
            lines.append(f"{slot_num}. ⬜ Свободно")

    real_players = len([p for p in booked if p and p[3] not in [None, "Свободно", ""] and p[1] not in ["Свободно"]])
    lines.append(f"\n👥 Заполнено слотов: {real_players}/10\n")
    lines.append("⚠️ Минимальное количество игроков: 4" if real_players < 4 else "✅ Можно начинать игру!")

    # Клавиатура с выбором судьи
    kb = keyboards.game_confirm_kb()

    # Добавляем кнопку выбора судьи, если есть игроки
    if all_players:
        # Создаём новую клавиатуру с дополнительной кнопкой
        builder = InlineKeyboardBuilder()
        builder.button(text="👨‍⚖️ Выбрать судью", callback_data="game_choose_judge")
        builder.button(text="✅ Подтвердить", callback_data="game_confirm_yes")
        builder.button(text="🔄 Перемешать", callback_data="game_confirm_no")
        builder.button(text="✏️ Редактировать", callback_data="game_confirm_edit")
        builder.adjust(1, 2, 1)
        kb = builder.as_markup()

    await message.answer("\n".join(lines), reply_markup=kb, parse_mode="Markdown")


@router.callback_query(F.data == "game_choose_judge")
async def choose_judge_start(callback: CallbackQuery, state: FSMContext):
    """Начало выбора судьи - показываем список игроков"""
    data = await state.get_data()
    booked = data.get("booked_players", []) or []

    # Собираем всех записанных игроков
    players = []
    for p in booked:
        if p and p[3] not in [None, "Свободно", ""] and p[1] not in ["Свободно"]:
            user_id, full_name, username, nickname, status = p
            name = nickname or full_name or f"Игрок {user_id}"
            players.append((user_id, name))

    if not players:
        await callback.answer("Нет игроков для выбора судьи!", show_alert=True)
        return

    # Строим клавиатуру выбора судьи
    builder = InlineKeyboardBuilder()
    for user_id, name in players:
        name_short = name[:20] + ".." if len(name) > 20 else name
        builder.button(text=f"👨‍⚖️ {name_short}", callback_data=f"game_set_judge:{user_id}")
    builder.button(text="❌ Отмена", callback_data="game_cancel_judge")
    builder.adjust(1)

    await callback.message.edit_text(
        "👨‍⚖️ **Выберите судью**\n\n"
        "Кто будет вести эту игру?\n\n"
        "⚠️ Если судья также будет играть, он автоматически исключается из игроков за столом.",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("game_set_judge:"))
async def set_judge(callback: CallbackQuery, state: FSMContext):
    """Устанавливает выбранного судью"""
    try:
        judge_id = int(callback.data.split(":")[1])
    except:
        await callback.answer("Некорректные данные", show_alert=True)
        return

    # Получаем данные пользователя
    user_info = await database.get_user_by_id(judge_id)
    if user_info:
        user_id, full_name, username, nickname = user_info
        judge_name = nickname or full_name or username or str(judge_id)
    else:
        judge_name = f"ID {judge_id}"

    # Сохраняем судью
    await database.set_current_game_judge_id(judge_id)
    await database.set_current_game_judge_name(judge_name)

    # Удаляем судью из списка игроков (если он там есть)
    data = await state.get_data()
    booked = data.get("booked_players", []) or []

    new_booked = []
    for p in booked:
        if p and p[0] == judge_id:
            continue  # пропускаем судью
        new_booked.append(p)

    await state.update_data(booked_players=new_booked)

    await callback.answer(f"✅ Судья выбран: {judge_name}")

    # Показываем обновлённый список
    await show_players_list_for_game(callback.message, state, new_booked)


@router.callback_query(F.data == "game_cancel_judge")
async def cancel_choose_judge(callback: CallbackQuery, state: FSMContext):
    """Отмена выбора судьи - возврат к списку"""
    data = await state.get_data()
    booked = data.get("booked_players", []) or []
    await show_players_list_for_game(callback.message, state, booked)
    await callback.answer()


@router.message(F.text == "🎲 Новая игра")
async def start_new_game(message: types.Message, state: FSMContext):
    if not await ensure_judge_pm(message):
        return

    if await database.get_setting("game_active") == "1":
        await message.answer("Уже есть активная игра. Сначала завершите её.", reply_markup=keyboards.game_admin_menu())
        return

    booked = await database.get_booked_players_for_game()
    if not booked:
        rm = keyboards.admin_menu() if message.from_user.id in config.ADMIN_IDS else keyboards.judge_menu()
        await message.answer("На вечер никто не записан.", reply_markup=rm)
        return

    # Сбрасываем судью (пока не выбран)
    await database.set_current_game_judge_id(None)
    await database.set_current_game_judge_name(None)

    await state.update_data(
        booked_players=booked,
        first_night_kill_recorded=False,
        night_kills_order=[],
        night_killed_slot=None,
        roles_assigned=False,
        winner_label=None,
        winning_team=None,
        nominated_list=[],
        vote_index=0,
        split_candidates=[],
        in_split=False,
        votes_received={},
        remaining_voters=0,
        protocol_chat_id=None,
        protocol_message_id=None,
    )

    await show_players_list_for_game(message, state, booked)


@router.callback_query(F.data == "game_confirm_yes")
async def confirm_game_players(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    booked = data.get("booked_players", []) or []
    judge_id = await database.get_current_game_judge_id()

    # Собираем игроков (судья уже исключён из списка на предыдущем этапе)
    real_players = []
    for p in booked:
        if not p:
            continue
        user_id, full_name, username, nickname, status = p
        if nickname not in [None, "Свободно", ""] and full_name not in ["Свободно"]:
            real_players.append(p)

    if len(real_players) < 4:
        await callback.message.edit_text(
            f"❌ **Недостаточно игроков!**\n\nЗаполнено слотов: {len(real_players)}/10\nДля игры нужно минимум 4 человека.",
            reply_markup=keyboards.game_confirm_kb()
        )
        await callback.answer()
        return

    # Проверяем, выбран ли судья
    judge_name = await database.get_current_game_judge_name()
    if not judge_name:
        # Предлагаем выбрать судью
        await callback.message.edit_text(
            "⚠️ **Судья не выбран!**\n\n"
            "Пожалуйста, выберите судью из списка игроков или нажмите «Пропустить», если судья будет назначен позже.\n\n"
            "⚖️ Судья не может одновременно играть за столом.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👨‍⚖️ Выбрать судью", callback_data="game_choose_judge")],
                [InlineKeyboardButton(text="⏩ Пропустить (назначить позже)", callback_data="game_confirm_skip_judge")],
            ])
        )
        await callback.answer()
        return

    slots = {}
    for i, (user_id, full_name, username, nickname, status) in enumerate(real_players, 1):
        slots[i] = create_empty_slot(nickname)
        slots[i].update({"user_id": user_id, "full_name": full_name, "username": username, "status": status})

    await state.update_data(slots=slots, booked_players=None)
    await save_slots(state, slots)
    await state.update_data(selected_mafia=[])
    await state.set_state(GameCreateState.choosing_mafia)

    await show_players_for_role_selection(callback.message, state, "mafia", 2)
    await callback.answer()


@router.callback_query(F.data == "game_confirm_skip_judge")
async def confirm_skip_judge(callback: CallbackQuery, state: FSMContext):
    """Пропустить выбор судьи (судья будет назначен позже)"""
    data = await state.get_data()
    booked = data.get("booked_players", []) or []

    real_players = []
    for p in booked:
        if not p:
            continue
        user_id, full_name, username, nickname, status = p
        if nickname not in [None, "Свободно", ""] and full_name not in ["Свободно"]:
            real_players.append(p)

    slots = {}
    for i, (user_id, full_name, username, nickname, status) in enumerate(real_players, 1):
        slots[i] = create_empty_slot(nickname)
        slots[i].update({"user_id": user_id, "full_name": full_name, "username": username, "status": status})

    await state.update_data(slots=slots, booked_players=None)
    await save_slots(state, slots)
    await state.update_data(selected_mafia=[])
    await state.set_state(GameCreateState.choosing_mafia)

    await show_players_for_role_selection(callback.message, state, "mafia", 2)
    await callback.answer()


@router.callback_query(F.data == "game_confirm_no")
async def reshuffle_players(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    booked = data.get("booked_players", []) or []
    if booked:
        random.shuffle(booked)
        await state.update_data(booked_players=booked)
    await show_players_list_for_game(callback.message, state, booked)
    await callback.answer("🔀 Игроки перемешаны!")


@router.callback_query(F.data == "game_confirm_edit")
async def edit_players_list(callback: CallbackQuery, state: FSMContext):
    await show_current_players_list(callback.message, state)
    await state.set_state(GameCreateState.editing_players_list)
    await callback.answer()


@router.callback_query(F.data == "edit_players_done")
async def edit_players_done(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    booked = data.get("booked_players", []) or []
    try:
        await callback.message.delete()
    except Exception:
        pass
    await show_players_list_for_game(callback.message, state, booked)
    await state.set_state(GameCreateState.editing_slots)
    await callback.answer()


async def show_current_players_list(message: types.Message, state: FSMContext):
    data = await state.get_data()
    booked = data.get("booked_players", []) or []
    players_text = "📋 **Текущий состав (10 слотов):**\n\n"

    for slot_num in range(1, 11):
        if slot_num <= len(booked) and booked[slot_num - 1]:
            user_id, full_name, username, nickname, status = booked[slot_num - 1]
            name = nickname or full_name or f"Игрок {user_id}"
            name = name[:17] + "..." if len(name) > 20 else name
            players_text += f"{slot_num}. {name}\n"
        else:
            players_text += f"{slot_num}. ⬜ Свободно\n"

    real_players = len([p for p in booked if p and p[3] not in [None, "Свободно", ""] and p[1] not in ["Свободно"]])
    players_text += f"\n✏️ **Заполнено: {real_players}/10**\n\n"
    players_text += "**Команды:**\n• `<номер> <ник>` — заполнить слот\n• `очистить <номер>` — очистить слот\n\nКогда закончите редактирование — нажмите кнопку **Готово**"

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Готово", callback_data="edit_players_done")
    builder.adjust(1)
    await message.answer(players_text, reply_markup=builder.as_markup(), parse_mode="Markdown")


async def show_players_for_role_selection(message: types.Message, state: FSMContext, role_key: str, count: int):
    data = await state.get_data()
    slots = data.get("slots") or {}
    judge_name = await database.get_current_game_judge_name()

    available = []
    for slot_num, info in slots.items():
        if info.get("alive", True) and info.get("role") == "Не задана":
            name = info.get("nickname") or info.get("full_name") or f"Слот {slot_num}"
            available.append((slot_num, name))

    if len(available) < count:
        await message.answer(f"❌ Недостаточно свободных игроков для выбора {count} {role_key}.")
        return

    role_names = {"mafia": "мафий", "don": "дона", "sheriff": "шерифа"}
    role_name = role_names.get(role_key, role_key)
    lines = [f"🎭 Выберите {count} {role_name}\n"]
    if judge_name:
        lines.append(f"\n⚖️ Судья: {judge_name}\n")
    for slot_num, name in available:
        lines.append(f"• Слот {slot_num}: {name}")
    lines.append("\nНажмите на игрока, чтобы выбрать.")

    await message.answer("\n".join(lines), reply_markup=keyboards.players_selection_kb(available, role_key, count),
                         parse_mode="Markdown")


@router.callback_query(F.data.startswith("select_mafia_"))
async def select_mafia_callback(callback: CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return
    slot_num = int(callback.data.split("_")[2])
    data = await state.get_data()
    selected = data.get("selected_mafia", [])

    if slot_num in selected:
        selected.remove(slot_num)
        action_text = f"❌ Игрок {slot_num} убран из мафии"
    else:
        if len(selected) >= 2:
            await callback.answer("Уже выбрано 2 мафии!", show_alert=True)
            return
        selected.append(slot_num)
        action_text = f"✅ Игрок {slot_num} добавлен в мафию"

    await state.update_data(selected_mafia=selected)
    slots = data.get("slots") or {}
    available = []
    for s_num, info in slots.items():
        if info.get("alive", True) and info.get("role") == "Не задана":
            name = info.get("nickname") or info.get("full_name") or f"Слот {s_num}"
            available.append((s_num, name))

    new_markup = keyboards.players_selection_kb(available, "mafia", 2, selected)
    try:
        await callback.message.edit_reply_markup(reply_markup=new_markup)
    except Exception as e:
        if "message is not modified" not in str(e):
            print(f"[ERROR] {e}")

    await callback.answer(action_text)

    if len(selected) == 2:
        slots = data.get("slots") or {}
        for m in selected:
            if m in slots:
                slots[m]["role"] = "Мафия"
                slots[m]["team"] = "Чёрные"
        await state.update_data(slots=slots, selected_mafia=None)
        await state.set_state(GameCreateState.choosing_don)
        await show_players_for_role_selection(callback.message, state, "don", 1)


@router.callback_query(F.data.startswith("select_don_"))
async def select_don_callback(callback: CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return
    slot_num = int(callback.data.split("_")[2])
    data = await state.get_data()
    slots = data.get("slots") or {}
    if slot_num in slots:
        slots[slot_num]["role"] = "Дон"
        slots[slot_num]["team"] = "Чёрные"
    await state.update_data(slots=slots)
    await save_slots(state, slots)
    await state.set_state(GameCreateState.choosing_sheriff)
    await callback.answer(f"✅ Дон назначен на слот {slot_num}")
    await show_players_for_role_selection(callback.message, state, "sheriff", 1)


@router.callback_query(F.data.startswith("select_sheriff_"))
async def select_sheriff_callback(callback: CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        return
    slot_num = int(callback.data.split("_")[2])
    data = await state.get_data()
    slots = data.get("slots") or {}
    if slot_num in slots:
        slots[slot_num]["role"] = "Шериф"
        slots[slot_num]["team"] = "Красные"

    for s_num, info in slots.items():
        if info.get("role") == "Не задана" and info.get("alive", True):
            info["role"] = "Мирный"
            info["team"] = "Красные"

    await state.update_data(slots=slots, roles_assigned=True)
    await save_slots(state, slots)

    # ========== ПОЛУЧАЕМ ДАТУ ИГРЫ ==========
    game_date = await get_current_game_date()
    await database.set_current_game_date(game_date)
    # Сбрасываем флаг архивации (начало нового вечера)
    await database.set_setting("evening_archived", "0")
    # ========================================

    evening_games = await database.get_games_by_date(game_date)
    evening_num = len(evening_games) + 1
    await database.set_current_game_number(evening_num)
    total_games = await database.get_total_games_count()
    global_num = total_games + 1
    await database.set_current_global_game_number(global_num)
    await database.set_setting("game_active", "1")

    try:
        await callback.message.delete()
    except Exception:
        pass

    judge_name = await database.get_current_game_judge_name()
    await callback.message.answer(
        f"✅ **Игра создана!**\n\n🎲 Игра №{evening_num} ({game_date}): №{global_num} по общей истории\n\n"
        f"⚖️ **Судья:** {judge_name if judge_name else 'Не назначен'}\n\n"
        f"{build_slots_text(slots, judge_name=judge_name)}",
        reply_markup=keyboards.game_admin_menu(),
        parse_mode="Markdown"
    )

    # ========== ОТКРЫТИЕ СТАВОК ==========
    # Получаем ID созданной игры
    async with database.get_db() as conn:
        async with conn.execute("SELECT id FROM game_history ORDER BY id DESC LIMIT 1") as cur:
            row = await cur.fetchone()
            if row:
                game_id = row[0]
                await open_bets_for_game(callback.message, state, game_id, evening_num)
    # ===================================

    await state.set_state(GameCreateState.editing_slots)
    await callback.answer("✅ Игра готова к старту!")


# ========== РЕДАКТИРОВАНИЕ СПИСКА ИГРОКОВ ==========

@router.message(GameCreateState.editing_players_list, F.text.regexp(r"^\d+\s+"))
async def edit_player_by_number(message: types.Message, state: FSMContext):
    """
    Редактирование списка игроков по номеру слота.
    Доступно только для судей/админов.
    """
    if not await ensure_judge_pm(message):
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❌ Формат: `<номер> <ник>`\nПример: `7 Вепрь`")
        return

    try:
        slot_num = int(parts[0])
    except ValueError:
        await message.answer("❌ Номер должен быть числом.")
        return

    if slot_num < 1 or slot_num > 10:
        await message.answer("❌ Номер слота от 1 до 10.")
        return

    new_nick = parts[1].strip()
    if not new_nick:
        await message.answer("❌ Ник не может быть пустым.")
        return

    data = await state.get_data()
    booked = data.get("booked_players", []) or []

    user_data = await database.get_user_by_nickname(new_nick)

    while len(booked) < slot_num:
        booked.append(
            (-(len(booked) + 1), "Свободно", None, "Свободно", "Пусто")
        )

    old_name = booked[slot_num - 1][3] or booked[slot_num - 1][1]

    if user_data:
        user_id, full_name, username, nickname = user_data
        booked[slot_num - 1] = (
            user_id,
            full_name,
            username,
            nickname,
            "Добавлен вручную",
        )
        await state.update_data(booked_players=booked)
        await message.answer(
            f"✅ Слот {slot_num}: {old_name} → {nickname} (найден в БД)"
        )
    else:
        booked[slot_num - 1] = (
            -slot_num,
            new_nick,
            None,
            new_nick,
            "Добавлен вручную",
        )
        await state.update_data(booked_players=booked)
        await message.answer(
            f"⚠️ Слот {slot_num}: {old_name} → {new_nick} (не найден в БД, статистика не сохранится)"
        )

    await show_current_players_list(message, state)


# ========== СТАВКИ ==========

async def send_bet_offer_to_user(bot: Bot, user_id: int, game_id: int, game_number: int,
                                 red_players: list, black_players: list,
                                 red_avg_elo: float, black_avg_elo: float):
    """Отправляет одному пользователю предложение сделать ставку"""
    # Рассчитываем коэффициенты
    red_prob = 1 / (1 + 10 ** ((black_avg_elo - red_avg_elo) / 400))
    black_prob = 1 - red_prob

    red_coef = round(1 / red_prob, 2) if red_prob > 0 else 2.0
    black_coef = round(1 / black_prob, 2) if black_prob > 0 else 2.0

    # Формируем текст
    red_names = ", ".join([p.get("nickname", f"Игрок {p['slot_num']}") for p in red_players[:5]])
    if len(red_players) > 5:
        red_names += f" и ещё {len(red_players) - 5}"

    black_names = ", ".join([p.get("nickname", f"Игрок {p['slot_num']}") for p in black_players[:5]])
    if len(black_players) > 5:
        black_names += f" и ещё {len(black_players) - 5}"

    text = (
        f"📊 **СТАВКИ НА ИГРУ #{game_number}**\n\n"
        f"🔴 **КРАСНЫЕ** (ср.Эло {red_avg_elo:.0f}):\n"
        f"   {red_names}\n\n"
        f"⚫ **ЧЁРНЫЕ** (ср.Эло {black_avg_elo:.0f}):\n"
        f"   {black_names}\n\n"
        f"📈 **КОЭФФИЦИЕНТЫ:**\n"
        f"   🔴 На красных: {red_coef}\n"
        f"   ⚫ На чёрных: {black_coef}\n\n"
        f"💰 Минимальная ставка: 50 жетонов\n"
        f"💡 Выигрыш = ставка × коэффициент\n\n"
        f"Сделайте ставку (ставки принимаются до окончания игры):"
    )

    # Клавиатура для ставок
    builder = InlineKeyboardBuilder()
    builder.button(text=f"🔴 Поставить на красных (x{red_coef})", callback_data=f"bet_red:{game_id}")
    builder.button(text=f"⚫ Поставить на чёрных (x{black_coef})", callback_data=f"bet_black:{game_id}")
    builder.button(text="❌ Пропустить", callback_data=f"bet_skip:{game_id}")
    builder.adjust(1)

    try:
        await bot.send_message(user_id, text, reply_markup=builder.as_markup(), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        print(f"[BETS] Failed to send to {user_id}: {e}")


async def open_bets_for_game(message: types.Message, state: FSMContext, game_id: int, game_number: int):
    """Открывает ставки на игру и рассылает предложения всем не играющим"""
    data = await state.get_data()
    slots = data.get("slots") or {}

    # Получаем игроков и их Эло
    red_players = []
    black_players = []
    red_elos = []
    black_elos = []

    for slot_num, slot in slots.items():
        if slot.get("user_id") and slot.get("user_id") > 0:
            team = slot.get("team")
            elo = await database.get_elo(slot["user_id"])
            if team == "Красные":
                red_players.append({"user_id": slot["user_id"], "nickname": slot.get("nickname"), "slot_num": slot_num})
                red_elos.append(elo)
            elif team == "Чёрные":
                black_players.append(
                    {"user_id": slot["user_id"], "nickname": slot.get("nickname"), "slot_num": slot_num})
                black_elos.append(elo)

    # Сохраняем состав игры для ставок
    await database.set_setting(f"bet_game_{game_id}_red", json.dumps(red_players))
    await database.set_setting(f"bet_game_{game_id}_black", json.dumps(black_players))

    # Создаём запись о ставках
    bet_id = await database.create_bet(game_id, game_number, await database.get_current_game_date(),
                                       message.from_user.id)
    await state.update_data(current_bet_id=bet_id)

    # Получаем всех пользователей
    async with database.get_db() as conn:
        async with conn.execute("SELECT user_id FROM users") as cur:
            all_users = [row[0] for row in await cur.fetchall()]

    # Исключаем игроков
    players_in_game = [p["user_id"] for p in red_players + black_players]
    spectators = [uid for uid in all_users if uid not in players_in_game and uid > 0]

    # Рассылаем предложения
    red_avg = sum(red_elos) / len(red_elos) if red_elos else 1500
    black_avg = sum(black_elos) / len(black_elos) if black_elos else 1500

    bot = message.bot

    sent = 0
    for user_id in spectators:
        await send_bet_offer_to_user(bot, user_id, game_id, game_number, red_players, black_players, red_avg, black_avg)
        sent += 1
        await asyncio.sleep(0.05)

    await message.answer(f"📊 Ставки открыты! Предложения отправлены {sent} зрителям.")


@router.message(GameCreateState.editing_players_list, F.text.regexp(r"^очистить\s+\d+"))
async def clear_player_by_number(message: types.Message, state: FSMContext):
    """
    Очистка слота по номеру.
    Доступно только для судей/админов.
    """
    if not await ensure_judge_pm(message):
        return

    try:
        slot_num = int(message.text.replace("очистить", "").strip())
    except ValueError:
        await message.answer(
            "❌ Формат: `очистить <номер>`\nПример: `очистить 7`"
        )
        return

    if slot_num < 1 or slot_num > 10:
        await message.answer("❌ Номер слота от 1 до 10.")
        return

    data = await state.get_data()
    booked = data.get("booked_players", []) or []

    if slot_num <= len(booked):
        booked[slot_num - 1] = (
            -slot_num,
            "Свободно",
            None,
            "Свободно",
            "Пусто",
        )
        await state.update_data(booked_players=booked)
        await message.answer(f"✅ Слот {slot_num} очищен")
    else:
        await message.answer(f"❌ Слот {slot_num} уже пуст")

    await show_current_players_list(message, state)