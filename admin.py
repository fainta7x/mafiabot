from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.types import CallbackQuery
from datetime import datetime, timedelta
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
import database
import keyboards
from handlers.booking import build_stats_text  # чтобы использовать build_stats_text

router = Router()
bot: Bot | None = None


class DebtEditState(StatesGroup):
    waiting_for_amount = State()


def setup_admin_handlers(bot_instance: Bot):
    global bot
    bot = bot_instance


def get_next_friday_str() -> str:
    now = datetime.utcnow()
    days_ahead = (4 - now.weekday()) % 7 or 7  # пятница = 4
    return (now + timedelta(days=days_ahead)).strftime('%d.%m')


# ===== Вход в админ-панель =====

@router.message(Command("admin"), F.from_user.id == config.ADMIN_ID, F.chat.type == "private")
async def admin_panel(message: types.Message):
    await message.answer(
        "🛠 Панель администратора.\nВыбери действие на клавиатуре ниже 👇",
        reply_markup=keyboards.admin_menu()
    )


# ===== Админ-меню (reply-клавиатура) =====

@router.message(F.text == "📋 Игроки", F.from_user.id == config.ADMIN_ID, F.chat.type == "private")
async def admin_show_players_btn(message: types.Message):
    players = await database.get_booked_players_detailed()
    if not players:
        await message.answer("На игру пока никто не записался.")
        return

    text = "📋 **Список записанных игроков:**\n\n"
    for i, (name, username, nickname, status) in enumerate(players, 1):
        user_link = f"@{username}" if username else "нет ника"
        nick_part = nickname if nickname not in (None, "", "Не установлен") else "ник не указан"
        text += (
            f"{i}. {name} ({user_link})\n"
            f"   Ник: {nick_part} — _{status}_\n\n"
        )

    await message.answer(
        text,
        reply_markup=keyboards.admin_menu(),
        parse_mode="Markdown"
    )


@router.message(F.text == "👥 Все пользователи", F.from_user.id == config.ADMIN_ID, F.chat.type == "private")
async def admin_all_users_btn(message: types.Message):
    users = await database.get_all_users_stat()
    if not users:
        await message.answer("База пользователей пуста")
        return

    # Основная сводка по всем игрокам
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

    # ===== Топ по посещениям =====
    top_players = await database.get_top_players_by_visits(limit=10)
    if top_players:
        text += "🏆 **Топ по посещениям:**\n"
        for i, (full_name, nickname, visits_count) in enumerate(top_players, 1):
            nick_part = nickname if nickname not in (None, "", "Не установлен") else "ник не указан"
            text += f"{i}. {full_name} ({nick_part}) — {visits_count} вечеров\n"
        text += "\n"

    # ===== Давно не были =====
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

    await message.answer(
        text,
        reply_markup=keyboards.admin_menu(),
        parse_mode="Markdown"
    )


@router.message(F.text == "💸 Разослать счета", F.from_user.id == config.ADMIN_ID, F.chat.type == "private")
async def admin_send_bills_btn(message: types.Message):
    assert bot is not None
    players = await database.get_all_players()
    if not players:
        await message.answer("Список игроков пуст!")
        return

    kb = keyboards.user_pay_now_kb()
    count = 0
    for (p_id,) in players:
        try:
            if await database.has_unpaid_session(p_id):
                continue

            await database.change_user_debt(p_id, -400)
            await database.set_unpaid_session(p_id, 1)

            await bot.send_message(
                p_id,
                "🎭 Игры окончены! Пожалуйста, оплатите участие.",
                reply_markup=kb
            )
            count += 1
        except Exception:
            continue

    await database.archive_current_evening()

    await message.answer(
        f"✅ Счета разосланы {count} игрокам.\n"
        f"🗄 Вечер сохранён в истории.\n"
        f"🗑 Текущий список записей очищен.",
        reply_markup=keyboards.admin_menu()
    )


@router.message(F.text == "❌ Отменить вечер", F.from_user.id == config.ADMIN_ID, F.chat.type == "private")
async def admin_cancel_evening(message: types.Message):
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

    # отправляем уведомление в НУЖНУЮ ТЕМУ группы
    try:
        await bot.send_message(
            config.GROUP_ID,
            text,
            message_thread_id=config.ANNOUNCE_TOPIC_ID
        )
    except Exception:
        pass

    await database.clear_bookings()

    await message.answer(
        f"Вечер отменён.\n"
        f"Уведомление отправлено {sent} игрокам.\n"
        f"Записи на вечер очищены.",
        reply_markup=keyboards.admin_menu()
    )


@router.message(F.text == "📣 Сделать анонс", F.from_user.id == config.ADMIN_ID, F.chat.type == "private")
async def admin_announce_evening(message: types.Message):
    assert bot is not None

    users = await database.get_all_user_ids()
    if not users:
        await message.answer("В базе пока нет пользователей.")
        return

    date_str = get_next_friday_str()

    # динамически получаем username бота
    me = await bot.get_me()
    bot_username = me.username  # без @

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
            await bot.send_message(
                u_id,
                text,
                reply_markup=keyboards.booking_kb()
            )
            sent += 1
        except Exception:
            continue

    stats_msg_id = None

    # отправляем анонс и статистику в НУЖНУЮ ТЕМУ группы
    try:
        # сам анонс с кнопками в тему
        await bot.send_message(
            config.GROUP_ID,
            text,
            reply_markup=keyboards.booking_kb(),
            message_thread_id=config.ANNOUNCE_TOPIC_ID
        )

        # отдельное сообщение со статистикой в ту же тему
        stats_text = await build_stats_text(date_str)
        stats_msg = await bot.send_message(
            config.GROUP_ID,
            stats_text,
            message_thread_id=config.ANNOUNCE_TOPIC_ID
        )
        stats_msg_id = stats_msg.message_id

        # сохраняем id сообщения статистики
        await database.set_stats_message(
            date_str,
            config.GROUP_ID,
            stats_msg_id
        )
    except Exception:
        pass

    if message.chat.type == "private":
        await message.answer(
            f"Анонс отправлен {sent} игрокам и в чат.",
            reply_markup=keyboards.admin_menu()
        )