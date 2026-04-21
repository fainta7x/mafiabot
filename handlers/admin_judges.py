from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

import database
import keyboards
from config import ADMIN_IDS  # список админов

router = Router()


# ========== ВСПОМОГАТЕЛЬНАЯ ПРОВЕРКА ПРАВ АДМИНА ==========

async def ensure_admin_pm(message: Message) -> bool:
    """Проверка: сообщение от админа в ЛС с ботом."""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав администратора.")
        return False
    if message.chat.type != "private":
        await message.answer("⚠️ Управление судьями доступно только в личке с ботом.")
        return False
    return True


async def ensure_admin_cb(callback: CallbackQuery) -> bool:
    """Проверка: callback от админа в ЛС."""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ У вас нет прав администратора.", show_alert=True)
        return False
    if callback.message.chat.type != "private":
        await callback.answer("⚠️ Только в личке с ботом.", show_alert=True)
        return False
    return True


# ========== 1. ВХОД В МЕНЮ СУДЕЙ (КНОПКА '⚖ Судьи') ==========

@router.message(F.text == "⚖ Судьи")
async def open_judges_menu(message: Message):
    if not await ensure_admin_pm(message):
        return

    await message.answer(
        "⚖ **Управление судьями**\n\n"
        "Здесь можно назначать и снимать судей, которые имеют право вести игры.",
        reply_markup=keyboards.judges_menu_kb()
    )


# ========== 2. СПИСОК СУДЕЙ ==========

@router.callback_query(F.data == "judge_list")
async def show_judges_list(callback: CallbackQuery):
    if not await ensure_admin_cb(callback):
        return

    judge_ids = await database.get_game_judges()
    judges = []

    # Получаем имена судей из БД пользователей
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


# ========== 3. НАЧАТЬ НАЗНАЧЕНИЕ СУДЬИ ==========

@router.callback_query(F.data == "judge_add")
async def judge_add_start(callback: CallbackQuery):
    if not await ensure_admin_cb(callback):
        return

    await callback.message.edit_text(
        "➕ **Назначение судьи**\n\n"
        "Отправьте в этот чат:\n"
        "• либо *числовой* `user_id` пользователя,\n"
        "• либо его ник / имя из базы (например, `Иван` или игровой ник).\n\n"
        "Можно просто ответить на сообщение пользователя командой — тогда его ID возьмём автоматически.\n\n"
        "_После ввода я попрошу подтвердить назначение._",
        reply_markup=keyboards.judge_back_kb(),
        parse_mode="Markdown"
    )
    await callback.answer()


# ========== 4. ОБРАБОТКА СООБЩЕНИЯ С КАНДИДАТОМ В СУДЬИ ==========

@router.message(F.text.regexp(r"^\d+$"))
async def judge_add_by_id(message: Message):
    """
    Если админ написал только цифры — считаем, что это user_id.
    """
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


@router.message()
async def judge_add_by_name(message: Message):
    """
    Фолбэк: если текст не число и не совпал с другими хендлерами,
    пытаемся найти пользователя по нику / имени.
    Лучше будет, если этот хендлер подключён после остальных админских,
    чтобы не перехватывать лишнее.
    """
    if not await ensure_admin_pm(message):
        return

    text = (message.text or "").strip()
    if not text:
        return

    info = await database.get_user_by_nickname(text)
    if not info:
        await message.answer(
            f"❌ Пользователь с ником/именем `{text}` не найден в базе.\n"
            f"Попробуйте ввести *числовой* user_id или другой ник.",
            parse_mode="Markdown",
            reply_markup=keyboards.judge_back_kb()
        )
        return

    user_id, full_name, username, nickname = info
    display_name = nickname or full_name or (f"@{username}" if username else f"ID {user_id}")

    await message.answer(
        f"Найден пользователь:\n"
        f"• {display_name}\n"
        f"• ID: `{user_id}`\n\n"
        f"Назначить его судьёй?",
        parse_mode="Markdown",
        reply_markup=keyboards.judge_candidate_kb(user_id, display_name)
    )


# ========== 5. ПОДТВЕРЖДЕНИЕ НАЗНАЧЕНИЯ / ОТМЕНА ==========

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


# ========== 6. УДАЛЕНИЕ СУДЬИ ИЗ СПИСКА ==========

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

    # Обновляем список
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


# ========== 7. НАЗАД / ВЫХОД ИЗ МЕНЮ СУДЕЙ ==========

@router.callback_query(F.data == "judge_back")
async def judge_back(callback: CallbackQuery):
    if not await ensure_admin_cb(callback):
        return

    # ВАЖНО: вместо edit_text просто отправляем НОВОЕ сообщение,
    # чтобы никогда не ловить "message is not modified"
    await callback.message.answer(
        "⚖ Управление судьями.\n\nВыберите действие:",
        reply_markup=keyboards.judges_menu_kb()
    )
    await callback.answer()