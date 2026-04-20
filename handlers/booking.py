from datetime import datetime, timedelta
from typing import List, Tuple, Optional

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery

import config
import keyboards
import database

router = Router()


# =========================================================
# BOOKING — ЗАПИСЬ НА ВЕЧЕР МАФИИ
# =========================================================


# =========================================================
# 1. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =========================================================

def get_next_friday() -> str:
    """
    Возвращает дату ближайшей пятницы в формате "ДД.ММ".
    """
    now = datetime.utcnow()
    weekday = now.weekday()

    if weekday <= 4:
        days_ahead = 4 - weekday
    else:
        days_ahead = 7 - (weekday - 4)

    return (now + timedelta(days=days_ahead)).strftime("%d.%m")


async def build_stats_text(date: str) -> str:
    """
    Строит текстовую сводку по записи на конкретную дату.
    """
    ontime = await database.get_players_by_status_for_date(date, "Вовремя")
    late = await database.get_players_by_status_for_date(date, "Позже")
    no = await database.get_players_by_status_for_date(date, "Не идёт")

    total = len(ontime) + len(late)

    def block(title: str, items: List[str]) -> str:
        if not items:
            return f"{title}: —"
        lines = [
            f"{i}. {name if name and name != 'Неизвестный' else 'Игрок без профиля'}"
            for i, name in enumerate(items, start=1)
        ]
        return f"{title}:\n" + "\n".join(lines)

    parts = [
        f"📊 Запись на {date} (всего {total}):",
        block("✅ Идут вовремя", ontime),
        block("⏳ Придут позже", late),
        block("❌ Не идут", no),
    ]
    return "\n\n".join(parts)


async def update_stats_message(bot: Bot, date: str) -> bool:
    """
    Обновляет сообщение со статистикой в группе.
    Если сообщение не найдено или не редактируется — создаёт новое.
    """
    new_text = await build_stats_text(date)
    stats_info = await database.get_stats_message(date)

    # Пробуем обновить существующее сообщение
    if stats_info and stats_info[0] and stats_info[1]:
        chat_id, msg_id = stats_info
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=new_text,
                parse_mode="Markdown"
            )
            return True
        except Exception as e:
            print(f"[STATS] Failed to edit message: {e}")
            # Сообщение недоступно — удаляем запись и создадим новое
            await database.set_stats_message(date, 0, 0)

    # Создаём новое сообщение
    try:
        new_msg = await bot.send_message(
            config.GROUP_ID,
            new_text,
            message_thread_id=config.ANNOUNCE_TOPIC_ID,
            parse_mode="Markdown"
        )
        await database.set_stats_message(date, config.GROUP_ID, new_msg.message_id)
        return True
    except Exception as e:
        print(f"[STATS] Failed to send new message: {e}")
        return False


# =========================================================
# 2. ХЕНДЛЕРЫ ЗАПИСИ
# =========================================================

@router.message(F.text == "🕵️ Записаться на игру", F.chat.type == "private")
async def book(message: Message):
    await message.answer(
        f"Запись на {get_next_friday()} в 20:00:",
        reply_markup=keyboards.booking_kb(),
    )


@router.callback_query(F.data.startswith("book_"))
async def handle_book(call: CallbackQuery, bot: Bot):
    # Обновляем пользователя в базе
    await database.add_or_update_user(
        user_id=call.from_user.id,
        username=call.from_user.username,
        full_name=call.from_user.full_name,
    )
    date = get_next_friday()
    await database.set_current_game_date(date)

    # --- Пользователь идёт (вовремя или позже) ---
    if call.data in ("book_ontime", "book_late"):
        status_map = {"book_ontime": "Вовремя", "book_late": "Позже"}
        status = status_map[call.data]

        await database.add_booking(call.from_user.id, status, date)

        # Ответ пользователю
        if call.message.chat.type == "private":
            await call.message.edit_text(
                f"✅ Вы записаны на {date}! Статус: {status}"
            )
        else:
            await call.answer(
                f"✅ Записал вас на {date}! Статус: {status}",
                show_alert=False,
            )

        # Подсчёт людей за столом
        total_attending = await database.count_all_attending_for_date(date)
        ontime_count = await database.count_ontime_players_for_date(date)

        # Если набралось 11 человек
        if total_attending == 11:
            await bot.send_message(config.ADMIN_ID, "🔥 Стол собран!")

            stats_info = await database.get_stats_message(date)
            if stats_info:
                chat_id, _ = stats_info
                await bot.send_message(
                    chat_id,
                    "🔥 **Стол собран! О времени сбора напишем позже**",
                )

        # Если 11 человек будут вовремя
        if ontime_count == 11:
            await bot.send_message(
                config.ADMIN_ID,
                "✅ Все 11 человек будут вовремя!",
            )

            stats_info = await database.get_stats_message(date)
            if stats_info:
                chat_id, _ = stats_info
                await bot.send_message(
                    chat_id,
                    "✅ **Отлично! 11 человек подтвердили, что будут к 20:00.**",
                )

        # Обновляем сообщение статистики
        await update_stats_message(bot, date)

    # --- Пользователь НЕ идёт ---
    elif call.data == "book_no":
        await database.add_booking(call.from_user.id, "Не идёт", date)

        if call.message.chat.type == "private":
            await call.message.edit_text(
                "😢 Жаль, что не получится прийти в этот раз.\n"
                "Если планы поменяются — просто снова запишитесь."
            )
        else:
            await call.answer(
                "Ок, отметил, что вы не идёте в этот вечер.",
                show_alert=False,
            )

        # Обновляем сообщение статистики
        await update_stats_message(bot, date)

    # Безопасное закрытие callback
    try:
        await call.answer()
    except Exception:
        pass


# =========================================================
# 3. ХЕНДЛЕРЫ ПРОСМОТРА
# =========================================================

@router.message(F.text == "🧾 Список игроков", F.chat.type == "private")
async def show_players_list(message: Message):
    date = get_next_friday()
    text = await build_stats_text(date)

    ontime = await database.get_players_by_status_for_date(date, "Вовремя")
    late = await database.get_players_by_status_for_date(date, "Позже")
    total = len(ontime) + len(late)

    if total == 0:
        await message.answer(
            f"📋 На вечер {date} пока никто не записался.\n\n"
            f"Стань первым — нажми «🕵️ Записаться на игру»!",
            reply_markup=keyboards.main_menu()
        )
        return

    text += "\n\n📌 Чтобы записаться — нажми «🕵️ Записаться на игру»"

    await message.answer(
        text,
        reply_markup=keyboards.main_menu(),
        parse_mode="Markdown"
    )