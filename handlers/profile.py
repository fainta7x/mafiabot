from aiogram import Router, F, types
from aiogram.enums import ParseMode

import stats_utils
from database import get_last_games, get_user_games, get_game_by_id
from keyboards import games_list_kb

router = Router()


@router.message(F.text == "📊 Статистика")
async def show_user_stats(message: types.Message):
    text = await stats_utils.build_user_stats_text(message.from_user.id)
    await message.answer(text)


@router.message(F.text == "📜 Все игры")
async def show_all_games(message: types.Message):
    games = await get_last_games(limit=10)

    if not games:
        await message.answer("Пока нет завершённых игр.")
        return

    buttons_data = []
    for g in games:
        game_id = g["id"]
        date_str = g.get("game_date") or ""
        game_number = g.get("game_number")
        global_game_number = g.get("global_game_number")

        # Если по каким-то старым играм нет номера вечера — fallback к порядковому номеру
        # в списке мы делать не будем, лучше явно показать только дату и, при наличии, глобальный номер.
        if game_number:
            title = f"Игра №{game_number}"
        else:
            title = "Игра"

        if date_str:
            title += f" ({date_str})"

        if global_game_number:
            title += f" — №{global_game_number} по истории"

        buttons_data.append((game_id, title, game_number or 0))

    kb = games_list_kb(buttons_data, prefix="allgames")
    await message.answer("Выбери игру:", reply_markup=kb)


@router.message(F.text == "📜 Мои игры")
async def show_my_games(message: types.Message):
    user_id = message.from_user.id
    games = await get_user_games(user_id=user_id, limit=10)

    if not games:
        await message.answer("Пока нет игр с твоим участием.")
        return

    buttons_data = []
    for g in games:
        game_id = g["id"]
        date_str = g.get("game_date") or ""
        game_number = g.get("game_number")
        global_game_number = g.get("global_game_number")

        if game_number:
            title = f"Игра №{game_number}"
        else:
            title = "Игра"

        if date_str:
            title += f" ({date_str})"

        if global_game_number:
            title += f" — №{global_game_number} по истории"

        buttons_data.append((game_id, title, game_number or 0))

    kb = games_list_kb(buttons_data, prefix="mygames")
    await message.answer("Выбери игру:", reply_markup=kb)


@router.callback_query(F.data.startswith(("allgames:", "mygames:")))
async def show_game_protocol(callback: types.CallbackQuery):
    """
    callback.data: allgames:{game_id}:{game_number} или mygames:{game_id}:{game_number}
    Теперь в качестве третьей части передаём именно game_number (номер игры в вечер),
    а не индекс в текущем списке.
    """
    try:
        prefix, game_id_str, game_number_str = callback.data.split(":", 2)
        game_id = int(game_id_str)
        # game_number в callback скорее всего нужен только как резерв.
        # Настоящее значение мы всё равно возьмём из БД.
        _ = int(game_number_str)
    except Exception:
        await callback.answer("Некорректные данные игры.", show_alert=True)
        return

    game = await get_game_by_id(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    date_str = game.get("game_date") or "-"
    winner_label = game.get("winner_label") or "Результат не указан"
    protocol = (game.get("protocol_text") or "").strip()

    game_number = game.get("game_number")
    global_game_number = game.get("global_game_number")

    # Убираем шапку, если вдруг она всё-таки попала в protocol_text
    lines = protocol.splitlines()
    if lines and lines[0].startswith("📑 Протокол"):
        lines = lines[1:]
    protocol_body = "\n".join(lines).lstrip()

    # Шапка: всегда стараемся использовать сохранённые номера
    if game_number:
        header = f"📑 Протокол игры №{game_number} ({date_str}): {winner_label}"
    else:
        # Fallback для очень старых игр без номера — просто без №
        header = f"📑 Протокол игры ({date_str}): {winner_label}"

    if global_game_number:
        header += f" — №{global_game_number} по общей истории"

    text = header
    if protocol_body:
        text += f"\n\n{protocol_body}"

    await callback.message.answer(
        text,
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()