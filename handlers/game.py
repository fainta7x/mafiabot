import random
import copy

from aiogram import Router, F, types
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

import config
import database
import keyboards

router = Router()


class GameCreateState(StatesGroup):
    editing_slots = State()
    waiting_fouls = State()
    waiting_nominees = State()
    waiting_votes = State()
    choosing_mafia = State()
    choosing_don = State()
    choosing_sheriff = State()
    waiting_kill_slot = State()          # номер убитого ночью
    waiting_night_suspects = State()     # подозреваемые от первой жертвы


# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====

def _format_player_name(full_name: str | None, nickname: str | None) -> str:
    if nickname and nickname not in ("", "Не установлен"):
        return nickname
    if full_name and full_name not in ("", "Неизвестный"):
        return full_name
    return "Без имени"


def build_slots_text(slots: dict[int, dict]) -> str:
    sorted_slots = dict(sorted(slots.items(), key=lambda x: x[0]))

    lines = ["🎲 Черновик новой игры.\n", "Текущие слоты игроков:\n"]
    for slot, info in sorted_slots.items():
        name_part = _format_player_name(info["full_name"], info["nickname"])
        lines.append(f"{slot}. {name_part}")

    lines.append(
        "\nЧтобы поменять или задать ник в слоте, напиши в чат:\n"
        "номер_слота пробел новый_ник\n"
        "Например: 3 Волк\n\n"
        "Можно добавлять новые слоты до 10 игрока.\n"
        "Когда всё будет готово — нажми «Ок» или отправь текстом «Ок»."
    )
    return "\n".join(lines)


def build_roles_summary(slots: dict[int, dict]) -> str:
    sorted_slots = dict(sorted(slots.items(), key=lambda x: x[0]))

    lines = ["🎭 Роли и команды по слотам:\n"]
    for slot, info in sorted_slots.items():
        name = _format_player_name(info.get("full_name"), info.get("nickname"))
        role = info.get("role", "Не задана")
        team = info.get("team", "—")
        lines.append(f"{slot}. {name} — {role} ({team})")

    return "\n".join(lines)


def build_game_state(slots: dict[int, dict], alive_only: bool = False) -> str:
    sorted_slots = dict(sorted(slots.items(), key=lambda x: x[0]))

    lines = ["📋 Текущее состояние игры:\n"]
    for slot, info in sorted_slots.items():
        name = _format_player_name(info.get("full_name"), info.get("nickname"))
        role = info.get("role", "Не задана")
        fouls = info.get("fouls", 0)
        alive = info.get("alive", True)
        status_reason = info.get("status_reason") or ("Жив" if alive else "Не в игре")
        nominated = info.get("nominated", False)
        votes = info.get("votes", 0)

        if alive_only and not alive:
            continue

        status_text = "Жив" if alive else status_reason
        nom_text = " | ВЫСТАВЛЕН" if nominated else ""
        votes_text = f" | Голоса: {votes}" if votes > 0 else ""

        lines.append(
            f"{slot}. {name} — {role} | Фолы: {fouls} | Статус: {status_text}{nom_text}{votes_text}"
        )

    if alive_only:
        lines.insert(0, "📋 ЖИВЫЕ игроки на данный момент:\n")

    return "\n".join(lines)


def build_votes_summary(slots: dict[int, dict]) -> str:
    sorted_slots = dict(sorted(slots.items(), key=lambda x: x[0]))
    lines = ["🗳 Результаты голосования (только выставленные):\n"]
    for slot, info in sorted_slots.items():
        if not info.get("nominated"):
            continue
        name = _format_player_name(info.get("full_name"), info.get("nickname"))
        role = info.get("role", "Не задана")
        votes = info.get("votes", 0)
        alive = info.get("alive", True)
        status_reason = info.get("status_reason") or ("Жив" if alive else "Не в игре")
        status_text = "Жив" if alive else status_reason
        lines.append(
            f"{slot}. {name} — {role} | Голоса: {votes} | Статус: {status_text}"
        )
    if len(lines) == 1:
        lines.append("Нет выставленных игроков.")
    return "\n".join(lines)


def _parse_slots_list(text: str) -> list[int]:
    cleaned = text.replace(",", " ")
    parts = cleaned.split()
    result = []
    for p in parts:
        if not p.strip():
            continue
        try:
            num = int(p)
        except ValueError:
            continue
        if num not in result:
            result.append(num)
    return result


# ===== СТАРТ И СЛОТЫ =====

@router.message(F.text == "🎲 Новая игра")
async def start_new_game(message: types.Message, state: FSMContext):
    if message.from_user.id != config.ADMIN_ID or message.chat.type != "private":
        return

    booked = await database.get_booked_players_for_game()

    if not booked:
        await message.answer(
            "На вечер никто не записан (со статусами «Вовремя» или «Позже») — не из кого собирать игру.",
            reply_markup=keyboards.admin_menu(),
        )
        return

    random.shuffle(booked)

    slots: dict[int, dict] = {}
    for i, (full_name, username, nickname, status) in enumerate(booked, start=1):
        slots[i] = {
            "full_name": full_name,
            "nickname": nickname,
            "username": username,
            "status": status,
            "fouls": 0,
            "alive": True,
            "status_reason": "Жив",
            "nominated": False,
            "votes": 0,
            "night_suspects": [],
        }

    await state.set_state(GameCreateState.editing_slots)
    await state.update_data(
        slots=slots,
        roles_assigned=False,
        nominated_list=[],
        vote_index=0,
        split_candidates=[],
        in_split=False,
        first_night_kill_recorded=False,
        waiting_night_suspects_slot=None,
        night_killed_slot=None,
    )

    text = build_slots_text(slots)
    await message.answer(text, reply_markup=keyboards.game_admin_menu())


@router.message(GameCreateState.editing_slots, F.text.regexp(r"^\d+\s+"))
async def manual_nick_edit(message: types.Message, state: FSMContext):
    # защита от команд статуса типа "5 ночь/день/жив"
    lower = message.text.strip().lower()
    if lower.endswith(" ночь") or lower.endswith(" день") or lower.endswith(" жив"):
        return

    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "Формат: <номер_слота> <новый_ник>\nПример: 3 Волк",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    try:
        slot_num = int(parts[0])
    except ValueError:
        await message.answer(
            "Первым должно быть число — номер слота. Пример: 3 Волк",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    new_nick = parts[1].strip()
    if not new_nick:
        await message.answer(
            "Ник не может быть пустым. Пример: 3 Волк",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    if slot_num < 1 or slot_num > 10:
        await message.answer(
            "Номер слота должен быть от 1 до 10.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    if slot_num in slots:
        slots[slot_num]["nickname"] = new_nick
        action = "обновлён"
    else:
        slots[slot_num] = {
            "full_name": None,
            "nickname": new_nick,
            "username": None,
            "status": "Добавлен вручную",
            "fouls": 0,
            "alive": True,
            "status_reason": "Жив",
            "nominated": False,
            "votes": 0,
            "night_suspects": [],
        }
        action = "создан"

    await state.update_data(slots=slots)

    text = build_slots_text(slots)
    await message.answer(
        f"Слот {slot_num} {action}, ник: «{new_nick}».\n\n{text}",
        reply_markup=keyboards.game_admin_menu(),
    )


# ===== ОСТАНОВКА ИГРЫ С ВЫБОРОМ ИСХОДА =====

@router.message(GameCreateState.editing_slots, F.text.casefold() == "остановить игру")
async def ask_game_finish_reason(message: types.Message, state: FSMContext):
    """
    Показываем варианты завершения игры:
    - Победа города
    - Победа мафии
    - Полная отмена игры
    """
    await message.answer(
        "Как завершить текущую игру?",
        reply_markup=keyboards.game_finish_keyboard(),
    )


@router.callback_query(F.data.startswith("game_end:"))
async def handle_game_finish(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}

    action = callback.data.split(":", 1)[1]

    if action == "city":
        result_text = "🏙 Игра завершена: Победа города (мирных жителей)."
    elif action == "mafia":
        result_text = "💀 Игра завершена: Победа мафии."
    else:
        result_text = "❌ Игра отменена без подведения итогов."

    # Здесь при желании можно сохранить результат куда-то в историю

    await state.clear()

    await callback.message.edit_text(result_text)
    await callback.message.answer(
        "Возвращаемся в админ-меню.",
        reply_markup=keyboards.admin_menu(),
    )
    await callback.answer()


# ===== ФОЛЫ =====

@router.message(GameCreateState.editing_slots, F.text.casefold() == "фол")
async def ask_fouls(message: types.Message, state: FSMContext):
    await state.set_state(GameCreateState.waiting_fouls)
    await message.answer(
        "Режим фолов.\n"
        "Чтобы ДОБАВИТЬ фол, введи номера слотов через пробел:\n"
        "например: `3 7` — по фолу игрокам 3 и 7.\n\n"
        "Чтобы СНЯТЬ фол, начни со знака минус:\n"
        "`- 3 8` — убрать по фолу с игроков 3 и 8.",
        reply_markup=keyboards.game_admin_menu(),
    )


@router.message(GameCreateState.waiting_fouls)
async def apply_fouls(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}

    text = message.text.strip()
    if not text:
        await message.answer(
            "Пустой ввод. Пример: `3 7` или `- 3 8`.",
            reply_markup=keyboards.game_admin_menu(),
        )
        await state.set_state(GameCreateState.editing_slots)
        return

    mode = "add"
    if text.startswith("-"):
        mode = "remove"
        text = text[1:].strip()

    nums = _parse_slots_list(text)
    if not nums:
        await message.answer(
            "Не получилось распознать номера слотов.\n"
            "Пример: `3 7` или `- 3 8`.",
            reply_markup=keyboards.game_admin_menu(),
        )
        await state.set_state(GameCreateState.editing_slots)
        return

    for n in nums:
        if n not in slots or n < 1 or n > 10:
            continue

        if not slots[n].get("alive", True):
            continue

        fouls = slots[n].get("fouls", 0)
        if mode == "add":
            fouls += 1
        else:
            fouls = max(0, fouls - 1)
        slots[n]["fouls"] = fouls

    await state.update_data(slots=slots)

    text = build_game_state(slots, alive_only=False)
    await message.answer(text, reply_markup=keyboards.game_admin_menu())

    await state.set_state(GameCreateState.editing_slots)


# ===== СТАТУСЫ ДЕНЬ/ЖИВ =====

@router.message(GameCreateState.editing_slots, F.text.regexp(r"^\d+\s+(день|жив)$"))
async def status_commands(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) != 2:
        return

    try:
        slot_num = int(parts[0])
    except ValueError:
        return

    cmd = parts[1].strip().lower()

    if slot_num not in slots:
        await message.answer(
            f"Слота №{slot_num} нет в текущем списке.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    slot = slots[slot_num]
    alive = slot.get("alive", True)

    if cmd == "день" and not alive:
        await message.answer(
            f"Слот {slot_num} уже не в игре, статус менять нельзя.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    if cmd == "день":
        slot["alive"] = False
        slot["status_reason"] = "Заголосован"
    elif cmd == "жив":
        slot["alive"] = True
        slot["status_reason"] = "Жив"
    else:
        return

    await state.update_data(slots=slots)
    text = build_game_state(slots, alive_only=False)
    await message.answer(text, reply_markup=keyboards.game_admin_menu())


@router.message(GameCreateState.editing_slots, F.text.casefold() == "игра")
async def show_game_state_all(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}

    if not slots:
        await message.answer(
            "Список слотов пуст.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    text = build_game_state(slots, alive_only=False)
    await message.answer(text, reply_markup=keyboards.game_admin_menu())


@router.message(GameCreateState.editing_slots, F.text.casefold() == "игра живые")
async def show_game_state_alive(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}

    if not slots:
        await message.answer(
            "Список слотов пуст.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    text = build_game_state(slots, alive_only=True)
    await message.answer(text, reply_markup=keyboards.game_admin_menu())


# ===== ВЫСТАВЛЕНИЕ =====

@router.message(GameCreateState.editing_slots, F.text.casefold() == "выставить")
async def ask_nominees(message: types.Message, state: FSMContext):
    await state.set_state(GameCreateState.waiting_nominees)
    await message.answer(
        "Введи номера выставленных слотов через пробел.\n"
        "Пример: `1 3 7`",
        reply_markup=keyboards.game_admin_menu(),
    )


@router.message(GameCreateState.waiting_nominees)
async def set_nominees(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}
    nominated_list: list[int] = data.get("nominated_list") or [
        s for s, info in slots.items() if info.get("nominated")
    ]

    nums = _parse_slots_list(message.text)
    if not nums:
        await message.answer(
            "Не удалось распознать номера. Пример: `1 3 7`.",
            reply_markup=keyboards.game_admin_menu(),
        )
        await state.set_state(GameCreateState.editing_slots)
        return

    for n in nums:
        if n in slots and 1 <= n <= 10:
            if not slots[n].get("alive", True):
                continue
            slots[n]["nominated"] = True
            slots[n].setdefault("votes", 0)
            if n not in nominated_list:
                nominated_list.append(n)

    await state.update_data(slots=slots, nominated_list=nominated_list, vote_index=0)

    text = build_game_state(slots, alive_only=False)
    await message.answer(
        text,
        reply_markup=keyboards.game_admin_menu(),
    )

    await state.set_state(GameCreateState.editing_slots)


# ===== ГОЛОСОВАНИЕ С ПОПИЛОМ =====

@router.message(GameCreateState.editing_slots, F.text.casefold() == "голоса")
async def start_votes(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}
    in_split: bool = data.get("in_split", False)
    split_candidates: list[int] = data.get("split_candidates") or []

    if in_split and split_candidates:
        nominated_list = [
            s for s in split_candidates
            if s in slots and slots[s].get("alive", True)
        ]
        for s, info in slots.items():
            info["nominated"] = s in nominated_list
            info["votes"] = 0
    else:
        nominated_list = [
            s for s, info in slots.items()
            if info.get("nominated") and info.get("alive", True)
        ]

    if not nominated_list:
        await message.answer(
            "Сначала нужно выставить живых игроков (кнопка «Выставить»).",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    await state.set_state(GameCreateState.waiting_votes)
    await state.update_data(
        nominated_list=nominated_list,
        vote_index=0,
        slots=slots,
    )

    first_slot = nominated_list[0]
    await message.answer(
        f"Голоса.\nСколько голосов за слот {first_slot}?",
        reply_markup=keyboards.game_admin_menu(),
    )


@router.message(GameCreateState.waiting_votes)
async def collect_votes(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}
    nominated_list: list[int] = data.get("nominated_list") or []
    vote_index: int = data.get("vote_index", 0)
    in_split: bool = data.get("in_split", False)

    if not nominated_list or vote_index >= len(nominated_list):
        await state.set_state(GameCreateState.editing_slots)
        await message.answer(
            "Что-то пошло не так с голосованием. Попробуй начать заново кнопкой «Голоса».",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    text = message.text.strip()
    try:
        votes = int(text)
    except ValueError:
        await message.answer(
            "Нужно ввести число голосов. Пример: 3",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    slot_num = nominated_list[vote_index]
    if slot_num in slots:
        slots[slot_num]["votes"] = max(0, votes)

    vote_index += 1
    await state.update_data(slots=slots, vote_index=vote_index, nominated_list=nominated_list)

    if vote_index < len(nominated_list):
        next_slot = nominated_list[vote_index]
        await message.answer(
            f"Сколько голосов за слот {next_slot}?",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    # === все голоса собраны ===
    live_nominated = [
        n for n in nominated_list
        if n in slots and slots[n].get("alive", True)
    ]

    leaders: list[int] = []
    max_votes = 0
    if live_nominated:
        max_votes = max(slots[n]["votes"] for n in live_nominated)
        if max_votes > 0:
            leaders = [n for n in live_nominated if slots[n]["votes"] == max_votes]

    # 1. Один лидер — его заголосовали
    if len(leaders) == 1:
        leader = leaders[0]
        slots[leader]["alive"] = False
        slots[leader]["status_reason"] = "Заголосован"

        for n in live_nominated:
            slots[n]["nominated"] = False
            slots[n]["votes"] = 0

        await state.update_data(
            slots=slots,
            nominated_list=[],
            vote_index=0,
            in_split=False,
            split_candidates=[],
        )

        summary = build_votes_summary(slots)
        game_state = build_game_state(slots, alive_only=False)

        await message.answer(
            summary + "\n\n" + game_state,
            reply_markup=keyboards.game_admin_menu(),
        )
        await state.set_state(GameCreateState.editing_slots)
        return

    # 2. Несколько лидеров с одинаковым max_votes > 0
    if len(leaders) > 1:
        leaders_sorted = sorted(leaders)
        leaders_text = ", ".join(str(n) for n in leaders_sorted)

        if not in_split:
            # Первый попил — объявляем и готовим переголосовку
            for n in live_nominated:
                slots[n]["votes"] = 0

            for s, info in slots.items():
                info["nominated"] = s in leaders

            await state.update_data(
                slots=slots,
                nominated_list=leaders_sorted,
                vote_index=0,
                in_split=True,
                split_candidates=leaders_sorted,
            )

            game_state = build_game_state(slots, alive_only=False)
            await message.answer(
                f"ПОПИЛ МЕЖДУ ИГРОКАМИ: {leaders_text}\n"
                f"У каждого оправдательная речь, затем переголосование только между ними.\n\n"
                f"{game_state}",
                reply_markup=keyboards.game_admin_menu(),
            )
            await state.set_state(GameCreateState.editing_slots)
            return
        else:
            # ВТОРОЙ ПОПИЛ — спрашиваем, что делать
            await state.update_data(
                slots=slots,
                split_candidates=leaders_sorted,
                nominated_list=leaders_sorted,
                vote_index=0,
                in_split=False,  # цикл переголосовок закончен, ждём решения
            )

            game_state = build_game_state(slots, alive_only=False)
            await message.answer(
                "Повторный попил: голоса снова поровну.\n"
                f"Игроки: {leaders_text}\n"
                "Что делаем?",
                reply_markup=keyboards.split_decision_keyboard(),
            )
            await state.set_state(GameCreateState.editing_slots)
            return

    # 3. max_votes == 0 или live_nominated пуст — никто не заголосован
    for n in live_nominated:
        slots[n]["nominated"] = False
        slots[n]["votes"] = 0

    await state.update_data(
        slots=slots,
        nominated_list=[],
        vote_index=0,
        in_split=False,
        split_candidates=[],
    )

    game_state = build_game_state(slots, alive_only=False)
    await message.answer(
        "Никто не был заголосован по итогам голосования.\n\n" + game_state,
        reply_markup=keyboards.game_admin_menu(),
    )
    await state.set_state(GameCreateState.editing_slots)


# ===== РЕШЕНИЕ ПО ВТОРОМУ ПОПИЛУ =====

@router.callback_query(F.data == "split:kill_all")
async def split_kill_all(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}
    split_candidates: list[int] = data.get("split_candidates") or []

    live_candidates = [
        n for n in split_candidates
        if n in slots and slots[n].get("alive", True)
    ]

    for n in live_candidates:
        slots[n]["alive"] = False
        slots[n]["status_reason"] = "Заголосован"
        slots[n]["nominated"] = False
        slots[n]["votes"] = 0

    await state.update_data(
        slots=slots,
        nominated_list=[],
        vote_index=0,
        in_split=False,
        split_candidates=[],
    )

    game_state = build_game_state(slots, alive_only=False)

    # редактируем старое сообщение, убираем инлайн-кнопки
    await callback.message.edit_text(
        "Решение: Поднять всех.\n"
        "Все игроки из попила заголосованы."
    )
    # новое сообщение с таблицей и обычным меню
    await callback.message.answer(
        game_state,
        reply_markup=keyboards.game_admin_menu(),
    )

    await callback.answer()


@router.callback_query(F.data == "split:keep_all")
async def split_keep_all(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}
    split_candidates: list[int] = data.get("split_candidates") or []

    live_candidates = [
        n for n in split_candidates
        if n in slots and slots[n].get("alive", True)
    ]

    for n in live_candidates:
        slots[n]["nominated"] = False
        slots[n]["votes"] = 0

    await state.update_data(
        slots=slots,
        nominated_list=[],
        vote_index=0,
        in_split=False,
        split_candidates=[],
    )

    game_state = build_game_state(slots, alive_only=False)

    await callback.message.edit_text(
        "Решение: Никого не заголосовывать.\n"
        "Все игроки из попила остаются в игре."
    )
    await callback.message.answer(
        game_state,
        reply_markup=keyboards.game_admin_menu(),
    )

    await callback.answer()


# ===== НОЧНОЙ ВЫСТРЕЛ: КНОПКА "УБИТЬ" =====

@router.message(GameCreateState.editing_slots, F.text.casefold() == "убить")
async def ask_night_kill_slot(message: types.Message, state: FSMContext):
    """
    Старт ночного убийства: просим ввести номер слота, кого убили ночью.
    """
    await state.set_state(GameCreateState.waiting_kill_slot)
    await message.answer(
        "Кого убили ночью?\n"
        "Введи номер слота (например: `5`).",
        reply_markup=keyboards.game_admin_menu(),
    )


@router.message(GameCreateState.waiting_kill_slot)
async def handle_night_kill_slot(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}
    first_night_kill_recorded: bool = data.get("first_night_kill_recorded", False)

    text = message.text.strip()
    try:
        slot_num = int(text)
    except ValueError:
        await message.answer(
            "Нужно ввести номер слота (одно число). Пример: `5`.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    if slot_num not in slots:
        await message.answer(
            f"Слота №{slot_num} нет в текущем списке.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    slot = slots[slot_num]
    if not slot.get("alive", True):
        await message.answer(
            f"Слот {slot_num} уже не в игре.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    # помечаем как убитого ночью
    slot["alive"] = False
    slot["status_reason"] = "Убит ночью"

    await state.update_data(slots=slots)

    # показываем обновлённое состояние
    game_state = build_game_state(slots, alive_only=False)
    await message.answer(
        f"Слот {slot_num} убит ночью.\n\n{game_state}",
        reply_markup=keyboards.game_admin_menu(),
    )

    # если это ПЕРВЫЙ убитый ночью за игру — даём право назвать 3 подозрительных
    if not first_night_kill_recorded:
        await state.update_data(
            first_night_kill_recorded=True,
            night_killed_slot=slot_num,
        )
        await state.set_state(GameCreateState.waiting_night_suspects)
        await message.answer(
            "У первого убитого ночью есть право назвать ДО 3 подозрительных игроков.\n\n"
            "Введи номера слотов через пробел (например: `2 5 7`).\n"
            "Если он никого не называет — просто отправь `0`.",
            reply_markup=keyboards.game_admin_menu(),
        )
    else:
        # остальные ночные жертвы — без права слова
        await state.set_state(GameCreateState.editing_slots)


@router.message(GameCreateState.waiting_night_suspects)
async def handle_night_suspects(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}
    killed_slot: int | None = data.get("night_killed_slot")

    if killed_slot is None or killed_slot not in slots:
        # что-то пошло не так, просто вернёмся в игру
        await state.set_state(GameCreateState.editing_slots)
        await message.answer(
            "Что-то пошло не так с записью подозрительных игроков.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    text = message.text.strip()

    if text == "0":
        suspects: list[int] = []
    else:
        nums = _parse_slots_list(text)
        suspects = [
            n for n in nums
            if n in slots and n != killed_slot
        ][:3]  # максимум 3

    slots[killed_slot]["night_suspects"] = suspects

    await state.update_data(
        slots=slots,
        night_killed_slot=None,
    )
    await state.set_state(GameCreateState.editing_slots)

    if suspects:
        suspects_text = ", ".join(str(n) for n in suspects)
        msg = (
            f"Слот {killed_slot} перед смертью назвал подозрительных игроков: {suspects_text}.\n"
            f"Информация сохранена."
        )
    else:
        msg = (
            f"Слот {killed_slot} никого не назвал.\n"
            f"Информация сохранена."
        )

    game_state = build_game_state(slots, alive_only=False)

    await message.answer(
        msg + "\n\n" + game_state,
        reply_markup=keyboards.game_admin_menu(),
    )


# ===== МАСТЕР РАЗДАЧИ РОЛЕЙ =====

@router.message(GameCreateState.editing_slots, F.text.casefold() == "ок")
async def handle_ok(message: types.Message, state: FSMContext):
    data = await state.get_data()
    roles_assigned = data.get("roles_assigned", False)
    slots: dict[int, dict] = data.get("slots") or {}

    if not slots:
        await message.answer(
            "Слоты пустые, делать нечего.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    if not roles_assigned:
        if len(slots) < 4:
            await message.answer(
                "Для классической раздачи (2 мафии, дон, шериф) нужно минимум 4 игрока.",
                reply_markup=keyboards.game_admin_menu(),
            )
            return

        await state.set_state(GameCreateState.choosing_mafia)
        await message.answer(
            "Шаг 1.\nВведи НОМЕРА двух мафий (через пробел или запятую).\nНапример: 2 7",
            reply_markup=keyboards.game_admin_menu(),
        )
    else:
        text = build_game_state(slots, alive_only=False)
        await message.answer(text, reply_markup=keyboards.game_admin_menu())


@router.message(GameCreateState.choosing_mafia)
async def choose_mafia(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}

    numbers = _parse_slots_list(message.text)
    if len(numbers) != 2:
        await message.answer(
            "Нужно указать РОВНО два разных номера слотов для мафии.\n"
            "Пример: 2 7",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    for n in numbers:
        if n not in slots or n < 1 or n > 10:
            await message.answer(
                f"Слот №{n} не найден. Используй существующие слоты от 1 до 10.",
                reply_markup=keyboards.game_admin_menu(),
            )
            return

    mafia1, mafia2 = numbers
    if mafia1 == mafia2:
        await message.answer(
            "Нужно указать ДВА РАЗНЫХ слота для мафии.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    data["mafia_slots"] = numbers
    await state.update_data(data)

    await state.set_state(GameCreateState.choosing_don)
    await message.answer(
        f"Мафия: слоты {mafia1} и {mafia2}.\n\n"
        "Шаг 2.\nВведи номер ДОНа (отличный от мафии).",
        reply_markup=keyboards.game_admin_menu(),
    )


@router.message(GameCreateState.choosing_don)
async def choose_don(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}
    mafia_slots: list[int] = data.get("mafia_slots", [])

    numbers = _parse_slots_list(message.text)
    if len(numbers) != 1:
        await message.answer(
            "Нужно указать ОДИН номер слота для дона.\nПример: 5",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    don_slot = numbers[0]

    if don_slot not in slots or don_slot < 1 or don_slot > 10:
        await message.answer(
            f"Слот №{don_slot} не найден. Используй существующие слоты от 1 до 10.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    if don_slot in mafia_slots:
        await message.answer(
            "Дон не может совпадать с мафией. Укажи другой слот.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    data["don_slot"] = don_slot
    await state.update_data(data)

    await state.set_state(GameCreateState.choosing_sheriff)
    await message.answer(
        f"Дон: слот {don_slot}.\n\n"
        "Шаг 3.\nВведи номер ШЕРИФА (не мафия и не дон).",
        reply_markup=keyboards.game_admin_menu(),
    )


@router.message(GameCreateState.choosing_sheriff)
async def choose_sheriff(message: types.Message, state: FSMContext):
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}
    mafia_slots: list[int] = data.get("mafia_slots", [])
    don_slot: int | None = data.get("don_slot")

    numbers = _parse_slots_list(message.text)
    if len(numbers) != 1:
        await message.answer(
            "Нужно указать ОДИН номер слота для шерифа.\nПример: 4",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    sheriff_slot = numbers[0]

    if sheriff_slot not in slots or sheriff_slot < 1 or sheriff_slot > 10:
        await message.answer(
            f"Слот №{sheriff_slot} не найден. Используй существующие слоты от 1 до 10.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    if sheriff_slot in mafia_slots or sheriff_slot == don_slot:
        await message.answer(
            "Шериф должен быть отдельным игроком (не мафия и не дон). Укажи другой слот.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    for slot_num, info in slots.items():
        info["role"] = "Мирный"
        info["team"] = "Красные"

    for m in mafia_slots:
        slots[m]["role"] = "Мафия"
        slots[m]["team"] = "Чёрные"

    if don_slot is not None:
        slots[don_slot]["role"] = "Дон"
        slots[don_slot]["team"] = "Чёрные"

    slots[sheriff_slot]["role"] = "Шериф"
    slots[sheriff_slot]["team"] = "Красные"

    await state.update_data(slots=slots, roles_assigned=True)

    summary = build_roles_summary(slots)

    await message.answer(
        summary,
        reply_markup=keyboards.game_admin_menu(),
    )
    await state.set_state(GameCreateState.editing_slots)


# ===== CATCH-ALL ВО ВРЕМЯ ИГРЫ =====

@router.message(GameCreateState.editing_slots)
async def catch_all_in_game(message: types.Message, state: FSMContext):
    """
    Ловим любой произвольный текст во время игры и просто показываем текущее состояние + кнопки.
    Это гарантирует, что клавиатура всегда останется на экране,
    даже если ты написал что-то произвольное.
    """
    data = await state.get_data()
    slots: dict[int, dict] = data.get("slots") or {}

    if not slots:
        await message.answer(
            "Слоты пустые. Нажми «🎲 Новая игра», чтобы начать новую партию.",
            reply_markup=keyboards.game_admin_menu(),
        )
        return

    text = build_game_state(slots, alive_only=False)
    await message.answer(
        text,
        reply_markup=keyboards.game_admin_menu(),
    )