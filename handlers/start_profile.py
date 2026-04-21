from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

import keyboards
import database
import config
from handlers.payment import payment_kb
from handlers.booking import build_stats_text, get_next_friday
from stats_utils import build_user_stats_text

router = Router()


class Form(StatesGroup):
    waiting_for_nickname = State()


async def _is_judge(user_id: int) -> bool:
    """
    Пользователь считается судьёй, если:
    - он в ADMIN_IDS, или
    - он в списке game_judges в БД.
    """
    if user_id in config.ADMIN_IDS:
        return True

    judges = await database.get_game_judges()
    return user_id in judges


def _get_main_menu_for_user(is_admin: bool, is_judge: bool):
    """
    Выбор ГЛАВНОГО меню (то, что показывается на /start и '🏠 В главное меню'):

    - админ -> main_menu_admin (игровое меню + '🛠 Админ-панель')
    - судья (но не админ) -> main_menu_judge (игровое меню + '⚖ Панель судьи')
    - обычный игрок -> main_menu
    """
    if is_admin:
        return keyboards.main_menu_admin()
    if is_judge:
        return keyboards.main_menu_judge()
    return keyboards.main_menu()


@router.message(Command("start"), F.chat.type == "private")
async def start(m: Message, command: CommandObject):
    await database.init_db()
    await database.add_or_update_user(
        m.from_user.id,
        m.from_user.username,
        m.from_user.full_name
    )

    user_id = m.from_user.id
    is_admin = user_id in config.ADMIN_IDS
    is_judge = await _is_judge(user_id)
    kb = _get_main_menu_for_user(is_admin, is_judge)

    args = (command.args or "").strip()

    if args == "players":
        date_str = get_next_friday()
        text = await build_stats_text(date_str)

        await m.answer(
            text,
            reply_markup=kb
        )
        return

    date = get_next_friday()
    await m.answer(
        f"🎭 Привет! Ближайшая игра {date} в 20:00",
        reply_markup=kb
    )


@router.message(F.text == "🏠 В главное меню", F.chat.type == "private")
async def back_to_main_menu(message: Message):
    user_id = message.from_user.id
    is_admin = user_id in config.ADMIN_IDS
    is_judge = await _is_judge(user_id)
    kb = _get_main_menu_for_user(is_admin, is_judge)

    date = get_next_friday()
    await message.answer(
        f"🎭 Привет! Ближайшая игра {date} в 20:00",
        reply_markup=kb
    )


@router.message(F.text == "⚖ Панель судьи", F.chat.type == "private")
async def open_judge_panel(message: Message):
    """
    Открывает ВНУТРЕННЮЮ панель судьи.
    Доступно только для судей/админов.
    """
    user_id = message.from_user.id
    if not await _is_judge(user_id):
        await message.answer("⛔ Эта панель доступна только судьям.")
        return

    await message.answer(
        "⚖ Панель судьи.\nЗдесь управление играми.",
        reply_markup=keyboards.judge_menu()
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


@router.message(F.text == "🧾 Список игроков в записи", F.chat.type == "private")
async def show_players_for_user(message: Message):
    """
    Показывает список игроков на ближайший вечер
    в том же виде, как в анонсе.
    """
    date_str = get_next_friday()
    text = await build_stats_text(date_str)

    if "всего 0" in text:
        await message.answer(f"На ближайший вечер {date_str} пока никто не записался.")
        return

    user_id = message.from_user.id
    is_admin = user_id in config.ADMIN_IDS
    is_judge = await _is_judge(user_id)
    kb = _get_main_menu_for_user(is_admin, is_judge)

    await message.answer(text, reply_markup=kb)


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

    user_id = message.from_user.id
    is_admin = user_id in config.ADMIN_IDS
    is_judge = await _is_judge(user_id)
    kb = _get_main_menu_for_user(is_admin, is_judge)

    await message.answer(
        f"✅ Ник изменён на: {new_nick}",
        reply_markup=kb
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