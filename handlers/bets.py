from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery
from aiogram.enums import ParseMode

import database

router = Router()

class BetState(StatesGroup):
    waiting_for_amount = State()

@router.callback_query(F.data.startswith("bet_red:"))
async def bet_red_start(callback: CallbackQuery, state: FSMContext):
    game_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    # 1. Проверка активности ставки
    bet = await database.get_active_bet(game_id)
    if not bet:
        await callback.answer("❌ Ставки на эту игру уже закрыты!", show_alert=True)
        return

    # 2. НОВАЯ ЛОГИКА: Проверка, ставил ли уже человек
    if await database.check_user_bet_exists(user_id, game_id):
        await callback.answer("❌ Вы уже сделали ставку на эту игру!", show_alert=True)
        return

    msg = await callback.message.answer(
        f"💰 **Ставка на Красных 🔴**\n\n"
        f"Введите сумму ставки (минимум 50 жетонов):\n"
        f"Ваш баланс: {await database.get_user_tokens(user_id)} 🪙",
        parse_mode=ParseMode.MARKDOWN
    )

    await state.update_data(bet_id=bet["id"], predicted_winner="Красные", game_id=game_id, prompt_msg_id=msg.message_id)
    await state.set_state(BetState.waiting_for_amount)
    await callback.answer()


@router.callback_query(F.data.startswith("bet_black:"))
async def bet_black_start(callback: CallbackQuery, state: FSMContext):
    game_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    bet = await database.get_active_bet(game_id)
    if not bet:
        await callback.answer("❌ Ставки на эту игру уже закрыты!", show_alert=True)
        return

    # 2. НОВАЯ ЛОГИКА: Проверка, ставил ли уже человек
    if await database.check_user_bet_exists(user_id, game_id):
        await callback.answer("❌ Вы уже сделали ставку на эту игру!", show_alert=True)
        return

    msg = await callback.message.answer(
        f"💰 **Ставка на Чёрных ⚫**\n\n"
        f"Введите сумму ставки (минимум 50 жетонов):\n"
        f"Ваш баланс: {await database.get_user_tokens(user_id)} 🪙",
        parse_mode=ParseMode.MARKDOWN
    )

    await state.update_data(bet_id=bet["id"], predicted_winner="Чёрные", game_id=game_id, prompt_msg_id=msg.message_id)
    await state.set_state(BetState.waiting_for_amount)
    await callback.answer()


@router.callback_query(F.data.startswith("bet_skip:"))
async def bet_skip(callback: CallbackQuery):
    await callback.answer("🔕 Вы пропустили ставки на эту игру")
    try: await callback.message.delete()
    except: pass


@router.message(BetState.waiting_for_amount)
async def bet_process_amount(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    bet_id, predicted_winner, game_id, prompt_msg_id = data.get("bet_id"), data.get("predicted_winner"), data.get("game_id"), data.get("prompt_msg_id")

    if not bet_id or not await database.get_active_bet(game_id):
        await message.answer("❌ Ставки на эту игру закрыты или не найдены!")
        await state.clear()
        return

    # Повторная проверка на дубль прямо перед сохранением (защита от нажатия кнопок в двух окнах)
    if await database.check_user_bet_exists(user_id, game_id):
        await message.answer("❌ Вы уже сделали ставку на эту игру!")
        await state.clear()
        return

    try:
        amount = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите целое число.")
        return

    if amount < 50:
        await message.answer("❌ Минимальная ставка — 50 жетонов.")
        return

    tokens = await database.get_user_tokens(user_id)
    if amount > tokens:
        await message.answer(f"❌ Не хватает жетонов! У вас {tokens} 🪙.")
        return

    if await database.place_bet(user_id, bet_id, amount, predicted_winner):
        team_icon = "🔴" if predicted_winner == "Красные" else "⚫"
        await database.add_tokens(user_id, -amount, comment=f"Ставка: {team_icon} {predicted_winner}")
        await message.answer(f"✅ **Ставка принята!**\n💰 {amount} 🪙 на {team_icon} {predicted_winner}")
    else:
        await message.answer("❌ Ошибка записи в БД.")

    try:
        if prompt_msg_id: await message.bot.delete_message(message.chat.id, prompt_msg_id)
        await message.delete()
    except: pass
    await state.clear()


@router.callback_query(F.data == "bet_cancel")
async def bet_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try: await callback.message.delete()
    except: pass
    await callback.answer("Ввод ставки отменен")