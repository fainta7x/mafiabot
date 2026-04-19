from datetime import datetime, timedelta
from typing import Optional, List, Tuple

from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.types import CallbackQuery
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
import database
import keyboards
from handlers.booking import build_stats_text, get_next_friday  # используется для анонсов / списка игроков

router = Router()
bot: Bot | None = None

# =========================================================
# ADMIN — АДМИНСКАЯ ПАНЕЛЬ И УПРАВЛЕНИЕ ВЕЧЕРОМ
#
# ОГЛАВЛЕНИЕ:
# 1. ОБЩИЕ ВСПОМОГАТЕЛЬНЫЕ ШТУКИ
#    - DebtEditState              — FSM для редактирования долга
#    - setup_admin_handlers       — сохранить инстанс Bot
#    - _is_admin                  — проверка прав администратора
#
# 2. ВХОД В АДМИН-ПАНЕЛЬ
#    - admin_panel                — команда /admin
#    - admin_panel_button         — кнопка "🛠 Перейти в админ-панель"
#
# 3. АДМИН-МЕНЮ (СПИСКИ ИГРОКОВ/ПОЛЬЗОВАТЕЛЕЙ)
#    - admin_show_players_btn     — "📋 Игроки" (запись на вечер)
#    - admin_all_users_btn        — "👥 Все пользователи"
#
# 4. ФИНАЛ ВЕЧЕРА: СЧЕТА / ОТМЕНА / АНОНСЫ
#    - admin_send_bills_btn       — "💸 Разослать счета"
#    - admin_cancel_evening       — "❌ Отменить вечер"
#    - admin_announce_evening     — "📣 Сделать анонс"
#
# 5. ДОЛЖНИКИ И РЕДАКТИРОВАНИЕ ДОЛГА
#    - admin_debtors_btn          — "💰 Должники"
#    - admin_edit_debt_start      — выбор должника, старт FSM
#    - admin_edit_debt_set_amount — ввод новой суммы долга
#
# 6. ИСТОРИЯ ВЕЧЕРОВ
#    - admin_history_menu         — "📚 История вечеров"
#    - admin_history_detail       — деталка по конкретной дате
# =========================================================


# =========================================================
# 1. ОБЩИЕ ВСПОМОГАТЕЛЬНЫЕ ШТУКИ
# =========================================================

class DebtEditState(StatesGroup):
    """
    FSM для редактирования суммы долга конкретного пользователя.
    """
    waiting_for_amount = State()


def setup_admin_handlers(bot_instance: Bot):
    """
    Сохраняем инстанс Bot для использования в админ-хендлерах
    (рассылка, анонсы, уведомления).
    """
    global bot
    bot = bot_instance


def _is_admin(user_id: int) -> bool:
    """
    Проверка, является ли пользователь администратором.
    """
    return user_id in config.ADMIN_IDS


# =========================================================
# 2. ВХОД В АДМИН-ПАНЕЛЬ
# =========================================================

@router.message(Command("admin"), F.chat.type == "private")
async def admin_panel(message: types.Message):
    """
    Команда /admin — вход в админ-панель (только для админов).
    """
    if not _is_admin(message.from_user.id):
        return

    await message.answer(
        "🛠 Панель администратора.\nВыбери действие на клавиатуре ниже 👇",
        reply_markup=keyboards.admin_menu(),
    )


@router.message(F.text.in_(["🛠 Админ-панель", "🛠 Перейти в админ-панель"]), F.chat.type == "private")
async def admin_panel_unified(message: types.Message):
    """
    Общий обработчик для всех вариантов входа в админ-панель.
    """
    if not _is_admin(message.from_user.id):
        await message.answer(
            "⛔ Эта кнопка доступна только администраторам.",
            reply_markup=keyboards.main_menu()
        )
        return

    await message.answer(
        "🛠 Панель администратора.\nВыбери действие на клавиатуре ниже 👇",
        reply_markup=keyboards.admin_menu(),
    )


# =========================================================
# 3. АДМИН-МЕНЮ (СПИСКИ ИГРОКОВ/ПОЛЬЗОВАТЕЛЕЙ)
# =========================================================

@router.message(F.text == "📋 Игроки", F.chat.type == "private")
async def admin_show_players_btn(message: types.Message):
    """
    Админский список игроков на ближайший вечер —
    в том же виде, как в анонсе (build_stats_text).
    """
    if not _is_admin(message.from_user.id):
        return

    date_str = get_next_friday()
    text = await build_stats_text(date_str)

    if "всего 0" in text:
        await message.answer(f"На ближайший вечер {date_str} пока никто не записался.")
        return

    await message.answer(
        text,
        reply_markup=keyboards.admin_menu(),
    )


@router.message(F.text == "👥 Все пользователи", F.chat.type == "private")
async def admin_all_users_btn(message: types.Message):
    """
    Полная база пользователей:
      - имя, ник, последний визит, долг, всего оплачено;
      - топ по посещениям;
      - кто давно не был.
    """
    if not _is_admin(message.from_user.id):
        return

    users = await database.get_all_users_stat()
    if not users:
        await message.answer("База пользователей пуста")
        return

    text = "👥 **База игроков:**\n\n"
    for name, nick, visit, debt, total_paid in users:
        if not visit or visit == "-":
            visit_text = "Ещё не был на вечерах"
        else:
            visit_text = visit

        total_paid = total_paid or 0
        text += (
            f"▪️ {name} ({nick})\n"
            f"   Визит: {visit_text} | Долг: {debt}₽ | Всего оплачено: {total_paid}₽\n\n"
        )

    # Топ по посещениям
    top_players = await database.get_top_players_by_visits(limit=10)
    if top_players:
        text += "🏆 **Топ по посещениям:**\n"
        for i, (full_name, nickname, visits_count) in enumerate(top_players, 1):
            nick_part = nickname if nickname not in (None, "", "Не установлен") else "ник не указан"
            text += f"{i}. {full_name} ({nick_part}) — {visits_count} вечеров\n"
        text += "\n"

    # Кто давно не был
    inactive_raw = await database.get_inactive_players()
    threshold_days = 30
    now = datetime.utcnow()
    inactive_players: List[Tuple[str, str, str]] = []

    for full_name, nickname, last_visit in inactive_raw:
        if not last_visit or last_visit == "-":
            inactive_players.append((full_name, nickname, "Ещё ни разу не был"))
            continue

        try:
            last_dt = datetime.strptime(last_visit, "%d.%m.%Y %H:%M")
        except ValueError:
            inactive_players.append((full_name, nickname, last_visit))
            continue

        diff_days = (now - last_dt).days
        if diff_days >= threshold_days:
            inactive_players.append((full_name, nickname, last_visit))

    if inactive_players:
        text += f"🕰 **Кто давно не был (>{threshold_days} дней):**\n"
        for full_name, nickname, visit_text in inactive_players:
            nick_part = nickname if nickname not in (None, "", "Не установлен") else "ник не указан"
            text += f"• {full_name} ({nick_part}) — последний визит: {visit_text}\n"

    await message.answer(
        text,
        reply_markup=keyboards.admin_menu(),
        parse_mode="Markdown",
    )


# =========================================================
# 4. ФИНАЛ ВЕЧЕРА: СЧЕТА / ОТМЕНА / АНОНСЫ
# =========================================================

@router.message(F.text == "💸 Разослать счета", F.chat.type == "private")
async def admin_send_bills_btn(message: types.Message):
    """
    Разослать счета всем игрокам, участвовавшим в вечере:
      - начислить долг,
      - пометить неоплаченную сессию,
      - отправить сообщение с кнопкой оплаты,
      - архивировать текущий вечер.
    """
    if not _is_admin(message.from_user.id):
        return

    assert bot is not None

    players = await database.get_all_players()
    if not players:
        await message.answer("Список игроков пуст!")
        return

    kb = keyboards.user_pay_now_kb()
    count = 0

    for (p_id,) in players:
        try:
            # Если уже есть неоплаченная сессия — не дублируем
            if await database.has_unpaid_session(p_id):
                continue

            await database.change_user_debt(p_id, -400)
            await database.set_unpaid_session(p_id, 1)

            await bot.send_message(
                p_id,
                "🎭 Игры окончены! Пожалуйста, оплатите участие.",
                reply_markup=kb,
            )
            count += 1
        except Exception:
            continue

    await database.archive_current_evening()

    await message.answer(
        f"✅ Счета разосланы {count} игрокам.\n"
        f"🗄 Вечер сохранён в истории.\n"
        f"🗑 Текущий список записей очищен.",
        reply_markup=keyboards.admin_menu(),
    )


@router.message(F.text == "❌ Отменить вечер", F.chat.type == "private")
async def admin_cancel_evening(message: types.Message):
    """
    Отменить текущий вечер:
      - разослать уведомление всем записанным игрокам,
      - продублировать в группу,
      - очистить записи на вечер.
    """
    if not _is_admin(message.from_user.id):
        return

    assert bot is not None

    players = await database.get_all_players()
    if not players:
        await message.answer("Список игроков пуст — никто не записан.")
        return

    text = (
        "❌ Вечер мафии отменён.\n"
        "Приносим извинения за неудобства.\n"
        "Следите за анонсами — пригласим вас на следующий вечер!"
    )

    sent = 0
    for (p_id,) in players:
        try:
            await bot.send_message(p_id, text)
            sent += 1
        except Exception:
            continue

    # Сообщение в группу анонсов
    try:
        await bot.send_message(
            config.GROUP_ID,
            text,
            message_thread_id=config.ANNOUNCE_TOPIC_ID,
        )
    except Exception:
        pass

    await database.clear_bookings()

    await message.answer(
        f"Вечер отменён.\n"
        f"Уведомление отправлено {sent} игрокам.\n"
        f"Записи на вечер очищены.",
        reply_markup=keyboards.admin_menu(),
    )


@router.message(F.text == "📣 Сделать анонс", F.chat.type == "private")
async def admin_announce_evening(message: types.Message):
    """
    Сделать анонс вечера:
      - личные сообщения всем пользователям,
      - пост в группе с inline-клавиатурой записи,
      - отдельное сообщение со статистикой (stats_message) для обновлений.
    """
    if not _is_admin(message.from_user.id):
        return

    assert bot is not None

    users = await database.get_all_user_ids()
    if not users:
        await message.answer("В базе пока нет пользователей.")
        return

    date_str = get_next_friday()

    me = await bot.get_me()
    bot_username = me.username  # без @

    players_link = f"https://t.me/{bot_username}?start=players"

    text = (
        f"📣 Анонс вечера мафии!\n\n"
        f"Приглашаем тебя поиграть в мафию в пятницу {date_str} в 20:00.\n"
        f"Выбери, придёшь ли ты на игру:\n\n"
        f"📋 Список записавшихся игроков: {players_link}"
    )

    # Рассылка в ЛС
    sent = 0
    for (u_id,) in users:
        try:
            await bot.send_message(
                u_id,
                text,
                reply_markup=keyboards.booking_kb(),
            )
            sent += 1
        except Exception:
            continue

    # Пост в группе + сообщение со статистикой
    try:
        await bot.send_message(
            config.GROUP_ID,
            text,
            reply_markup=keyboards.booking_kb(),
            message_thread_id=config.ANNOUNCE_TOPIC_ID,
        )

        stats_text = await build_stats_text(date_str)
        stats_msg = await bot.send_message(
            config.GROUP_ID,
            stats_text,
            message_thread_id=config.ANNOUNCE_TOPIC_ID,
        )

        await database.set_stats_message(
            date_str,
            config.GROUP_ID,
            stats_msg.message_id,
        )
    except Exception:
        pass

    if message.chat.type == "private":
        await message.answer(
            f"Анонс отправлен {sent} игрокам и в чат.",
            reply_markup=keyboards.admin_menu(),
        )


# =========================================================
# 5. ДОЛЖНИКИ И РЕДАКТИРОВАНИЕ СУММЫ ДОЛГА
# =========================================================

@router.message(F.text == "💰 Должники", F.chat.type == "private")
async def admin_debtors_btn(message: types.Message):
    """
    Показать список должников с кнопкой «✏️ Изменить сумму»
    для каждого (запускает FSM редактирования долга).
    """
    if not _is_admin(message.from_user.id):
        return

    debtors = await database.get_debtors()
    if not debtors:
        await message.answer("Сейчас нет должников 🎉")
        return

    for full_name, nickname, username, debt, user_id in debtors:
        user_link = f"@{username}" if username else "нет ника"
        nick_part = nickname if nickname not in (None, "", "Не установлен") else "ник не указан"
        text = (
            f"👤 {full_name} ({user_link})\n"
            f"Ник: {nick_part}\n"
            f"Текущий долг: {abs(debt)}₽"
        )

        kb = InlineKeyboardBuilder()
        kb.button(
            text="✏️ Изменить сумму",
            callback_data=f"editdebt_{user_id}",
        )
        kb.adjust(1)

        await message.answer(
            text,
            reply_markup=kb.as_markup(),
            parse_mode="Markdown",
        )


@router.callback_query(F.data.startswith("editdebt_"))
async def admin_edit_debt_start(call: CallbackQuery, state: FSMContext):
    """
    Старт редактирования долга:
      - сохраняем user_id должника в FSM,
      - переводим FSM в состояние ожидания суммы.
    """
    if not _is_admin(call.from_user.id):
        await call.answer("Недостаточно прав.", show_alert=True)
        return

    user_id_str = call.data.replace("editdebt_", "")
    try:
        user_id = int(user_id_str)
    except ValueError:
        await call.answer("Некорректный ID пользователя.", show_alert=True)
        return

    await state.update_data(edit_debt_user_id=user_id)
    await state.set_state(DebtEditState.waiting_for_amount)

    await call.message.answer(
        f"Введи новую сумму долга для пользователя {user_id} (в рублях).\n"
        f"Например: 200 или 0, чтобы закрыть долг."
    )
    await call.answer()


@router.message(DebtEditState.waiting_for_amount)
async def admin_edit_debt_set_amount(message: types.Message, state: FSMContext):
    """
    Обработка введённой суммы долга:
      - сохраняем новую сумму,
      - при 0 — снимаем флаг неоплаченной сессии.
    """
    if not _is_admin(message.from_user.id):
        return

    data = await state.get_data()
    user_id = data.get("edit_debt_user_id")
    if not user_id:
        await message.answer("Не найден пользователь для изменения долга.")
        await state.clear()
        return

    try:
        amount = int((message.text or "").strip())
    except ValueError:
        await message.answer(
            "Нужно ввести целое число (например, 200 или 0). Попробуй ещё раз."
        )
        return

    new_debt = -amount
    await database.set_user_debt(user_id, new_debt)

    if amount == 0:
        await database.set_unpaid_session(user_id, 0)

    await message.answer(
        f"Долг для пользователя {user_id} обновлён.\n"
        f"Новая сумма: {amount}₽.",
        reply_markup=keyboards.admin_menu(),
    )
    await state.clear()


# =========================================================
# 6. ИСТОРИЯ ВЕЧЕРОВ
# =========================================================

@router.message(F.text == "📚 История вечеров", F.chat.type == "private")
async def admin_history_menu(message: types.Message):
    """
    Показать список последних вечеров (даты) с кнопками.
    """
    if not _is_admin(message.from_user.id):
        return

    evenings = await database.get_evenings_list(limit=10)
    if not evenings:
        await message.answer("История вечеров пока пуста.")
        return

    kb = keyboards.evenings_history_kb(evenings)
    await message.answer(
        "📚 Выберите вечер, чтобы посмотреть список игроков:",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("hist_"))
async def admin_history_detail(call: CallbackQuery):
    """
    Подробности по конкретному вечеру:
      - список игроков, статус, сколько оплатил,
      - суммарная сумма за вечер.
    """
    if not _is_admin(call.from_user.id):
        await call.answer("Недостаточно прав.", show_alert=True)
        return

    date_str = call.data.replace("hist_", "")
    players = await database.get_evening_players(date_str)
    if not players:
        await call.answer("Для этого вечера нет записей.", show_alert=True)
        return

    text = f"📅 Вечер {date_str}\n\n"
    total_amount = 0

    for i, (full_name, nickname, status, amount) in enumerate(players, 1):
        nick_part = nickname if nickname not in (None, "", "Не установлен") else "ник не указан"
        amount_text = f"{amount}₽" if amount and amount > 0 else "—"
        text += (
            f"{i}. {full_name} ({nick_part}) — _{status}_ — оплатил: {amount_text}\n"
        )
        if amount:
            total_amount += amount

    text += f"\n💰 Сумма за вечер: {total_amount}₽"

    await call.message.answer(text, parse_mode="Markdown")
    await call.answer()