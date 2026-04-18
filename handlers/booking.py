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
#
# ОГЛАВЛЕНИЕ:
# 1. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
#    - get_next_friday      — ближайшая пятница в формате ДД.MM
#    - build_stats_text     — текстовый блок со списком записавшихся
#
# 2. ХЕНДЛЕРЫ ЗАПИСИ
#    - book                 — кнопка "🕵️ Записаться на игру"
#    - handle_book          — обработка inline-кнопок book_*
# =========================================================


# =========================================================
# 1. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =========================================================

def get_next_friday() -> str:
    """
    Возвращает дату ближайшей пятницы в формате "ДД.MM".

    Логика:
      - если сегодня понедельник–пятница -> пятница этой недели;
      - если суббота/воскресенье        -> пятница следующей недели.
    """
    now = datetime.utcnow()
    weekday = now.weekday()  # 0=понедельник, 4=пятница

    if weekday <= 4:
        # пятница этой недели (если сегодня понедельник–пятница)
        days_ahead = 4 - weekday
    else:
        # суббота/воскресенье -> пятница следующей недели
        days_ahead = 7 - (weekday - 4)

    return (now + timedelta(days=days_ahead)).strftime("%d.%m")


async def build_stats_text(date: str) -> str:
    """
    Строит текстовую сводку по записи на конкретную дату.

    Использует статусы:
      - "Вовремя"
      - "Позже"
      - "Не идёт"

    Формат:
      📊 Запись на <date> (всего N):
      ✅ Идут вовремя:
      1. Игрок
      ...
      ⏳ Придут позже:
      ...
      ❌ Не идут:
      ...
    """
    ontime = await database.get_players_by_status_for_date(date, "Вовремя")
    late = await database.get_players_by_status_for_date(date, "Позже")
    no = await database.get_players_by_status_for_date(date, "Не идёт")

    # считаем только тех, кто придёт (Вовремя + Позже)
    total = len(ontime) + len(late)

    def block(title: str, items: List[str]) -> str:
        if not items:
            return f"{title}: —"
        # нумерация 1., 2., 3. и защита от пустого/неизвестного имени
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


# =========================================================
# 2. ХЕНДЛЕРЫ ЗАПИСИ
# =========================================================

@router.message(F.text == "🕵️ Записаться на игру", F.chat.type == "private")
async def book(message: Message):
    """
    Кнопка в ЛС для открытия inline-клавиатуры записи на ближайшую игру.
    """
    await message.answer(
        f"Запись на {get_next_friday()} в 20:00:",
        reply_markup=keyboards.booking_kb(),
    )


@router.callback_query(F.data.startswith("book_"))
async def handle_book(call: CallbackQuery, bot: Bot):
    """
    Обработка нажатий на inline-кнопки записи:
      - book_ontime — придёт вовремя
      - book_late   — придёт позже
      - book_no     — не идёт

    Делает:
      1) Обновляет/создаёт пользователя в БД.
      2) Ставит запись на ближайшую пятницу.
      3) Обновляет статистику в группе (сообщение с анонсом).
      4) Шлёт админу уведомления при наборе 11 игроков.
    """
    # Обновляем пользователя в базе
    await database.add_or_update_user(
        user_id=call.from_user.id,
        username=call.from_user.username,
        full_name=call.from_user.full_name,
    )
    date = get_next_friday()

    # ВАЖНО: сохраняем дату текущей игры/вечера для истории игр/ролей
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

        # Если набралось 11 человек (любых, кто идёт)
        if total_attending == 11:
            # Пишем админу в ЛС
            await bot.send_message(config.ADMIN_ID, "🔥 Стол собран!")

            # Пишем в группу анонса (берём ID чата из базы)
            stats_info = await database.get_stats_message(date)
            if stats_info:
                chat_id, _ = stats_info
                await bot.send_message(
                    chat_id,
                    "🔥 **Стол собран! О времени сбора напишем позже**",
                )

        # Если именно 11 человек придут ровно к 20:00
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

        # Обновляем сообщение-статистику в группе (если оно есть)
        stats_info = await database.get_stats_message(date)
        if stats_info:
            chat_id, msg_id = stats_info
            new_text = await build_stats_text(date)
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=new_text,
                )
            except Exception:
                # Если не удалось отредактировать — просто молча игнорируем
                pass

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

        # Обновляем сообщение-статистику в группе (если оно есть)
        stats_info = await database.get_stats_message(date)
        if stats_info:
            chat_id, msg_id = stats_info
            new_text = await build_stats_text(date)
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=new_text,
                )
            except Exception:
                pass

    # Безопасное закрытие callback
    try:
        await call.answer()
    except Exception:
        pass