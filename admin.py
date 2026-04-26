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
from handlers.booking import build_stats_text, get_next_friday

router = Router()
bot: Bot | None = None


# =========================================================
# 1. ОБЩИЕ ВСПОМОГАТЕЛЬНЫЕ ШТУКИ
# =========================================================

class DebtEditState(StatesGroup):
    waiting_for_amount = State()


def setup_admin_handlers(bot_instance: Bot):
    global bot
    bot = bot_instance


def _is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


async def _is_judge(user_id: int) -> bool:
    if _is_admin(user_id):
        return True
    judges = await database.get_game_judges()
    return user_id in judges


async def get_player_games_count_for_evening(user_id: int, game_date: str) -> int:
    """
    Возвращает количество игр, которые игрок сыграл в указанную дату
    """
    async with database.get_db() as conn:
        async with conn.execute("""
            SELECT COUNT(DISTINCT game_number)
            FROM game_slots_history
            WHERE user_id = ? AND game_date = ?
        """, (user_id, game_date)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


def calculate_evening_cost(games_count: int) -> int:
    """
    Рассчитывает стоимость вечера:
    - 100₽ за игру
    - Максимум 400₽
    """
    return min(games_count * 100, 400)


# =========================================================
# 2. ВХОД В АДМИН-ПАНЕЛЬ
# =========================================================

@router.message(Command("admin"), F.chat.type == "private")
async def admin_panel(message: types.Message):
    if not _is_admin(message.from_user.id):
        return
    await message.answer(
        "🛠 Панель администратора.\nВыбери действие на клавиатуре ниже 👇",
        reply_markup=keyboards.admin_menu(),
    )


@router.message(F.text.in_(["🛠 Админ-панель", "🛠 Перейти в админ-панель"]), F.chat.type == "private")
async def admin_panel_unified(message: types.Message):
    if not _is_admin(message.from_user.id):
        await message.answer(
            "⛔ Эта кнопка доступна только администраторам.",
            reply_markup=keyboards.main_menu_judge()
            if await _is_judge(message.from_user.id)
            else keyboards.main_menu()
        )
        return
    await message.answer(
        "🛠 Панель администратора.\nВыбери действие на клавиатуре ниже 👇",
        reply_markup=keyboards.admin_menu(),
    )


# =========================================================
# 3. МЕНЮ СПИСКОВ
# =========================================================

@router.message(F.text == "📋 Игроки", F.chat.type == "private")
async def show_players_btn(message: types.Message):
    user_id = message.from_user.id
    is_admin = _is_admin(user_id)
    is_judge = await _is_judge(user_id)
    if not is_admin and not is_judge:
        return
    date_str = get_next_friday()
    text = await build_stats_text(date_str)
    if "всего 0" in text:
        await message.answer(f"На ближайший вечер {date_str} пока никто не записался.")
        return
    reply_kb = keyboards.admin_menu() if is_admin else keyboards.judge_menu()
    await message.answer(text, reply_markup=reply_kb)


@router.message(F.text == "👥 Все пользователи", F.chat.type == "private")
async def admin_all_users_btn(message: types.Message):
    if not _is_admin(message.from_user.id):
        return
    users = await database.get_all_users_stat()
    if not users:
        await message.answer("База пользователей пуста")
        return
    text = "👥 **База игроков:**\n\n"
    for name, nick, visit, debt, total_paid, *_ in users:
        if not visit or visit == "-":
            visit_text = "Ещё не был на вечерах"
        else:
            visit_text = visit
        total_paid = total_paid or 0
        text += f"▪️ {name} ({nick})\n   Визит: {visit_text} | Долг: {debt}₽ | Всего оплачено: {total_paid}₽\n\n"
    top_players = await database.get_top_players_by_visits(limit=10)
    if top_players:
        text += "🏆 **Топ по посещениям:**\n"
        for i, (full_name, nickname, visits_count) in enumerate(top_players, 1):
            nick_part = nickname if nickname not in (None, "", "Не установлен") else "ник не указан"
            text += f"{i}. {full_name} ({nick_part}) — {visits_count} вечеров\n"
        text += "\n"
    inactive_raw = await database.get_inactive_players()
    threshold_days = 30
    now = datetime.utcnow()
    inactive_players = []
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
    await message.answer(text, reply_markup=keyboards.admin_menu(), parse_mode="Markdown")


# =========================================================
# 4. ФИНАЛ ВЕЧЕРА: СЧЕТА / ОТМЕНА / АНОНСЫ
# =========================================================

@router.message(F.text == "💸 Разослать счета", F.chat.type == "private")
async def admin_send_bills_btn(message: types.Message):
    """
    Разослать счета всем игрокам, участвовавшим в вечере.
    Сумма зависит от количества сыгранных игр.
    """
    if not _is_admin(message.from_user.id):
        return

    assert bot is not None

    date_str = get_next_friday()

    # Получаем ТОЛЬКО пришедших игроков
    players = await database.get_booked_players_for_game()

    if not players:
        await message.answer("Нет игроков, которые пришли на игру.")
        return

    kb = keyboards.user_pay_now_kb()
    count = 0
    failed_users = []
    bills_info = []

    # Рассылаем счета
    for player in players:
        try:
            p_id = player[0]
            if await database.has_unpaid_session(p_id):
                continue

            # Подсчитываем количество игр игрока за этот вечер
            games_played = await get_player_games_count_for_evening(p_id, date_str)
            cost = calculate_evening_cost(games_played)

            if cost == 0:
                continue

            await database.change_user_debt(p_id, -cost)
            await database.set_unpaid_session(p_id, 1)

            # Получаем имя игрока для отчёта
            user_info = await database.get_user_by_id(p_id)
            name = user_info[3] or user_info[1] if user_info else str(p_id)
            bills_info.append(f"• {name}: {games_played} игр → {cost}₽")

            await bot.send_message(
                p_id,
                f"🎭 Игры окончены!\n\n"
                f"Вы сыграли {games_played} игр.\n"
                f"Сумма к оплате: {cost}₽ (100₽ за игру, максимум 400₽)",
                reply_markup=kb,
            )
            count += 1
        except Exception as e:
            print(f"[BILLS] Error for user {player}: {e}")
            failed_users.append(player[0])
            continue

    # ========== АРХИВАЦИЯ ВЕЧЕРА И УСТАНОВКА ФЛАГА ==========
    try:
        await database.archive_current_evening()
        await database.set_setting("evening_archived", "1")
        await database.mark_evening_bills_sent(date_str)

        # Отправляем отчёт админу
        report = f"✅ Счета разосланы {count} игрокам.\n\n"
        if bills_info:
            report += "📊 **Детали:**\n" + "\n".join(bills_info) + "\n\n"
        report += f"🗄 Вечер сохранён в истории.\n"
        report += f"🗑 Текущий список записей очищен.\n"
        report += f"📅 Следующий вечер будет на {get_next_friday()}"

        await message.answer(report)
    except Exception as e:
        await message.answer(f"❌ Ошибка при архивации вечера: {e}")
        return
    # ========================================================

    if failed_users:
        await message.answer(f"⚠️ Не удалось отправить счёт пользователям: {failed_users}")

    await message.answer(
        "🛠 Панель администратора.",
        reply_markup=keyboards.admin_menu(),
    )


@router.message(F.text == "❌ Отменить вечер", F.chat.type == "private")
async def admin_cancel_evening(message: types.Message):
    if not _is_admin(message.from_user.id):
        return
    assert bot is not None
    players = await database.get_all_players()
    if not players:
        await message.answer("Список игроков пуст — никто не записан.")
        return
    text = (
        "❌ Вечер мафии отменен.\n"
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
        f"Вечер отменен.\nУведомление отправлено {sent} игрокам.\nЗаписи на вечер очищены.",
        reply_markup=keyboards.admin_menu(),
    )


@router.message(F.text == "📣 Сделать анонс", F.chat.type == "private")
async def admin_announce_evening(message: types.Message, bot: Bot):
    if not _is_admin(message.from_user.id):
        return
    users = await database.get_all_user_ids()
    if not users:
        await message.answer("В базе пока нет пользователей.")
        return
    date_str = get_next_friday()
    me = await bot.get_me()
    bot_username = me.username
    players_link = f"https://t.me/{bot_username}?start=players"
    text = (
        f"📣 Анонс вечера мафии!\n\n"
        f"Приглашаем тебя поиграть в мафию в пятницу {date_str} в 20:00.\n"
        f"Выбери, придёшь ли ты на игру:\n\n"
        f"📋 Список записавшихся игроков: {players_link}"
    )
    sent = 0
    for (u_id,) in users:
        try:
            await bot.send_message(u_id, text, reply_markup=keyboards.booking_kb())
            sent += 1
        except Exception:
            continue
    try:
        stats_info = await database.get_stats_message(date_str)
        if stats_info:
            chat_id, msg_id = stats_info
            try:
                await bot.delete_message(chat_id, msg_id)
            except Exception:
                pass
            await database.set_stats_message(date_str, 0, 0)
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
        await database.set_stats_message(date_str, config.GROUP_ID, stats_msg.message_id)
    except Exception as e:
        print(f"[ANNOUNCE] Failed to send to group: {e}")
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
    if not _is_admin(message.from_user.id):
        return
    debtors = await database.get_debtors()
    if not debtors:
        await message.answer("Сейчас нет должников 🎉")
        return
    import re
    def escape_md(text):
        if not text:
            return ""
        special_chars = r'([_*\[\]()~`>#+\-=|{}.!])'
        return re.sub(special_chars, r'\\\1', str(text))
    for full_name, nickname, username, debt, user_id in debtors:
        user_link = f"@{username}" if username else "нет ника"
        nick_part = nickname if nickname not in (None, "", "Не установлен") else "ник не указан"
        safe_full_name = escape_md(full_name)
        safe_nick_part = escape_md(nick_part)
        safe_user_link = escape_md(user_link)
        text = f"👤 {safe_full_name} ({safe_user_link})\nНик: {safe_nick_part}\nТекущий долг: {abs(debt)}₽"
        kb = InlineKeyboardBuilder()
        kb.button(text="✏️ Изменить сумму", callback_data=f"editdebt_{user_id}")
        kb.adjust(1)
        await message.answer(text, reply_markup=kb.as_markup(), parse_mode="Markdown")


@router.callback_query(F.data.startswith("editdebt_"))
async def admin_edit_debt_start(call: CallbackQuery, state: FSMContext):
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
    if not _is_admin(message.from_user.id):
        return
    data = await state.get_data()
    user_id = data.get("edit_debt_user_id")
    if not user_id:
        await message.answer("❌ Не найден пользователь для изменения долга. Попробуйте снова.")
        await state.clear()
        return
    try:
        amount = int((message.text or "").strip())
    except ValueError:
        await message.answer("❌ Нужно ввести целое число (например, 200 или 0). Попробуй ещё раз.")
        return
    user_exists = await database.get_user_by_id(user_id)
    if not user_exists:
        await message.answer(f"❌ Пользователь с ID {user_id} не найден в базе.")
        await state.clear()
        return
    new_debt = -amount
    await database.set_user_debt(user_id, new_debt)
    if amount == 0:
        await database.set_unpaid_session(user_id, 0)
    user_info = await database.get_user_by_id(user_id)
    name = user_info[3] or user_info[1] if user_info else str(user_id)
    await message.answer(
        f"✅ Долг для пользователя {name} обновлён.\nНовая сумма: {amount}₽.",
        reply_markup=keyboards.admin_menu(),
    )
    await state.clear()


# =========================================================
# 6. ИСТОРИЯ ВЕЧЕРОВ
# =========================================================

@router.message(F.text == "📚 История вечеров", F.chat.type == "private")
async def admin_history_menu(message: types.Message):
    if not _is_admin(message.from_user.id):
        return
    evenings = await database.get_evenings_list(limit=10)
    if not evenings:
        await message.answer("История вечеров пока пуста.")
        return
    kb = keyboards.evenings_history_kb(evenings)
    await message.answer("📚 Выберите вечер, чтобы посмотреть список игроков:", reply_markup=kb)


@router.callback_query(F.data.startswith("hist_"))
async def admin_history_detail(call: CallbackQuery):
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
        text += f"{i}. {full_name} ({nick_part}) — _{status}_ — оплатил: {amount_text}\n"
        if amount:
            total_amount += amount
    text += f"\n💰 Сумма за вечер: {total_amount}₽"
    await call.message.answer(text, parse_mode="Markdown")
    await call.answer()


def stats_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔍 Найти игрока", callback_data="search_player")
    builder.button(text="📖 Книга ачивок", callback_data="achievements_menu")
    builder.adjust(1)
    return builder.as_markup()