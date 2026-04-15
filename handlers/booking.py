from datetime import datetime, timedelta

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery

import config
import keyboards
import database

router = Router()


def get_next_friday() -> str:
    now = datetime.utcnow()
    days_ahead = (4 - now.weekday()) % 7 or 7
    return (now + timedelta(days=days_ahead)).strftime('%d.%m')
async def build_stats_text(date: str) -> str:
    ontime = await database.get_players_by_status_for_date(date, "Вовремя")
    late = await database.get_players_by_status_for_date(date, "Позже")
    no = await database.get_players_by_status_for_date(date, "Не идёт")

    def block(title: str, items: list) -> str:
        if not items:
            return f"{title}: —"
        return f"{title}:\n" + "\n".join(f"• {name}" for name in items)

    parts = [
        f"📊 Запись на {date}:",
        block("✅ Идут вовремя", ontime),
        block("⏳ Придут позже", late),
        block("❌ Не идут", no),
    ]
    return "\n\n".join(parts)


@router.message(F.text == "🕵️ Записаться на игру", F.chat.type == "private")
async def book(m: Message):
    await m.answer(
        f"Запись на {get_next_friday()} в 20:00:",
        reply_markup=keyboards.booking_kb()
    )


@router.callback_query(F.data.startswith("book_"))
async def handle_book(call: CallbackQuery, bot: Bot):
    date = get_next_friday()

    if call.data in ("book_ontime", "book_late"):
        status_map = {"book_ontime": "Вовремя", "book_late": "Позже"}
        status = status_map[call.data]

        await database.add_booking(call.from_user.id, status, date)

        # личка: редактируем сообщение
        if call.message.chat.type == "private":
            await call.message.edit_text(
                f"✅ Вы записаны на {date}! Статус: {status}"
            )
        else:
            # группа: просто всплывашка
            await call.answer(
                f"✅ Записал вас на {date}! Статус: {status}",
                show_alert=False
            )

        # после любой записи считаем, сколько человек
        total_attending = await database.count_all_attending_for_date(date)
        ontime_count = await database.count_ontime_players_for_date(date)

        # если суммарно набралось 11 человек (Вовремя + Позже)
        if total_attending == 11:
            await bot.send_message(
                config.ADMIN_ID,
                "Стол есть, точное время напишем позже"
            )

        # если именно «Вовремя» стало 11
        if ontime_count == 11:
            await bot.send_message(
                config.ADMIN_ID,
                "Стол есть, ждём всех к 21:00"
            )

        # обновляем сообщение статистики в группе
        stats_info = await database.get_stats_message(date)
        if stats_info:
            chat_id, msg_id = stats_info
            new_text = await build_stats_text(date)
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=new_text
                )
            except Exception:
                pass

    elif call.data == "book_no":
        # РАНЬШЕ: remove_booking → теперь просто ставим статус "Не идёт"
        await database.add_booking(call.from_user.id, "Не идёт", date)

        if call.message.chat.type == "private":
            await call.message.edit_text(
                "😢 Жаль, что не получится прийти в этот раз.\n"
                "Если планы поменяются — просто снова запишитесь."
            )
        else:
            await call.answer(
                "Ок, отметил, что вы не идёте в этот вечер.",
                show_alert=False
            )

        # обновляем сообщение статистики в группе
        stats_info = await database.get_stats_message(date)
        if stats_info:
            chat_id, msg_id = stats_info
            new_text = await build_stats_text(date)
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=new_text
                )
            except Exception:
                pass

    try:
        await call.answer()
    except Exception:
        pass
