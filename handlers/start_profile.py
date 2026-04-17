from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram import F

import keyboards
import database
import config
from handlers.payment import payment_kb
from handlers.booking import build_stats_text, get_next_friday  # ТУТ только build_stats_text

router = Router()


class Form(StatesGroup):
    waiting_for_nickname = State()


@router.message(Command("start"), F.chat.type == "private")
async def start(m: Message, command: CommandObject):
    await database.init_db()
    await database.add_or_update_user(
        m.from_user.id,
        m.from_user.username,
        m.from_user.full_name
    )

    args = (command.args or "").strip()

    if args == "players":
        date_str = get_next_friday()
        text = await build_stats_text(date_str)

        await m.answer(
            text,
            reply_markup=keyboards.main_menu()
        )
        return

    await m.answer(
        f"🎭 Привет! Ближайшая игра {get_next_friday()} в 20:00",
        reply_markup=keyboards.main_menu()
    )


@router.message(F.text == "🏠 В главное меню", F.chat.type == "private")
async def back_to_main_menu(message: Message):
    await message.answer(
        f"🎭 Привет! Ближайшая игра {get_next_friday()} в 20:00",
        reply_markup=keyboards.main_menu()
    )


@router.message(F.text == "👤 Мой профиль", F.chat.type == "private")
async def show_profile(message: Message):
    data = await database.get_user_profile(message.from_user.id)
    if data:
        name, nick, debt, visit = data

        if not visit or visit == "-":
            visit_text = "Ещё не был на вечерах"
        else:
            visit_text = visit

        text = (
            f"👤 **Ваш профиль:**\n\n"
            f"Имя: {name}\n"
            f"Игровой ник: {nick or 'Не указан'}\n"
            f"Последний визит: {visit_text}\n"
            f"Долг: {debt} руб."
        )
        await message.answer(
            text,
            reply_markup=keyboards.profile_kb(debt),
            parse_mode="Markdown"
        )
    else:
        await message.answer("Сначала нажмите /start, чтобы создать профиль.")


@router.message(F.text == "🧾 Список игроков", F.chat.type == "private")
async def show_players_for_user(message: Message):
    """
    Показывает список игроков на ближайший вечер
    в том же виде, как в анонсе (build_stats_text + get_next_friday).
    """
    date_str = get_next_friday()
    text = await build_stats_text(date_str)

    # Если на эту дату никого нет (всего 0)
    if "всего 0" in text:
        await message.answer(f"На ближайший вечер {date_str} пока никто не записался.")
        return

    await message.answer(text)


@router.callback_query(F.data == "edit_nickname")
async def change_nick_step1(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Введите ваш новый игровой ник (макс. 50 символов):")
    await state.set_state(Form.waiting_for_nickname)
    await call.answer()


@router.message(Form.waiting_for_nickname)
async def change_nick_step2(message: Message, state: FSMContext):
    new_nick = (message.text or "").strip()[:50]
    if not new_nick:
        await message.answer("Ник не может быть пустым. Попробуйте снова.")
        return
    await database.update_nickname(message.from_user.id, new_nick)
    await state.clear()
    await message.answer(
        f"✅ Ник изменён на: {new_nick}",
        reply_markup=keyboards.main_menu()
    )


@router.callback_query(F.data == "profile_pay")
async def profile_pay(call: CallbackQuery):
    kb = payment_kb(call.from_user.id)
    await call.message.answer(
        f"💰 **Реквизиты для оплаты:**\n\n"
        f"📞 Номер: `{config.PHONE}`\n"
        f"🏦 Банк: {config.BANK}\n\n"
        f"После перевода нажмите кнопку ниже.",
        reply_markup=kb,
        parse_mode="Markdown"
    )
    await call.answer()