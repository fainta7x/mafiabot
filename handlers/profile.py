from aiogram import Router, F, types
from aiogram.enums import ParseMode
from aiogram.types import FSInputFile

import stats_utils
from database import (
    get_last_games,
    get_user_games,
    get_game_by_id,
    get_last_game_slots,  # новый импорт
)
from keyboards import games_list_kb
from pic_profile import create_profile_pic
from game.pic_endgame import create_endgame_pic_summary  # путь поправь, если pic_endgame лежит не в пакете game

router = Router()


@router.message(F.text == "📊 Статистика")
async def show_user_stats(message: types.Message):
    user_id = message.from_user.id

    try:
        # 1. Данные для картинки профиля
        stats_data = await stats_utils.build_user_stats_data(user_id)

        # 2. Генерируем картинку профиля
        nickname = stats_data.get("nickname") or message.from_user.full_name
        img_path = create_profile_pic(nickname, stats_data)
        print(f"[PROFILE] Generated profile image for {user_id}: {img_path}")

        # 3. Текстовая версия
        text = await stats_utils.build_user_stats_text(user_id)

        # 4. Отправляем картинку + подпись
        photo = FSInputFile(img_path)
        await message.answer_photo(
            photo=photo,
            caption=text,
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        # Fallback — хотя бы текст
        print(f"[PROFILE][ERROR] Failed to send profile image for {user_id}: {e}")
        text = await stats_utils.build_user_stats_text(user_id)
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
    В третьей части передаём game_number (номер игры в вечер).
    """
    try:
        prefix, game_id_str, game_number_str = callback.data.split(":", 2)
        game_id = int(game_id_str)
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
    global_game_number = game.get("global_game_number") or 0

    # Убираем шапку, если вдруг она попала в protocol_text
    lines = protocol.splitlines()
    if lines and lines[0].startswith("📑 Протокол"):
        lines = lines[1:]
    protocol_body = "\n".join(lines).lstrip()

    # Шапка: используем сохранённые номера
    if game_number:
        header = f"📑 Протокол игры №{game_number} ({date_str}): {winner_label}"
    else:
        header = f"📑 Протокол игры ({date_str}): {winner_label}"

    if global_game_number:
        header += f" — №{global_game_number} по общей истории"

    text = header
    if protocol_body:
        text += f"\n\n{protocol_body}"

    # Пробуем нарисовать картинку протокола, если есть слоты последней игры
    try:
        slots = await get_last_game_slots()
        if not slots:
            # Нет слотов — шлём только текст, как раньше
            await callback.message.answer(
                text,
                parse_mode=ParseMode.HTML,
            )
            await callback.answer()
            return

        img_path = create_endgame_pic_summary(
            slots=slots,
            game_date=date_str,
            evening_game_number=game_number or 0,
            global_game_number=global_game_number or 0,
            winner_label=winner_label,
        )
        print(f"[GAME_PROTOCOL] Generated protocol image for game_id={game_id}: {img_path}")

        photo = FSInputFile(img_path)
        await callback.message.answer_photo(
            photo=photo,
            caption=text,
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        print(f"[GAME_PROTOCOL][ERROR] Failed to send image for game_id={game_id}: {e}")
        await callback.message.answer(
            text,
            parse_mode=ParseMode.HTML,
        )

    await callback.answer()