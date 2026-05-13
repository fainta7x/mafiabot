# handlers/bets.py
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
    """Начало ставки на Красных"""
    game_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    # Проверяем, активны ли ещё ставки
    bet = await database.get_active_bet(game_id)
    if not bet:
        await callback.answer("❌ Ставки на эту игру уже закрыты!", show_alert=True)
        return

    # Запоминаем ID сообщения-вопроса, чтобы потом его удалить
    msg = await callback.message.answer(
        f"💰 **Ставка на Красных 🔴**\n\n"
        f"Введите сумму ставки (минимум 50 жетонов):\n"
        f"Ваш баланс: {await database.get_user_tokens(user_id)} 🪙",
        parse_mode=ParseMode.MARKDOWN
    )

    await state.update_data(
        bet_id=bet["id"],
        predicted_winner="Красные",
        game_id=game_id,
        prompt_msg_id=msg.message_id  # Сохраняем ID для удаления
    )
    await state.set_state(BetState.waiting_for_amount)
    await callback.answer()


@router.callback_query(F.data.startswith("bet_black:"))
async def bet_black_start(callback: CallbackQuery, state: FSMContext):
    """Начало ставки на Чёрных"""
    game_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    bet = await database.get_active_bet(game_id)
    if not bet:
        await callback.answer("❌ Ставки на эту игру уже закрыты!", show_alert=True)
        return

    msg = await callback.message.answer(
        f"💰 **Ставка на Чёрных ⚫**\n\n"
        f"Введите сумму ставки (минимум 50 жетонов):\n"
        f"Ваш баланс: {await database.get_user_tokens(user_id)} 🪙",
        parse_mode=ParseMode.MARKDOWN
    )

    await state.update_data(
        bet_id=bet["id"],
        predicted_winner="Чёрные",
        game_id=game_id,
        prompt_msg_id=msg.message_id
    )
    await state.set_state(BetState.waiting_for_amount)
    await callback.answer()


@router.callback_query(F.data.startswith("bet_skip:"))
async def bet_skip(callback: CallbackQuery):
    """Пропуск ставки"""
    await callback.answer("🔕 Вы пропустили ставки на эту игру")
    try:
        await callback.message.delete()
    except Exception:
        pass


@router.message(BetState.waiting_for_amount)
async def bet_process_amount(message: types.Message, state: FSMContext):
    """Обработка введённой суммы ставки"""
    user_id = message.from_user.id
    data = await state.get_data()
    bet_id = data.get("bet_id")
    predicted_winner = data.get("predicted_winner")
    game_id = data.get("game_id")
    prompt_msg_id = data.get("prompt_msg_id")

    if not bet_id:
        await message.answer("❌ Ошибка: ставка не найдена. Попробуйте снова.")
        await state.clear()
        return

    # Проверяем, активны ли ещё ставки
    bet = await database.get_active_bet(game_id)
    if not bet:
        await message.answer("❌ Ставки на эту игру уже закрыты!")
        await state.clear()
        return

    # Проверяем введенную сумму
    try:
        amount = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите целое число (например: 100). Попробуйте еще раз.")
        return

    if amount < 50:
        await message.answer("❌ Минимальная ставка — 50 жетонов. Введите сумму больше.")
        return

    tokens = await database.get_user_tokens(user_id)
    if amount > tokens:
        await message.answer(f"❌ Не хватает жетонов! У вас {tokens} 🪙, а вы ставите {amount} 🪙.")
        return

    # Сохраняем ставку
    success = await database.place_bet(user_id, bet_id, amount, predicted_winner)
    if not success:
        await message.answer("❌ Ошибка при сохранении ставки. Возможно, вы уже ставили на эту игру.")
        await state.clear()
        return

    # Списываем жетоны С КОММЕНТАРИЕМ ДЛЯ ТРАНЗАКЦИЙ
    team_icon = "🔴" if predicted_winner == "Красные" else "⚫"
    await database.add_tokens(
        user_id,
        -amount,
        comment=f"Ставка на игру: {team_icon} {predicted_winner}"
    )

    await message.answer(
        f"✅ **Ставка принята!**\n\n"
        f"💰 Сумма: {amount} 🪙\n"
        f"🏆 Ваш выбор: {team_icon} {predicted_winner}\n\n"
        f"Результат игры будет рассчитан автоматически в конце игры!",
        parse_mode=ParseMode.MARKDOWN
    )

    # Пытаемся удалить старые сообщения (чтобы не засорять чат)
    try:
        if prompt_msg_id:
            await message.bot.delete_message(message.chat.id, prompt_msg_id)
        await message.delete()  # Удаляем само сообщение с цифрой от пользователя
    except Exception:
        pass

    await state.clear()


@router.callback_query(F.data == "bet_cancel")
async def bet_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена ввода ставки"""
    await state.clear()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer("Ввод ставки отменен")