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


# ========== РЕГЛАМЕНТ ==========

REGULATIONS_TEXT = """
📋 РЕГЛАМЕНТ НАЧИСЛЕНИЯ ДОПОЛНИТЕЛЬНЫХ БАЛЛОВ И ШТРАФОВ

1. Лучший ход (ЛХ)
ЛХ 3 черных: +0,6
ЛХ 2 черных: +0,3
ЛХ 1 черный: +0,1
Примечание: При отсутствии угаданных черных игроков баллы ЛХ не начисляются.

2. Протоколы и мнения для ПУ
Для ПУ:

Верный/неверный протокол считается отдельно каждый цвет до первой ошибки, если в одном ошибка, то сразу отрицательный: +0,1....0,2....0,2 максимум 0,5 / за 1 ошибку -0,2....-0,3......

Мнение: +0,2 / 0 / -0,2 (больше 1 цвета) (Если гарантирует точную угадайку то расширить до 0,3 - 0,4)

По версиям: +0,4 / -0,4

Максимальный доп 0.8

Для умерших игроков (кроме ПУ):
Оставление по версиям протокол: +0,4 / -0,4
Важно: любая ошибка в протоколе карается штрафом -0,4 сразу, без учета мнения и других даже правильных цветов в протоколе.

Цвета в протоколе оцениваются по их сложности за 2 правильных сложных цвета можно и 0,6-0,8 получить

Верное/неверное мнение: +0,2 / 0 / -0,2

Максимум можно получить в "Казино" от 0,7 до -0,6

3. Игровые решения и импакт
Решения за столом (для принимающих решение):
Правильный/неправильный сбор рук: от +0,5 до +0,7 / от -0,2 до -0,6 (зависит от ситуации).
Голосование против завещания: оценивается аналогично сбору рук.
Для игроков, не принимавших решение: значение бонуса или штрафа уменьшается на 0,2. (Если игрок должен получить 1.6, вы получить 1,4. Если -0,6, то -0,2 до -0,4)

Качество индивидуальной игры:
Стабильно хорошая игра: от +0,3 до +0,5.
Критерий: атака максимум в одного красного (без «уничтожения»), верные цвета по остальным игрокам. Оцениваются действия, а не слова.
Командный бонус: Если все красные заслуживают плюс, распределяется до 4,0 баллов суммарно на всех (без учета ПУ) на основе личного вклада (импакта).

4. Дисциплинарные санкции (Техфолы)
Начисляются за агрессию, крики, неуважение, намеки на роль или «ночную» информацию.
Техфол: от -0,3 (-0,6 техфол ставится только за влияние на протокол)
Второй техфол: удаление из-за стола с суммой штрафа ранее. 
Удаление: -0,6 баллов (не критика) -1 (критика)
Слом красного в красного на 10 человек -0,6
ППК: -1,5 балл.
Порядок вынесения: сначала предупреждение, при повторении — техфол. Техфолы не оспариваются.

5. Корректировка допов
Изменение «своего» допа возможно в пределах 0,2 балла.

Саммари: 
1)Просто играете норм игру 1,2-1,4
2)Тащили игру 1,5-1,8
3)Руин по версиям -0,4 за неправильное определение того кто решает, -0,2 тем кто голосовал из красных с ним.
4)Руин соло игры от -0,6 до -0,8

Просто посидели в игре - 0
"""


@router.message(F.text == "📋 РЕГЛАМЕНТ")
async def show_regulations(message: Message):
    """Показывает регламент начисления допов и штрафов"""
    user_id = message.from_user.id
    is_admin = user_id in config.ADMIN_IDS
    is_judge = await _is_judge(user_id)
    kb = _get_main_menu_for_user(is_admin, is_judge)

    await message.answer(
        REGULATIONS_TEXT,
        parse_mode=None,
        reply_markup=kb
    )


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