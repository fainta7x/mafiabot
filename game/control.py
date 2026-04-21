import random
from datetime import datetime

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode
from aiogram.types import FSInputFile, CallbackQuery  # ← ДОБАВИЛИ CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
import database
import keyboards
from .state import GameCreateState
from .text import build_slots_text, build_game_state, build_protocol_text
from .pic_endgame import create_endgame_pic_summary

# ========== ПРОВЕРКИ ПРАВ СУДЬИ ДЛЯ ИГРОВЫХ ХЕНДЛЕРОВ ==========

async def _is_judge(user_id: int) -> bool:
    """
    Пользователь имеет право вести игры, если:
    - он в списке game_judges в БД,
    - или он в ADMIN_IDS (из config).
    """
    if user_id in config.ADMIN_IDS:
        return True

    judges = await database.get_game_judges()
    return user_id in judges


async def ensure_judge_cb(callback: CallbackQuery) -> bool:
    """
    Проверка: callback от судьи (или админа).
    Если нет прав — показываем алерт и возвращаем False.
    """
    user_id = callback.from_user.id

    if not await _is_judge(user_id):
        await callback.answer("❌ У вас нет прав судьи.", show_alert=True)
        return False

    # Если хочешь ограничить управление только личкой — оставляем эту проверку.
    # Если можно и в группе, можно эту часть убрать.
    if callback.message.chat.type != "private":
        await callback.answer("⚠️ Управление игрой доступно только в личке с ботом.", show_alert=True)
        return False

    return True

router = Router()


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ПРАВ ДОСТУПА ==========

def is_admin_pm(message: types.Message) -> bool:
    """
    Синхронная проверка:
    - сообщение из лички
    - пользователь в ADMIN_IDS.
    """
    if not message.from_user or message.chat.type != "private":
        return False
    return message.from_user.id in config.ADMIN_IDS


async def ensure_admin_pm(message: types.Message) -> bool:
    """
    Строгая админ-проверка:
    доступ ТОЛЬКО для супер-админов (ADMIN_IDS).
    Используется для анонсов, счетов, истории, должников и т.п.
    """
    if not message.from_user or message.chat.type != "private":
        return False
    user_id = message.from_user.id
    return user_id in config.ADMIN_IDS


async def ensure_judge_pm(message: types.Message) -> bool:
    """
    Проверка прав ведущего игры:
    - личка
    - либо супер-админ (ADMIN_IDS)
    - либо судья из БД (game_judges).
    ЭТИМ пользуемся во всех игровых хендлерах: новая игра, продолжить, фолы, ППК, кик и т.п.
    """
    if not message.from_user or message.chat.type != "private":
        return False

    user_id = message.from_user.id

    # Супер-админ всегда имеет доступ
    if user_id in config.ADMIN_IDS:
        return True

    # Судья из настроек БД
    if await database.is_game_judge(user_id):
        return True

    # Здесь можно при желании отвечать сообщением о нехватке прав
    # await message.answer("❌ У вас нет прав судьи для управления игрой.")
    return False


# ========== ПРОЧИЕ УТИЛИТЫ ==========

def parse_slot_num(raw: str, min_slot: int = 1, max_slot: int = 10) -> tuple[bool, int | None, str | None]:
    text = (raw or "").strip()
    if not text.isdigit():
        return False, None, f"Нужно ввести номер слота (число от {min_slot} до {max_slot})."
    num = int(text)
    if num < min_slot or num > max_slot:
        return False, None, f"Номер слота должен быть от {min_slot} до {max_slot}."
    return True, num, None


async def get_slots(message: types.Message, state: FSMContext, allow_empty: bool = False) -> dict:
    """
    Возвращает слоты из FSM-состояния.
    Если слотов нет и allow_empty=False — пишет сообщение и возвращает {}.
    """
    data = await state.get_data()
    slots = data.get("slots") or {}

    if not slots and not allow_empty:
        await message.answer(
            "Слоты пустые. Нажмите «🎲 Новая игра», чтобы начать новую партию.",
            reply_markup=keyboards.game_admin_menu()
        )

    return slots


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


async def save_slots(state: FSMContext, slots: dict):
    """Сохраняет слоты и метаданные в состояние и БД."""
    # Убеждаемся, что ключи — целые числа
    slots_int = {int(k): v for k, v in slots.items()}
    await state.update_data(slots=slots_int)

    # Сохраняем метаданные вместе со слотами
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


async def show_game_state_all(message: types.Message, state: FSMContext):
    """Показывает текущее состояние игры (для ведущего)."""
    data = await state.get_data()
    slots = data.get("slots") or {}
    print(f"[DIAG] show_game_state_all: slots keys = {list(slots.keys())}")
    if 6 in slots:
        print(f"[DIAG] Слот 6: alive={slots[6].get('alive')}")
    if slots:
        judge_name = await database.get_current_game_judge_name()
        await message.answer(
            build_game_state(slots, alive_only=False, judge_name=judge_name),
            reply_markup=keyboards.game_admin_menu()
        )


# ========== 1. НОВАЯ ИГРА (ИНТЕРАКТИВНАЯ) ==========

async def show_players_list_for_game(
    message: types.Message,
    state: FSMContext,
    booked: list | None = None
):
    """Показывает предварительный список всех 10 слотов + судью."""
    if booked is None:
        data = await state.get_data()
        booked = data.get("booked_players", []) or []

    # Берём судью из БД
    judge_name = await database.get_current_game_judge_name()

    lines: list[str] = []

    header = "📋 Предварительный состав игры (10 слотов):\n"
    if judge_name:
        header = header + f"\nСудья: {judge_name}\n"
    lines.append(header)

    lines.append("")
    for slot_num in range(1, 11):
        if slot_num <= len(booked) and booked[slot_num - 1]:
            user_id, full_name, username, nickname, status = booked[slot_num - 1]
            name = nickname or full_name or f"Игрок {user_id}"
            lines.append(f"{slot_num}. ✅ {name}")
        else:
            lines.append(f"{slot_num}. ⬜ Свободно")

    real_players = len(
        [
            p for p in booked
            if p
            and p[3] not in [None, "Свободно", ""]
            and p[1] not in ["Свободно"]
        ]
    )

    lines.append("")
    lines.append(f"👥 Заполнено слотов: {real_players}/10")
    lines.append("")
    if real_players < 4:
        lines.append("⚠️ Минимальное количество игроков: 4")
    else:
        lines.append("✅ Можно начинать игру!")

    lines.append("")
    lines.append("Подтвердите состав или отредактируйте слоты.")

    text = "\n".join(lines)

    await message.answer(
        text,
        reply_markup=keyboards.game_confirm_kb(),
        parse_mode="Markdown"
    )


async def show_current_players_list(message: types.Message, state: FSMContext):
    """Показывает текущий список слотов с инлайн-кнопкой Готово."""
    data = await state.get_data()
    booked = data.get("booked_players", []) or []

    players_text = "📋 **Текущий состав (10 слотов):**\n\n"

    for slot_num in range(1, 11):
        if slot_num <= len(booked) and booked[slot_num - 1]:
            user_id, full_name, username, nickname, status = booked[slot_num - 1]
            name = nickname or full_name or f"Игрок {user_id}"
            if len(name) > 20:
                name = name[:17] + "..."
            players_text += f"{slot_num}. {name}\n"
        else:
            players_text += f"{slot_num}. ⬜ Свободно\n"

    real_players = len(
        [
            p for p in booked
            if p
            and p[3] not in [None, "Свободно", ""]
            and p[1] not in ["Свободно"]
        ]
    )

    players_text += f"\n✏️ **Заполнено: {real_players}/10**\n\n"
    players_text += "**Команды:**\n"
    players_text += "• `<номер> <ник>` — заполнить слот\n"
    players_text += "• `очистить <номер>` — очистить слот\n\n"
    players_text += "Когда закончите редактирование — нажмите кнопку **Готово**"

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Готово", callback_data="edit_players_done")
    builder.adjust(1)

    await message.answer(
        players_text,
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )


@router.message(F.text == "🎲 Новая игра")
async def start_new_game(message: types.Message, state: FSMContext):
    """
    Создание новой игры.
    Доступно и админам, и судьям (ensure_judge_pm).
    """
    if not await ensure_judge_pm(message):
        return

    if await database.get_setting("game_active") == "1":
        await message.answer(
            "Уже есть активная игра. Сначала завершите её.",
            reply_markup=keyboards.game_admin_menu()
        )
        return

    booked = await database.get_booked_players_for_game()
    if not booked:
        # Админу покажем админ-меню, судье — меню судьи
        if message.from_user.id in config.ADMIN_IDS:
            rm = keyboards.admin_menu()
        else:
            rm = keyboards.judge_menu()
        await message.answer(
            "На вечер никто не записан.",
            reply_markup=rm
        )
        return

    # Сохраняем Судью текущей игры
    judge_id = message.from_user.id

    # Пытаемся взять ник Судьи из БД
    db_user = await database.get_user_by_id(judge_id)
    if db_user:
        _, full_name, username, nickname = db_user
        judge_name = nickname or full_name or username or str(judge_id)
    else:
        # Фоллбек, если в users ещё нет записи
        judge_name = (
            message.from_user.username
            or message.from_user.full_name
            or str(judge_id)
        )

    await database.set_current_game_judge_id(judge_id)
    await database.set_current_game_judge_name(judge_name)

    # Убираем Судью из записанных игроков, если он там есть
    # booked: (user_id, full_name, username, nickname, status)
    booked = [p for p in booked if not (p and p[0] == judge_id)]

    # Сохраняем список записанных игроков
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
async def confirm_game_players(callback: types.CallbackQuery, state: FSMContext):
    """Подтверждение состава игроков и переход к раздаче ролей."""
    data = await state.get_data()
    booked = data.get("booked_players", []) or []

    # Узнаём Судью, чтобы точно не посадить его за стол
    judge_id = await database.get_current_game_judge_id()

    real_players = []
    for p in booked:
        if not p:
            continue
        user_id, full_name, username, nickname, status = p

        # пропускаем Судью
        if judge_id and user_id == judge_id:
            continue

        # логика "реальный игрок"
        if nickname not in [None, "Свободно", ""] and full_name not in ["Свободно"]:
            real_players.append(p)

    if len(real_players) < 4:
        await callback.message.edit_text(
            "❌ **Недостаточно игроков!**\n\n"
            f"Заполнено слотов: {len(real_players)}/10\n"
            "Для игры нужно минимум 4 человека.\n\n"
            "Заполните слоты командой `<номер> <ник>`",
            reply_markup=keyboards.game_confirm_kb()
        )
        await callback.answer()
        return

    random.shuffle(real_players)
    slots = {}
    for i, (user_id, full_name, username, nickname, status) in enumerate(real_players, 1):
        slots[i] = create_empty_slot(nickname)
        slots[i].update(
            {
                "user_id": user_id,
                "full_name": full_name,
                "username": username,
                "status": status,
            }
        )

    await state.update_data(slots=slots, booked_players=None)
    await save_slots(state, slots)
    await state.update_data(selected_mafia=[])
    await state.set_state(GameCreateState.choosing_mafia)

    await show_players_for_role_selection(callback.message, state, "mafia", 2)
    await callback.answer()


@router.callback_query(F.data == "game_confirm_no")
async def reshuffle_players(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    booked = data.get("booked_players", []) or []

    if booked:
        random.shuffle(booked)
        await state.update_data(booked_players=booked)

    await show_players_list_for_game(callback.message, state, booked)
    await callback.answer("🔀 Игроки перемешаны!")


@router.callback_query(F.data == "game_confirm_edit")
async def edit_players_list(callback: types.CallbackQuery, state: FSMContext):
    await show_current_players_list(callback.message, state)
    await state.set_state(GameCreateState.editing_players_list)
    await callback.answer()


@router.callback_query(F.data == "edit_players_done")
async def edit_players_done(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    booked = data.get("booked_players", []) or []

    try:
        await callback.message.delete()
    except Exception:
        pass

    await show_players_list_for_game(callback.message, state, booked)
    await state.set_state(GameCreateState.editing_slots)
    await callback.answer()


@router.message(GameCreateState.editing_players_list, F.text.regexp(r"^\d+\s+"))
async def edit_player_by_number(message: types.Message, state: FSMContext):
    """
    Редактирование списка игроков по номеру слота.
    Это чисто игровая функция, поэтому доступна и админам, и судьям.
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


@router.message(GameCreateState.editing_players_list, F.text.regexp(r"^очистить\s+\d+"))
async def clear_player_by_number(message: types.Message, state: FSMContext):
    if not await ensure_admin_pm(message):
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


# ========== 2. РАЗДАЧА РОЛЕЙ ==========
async def show_players_for_role_selection(
    message: types.Message,
    state: FSMContext,
    role_key: str,
    count: int,
):
    data = await state.get_data()
    slots = data.get("slots") or {}

    # Берём судью
    judge_name = await database.get_current_game_judge_name()

    available = []
    for slot_num, info in slots.items():
        if info.get("alive", True) and info.get("role") == "Не задана":
            name = (
                info.get("nickname")
                or info.get("full_name")
                or f"Слот {slot_num}"
            )
            available.append((slot_num, name))

    if len(available) < count:
        await message.answer(
            f"❌ Недостаточно свободных игроков для выбора {count} {role_key}."
        )
        return

    role_names = {"mafia": "мафий", "don": "дона", "sheriff": "шерифа"}
    role_name = role_names.get(role_key, role_key)

    lines: list[str] = []

    title = f"🎭 Выберите {count} {role_name}\n"
    if judge_name:
        title = title + f"\nСудья: {judge_name}\n"
    lines.append(title)

    for slot_num, name in available:
        lines.append(f"• Слот {slot_num}: {name}")

    lines.append("")
    lines.append("Нажмите на игрока, чтобы выбрать.")

    text = "\n".join(lines)

    await message.answer(
        text,
        reply_markup=keyboards.players_selection_kb(
            available, role_key, count
        ),
        parse_mode="Markdown",
    )


@router.callback_query(F.data.startswith("select_mafia_"))
async def select_mafia_callback(callback: types.CallbackQuery, state: FSMContext):
    # Проверка: админ или судья
    if not await ensure_judge_cb(callback):
        await callback.answer("Недостаточно прав судьи.", show_alert=True)
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
            name = (
                info.get("nickname")
                or info.get("full_name")
                or f"Слот {s_num}"
            )
            available.append((s_num, name))

    new_markup = keyboards.players_selection_kb(available, "mafia", 2, selected)

    try:
        await callback.message.edit_reply_markup(reply_markup=new_markup)
    except Exception as e:
        if "message is not modified" not in str(e):
            print(f"[ERROR] edit_reply_markup failed: {e}")

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
async def select_don_callback(callback: types.CallbackQuery, state: FSMContext):
    # Проверка: админ или судья
    if not await ensure_judge_cb(callback):
        await callback.answer("Недостаточно прав судьи.", show_alert=True)
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
async def select_sheriff_callback(callback: types.CallbackQuery, state: FSMContext):
    # Проверка: админ или судья
    if not await ensure_judge_cb(callback):
        await callback.answer("Недостаточно прав судьи.", show_alert=True)
        return

    slot_num = int(callback.data.split("_")[2])

    data = await state.get_data()
    slots = data.get("slots") or {}

    if slot_num in slots:
        slots[slot_num]["role"] = "Шериф"
        slots[slot_num]["team"] = "Красные"

    # всем оставшимся живым — Мирный, Красные
    for s_num, info in slots.items():
        if info.get("role") == "Не задана" and info.get("alive", True):
            info["role"] = "Мирный"
            info["team"] = "Красные"

    await state.update_data(slots=slots, roles_assigned=True)
    await save_slots(state, slots)

    game_date = datetime.now().strftime("%d.%m.%Y")
    await database.set_current_game_date(game_date)

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
        f"✅ **Игра создана!**\n\n"
        f"🎲 Игра №{evening_num} ({game_date}): №{global_num} по общей истории\n\n"
        f"{build_slots_text(slots, judge_name=judge_name)}",
        reply_markup=keyboards.game_admin_menu(),
        parse_mode="Markdown"
    )

    await state.set_state(GameCreateState.editing_slots)
    await callback.answer("✅ Игра готова к старту!")


# ========== 4. ПРОДОЛЖИТЬ ИГРУ ==========
@router.message(F.text == "♻️ Продолжить игру")
async def resume_game(message: types.Message, state: FSMContext):
    # Уже ОК: админ или судья
    if not await ensure_judge_pm(message):
        return

    if await database.get_setting("game_active") != "1":
        # здесь логично тоже развести меню админ/судья
        if message.from_user.id in config.ADMIN_IDS:
            rm = keyboards.admin_menu()
        else:
            rm = keyboards.judge_menu()
        await message.answer(
            "Нет активной сохранённой игры.", reply_markup=rm
        )
        return

    slots = await database.load_current_game_slots()
    metadata = await database.load_current_game_metadata()

    if not slots:
        if message.from_user.id in config.ADMIN_IDS:
            rm = keyboards.admin_menu()
        else:
            rm = keyboards.judge_menu()
        await message.answer(
            "Не удалось найти сохранённые слоты.",
            reply_markup=rm,
        )
        return

    await state.set_state(GameCreateState.editing_slots)
    await state.update_data(
        slots=slots,
        roles_assigned=metadata.get("roles_assigned", False),
        nominated_list=[],
        vote_index=0,
        split_candidates=[],
        in_split=False,
        first_night_kill_recorded=metadata.get("first_night_kill_recorded", False),
        night_kills_order=metadata.get("night_kills_order", []),
        night_killed_slot=None,
        winner_label=metadata.get("winner_label"),
        winning_team=metadata.get("winning_team"),
        protocol_chat_id=None,
        protocol_message_id=None,
    )

    await message.answer(
        f"Продолжаем незавершённую игру.\n\n"
        f"{build_game_state(slots, alive_only=False)}",
        reply_markup=keyboards.game_admin_menu(),
    )


# ========== 5. ПОКАЗ СОСТОЯНИЯ ==========
@router.message(GameCreateState.editing_slots, F.text == "⏹ Остановить")
async def ask_game_finish_reason(message: types.Message, state: FSMContext):
    # Остановка игры — это всё ещё игровое действие → судья тоже может
    if not await ensure_judge_pm(message):
        return

    await message.answer(
        "⚠️ **Остановка игры**\n\nВыберите результат:",
        reply_markup=keyboards.game_finish_keyboard(),
    )


@router.message(GameCreateState.editing_slots, F.text.casefold() == "игра")
async def show_game_state_all_handler(message: types.Message, state: FSMContext):
    if not await ensure_judge_pm(message):
        return

    await show_game_state_all(message, state)


@router.message(GameCreateState.editing_slots, F.text.casefold() == "игра живые")
async def show_game_state_alive(message: types.Message, state: FSMContext):
    if not await ensure_judge_pm(message):
        return

    slots = await get_slots(message, state)
    if slots:
        await message.answer(
            build_game_state(slots, alive_only=True),
            reply_markup=keyboards.game_admin_menu(),
        )


@router.message(GameCreateState.editing_slots, F.text.casefold() == "ок")
async def ok_show_state(message: types.Message, state: FSMContext):
    if not await ensure_judge_pm(message):
        return

    await show_game_state_all(message, state)


# ========== 6. ЗАВЕРШЕНИЕ ИГРЫ И РЕДАКТОР БАЛЛОВ ==========
@router.callback_query(F.data.startswith("game_end:"))
async def handle_game_finish(callback: types.CallbackQuery, state: FSMContext):
    # раньше было только ADMIN_IDS — делаем админ или судья
    if not await ensure_judge_cb(callback):
        await callback.answer("Недостаточно прав судьи.", show_alert=True)
        return

    data = await state.get_data()
    slots = data.get("slots") or {}
    action = callback.data.split(":", 1)[1]

    if action == "cancel":
        await clear_game_state(state)
        await callback.message.edit_text("❌ **Игра отменена**\n\nИгра полностью удалена без сохранения.")
        # здесь логичнее вернуть в меню в зависимости от роли, но
        # если функция используется только админами, можно оставить admin_menu
        await callback.message.answer("🛠 Админ-панель", reply_markup=keyboards.admin_menu())
        await callback.answer()
        return

    if action == "city":
        winning_team = "Красные"
        winner_label = "Победа города"
        await state.update_data(winning_team=winning_team, winner_label=winner_label)

        for slot in slots.values():
            slot["base_points"] = 1 if slot.get("team") == winning_team else 0

        await save_slots(state, slots)
        await state.set_state(GameCreateState.score_editor_select_player)

        await callback.message.edit_text(
            f"🏆 **Победитель: {winner_label}**\n\n"
            f"🎲 **Редактор баллов**\n\n"
            f"Выберите игрока для редактирования Доп, ПР или МН:\n\n"
            f"🔴 Красные — победа (+1 очко за игру)\n"
            f"⚫ Чёрные — поражение (0 очков за игру)",
            reply_markup=keyboards.score_editor_player_kb(slots, winning_team)
        )
        await callback.answer()
        return

    elif action == "mafia":
        winning_team = "Чёрные"
        winner_label = "Победа мафии"
        await state.update_data(winning_team=winning_team, winner_label=winner_label)

        for slot in slots.values():
            slot["base_points"] = 1 if slot.get("team") == winning_team else 0

        await save_slots(state, slots)
        await state.set_state(GameCreateState.score_editor_select_player)

        await callback.message.edit_text(
            f"🏆 **Победитель: {winner_label}**\n\n"
            f"🎲 **Редактор баллов**\n\n"
            f"Выберите игрока для редактирования Доп, ПР или МН:\n\n"
            f"⚫ Чёрные — победа (+1 очко за игру)\n"
            f"🔴 Красные — поражение (0 очков за игру)",
            reply_markup=keyboards.score_editor_player_kb(slots, winning_team)
        )
        await callback.answer()
        return

    elif action == "ppk":
        await state.set_state(GameCreateState.ppk_team_select)
        await callback.message.edit_text(
            "⚠️ **ППК (Победа Противоположной Команды)**\n\n"
            "Какая команда одержала победу?",
            reply_markup=keyboards.ppk_team_selection_kb()
        )
        await callback.answer()
        return

    elif action == "cancel":
        await clear_game_state(state)
        await callback.message.edit_text("❌ **Игра отменена**\n\nИгра полностью удалена без сохранения.")
        await callback.message.answer("🛠 Админ-панель", reply_markup=keyboards.admin_menu())
        await callback.answer()
        return

    else:
        await callback.answer("Неизвестное действие", show_alert=True)
        return

    # (нижний код на практике не выполняется из-за ретурнов выше,
    # но я оставил его как у тебя, можно удалить как мёртвый)
    await state.update_data(winning_team=winning_team, winner_label=winner_label)

    for slot in slots.values():
        slot["base_points"] = 1 if slot.get("team") == winning_team else 0

    await save_slots(state, slots)
    await state.set_state(GameCreateState.score_editor_select_player)

    await callback.message.edit_text(
        f"🏆 **Победитель: {winner_label}**\n\n"
        f"🎲 **Редактор баллов**\n\n"
        f"Выберите игрока для редактирования Доп, ПР или МН:\n\n"
        f"🔴 Красные — победа (+1 очко за игру)\n"
        f"⚫ Чёрные — поражение (0 очков за игру)",
        reply_markup=keyboards.score_editor_player_kb(slots, winning_team)
    )
    await callback.answer()


@router.callback_query(GameCreateState.score_editor_select_player, F.data.startswith("score_edit_"))
async def score_editor_select_player(callback: types.CallbackQuery, state: FSMContext):
    # редактирование баллов — часть постигровой работы судьи → тоже проверяем права
    if not await ensure_judge_cb(callback):
        await callback.answer("Недостаточно прав судьи.", show_alert=True)
        return

    slot_num = int(callback.data.split("_")[2])

    data = await state.get_data()
    slots = data.get("slots") or {}

    if slot_num not in slots:
        await callback.answer("Игрок не найден!", show_alert=True)
        return

    slot_data = slots[slot_num]
    name = slot_data.get("nickname") or slot_data.get("full_name") or f"Слот {slot_num}"
    role = slot_data.get("role", "Не задана")
    team = slot_data.get("team", "")
    team_icon = "🔴" if team == "Красные" else "⚫" if team == "Чёрные" else "⚪"

    await state.update_data(score_edit_slot=slot_num)
    await state.set_state(GameCreateState.score_editor_select_type)

    protocol_text = slot_data.get("will_protocol_raw", "")
    opinion_text = slot_data.get("will_opinion", "")

    info_text = (
        f"{team_icon} **Слот {slot_num} - {name}**\n"
        f"Роль: {role}\n\n"
        f"📊 **Текущие баллы:**\n"
        f"  • Игра: {slot_data.get('base_points', 0):+.1f}\n"
        f"  • Доп: {slot_data.get('bonus_points', 0):+.1f}\n"
        f"  • ПР: {slot_data.get('will_protocol_points', 0):+.1f}\n"
        f"  • МН: {slot_data.get('will_opinion_points', 0):+.1f}\n"
        f"  • ЛХ: {slot_data.get('lh_points', 0):+.1f}\n\n"
    )

    if protocol_text:
        info_text += f"📋 **Протокол:** {protocol_text[:100]}...\n\n"
    if opinion_text:
        info_text += f"💬 **Мнение:** {opinion_text[:100]}...\n\n"

    info_text += "Выберите тип баллов для изменения:"

    await callback.message.edit_text(info_text, reply_markup=keyboards.score_type_kb(slot_num, slot_data))
    await callback.answer()


@router.callback_query(GameCreateState.score_editor_select_type, F.data.startswith("score_type_"))
async def score_editor_select_type(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        await callback.answer("Недостаточно прав судьи.", show_alert=True)
        return

    parts = callback.data.split("_")
    score_type = parts[2]
    slot_num = int(parts[3])

    data = await state.get_data()
    slots = data.get("slots") or {}

    if slot_num not in slots:
        await callback.answer("Игрок не найден!", show_alert=True)
        return

    current_value = 0.0
    if score_type == "bonus":
        current_value = slots[slot_num].get("bonus_points", 0)
    elif score_type == "protocol":
        current_value = slots[slot_num].get("will_protocol_points", 0)
    elif score_type == "opinion":
        current_value = slots[slot_num].get("will_opinion_points", 0)

    await state.update_data(score_edit_type=score_type, score_edit_slot=slot_num, score_old_value=current_value)
    await state.set_state(GameCreateState.score_editor_select_value)

    type_names = {"bonus": "Доп", "protocol": "ПР", "opinion": "МН"}
    type_name = type_names.get(score_type, score_type)

    await callback.message.edit_text(
        f"📊 **Редактирование {type_name}**\n\n"
        f"Текущее значение: {current_value:+.1f}\n\n"
        f"Выберите новое значение:",
        reply_markup=keyboards.score_value_kb(current_value)
    )
    await callback.answer()


@router.callback_query(GameCreateState.score_editor_select_value, F.data.startswith("score_val_"))
async def score_editor_set_value(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        await callback.answer("Недостаточно прав судьи.", show_alert=True)
        return

    value = float(callback.data.split("_")[2])

    data = await state.get_data()
    slot_num = data.get("score_edit_slot")
    score_type = data.get("score_edit_type")
    old_value = data.get("score_old_value", 0)
    slots = data.get("slots") or {}

    if slot_num not in slots:
        await callback.answer("Игрок не найден!", show_alert=True)
        return

    if score_type == "bonus":
        slots[slot_num]["bonus_points"] = value
    elif score_type == "protocol":
        slots[slot_num]["will_protocol_points"] = value
    elif score_type == "opinion":
        slots[slot_num]["will_opinion_points"] = value

    await save_slots(state, slots)

    type_names = {"bonus": "Доп", "protocol": "ПР", "opinion": "МН"}
    type_name = type_names.get(score_type, score_type)

    await callback.answer(f"✅ {type_name} изменён: {old_value:+.1f} → {value:+.1f}")

    await state.set_state(GameCreateState.score_editor_select_type)
    slot_data = slots.get(slot_num, {})

    await callback.message.edit_text(
        f"📊 **Редактирование баллов слота {slot_num}**\n\n"
        f"✅ {type_name} установлен: {value:+.1f}\n\n"
        f"Выберите тип баллов для дальнейшего редактирования:",
        reply_markup=keyboards.score_type_kb(slot_num, slot_data)
    )


@router.callback_query(F.data == "score_back_to_players")
async def score_back_to_players(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        await callback.answer("Недостаточно прав судьи.", show_alert=True)
        return

    data = await state.get_data()
    slots = data.get("slots") or {}
    winning_team = data.get("winning_team")

    await state.set_state(GameCreateState.score_editor_select_player)

    await callback.message.edit_text(
        f"🏆 **Редактор баллов**\n\n"
        f"Выберите игрока для редактирования Доп, ПР или МН:",
        reply_markup=keyboards.score_editor_player_kb(slots, winning_team)
    )
    await callback.answer()


@router.callback_query(F.data == "score_back_to_types")
async def score_back_to_types(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        await callback.answer("Недостаточно прав судьи.", show_alert=True)
        return

    data = await state.get_data()
    slot_num = data.get("score_edit_slot")
    slots = data.get("slots") or {}

    if slot_num not in slots:
        await callback.answer("Игрок не найден!", show_alert=True)
        return

    await state.set_state(GameCreateState.score_editor_select_type)
    slot_data = slots.get(slot_num, {})

    await callback.message.edit_text(
        f"📊 **Редактирование баллов слота {slot_num}**\n\n"
        f"Выберите тип баллов для изменения:",
        reply_markup=keyboards.score_type_kb(slot_num, slot_data)
    )
    await callback.answer()


@router.callback_query(F.data == "score_back_to_values")
async def score_back_to_values(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        await callback.answer("Недостаточно прав судьи.", show_alert=True)
        return

    data = await state.get_data()
    old_value = data.get("score_old_value", 0)

    await state.set_state(GameCreateState.score_editor_select_value)

    await callback.message.edit_text(
        f"📊 **Выбор значения**\n\n"
        f"Текущее значение: {old_value:+.1f}\n\n"
        f"Выберите новое значение:",
        reply_markup=keyboards.score_value_kb(old_value)
    )
    await callback.answer()


@router.callback_query(F.data == "score_finish")
async def score_finish(callback: types.CallbackQuery, state: FSMContext):
    # Только судья/админ могут финализировать баллы
    if not await ensure_judge_cb(callback):
        await callback.answer("Недостаточно прав судьи.", show_alert=True)
        return

    data = await state.get_data()
    slots = data.get("slots") or {}
    winning_team = data.get("winning_team")
    winner_label = data.get("winner_label")

    for slot in slots.values():
        if not slot.get("pu_mark") or slot.get("team") != "Красные":
            slot["lh_points"] = float(slot.get("lh_points") or 0.0)
            continue
        suspects = slot.get("night_suspects") or []
        correct = sum(1 for n in suspects if slots.get(n, {}).get("team") == "Чёрные")
        slot["lh_points"] = [0.0, 0.1, 0.3, 0.6][correct] if correct <= 3 else 0.0

    await database.apply_game_result_to_users(slots, winning_team)

    game_date = await database.get_current_game_date() or "-"
    evening_num = await database.get_current_game_number() or 1
    global_num = await database.get_current_global_game_number() or 1

    protocol_body = await build_protocol_text(slots, updated=False, winner_label=winner_label)
    await database.save_game_history(game_date, winner_label, protocol_body, evening_num, global_num)
    await database.save_game_slots_history(game_date, slots)

    try:
        await callback.message.delete()
    except Exception:
        pass

    header = f"📑 Протокол игры №{evening_num} ({game_date}): №{global_num} по общей истории — {winner_label}"
    full_protocol = f"{header}\n\n{protocol_body}"

    await callback.message.answer(full_protocol, reply_markup=keyboards.game_admin_menu(), parse_mode=ParseMode.HTML)

    await state.update_data(slots=slots, protocol_chat_id=None, protocol_message_id=None, winner_label=winner_label)
    await save_slots(state, slots)
    await state.set_state(GameCreateState.editing_slots)

    await callback.answer("✅ Игра сохранена! Нажмите «Завершить игру» для графического протокола.")


@router.callback_query(F.data == "score_cancel")
async def score_cancel(callback: types.CallbackQuery, state: FSMContext):
    # Отмена редактирования тоже только для судьи/админа
    if not await ensure_judge_cb(callback):
        await callback.answer("Недостаточно прав судьи.", show_alert=True)
        return

    data = await state.get_data()
    slots = data.get("slots") or {}

    await state.set_state(GameCreateState.editing_slots)

    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(
        build_game_state(slots, alive_only=False),
        reply_markup=keyboards.game_admin_menu()
    )
    await callback.answer("Редактирование отменено")


@router.message(F.text == "🏁 Завершить")
async def final_finish_game(message: types.Message, state: FSMContext):
    # Завершить игру (графический протокол) — игровое действие → судья тоже может
    if not await ensure_judge_pm(message):
        return

    active = await database.get_setting("game_active")
    if active != "1":
        # Разводим меню: если судья, можно сделать отдельное judge_menu()
        if message.from_user.id in config.ADMIN_IDS:
            rm = keyboards.admin_menu()
        else:
            rm = keyboards.judge_menu()
        await message.answer("Сейчас нет активной игры.", reply_markup=rm)
        return

    data = await state.get_data()
    # Берём слоты из FSM или из БД
    slots = data.get("slots") or await database.load_current_game_slots()

    if not slots:
        if message.from_user.id in config.ADMIN_IDS:
            rm = keyboards.admin_menu()
        else:
            rm = keyboards.judge_menu()
        await message.answer("Нет данных об игре.", reply_markup=rm)
        await clear_game_state(state)
        return

    # Переносим порядок ночных убийств в slots, чтобы картинка увидела завещания
    night_kills_order = data.get("night_kills_order") or data.get("_night_kills_order") or []
    # Сохраняем только если там что‑то есть
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

    if message.from_user.id in config.ADMIN_IDS:
        rm = keyboards.admin_menu()
    else:
        rm = keyboards.judge_menu()

    await message.answer("✅ Игра полностью завершена. Можно запускать новую.", reply_markup=rm)


# ========== 7. РЕЖИМ РЕДАКТИРОВАНИЯ ==========
@router.message(GameCreateState.editing_slots, F.text == "✏️ Редактировать")
async def enter_edit_mode(message: types.Message, state: FSMContext):
    # Режим редактирования игры — тоже судья/админ
    if not await ensure_judge_pm(message):
        return

    data = await state.get_data()
    slots = data.get("slots") or {}

    slots = {int(k): v for k, v in slots.items()}

    if not slots:
        await message.answer("Нет активной игры для редактирования.", reply_markup=keyboards.game_admin_menu())
        return

    await state.set_state(GameCreateState.edit_mode_select_slot)
    await message.answer(
        "✏️ **Режим редактирования игры**\n\nВыберите слот для редактирования:",
        reply_markup=get_slot_selection_keyboard(slots)
    )


# ========== 8. УПРАВЛЕНИЕ ФОЛАМИ ==========
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
    await message.answer(
        "⚠️ **Управление фолами**\n\nВыберите игрока:",
        reply_markup=keyboards.foul_select_kb(alive_slots)
    )


@router.callback_query(GameCreateState.foul_select, F.data.startswith("foul_select_"))
async def foul_select_player(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        await callback.answer("Недостаточно прав судьи.", show_alert=True)
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
        f"⚠️ **Фолы игрока {slot_num} - {name}**\n\n"
        f"Текущее количество фолов: {current_fouls}\n\n"
        f"Выберите действие:",
        reply_markup=keyboards.foul_action_kb(slot_num, current_fouls)
    )
    await callback.answer()


@router.callback_query(GameCreateState.foul_action, F.data.startswith("foul_add_"))
async def foul_add(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        await callback.answer("Недостаточно прав судьи.", show_alert=True)
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

        # Штраф в ДЦ
        current_dc = slots[slot_num].get("dc_points", 0.0)
        slots[slot_num]["dc_points"] = round(current_dc - 1.0, 1)

        await save_slots(state, slots)

        name = slots[slot_num].get("nickname") or slots[slot_num].get("full_name") or f"Слот {slot_num}"
        await callback.answer(f"⚠️ Игрок {name} удалён за 4 фола!", show_alert=True)

        game_state = build_game_state(slots, alive_only=False)
        await callback.message.answer(game_state, reply_markup=keyboards.game_admin_menu())

        alive_slots = {k: v for k, v in slots.items() if v.get("alive", True)}
        if alive_slots:
            await callback.message.answer(
                "⚠️ **Управление фолами**\n\nВыберите игрока:",
                reply_markup=keyboards.foul_select_kb(alive_slots)
            )
            await state.set_state(GameCreateState.foul_select)
        else:
            await state.set_state(GameCreateState.editing_slots)
        return

    await callback.answer(f"✅ Фол добавлен игроку {slot_num}")

    game_state = build_game_state(slots, alive_only=False)
    await callback.message.answer(game_state, reply_markup=keyboards.game_admin_menu())

    alive_slots = {k: v for k, v in slots.items() if v.get("alive", True)}
    await callback.message.answer(
        "⚠️ **Управление фолами**\n\nВыберите игрока:",
        reply_markup=keyboards.foul_select_kb(alive_slots)
    )
    await state.set_state(GameCreateState.foul_select)


@router.callback_query(GameCreateState.foul_action, F.data.startswith("foul_remove_"))
async def foul_remove(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        await callback.answer("Недостаточно прав судьи.", show_alert=True)
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
    await callback.message.answer(
        "⚠️ **Управление фолами**\n\nВыберите игрока:",
        reply_markup=keyboards.foul_select_kb(alive_slots)
    )
    await state.set_state(GameCreateState.foul_select)


@router.callback_query(F.data == "foul_cancel")
async def foul_cancel(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        await callback.answer("Недостаточно прав судьи.", show_alert=True)
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


# ========== 10. ДИСЦИПЛИНАРНЫЕ ФУНКЦИИ ==========

@router.callback_query(GameCreateState.foul_action, F.data.startswith("tech_foul_small_"))
async def tech_foul_small(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        await callback.answer("Недостаточно прав судьи.", show_alert=True)
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

    # Добавляем в ДЦ (дисциплинарные), а не в Допы
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
    await callback.message.answer(
        "⚠️ **Управление фолами**\n\nВыберите игрока:",
        reply_markup=keyboards.foul_select_kb(alive_slots)
    )
    await state.set_state(GameCreateState.foul_select)


@router.callback_query(GameCreateState.foul_action, F.data.startswith("tech_foul_big_"))
async def tech_foul_big(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        await callback.answer("Недостаточно прав судьи.", show_alert=True)
        return

    # callback.data = "tech_foul_big_6" -> split = ['tech', 'foul', 'big', '6']
    slot_num = int(callback.data.split("_")[3])

    data = await state.get_data()
    slots = data.get("slots") or {}

    if slot_num not in slots:
        await callback.answer("Игрок не найден!", show_alert=True)
        return

    tech_fouls = slots[slot_num].get("technical_fouls", [])
    tech_fouls.append("big")
    slots[slot_num]["technical_fouls"] = tech_fouls

    # Вариант с ДЦ (основной)
    current_dc = slots[slot_num].get("dc_points", 0.0)
    slots[slot_num]["dc_points"] = round(current_dc - 0.6, 1)

    await save_slots(state, slots)
    await callback.answer("✅ Большой техфол (-0.6) добавлен в ДЦ")

    # Проверяем на удаление (2 техфола = удаление)
    if len(tech_fouls) >= 2 and slots[slot_num].get("alive", True):
        slots[slot_num]["alive"] = False
        slots[slot_num]["status_reason"] = "Удалён (2 техфола)"
        slots[slot_num]["kicked"] = True
        await save_slots(state, slots)
        await callback.answer("⚠️ Игрок удалён за 2 техфола!", show_alert=True)

    game_state = build_game_state(slots, alive_only=False)
    await callback.message.answer(game_state, reply_markup=keyboards.game_admin_menu())

    alive_slots = {k: v for k, v in slots.items() if v.get("alive", True)}
    await callback.message.answer(
        "⚠️ **Управление фолами**\n\nВыберите игрока:",
        reply_markup=keyboards.foul_select_kb(alive_slots)
    )
    await state.set_state(GameCreateState.foul_select)


@router.callback_query(GameCreateState.foul_action, F.data.startswith("kick_player_"))
async def kick_player(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        await callback.answer("Недостаточно прав судьи.", show_alert=True)
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

    # Штраф в ДЦ, а не в Допы
    current_dc = slots[slot_num].get("dc_points", 0.0)
    slots[slot_num]["dc_points"] = round(current_dc - 1.0, 1)

    await save_slots(state, slots)
    await callback.answer("🚫 Игрок удалён из игры (-1.0 в ДЦ)")

    game_state = build_game_state(slots, alive_only=False)
    await callback.message.answer(game_state, reply_markup=keyboards.game_admin_menu())

    alive_slots = {k: v for k, v in slots.items() if v.get("alive", True)}
    await callback.message.answer(
        "⚠️ **Управление фолами**\n\nВыберите игрока:",
        reply_markup=keyboards.foul_select_kb(alive_slots)
    )
    await state.set_state(GameCreateState.foul_select)


# ========== 11. ППК (Победа Противоположной Команды) ==========

@router.callback_query(F.data == "game_end:ppk")
async def handle_ppk_start(callback: types.CallbackQuery, state: FSMContext):
    """Начало обработки ППК — выбор команды-победителя."""
    if not await ensure_judge_cb(callback):
        await callback.answer("Недостаточно прав судьи.", show_alert=True)
        return

    await state.set_state(GameCreateState.ppk_team_select)
    await callback.message.edit_text(
        "⚠️ **ППК (Победа Противоположной Команды)**\n\n"
        "Какая команда одержала победу?",
        reply_markup=keyboards.ppk_team_selection_kb()
    )
    await callback.answer()


@router.callback_query(GameCreateState.ppk_team_select, F.data.startswith("ppk_team_"))
async def ppk_select_team(callback: types.CallbackQuery, state: FSMContext):
    """Выбор команды-победителя при ППК."""
    if not await ensure_judge_cb(callback):
        await callback.answer("Недостаточно прав судьи.", show_alert=True)
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
        f"⚠️ **ППК**\n\nПобедившая команда: {winning_team}\n\n"
        f"Кто виноват в поражении (выберите игрока из проигравшей команды):",
        reply_markup=keyboards.ppk_culprit_selection_kb(slots, "Красные" if team == "black" else "Чёрные")
    )
    await callback.answer()


@router.callback_query(GameCreateState.ppk_culprit_select, F.data.startswith("ppk_culprit_"))
async def ppk_select_culprit(callback: types.CallbackQuery, state: FSMContext):
    """Выбор виновника ППК."""
    if not await ensure_judge_cb(callback):
        await callback.answer("Недостаточно прав судьи.", show_alert=True)
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
        f"⚠️ **ППК**\n\n"
        f"Вы уверены, что {name} (слот {slot_num}) является виновником?\n\n"
        f"Ему будет начислен штраф -1.5 балла.",
        reply_markup=keyboards.ppk_confirmation_kb(slot_num, name)
    )
    await callback.answer()


@router.callback_query(GameCreateState.ppk_confirm, F.data == "ppk_confirm_yes")
async def ppk_confirm(callback: types.CallbackQuery, state: FSMContext):
    if not await ensure_judge_cb(callback):
        await callback.answer("Недостаточно прав судьи.", show_alert=True)
        return

    data = await state.get_data()
    slots = data.get("slots") or {}
    slot_num = data.get("ppk_culprit_slot")
    winning_team = data.get("ppk_winning_team")
    winner_label = data.get("ppk_winner_label")

    # Сохраняем имя виновника для отображения в протоколе
    culprit_name = None
    if slot_num and slot_num in slots:
        culprit_name = slots[slot_num].get("nickname") or slots[slot_num].get("full_name") or f"Слот {slot_num}"
        current_dc = slots[slot_num].get("dc_points", 0.0)
        slots[slot_num]["dc_points"] = round(current_dc - 1.5, 1)
        slots[slot_num]["ppk"] = True
        slots[slot_num]["alive"] = False  # Виновник становится мёртвым
        slots[slot_num]["status_reason"] = "Удалён (ППК)"
        slots[slot_num]["kicked"] = True

    # Начисляем базовые очки
    for slot in slots.values():
        if slot.get("team") == winning_team:
            slot["base_points"] = 1
        else:
            slot["base_points"] = 0

    # Обновляем заголовок с именем виновника
    if culprit_name:
        winner_label = f"ППК: {winning_team} (Виновник: {culprit_name})"

    await state.update_data(winning_team=winning_team, winner_label=winner_label, slots=slots)
    await save_slots(state, slots)

    await state.set_state(GameCreateState.score_editor_select_player)

    await callback.message.edit_text(
        f"🏆 **{winner_label}**\n\n"
        f"🎲 **Редактор баллов**\n\n"
        f"Выберите игрока для редактирования Доп, ПР или МН:",
        reply_markup=keyboards.score_editor_player_kb(slots, winning_team)
    )
    await callback.answer()


@router.callback_query(F.data == "ppk_cancel")
async def ppk_cancel(callback: types.CallbackQuery, state: FSMContext):
    """Отмена ППК."""
    if not await ensure_judge_cb(callback):
        await callback.answer("Недостаточно прав судьи.", show_alert=True)
        return

    await state.set_state(GameCreateState.editing_slots)
    await callback.message.delete()
    await callback.message.answer(
        "❌ ППК отменена. Игра продолжается.",
        reply_markup=keyboards.game_admin_menu()
    )
    await callback.answer()


@router.callback_query(F.data == "ppk_back_to_teams")
async def ppk_back_to_teams(callback: types.CallbackQuery, state: FSMContext):
    """Возврат к выбору команды."""
    if not await ensure_judge_cb(callback):
        await callback.answer("Недостаточно прав судьи.", show_alert=True)
        return

    await state.set_state(GameCreateState.ppk_team_select)
    await callback.message.edit_text(
        "⚠️ **ППК (Победа Противоположной Команды)**\n\n"
        "Какая команда одержала победу?",
        reply_markup=keyboards.ppk_team_selection_kb()
    )
    await callback.answer()


# ========== 12. АВТОУДАЛЕНИЕ ЗА 4 ФОЛА ==========

async def check_auto_kick(state: FSMContext, slot_num: int):
    """Проверяет, не набрал ли игрок 4 фола, и автоматически удаляет его."""
    data = await state.get_data()
    slots = data.get("slots") or {}

    if slot_num not in slots:
        return False

    fouls = slots[slot_num].get("fouls", 0)

    if fouls >= 4 and slots[slot_num].get("alive", True):
        # Автоматическое удаление
        slots[slot_num]["alive"] = False
        slots[slot_num]["status_reason"] = "Удалён (4 фола)"
        slots[slot_num]["kicked"] = True

        # Штраф -1.0 к бонусным очкам
        current_bonus = slots[slot_num].get("bonus_points", 0.0)
        slots[slot_num]["bonus_points"] = round(current_bonus - 1.0, 1)

        await state.update_data(slots=slots)
        await save_slots(state, slots)

        # Здесь можно добавить отправку сообщения о том, что игрок автоудалён
        return True

    return False


# ========== 9. CATCH-ALL ==========
@router.message(GameCreateState.editing_slots)
async def catch_all_in_game(message: types.Message, state: FSMContext):
    # Любой текст в состоянии игры — тоже доступен судье
    if not await ensure_judge_pm(message):
        return

    slots = await get_slots(message, state)
    if slots:
        await message.answer(
            build_game_state(slots, alive_only=False),
            reply_markup=keyboards.game_admin_menu()
        )