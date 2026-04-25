from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

import database
import keyboards
from config import ADMIN_IDS  # список админов

router = Router()


# ========== ФУНКЦИИ ПРОВЕРКИ ПРАВ ==========

async def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь глобальным администратором"""
    return user_id in ADMIN_IDS


async def is_judge(user_id: int) -> bool:
    """Проверка, является ли пользователь судьёй"""
    judges = await database.get_game_judges()
    return user_id in judges


async def ensure_admin_pm(message: Message) -> bool:
    """Проверка прав для ДОСТУПА К АДМИН-ПАНЕЛИ (только глобальные админы)"""
    if not message.from_user:
        return False

    user_id = message.from_user.id

    if not await is_admin(user_id):
        await message.answer("⛔ У вас нет прав администратора для доступа к админ-панели.")
        return False

    return True


async def ensure_admin_cb(callback: CallbackQuery) -> bool:
    """Проверка прав для ДОСТУПА К АДМИН-ПАНЕЛИ (только глобальные админы)"""
    if not callback.from_user:
        return False

    user_id = callback.from_user.id

    if not await is_admin(user_id):
        await callback.answer("⛔ У вас нет прав администратора для доступа к админ-панели.", show_alert=True)
        return False

    return True


async def ensure_judge_or_admin_pm(message: Message) -> bool:
    """Проверка прав для ДОСТУПА К ПАНЕЛИ СУДЕЙ (админы или судьи)"""
    if not message.from_user:
        return False

    user_id = message.from_user.id

    if await is_admin(user_id) or await is_judge(user_id):
        return True

    await message.answer("⛔ У вас нет прав судьи для доступа к этой панели.")
    return False


async def ensure_judge_or_admin_cb(callback: CallbackQuery) -> bool:
    """Проверка прав для ДОСТУПА К ПАНЕЛИ СУДЕЙ (админы или судьи)"""
    if not callback.from_user:
        return False

    user_id = callback.from_user.id

    if await is_admin(user_id) or await is_judge(user_id):
        return True

    await callback.answer("⛔ У вас нет прав судьи для доступа к этой панели.", show_alert=True)
    return False


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ ПРОВЕРКИ СОСТОЯНИЯ ==========

async def _is_in_game_edit_state(state: FSMContext) -> bool:
    """
    Проверяет, находится ли бот в состоянии редактирования игры.
    """
    current_state = await state.get_state()
    if not current_state:
        return False

    # Проверяем все возможные состояния из profile.py и create_game.py
    game_states = [
        "EditGameState",        # Основное состояние ожидания ввода
        "GameCreateState",      # Состояния из game/state.py
        "waiting_for_value",    # FSM состояние ввода
    ]

    for game_state in game_states:
        if game_state in str(current_state):
            return True

    return False


# ========== 1. ВХОД В МЕНЮ СУДЕЙ (КНОПКА '⚖ Судьи') ==========

@router.message(F.text == "⚖ Судьи")
async def open_judges_menu(message: Message):
    if not await ensure_judge_or_admin_pm(message):
        return

    await message.answer(
        "⚖ **Панель судей**\n\n"
        "Здесь вы можете управлять игровыми процессами.",
        reply_markup=keyboards.judges_menu_kb()
    )


# ========== 2. СПИСОК СУДЕЙ (ТОЛЬКО ДЛЯ АДМИНОВ) ==========

@router.callback_query(F.data == "judge_list")
async def show_judges_list(callback: CallbackQuery):
    if not await ensure_admin_cb(callback):
        return

    judge_ids = await database.get_game_judges()
    judges = []

    for uid in judge_ids:
        info = await database.get_user_by_id(uid)
        if info:
            user_id, full_name, username, nickname = info
            display_name = nickname or full_name or f"ID {user_id}"
        else:
            user_id = uid
            display_name = f"ID {uid}"
        judges.append((user_id, display_name))

    text_lines = ["⚖ **Текущие судьи:**"]
    if not judges:
        text_lines.append("Пока никого нет.")
    else:
        for user_id, name in judges:
            text_lines.append(f"• {name} (`{user_id}`)")

    await callback.message.edit_text(
        "\n".join(text_lines),
        reply_markup=keyboards.judges_list_kb(judges),
        parse_mode="Markdown"
    )
    await callback.answer()


# ========== 3. НАЧАТЬ НАЗНАЧЕНИЕ СУДЬИ (ТОЛЬКО АДМИНЫ) ==========

@router.callback_query(F.data == "judge_add")
async def judge_add_start(callback: CallbackQuery):
    if not await ensure_admin_cb(callback):
        return

    await callback.message.edit_text(
        "➕ **Назначение судьи**\n\n"
        "Отправьте в этот чат:\n"
        "• либо *числовой* `user_id` пользователя,\n"
        "• либо его ник / имя из базы.\n\n"
        "_После ввода я попрошу подтвердить назначение._",
        reply_markup=keyboards.judge_back_kb(),
        parse_mode="Markdown"
    )
    await callback.answer()


# ========== 4. ОБРАБОТКА СООБЩЕНИЙ ДЛЯ НАЗНАЧЕНИЯ (ТОЛЬКО АДМИНЫ) ==========

@router.message(F.text.regexp(r"^\d+$"))
async def judge_add_by_id(message: Message, state: FSMContext):
    # ========== ВАЖНО: проверяем, не в режиме ли редактирования игры ==========
    if await _is_in_game_edit_state(state):
        # Если мы в игровом состоянии - игнорируем, не отвечаем
        return
    # ========================================================================

    if not await ensure_admin_pm(message):
        return

    user_id = int(message.text.strip())
    info = await database.get_user_by_id(user_id)
    if not info:
        await message.answer(
            f"❌ Пользователь с ID `{user_id}` не найден в базе.",
            parse_mode="Markdown",
            reply_markup=keyboards.judge_back_kb()
        )
        return

    _, full_name, username, nickname = info
    display_name = nickname or full_name or (f"@{username}" if username else f"ID {user_id}")

    await message.answer(
        f"Найден пользователь:\n"
        f"• {display_name}\n"
        f"• ID: `{user_id}`\n\n"
        f"Назначить его судьёй?",
        parse_mode="Markdown",
        reply_markup=keyboards.judge_candidate_kb(user_id, display_name)
    )


# ========== 5. ПОДТВЕРЖДЕНИЕ НАЗНАЧЕНИЯ / ОТМЕНА (ТОЛЬКО АДМИНЫ) ==========

@router.callback_query(F.data.startswith("judge_confirm_add_"))
async def judge_confirm_add(callback: CallbackQuery):
    if not await ensure_admin_cb(callback):
        return

    try:
        user_id = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.answer("Некорректный ID.", show_alert=True)
        return

    await database.add_game_judge(user_id)

    info = await database.get_user_by_id(user_id)
    if info:
        _, full_name, username, nickname = info
        display_name = nickname or full_name or (f"@{username}" if username else f"ID {user_id}")
    else:
        display_name = f"ID {user_id}"

    await callback.message.edit_text(
        f"✅ Пользователь {display_name} назначен судьёй.\n\n"
        f"Можно вернуться к списку судей.",
        parse_mode="Markdown",
        reply_markup=keyboards.judges_menu_kb()
    )
    await callback.answer("Судья добавлен.")


@router.callback_query(F.data == "judge_cancel_add")
async def judge_cancel_add(callback: CallbackQuery):
    if not await ensure_admin_cb(callback):
        return

    await callback.message.edit_text(
        "❌ Назначение судьи отменено.",
        reply_markup=keyboards.judges_menu_kb()
    )
    await callback.answer()


# ========== 6. УДАЛЕНИЕ СУДЬИ (ТОЛЬКО АДМИНЫ) ==========

@router.callback_query(F.data.startswith("judge_remove_"))
async def judge_remove(callback: CallbackQuery):
    if not await ensure_admin_cb(callback):
        return

    try:
        user_id = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.answer("Некорректный ID.", show_alert=True)
        return

    await database.remove_game_judge(user_id)

    judge_ids = await database.get_game_judges()
    judges = []
    for uid in judge_ids:
        info = await database.get_user_by_id(uid)
        if info:
            _uid, full_name, username, nickname = info
            display_name = nickname or full_name or f"ID {_uid}"
        else:
            _uid = uid
            display_name = f"ID {uid}"
        judges.append((_uid, display_name))

    text_lines = ["⚖ **Текущие судьи:**"]
    if not judges:
        text_lines.append("Пока никого нет.")
    else:
        for _uid, name in judges:
            text_lines.append(f"• {name} (`{_uid}`)")

    await callback.message.edit_text(
        "\n".join(text_lines),
        reply_markup=keyboards.judges_list_kb(judges),
        parse_mode="Markdown"
    )
    await callback.answer("Судья удалён.")


# ========== 7. НАЗАД / ВЫХОД ==========

@router.callback_query(F.data == "judge_back")
async def judge_back(callback: CallbackQuery):
    if not await ensure_admin_cb(callback):
        return

    await callback.message.answer(
        "⚖ Управление судьями.\n\nВыберите действие:",
        reply_markup=keyboards.judges_menu_kb()
    )
    await callback.answer()