from datetime import datetime, timedelta
from typing import Optional, List, Tuple
import re

from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.types import CallbackQuery, FSInputFile, Message
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
import os
import config
import database
import keyboards
from handlers.booking import build_stats_text, get_next_friday

router = Router()
bot: Bot | None = None

# Константы для Эло
STARTING_ELO = 1500

# Категории ачивок
ACHIEVEMENTS = {
    # ========== ИГРОВЫЕ (games) ==========
    "first_game": {"name": "Первая игра", "description": "Сыграть первую игру", "icon": "🎭", "type": "games",
                   "value": 1},
    "ten_games": {"name": "Новичок", "description": "Сыграть 10 игр", "icon": "🌟", "type": "games", "value": 10},
    "twenty_games": {"name": "Любитель", "description": "Сыграть 20 игр", "icon": "🎲", "type": "games", "value": 20},
    "thirty_games": {"name": "Завсегдатай", "description": "Сыграть 30 игр", "icon": "🎯", "type": "games", "value": 30},
    "fifty_games": {"name": "Опытный игрок", "description": "Сыграть 50 игр", "icon": "⚡", "type": "games",
                    "value": 50},
    "seventy_games": {"name": "Профи", "description": "Сыграть 70 игр", "icon": "🎓", "type": "games", "value": 70},
    "hundred_games": {"name": "Ветеран", "description": "Сыграть 100 игр", "icon": "🔥", "type": "games", "value": 100},
    "one_fifty_games": {"name": "Мастер", "description": "Сыграть 150 игр", "icon": "🏆", "type": "games", "value": 150},
    "two_hundred_games": {"name": "Легенда", "description": "Сыграть 200 игр", "icon": "👑", "type": "games",
                          "value": 200},

    # ========== ПОБЕДНЫЕ (wins) ==========
    "first_win": {"name": "Первая победа", "description": "Одержать первую победу", "icon": "🏆", "type": "wins",
                  "value": 1},
    "five_wins": {"name": "Первые успехи", "description": "Одержать 5 побед", "icon": "🌱", "type": "wins", "value": 5},
    "ten_wins": {"name": "Серийный победитель", "description": "Одержать 10 побед", "icon": "🎯", "type": "wins",
                 "value": 10},
    "twenty_wins": {"name": "Закалка", "description": "Одержать 20 побед", "icon": "⚔️", "type": "wins", "value": 20},
    "thirty_wins": {"name": "Победный дух", "description": "Одержать 30 побед", "icon": "🎖️", "type": "wins",
                    "value": 30},
    "forty_wins": {"name": "Покоритель", "description": "Одержать 40 побед", "icon": "⭐", "type": "wins", "value": 40},
    "fifty_wins": {"name": "Мастер побед", "description": "Одержать 50 побед", "icon": "🏅", "type": "wins",
                   "value": 50},
    "seventy_wins": {"name": "Герой", "description": "Одержать 70 побед", "icon": "🦸", "type": "wins", "value": 70},
    "hundred_wins": {"name": "Легенда побед", "description": "Одержать 100 побед", "icon": "🏅", "type": "wins",
                     "value": 100},

    # ========== РЕЙТИНГОВЫЕ (rating) ==========
    "elo_1400": {"name": "Начало пути", "description": "Достичь рейтинга Эло 1400", "icon": "🌱", "type": "rating",
                 "value": 1400},
    "elo_1500": {"name": "Старт", "description": "Достичь рейтинга Эло 1500", "icon": "🌱", "type": "rating",
                 "value": 1500},
    "elo_1550": {"name": "Бронзовый рейтинг", "description": "Достичь рейтинга Эло 1550", "icon": "🥉", "type": "rating",
                 "value": 1550},
    "elo_1600": {"name": "Серебряный рейтинг", "description": "Достичь рейтинга Эло 1600", "icon": "⭐",
                 "type": "rating", "value": 1600},
    "elo_1650": {"name": "Золотой рейтинг", "description": "Достичь рейтинга Эло 1650", "icon": "⭐", "type": "rating",
                 "value": 1650},
    "elo_1700": {"name": "Платиновый рейтинг", "description": "Достичь рейтинга Эло 1700", "icon": "🏅",
                 "type": "rating", "value": 1700},
    "elo_1750": {"name": "Алмазный рейтинг", "description": "Достичь рейтинга Эло 1750", "icon": "💎", "type": "rating",
                 "value": 1750},
    "elo_1800": {"name": "Мастер Эло", "description": "Достичь рейтинга Эло 1800", "icon": "💎", "type": "rating",
                 "value": 1800},
    "elo_1900": {"name": "Элитный рейтинг", "description": "Достичь рейтинга Эло 1900", "icon": "👑", "type": "rating",
                 "value": 1900},

    # ========== СУДЕЙСКИЕ (judge) ==========
    "first_judge": {"name": "Первое свидание с правосудием", "description": "Отсудить первую игру", "icon": "⚖️",
                    "type": "judged", "value": 1},
    "five_judged": {"name": "Стажёр", "description": "Отсудить 5 игр", "icon": "📋", "type": "judged", "value": 5},
    "ten_judged": {"name": "Судья", "description": "Отсудить 10 игр", "icon": "👨‍⚖️", "type": "judged", "value": 10},
    "twenty_judged": {"name": "Мировой судья", "description": "Отсудить 20 игр", "icon": "🏛️", "type": "judged",
                      "value": 20},
    "fifty_judged": {"name": "Верховный судья", "description": "Отсудить 50 игр", "icon": "⚖️👑", "type": "judged",
                     "value": 50},

    # ========== РОЛЕВЫЕ (roles) ==========
    "sheriff_win": {"name": "Защитник города", "description": "Выиграть в роли Шерифа", "icon": "🕵️", "type": "role",
                    "value": "Шериф"},
    "mafia_win": {"name": "Тень", "description": "Выиграть в роли Мафии", "icon": "🔪", "type": "role",
                  "value": "Мафия"},
    "don_win": {"name": "Крёстный отец", "description": "Выиграть в роли Дона", "icon": "👑", "type": "role",
                "value": "Дон"},

    # ========== ОСОБЫЕ (special) ==========
    "pu_once": {"name": "В центре внимания", "description": "Стать ПУ в первый раз", "icon": "🎯", "type": "special",
                "value": 1},
    "pu_three": {"name": "Частая цель", "description": "Стать ПУ 3 раза", "icon": "🎪", "type": "special", "value": 3},
    "pu_master": {"name": "ПУ-мастер", "description": "Стать ПУ 5 раз", "icon": "👑", "type": "special", "value": 5},
    "pu_ten": {"name": "Легендарная жертва", "description": "Стать ПУ 10 раз", "icon": "🦁", "type": "special",
               "value": 10},
}


async def check_and_award_achievements(bot_instance: Bot, user_id: int = None):
    async with database.get_db() as conn:
        if user_id:
            players = [(user_id,)]
        else:
            async with conn.execute("SELECT user_id FROM users WHERE games_played > 0") as cur:
                players = await cur.fetchall()

        all_new_achievements = []
        for (u_id,) in players:
            async with conn.execute("SELECT nickname, games_played, games_won, elo FROM users WHERE user_id = ?",
                                    (u_id,)) as cur:
                player_data = await cur.fetchone()
                if not player_data: continue
                nickname, games_played, games_won, elo = player_data

            async with conn.execute("SELECT achievement_id FROM user_achievements WHERE user_id = ?", (u_id,)) as cur:
                earned = {row[0] for row in await cur.fetchall()}

            async with conn.execute("""
                                    SELECT s.role, COUNT(*) as wins
                                    FROM game_slots_history s
                                             JOIN game_history g
                                                  ON g.game_date = s.game_date AND g.game_number = s.game_number
                                    WHERE s.user_id = ?
                                      AND s.base_points >= 1
                                    GROUP BY s.role
                                    """, (u_id,)) as cur:
                role_wins = {row[0]: row[1] for row in await cur.fetchall()}

            async with conn.execute("SELECT COUNT(*) FROM game_slots_history WHERE user_id = ? AND pu = 1",
                                    (u_id,)) as cur:
                pu_count = (await cur.fetchone())[0] or 0

            async with conn.execute("SELECT COUNT(*) FROM game_history WHERE judge_id = ?", (u_id,)) as cur:
                judged_games = (await cur.fetchone())[0] or 0

            for ach_id, ach in ACHIEVEMENTS.items():
                if ach_id in earned: continue
                earned_ach = False
                if ach["type"] == "games":
                    earned_ach = games_played >= ach["value"]
                elif ach["type"] == "wins":
                    earned_ach = games_won >= ach["value"]
                elif ach["type"] == "rating":
                    earned_ach = (elo or 0) >= ach["value"]
                elif ach["type"] == "judged":
                    earned_ach = judged_games >= ach["value"]
                elif ach["type"] == "role":
                    earned_ach = role_wins.get(ach["value"], 0) >= 1
                elif ach["type"] == "special":
                    if ach_id == "pu_once":
                        earned_ach = pu_count >= 1
                    elif ach_id == "pu_three":
                        earned_ach = pu_count >= 3
                    elif ach_id == "pu_master":
                        earned_ach = pu_count >= 5
                    elif ach_id == "pu_ten":
                        earned_ach = pu_count >= 10

                if earned_ach:
                    await conn.execute(
                        "INSERT INTO user_achievements (user_id, achievement_id, earned_at) VALUES (?, ?, datetime('now'))",
                        (u_id, ach_id))
                    all_new_achievements.append((u_id, nickname, ach_id, ach))
        await conn.commit()

        for u_id, nick, ach_id, ach in all_new_achievements:
            try:
                await bot_instance.send_message(
                    u_id,
                    f"🏆 **НОВАЯ АЧИВКА!**\n\n{ach['icon']} **{ach['name']}**\n_{ach['description']}_\n\nПоздравляем! 🎉",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                print(f"[ACHIEVEMENT] Failed to notify {nick}: {e}")
        return all_new_achievements


class DebtEditState(StatesGroup):
    waiting_for_amount = State()


def setup_admin_handlers(bot_instance: Bot):
    global bot
    bot = bot_instance


def _is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


async def _is_judge(user_id: int) -> bool:
    if _is_admin(user_id): return True
    judges = await database.get_game_judges()
    return user_id in judges


async def get_player_games_count_for_evening(user_id: int, game_date: str) -> int:
    # Обязательно конвертируем дату в формат базы (2026-05-13), иначе найдет 0 игр
    search_date = database._ensure_iso_date(game_date)

    async with database.get_db() as conn:
        async with conn.execute("""
                                SELECT COUNT(DISTINCT game_number)
                                FROM game_slots_history
                                WHERE user_id = ?
                                  AND game_date = ?
                                """, (user_id, search_date)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


def calculate_evening_cost(games_count: int) -> int:
    return min(games_count * 100, 400)


@router.message(Command("admin"), F.chat.type == "private")
async def admin_panel(message: types.Message):
    if not _is_admin(message.from_user.id): return
    await message.answer("🛠 Панель администратора.\nВыбери действие на клавиатуре ниже 👇",
                         reply_markup=keyboards.admin_menu())


@router.message(F.text.in_(["🛠 Админ-панель", "🛠 Перейти в админ-панель"]), F.chat.type == "private")
async def admin_panel_unified(message: types.Message):
    if not _is_admin(message.from_user.id):
        kb = keyboards.main_menu_judge() if await _is_judge(message.from_user.id) else keyboards.main_menu()
        await message.answer("⛔ Эта кнопка доступна только администраторам.", reply_markup=kb)
        return
    await message.answer("🛠 Панель администратора.\nВыбери действие на клавиатуре ниже 👇",
                         reply_markup=keyboards.admin_menu())


@router.message(F.text == "📋 Игроки", F.chat.type == "private")
async def show_players_btn(message: types.Message):
    user_id = message.from_user.id
    is_admin, is_judge = _is_admin(user_id), await _is_judge(user_id)
    if not is_admin and not is_judge: return
    date_str = get_next_friday()
    text = await build_stats_text(date_str)
    if "всего 0" in text:
        await message.answer(f"На ближайший вечер {date_str} пока никто не записался.")
        return
    reply_kb = keyboards.admin_menu() if is_admin else keyboards.judge_menu()
    await message.answer(text, reply_markup=reply_kb)


@router.message(F.text == "👥 Все пользователи")
async def admin_all_users_btn(message: types.Message):
    if not _is_admin(message.from_user.id): return
    users = await database.get_all_users()
    if not users:
        await message.answer("📭 База пользователей пуста.")
        return
    header = f"👥 **Список игроков (всего: {len(users)})**\nПотеря данных? `ID` кликабелен.\n\n"
    lines = []
    for i, u in enumerate(users, 1):
        uid = u.get('user_id')
        nick = u.get('nickname') or "Без ника"
        full = u.get('full_name') or ""
        name_part = nick if not full else f"{nick} ({full})"
        lines.append(f"{i}. {name_part} — `{uid}`")

    full_text = header + "\n".join(lines)
    if len(full_text) <= 4096:
        await message.answer(full_text, parse_mode="Markdown")
    else:
        for x in range(0, len(full_text), 4000):
            await message.answer(full_text[x:x + 4000], parse_mode="Markdown")


@router.message(F.text == "💸 Разослать счета", F.chat.type == "private")
async def admin_send_bills_btn(message: types.Message):
    if not _is_admin(message.from_user.id): return
    assert bot is not None

    date_str = get_next_friday()
    search_date = database._ensure_iso_date(date_str)
    display_date = database.format_date_to_user(date_str)

    # 1. АВТО-РЕГИСТРАЦИЯ "ЗАЙЦЕВ"
    # Ищем всех, кто есть в играх за сегодня, но забыл нажать кнопку "Записаться"
    async with database.get_db() as conn:
        await conn.execute("""
                           INSERT OR IGNORE INTO evening_booking (user_id, status, date)
                           SELECT DISTINCT user_id, 'Позже', ?
                           FROM game_slots_history
                           WHERE game_date = ?
                             AND user_id IS NOT NULL
                             AND user_id != 0
                           """, (date_str, search_date))
        await conn.commit()

    # 2. Получаем полный список игроков (записанные + найденные "зайцы")
    players = await database.get_booked_players_for_game()
    if not players:
        await message.answer("Нет игроков, которые пришли на игру.")
        return

    kb = keyboards.user_pay_now_kb()
    count, bills_info, failed_users = 0, [], []

    # 3. Рассылка счетов
    for player in players:
        try:
            p_id, nickname = player[0], player[3]
            if await database.has_unpaid_session(p_id): continue

            # Считаем количество сыгранных игр
            games = await get_player_games_count_for_evening(p_id, search_date)

            # --- НОВАЯ ЛОГИКА ЖЕТОНОВ ---
            # 400 жетонов, если сыграл хотя бы 1 игру (никаких начислений за статус записи)
            tokens = 400 if games >= 1 else 0
            if tokens > 0:
                await database.add_tokens(p_id, tokens, f"За участие в вечере {display_date}")

            # Считаем сумму к оплате
            cost = calculate_evening_cost(games)
            if cost == 0: continue

            # Списываем долг и ставим сессию неоплаченной
            await database.change_user_debt(p_id, -cost)
            await database.log_transaction(p_id, -cost, 'charge', f"Игры {display_date} ({games} шт.)")
            await database.set_unpaid_session(p_id, 1)

            u_info = await database.get_user_by_id(p_id)
            name = u_info[3] or u_info[1] if u_info else str(p_id)
            bills_info.append(f"• {name}: {games} игр → {cost}₽")

            # Формируем текст для юзера
            msg_text = f"🎭 Игры окончены!\n\n"
            if tokens > 0:
                msg_text += f"✅ Бонус за вечер: +{tokens} жетонов\n"
            msg_text += f"🎮 Игр сыграно: {games}\n💰 К оплате: {cost}₽"

            await bot.send_message(p_id, msg_text, reply_markup=kb)
            count += 1
        except Exception as e:
            print(f"[BILLS ERROR] {e}")
            failed_users.append(player[0])
            continue

    # 4. АРХИВАЦИЯ ВЕЧЕРА
    try:
        await database.archive_current_evening()
        await database.set_setting("evening_archived", "1")
        await database.mark_evening_bills_sent(date_str)

        report = f"✅ Счета разосланы {count} игрокам за {display_date}.\n\n"
        if bills_info: report += "📊 **Детали:**\n" + "\n".join(bills_info) + "\n"
        await message.answer(report + f"\n🏆 Проверяю ачивки...")

        # 5. ВЫДАЧА АЧИВОК
        from achievements import check_and_award_achievements
        new_achs = await check_and_award_achievements(bot)
        if new_achs:
            ach_rep = "\n🏆 **Новые ачивки:**\n" + "\n".join(
                [f"• {a[1]}: {a[3]['icon']} {a[3]['name']}" for a in new_achs])
            await message.answer(ach_rep, parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"❌ Ошибка архивации: {e}")

    if failed_users: await message.answer(f"⚠️ Ошибки отправки у: {failed_users}")
    await message.answer("🛠 Панель администратора.", reply_markup=keyboards.admin_menu())


@router.message(F.text == "❌ Отменить вечер", F.chat.type == "private")
async def admin_cancel_evening(message: types.Message):
    if not _is_admin(message.from_user.id): return
    assert bot is not None
    players = await database.get_all_players()
    if not players: return await message.answer("Список игроков пуст.")
    text = "❌ Вечер мафии отменен. Приносим извинения!"
    sent = 0
    for (p_id,) in players:
        try:
            await bot.send_message(p_id, text)
            sent += 1
        except:
            continue
    try:
        await bot.send_message(config.GROUP_ID, text, message_thread_id=config.ANNOUNCE_TOPIC_ID)
    except:
        pass
    await database.clear_bookings()
    await message.answer(f"Отменено. Уведомлено {sent} чел.", reply_markup=keyboards.admin_menu())


@router.message(F.text == "📣 Сделать анонс", F.chat.type == "private")
async def admin_announce_evening(message: types.Message, bot: Bot):
    if not _is_admin(message.from_user.id): return
    users = await database.get_all_user_ids()
    if not users: return await message.answer("База пуста.")
    date_str = get_next_friday()
    me = await bot.get_me()
    text = f"📣 Анонс мафии!\nЖдем в пятницу {date_str} в 20:00.\nПридёшь?\n\n📋 Список: https://t.me/{me.username}?start=players"
    sent = 0
    for (u_id,) in users:
        try:
            await bot.send_message(u_id, text, reply_markup=keyboards.booking_kb())
            sent += 1
        except:
            continue
    try:
        await bot.send_message(config.GROUP_ID, text, reply_markup=keyboards.booking_kb(),
                               message_thread_id=config.ANNOUNCE_TOPIC_ID)
        s_text = await build_stats_text(date_str)
        s_msg = await bot.send_message(config.GROUP_ID, s_text, message_thread_id=config.ANNOUNCE_TOPIC_ID)
        await database.set_stats_message(date_str, config.GROUP_ID, s_msg.message_id)
    except Exception as e:
        print(f"Announce error: {e}")
    await message.answer(f"Анонс отправлен {sent} игрокам.", reply_markup=keyboards.admin_menu())


@router.message(F.text == "💰 Должники", F.chat.type == "private")
async def admin_debtors_btn(message: types.Message):
    if not _is_admin(message.from_user.id): return
    debtors = await database.get_debtors()
    if not debtors: return await message.answer("Должников нет 🎉")
    for full, nick, user_n, debt, u_id in debtors:
        u_link = f"@{user_n}" if user_n else "нет ника"
        n_part = nick if nick not in (None, "", "Не установлен") else "не указан"
        text = f"👤 {full} ({u_link})\nНик: {n_part}\nДолг: {abs(debt)}₽"
        kb = InlineKeyboardBuilder()
        kb.button(text="✏️ Изменить", callback_data=f"editdebt_{u_id}")
        await message.answer(text, reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("editdebt_"))
async def admin_edit_debt_start(call: CallbackQuery, state: FSMContext):
    u_id = int(call.data.split("_")[1])
    await state.update_data(edit_debt_user_id=u_id)
    await state.set_state(DebtEditState.waiting_for_amount)
    await call.message.answer(f"Введи новую сумму долга для {u_id} (в рублях).\n0 — закрыть долг.")
    await call.answer()


@router.message(DebtEditState.waiting_for_amount)
async def admin_edit_debt_set_amount(message: types.Message, state: FSMContext):
    data = await state.get_data()
    u_id = data.get("edit_debt_user_id")
    try:
        amt = int(message.text.strip())
        await database.log_transaction(u_id, amt, 'debt_correction', "Ручная правка админом")
        await database.set_user_debt(u_id, -amt)
        if amt == 0: await database.set_unpaid_session(u_id, 0)
        await message.answer(f"✅ Долг обновлен: {amt}₽.", reply_markup=keyboards.admin_menu())
    except:
        await message.answer("Введите целое число.")
    await state.clear()


@router.message(F.text == "📚 История вечеров", F.chat.type == "private")
async def admin_history_menu(message: types.Message):
    if not _is_admin(message.from_user.id): return
    years = await database.get_history_years()
    if not years:
        await message.answer("История пуста.")
        return
    await message.answer("📚 Выберите год:", reply_markup=keyboards.years_kb(years))


@router.callback_query(F.data == "admin_evenings_history")
async def back_to_evenings_list(call: CallbackQuery):
    evs = await database.get_evenings_list(limit=15)
    await call.message.edit_text("📚 Выберите вечер:", reply_markup=keyboards.evenings_history_kb(evs))


@router.callback_query(F.data.startswith("hist_"))
async def admin_history_detail(call: CallbackQuery):
    date_str = call.data.split("_")[1]

    # --- ИСПРАВЛЕННАЯ ЛОГИКА ЗАГОЛОВКА ---
    if "." in date_str or "-" in date_str:
        display_date = database.format_date_to_user(date_str)
    else:
        display_date = f"Вечер №{date_str}"
    # ------------------------------------

    players = await database.get_evening_players(date_str)
    if not players: return await call.answer("Нет данных.")

    EXCLUDED = ["Чагин", "Матроскина", "Стаут", "Гриня", "Evgeniy Chagin", "Екатерина", "Di D", "Григорий Подколзин"]

    text = f"📅 *Отчет за {display_date}*\n\n"
    total, idx = 0, 1

    for p in players:
        p_id, full, nick, status, games = p[0], p[1], p[2], p[3], p[4]
        if status == "Не идёт" or nick in EXCLUDED or full in EXCLUDED: continue

        display_name = nick if nick and str(nick).strip() not in ["", "None", "Не установлен"] else "Гость"
        if games == 0 and status in ["Вовремя", "Позже"]: games = 1

        cost = 400 if games >= 4 else (games * 100)
        total += cost
        text += f"{idx}. {display_name} — {games} игр — {cost}₽\n"
        idx += 1

    text += f"\n💰 *ИТОГО: {total}₽*"

    # --- ДИНАМИЧЕСКАЯ КНОПКА НАЗАД ---
    # Извлекаем год и месяц из даты (ожидаем формат ГГГГ-ММ-ДД)
    # Если дата в другом формате, этот сплит может сломаться, убедись что формат даты стабильный
    year, month = date_str.split("-")[:2]

    kb = InlineKeyboardBuilder()
    # Теперь при нажатии бот будет знать, в какой месяц вернуться
    kb.button(text="⬅️ Назад", callback_data=f"back_to_month_{year}_{month}")
    # --------------------------------

    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=kb.as_markup())
    await call.answer()

# Выбор месяца
@router.callback_query(F.data.startswith("yr_"))
async def admin_history_months(call: CallbackQuery):
    year = call.data.split("_")[1]
    months = await database.get_history_months(year)
    await call.message.edit_text(f"📚 Выберите месяц ({year} год):", reply_markup=keyboards.months_kb(year, months))
    await call.answer()

# Выбор конкретного вечера
@router.callback_query(F.data.startswith("mo_"))
async def admin_history_evenings(call: CallbackQuery):
    _, year, month = call.data.split("_")
    evenings = await database.get_history_evenings(year, month)
    await call.message.edit_text(f"📅 Вечера за {month}.{year}:", reply_markup=keyboards.evenings_kb(year, month, evenings))
    await call.answer()

# Навигация "Назад"
@router.callback_query(F.data == "back_years")
async def back_to_years(call: CallbackQuery):
    years = await database.get_history_years()
    await call.message.edit_text("📚 Выберите год:", reply_markup=keyboards.years_kb(years))
    await call.answer()

@router.callback_query(F.data.startswith("back_months_"))
async def back_to_months(call: CallbackQuery):
    year = call.data.split("_")[2]
    months = await database.get_history_months(year)
    await call.message.edit_text(f"📚 Выберите месяц ({year} год):", reply_markup=keyboards.months_kb(year, months))
    await call.answer()


@router.callback_query(F.data.startswith("back_to_month_"))
async def back_to_specific_month(call: CallbackQuery):
    # Разбиваем строку по нижнему подчеркиванию
    parts = call.data.split("_")

    # Берем два последних элемента — это всегда год и месяц
    year = parts[-2]
    month = parts[-1]

    evenings = await database.get_history_evenings(year, month)

    await call.message.edit_text(
        f"📅 Вечера за {month}.{year}:",
        reply_markup=keyboards.evenings_kb(year, month, evenings)
    )
    await call.answer()


# ========== БЭКАП ==========
@router.message(F.text == "📁 Бэкапы")
async def admin_backup_menu(message: Message):
    """Открывает подменю бэкапов"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён")
        return
    
    await message.answer(
        "📁 **Управление бэкапами**\n\nВыберите действие:",
        parse_mode="Markdown",
        reply_markup=keyboards.backup_submenu()
    )


@router.message(F.text == "📁 Создать бэкап")
async def admin_create_backup(message: Message):
    """Создание бэкапа и отправка"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён")
        return
    
    await message.answer("⏳ Создаю бэкап...")
    
    # Создаём временный файл
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"mafia_crm_backup_{timestamp}.db"
    temp_dir = tempfile.gettempdir()
    temp_path = os.path.join(temp_dir, filename)
    
    try:
        # Копируем БД во временный файл
        shutil.copy2(db.DB_NAME, temp_path)
        
        # Отправляем файл
        await message.answer_document(
            FSInputFile(temp_path),
            caption="📁 Бэкап базы данных"
        )
        await message.answer("✅ Бэкап создан и отправлен!")
        
        # Удаляем временный файл
        os.remove(temp_path)
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
    
    # Возвращаемся в подменю
    await admin_backup_menu(message)


@router.message(F.text == "🔄 Восстановить бэкап")
async def admin_restore_backup(message: Message):
    """Запрос на отправку файла для восстановления"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён")
        return
    
    await message.answer(
        "📁 **Восстановление базы данных**\n\n"
        "Отправьте файл бэкапа (`.db`) с вашего компьютера.\n\n"
        "⚠️ Текущие данные будут заменены!",
        parse_mode="Markdown"
    )


@router.message(F.document)
async def handle_backup_file(message: Message):
    """Обработка загруженного файла бэкапа"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён")
        return
    
    document = message.document
    
    # Проверяем расширение
    if not document.file_name.endswith('.db'):
        await message.answer("❌ Отправьте файл с расширением `.db`")
        return
    
    await message.answer("⏳ Восстанавливаю базу данных...")
    
    # Скачиваем файл
    file = await message.bot.get_file(document.file_id)
    temp_path = f"temp_restore_{document.file_name}"
    await message.bot.download_file(file.file_path, temp_path)
    
    try:
        # Проверяем, что это SQLite файл
        with open(temp_path, 'rb') as f:
            header = f.read(16)
            if header[:6] != b'SQLite':
                await message.answer("❌ Файл не является SQLite базой данных")
                os.remove(temp_path)
                return
        
        # Создаём бэкап текущей БД
        backup_dir = "backups"
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"before_restore_{timestamp}.db")
        shutil.copy2(db.DB_NAME, backup_path)
        
        # Восстанавливаем
        shutil.copy2(temp_path, db.DB_NAME)
        
        # Удаляем временный файл
        os.remove(temp_path)
        
        await message.answer(
            "✅ **База данных восстановлена!**\n\n"
            f"📁 Бэкап старой БД сохранён: `{backup_path}`\n\n"
            "🔄 Перезапустите бота для применения изменений.",
            parse_mode="Markdown"
        )
        
    except Exception as e:
        await message.answer(f"❌ Ошибка восстановления: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)


@router.message(F.text == "🔙 Назад в админ-меню")
async def back_to_admin_menu(message: Message):
    """Возврат в главное админ-меню"""
    await message.answer(
        "🔙 Возврат в админ-панель",
        reply_markup=keyboards.admin_menu()
    )