from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardMarkup
from typing import Dict, List

import database

router = Router()

# ========== КАТЕГОРИИ АЧИВОК ==========
CATEGORIES = {
    "games": {"name": "🎮 Игровые", "icon": "🎮", "order": 1},
    "wins": {"name": "🏆 Победные", "icon": "🏆", "order": 2},
    "rating": {"name": "📊 Рейтинговые", "icon": "📊", "order": 3},
    "roles": {"name": "🎭 Ролевые", "icon": "🎭", "order": 4},
    "judge": {"name": "⚖️ Судейские", "icon": "⚖️", "order": 5},
    "special": {"name": "✨ Особые", "icon": "✨", "order": 6},
}

ACHIEVEMENTS = {
    # ========== ИГРОВЫЕ (games) ==========
    "first_game": {
        "name": "Первая игра",
        "description": "Сыграть первую игру",
        "icon": "🎭",
        "category": "games",
        "type": "games",
        "value": 1,
        "rarity": "common",
    },
    "ten_games": {
        "name": "Новичок",
        "description": "Сыграть 10 игр",
        "icon": "🌟",
        "category": "games",
        "type": "games",
        "value": 10,
        "rarity": "common",
    },
    "twenty_games": {
        "name": "Любитель",
        "description": "Сыграть 20 игр",
        "icon": "🎲",
        "category": "games",
        "type": "games",
        "value": 20,
        "rarity": "common",
    },
    "thirty_games": {
        "name": "Завсегдатай",
        "description": "Сыграть 30 игр",
        "icon": "🎯",
        "category": "games",
        "type": "games",
        "value": 30,
        "rarity": "rare",
    },
    "fifty_games": {
        "name": "Опытный игрок",
        "description": "Сыграть 50 игр",
        "icon": "⚡",
        "category": "games",
        "type": "games",
        "value": 50,
        "rarity": "rare",
    },
    "seventy_games": {
        "name": "Профи",
        "description": "Сыграть 70 игр",
        "icon": "🎓",
        "category": "games",
        "type": "games",
        "value": 70,
        "rarity": "epic",
    },
    "hundred_games": {
        "name": "Ветеран",
        "description": "Сыграть 100 игр",
        "icon": "🔥",
        "category": "games",
        "type": "games",
        "value": 100,
        "rarity": "epic",
    },
    "one_fifty_games": {
        "name": "Мастер",
        "description": "Сыграть 150 игр",
        "icon": "🏆",
        "category": "games",
        "type": "games",
        "value": 150,
        "rarity": "legendary",
    },
    "two_hundred_games": {
        "name": "Легенда",
        "description": "Сыграть 200 игр",
        "icon": "👑",
        "category": "games",
        "type": "games",
        "value": 200,
        "rarity": "legendary",
    },

    # ========== ПОБЕДНЫЕ (wins) ==========
    "first_win": {
        "name": "Первая победа",
        "description": "Одержать первую победу",
        "icon": "🏆",
        "category": "wins",
        "type": "wins",
        "value": 1,
        "rarity": "common",
    },
    "five_wins": {
        "name": "Первые успехи",
        "description": "Одержать 5 побед",
        "icon": "🌱",
        "category": "wins",
        "type": "wins",
        "value": 5,
        "rarity": "common",
    },
    "ten_wins": {
        "name": "Серийный победитель",
        "description": "Одержать 10 побед",
        "icon": "🎯",
        "category": "wins",
        "type": "wins",
        "value": 10,
        "rarity": "rare",
    },
    "twenty_wins": {
        "name": "Закалка",
        "description": "Одержать 20 побед",
        "icon": "⚔️",
        "category": "wins",
        "type": "wins",
        "value": 20,
        "rarity": "rare",
    },
    "thirty_wins": {
        "name": "Победный дух",
        "description": "Одержать 30 побед",
        "icon": "🎖️",
        "category": "wins",
        "type": "wins",
        "value": 30,
        "rarity": "rare",
    },
    "forty_wins": {
        "name": "Покоритель",
        "description": "Одержать 40 побед",
        "icon": "⭐",
        "category": "wins",
        "type": "wins",
        "value": 40,
        "rarity": "epic",
    },
    "fifty_wins": {
        "name": "Мастер побед",
        "description": "Одержать 50 побед",
        "icon": "🏅",
        "category": "wins",
        "type": "wins",
        "value": 50,
        "rarity": "epic",
    },
    "seventy_wins": {
        "name": "Герой",
        "description": "Одержать 70 побед",
        "icon": "🦸",
        "category": "wins",
        "type": "wins",
        "value": 70,
        "rarity": "epic",
    },
    "hundred_wins": {
        "name": "Легенда побед",
        "description": "Одержать 100 побед",
        "icon": "🏅",
        "category": "wins",
        "type": "wins",
        "value": 100,
        "rarity": "legendary",
    },

    # ========== РЕЙТИНГОВЫЕ (rating) ==========
    "elo_1400": {
        "name": "Начало пути",
        "description": "Достичь рейтинга Эло 1400",
        "icon": "🌱",
        "category": "rating",
        "type": "rating",
        "value": 1400,
        "rarity": "common",
    },
    "elo_1500": {
        "name": "Старт",
        "description": "Достичь рейтинга Эло 1500",
        "icon": "🌱",
        "category": "rating",
        "type": "rating",
        "value": 1500,
        "rarity": "common",
    },
    "elo_1550": {
        "name": "Бронзовый рейтинг",
        "description": "Достичь рейтинга Эло 1550",
        "icon": "🥉",
        "category": "rating",
        "type": "rating",
        "value": 1550,
        "rarity": "rare",
    },
    "elo_1600": {
        "name": "Серебряный рейтинг",
        "description": "Достичь рейтинга Эло 1600",
        "icon": "⭐",
        "category": "rating",
        "type": "rating",
        "value": 1600,
        "rarity": "rare",
    },
    "elo_1650": {
        "name": "Золотой рейтинг",
        "description": "Достичь рейтинга Эло 1650",
        "icon": "⭐",
        "category": "rating",
        "type": "rating",
        "value": 1650,
        "rarity": "epic",
    },
    "elo_1700": {
        "name": "Платиновый рейтинг",
        "description": "Достичь рейтинга Эло 1700",
        "icon": "🏅",
        "category": "rating",
        "type": "rating",
        "value": 1700,
        "rarity": "epic",
    },
    "elo_1750": {
        "name": "Алмазный рейтинг",
        "description": "Достичь рейтинга Эло 1750",
        "icon": "💎",
        "category": "rating",
        "type": "rating",
        "value": 1750,
        "rarity": "legendary",
    },
    "elo_1800": {
        "name": "Мастер Эло",
        "description": "Достичь рейтинга Эло 1800",
        "icon": "💎",
        "category": "rating",
        "type": "rating",
        "value": 1800,
        "rarity": "legendary",
    },
    "elo_1900": {
        "name": "Элитный рейтинг",
        "description": "Достичь рейтинга Эло 1900",
        "icon": "👑",
        "category": "rating",
        "type": "rating",
        "value": 1900,
        "rarity": "legendary",
    },

    # ========== СУДЕЙСКИЕ (judge) ==========
    "first_judge": {
        "name": "Первое свидание с правосудием",
        "description": "Отсудить первую игру",
        "icon": "⚖️",
        "category": "judge",
        "type": "judged",
        "value": 1,
        "rarity": "common",
    },
    "five_judged": {
        "name": "Стажёр",
        "description": "Отсудить 5 игр",
        "icon": "📋",
        "category": "judge",
        "type": "judged",
        "value": 5,
        "rarity": "common",
    },
    "ten_judged": {
        "name": "Судья",
        "description": "Отсудить 10 игр",
        "icon": "👨‍⚖️",
        "category": "judge",
        "type": "judged",
        "value": 10,
        "rarity": "rare",
    },
    "twenty_judged": {
        "name": "Мировой судья",
        "description": "Отсудить 20 игр",
        "icon": "🏛️",
        "category": "judge",
        "type": "judged",
        "value": 20,
        "rarity": "epic",
    },
    "fifty_judged": {
        "name": "Верховный судья",
        "description": "Отсудить 50 игр",
        "icon": "⚖️👑",
        "category": "judge",
        "type": "judged",
        "value": 50,
        "rarity": "legendary",
    },

    # ========== РОЛЕВЫЕ (roles) ==========
    "sheriff_win": {
        "name": "Защитник города",
        "description": "Выиграть в роли Шерифа",
        "icon": "🕵️",
        "category": "roles",
        "type": "role",
        "value": "Шериф",
        "rarity": "rare",
    },
    "mafia_win": {
        "name": "Тень",
        "description": "Выиграть в роли Мафии",
        "icon": "🔪",
        "category": "roles",
        "type": "role",
        "value": "Мафия",
        "rarity": "rare",
    },
    "don_win": {
        "name": "Крёстный отец",
        "description": "Выиграть в роли Дона",
        "icon": "👑",
        "category": "roles",
        "type": "role",
        "value": "Дон",
        "rarity": "epic",
    },

    # ========== ОСОБЫЕ (special) ==========
    "pu_once": {
        "name": "В центре внимания",
        "description": "Стать ПУ в первый раз",
        "icon": "🎯",
        "category": "special",
        "type": "special",
        "value": 1,
        "rarity": "common",
    },
    "pu_three": {
        "name": "Частая цель",
        "description": "Стать ПУ 3 раза",
        "icon": "🎪",
        "category": "special",
        "type": "special",
        "value": 3,
        "rarity": "rare",
    },
    "pu_master": {
        "name": "ПУ-мастер",
        "description": "Стать ПУ 5 раз",
        "icon": "👑",
        "category": "special",
        "type": "special",
        "value": 5,
        "rarity": "epic",
    },
    "pu_ten": {
        "name": "Легендарная жертва",
        "description": "Стать ПУ 10 раз",
        "icon": "🦁",
        "category": "special",
        "type": "special",
        "value": 10,
        "rarity": "legendary",
    },
    "perfect_game": {
        "name": "Идеальная игра",
        "description": "Закончить игру без фолов и техфолов",
        "icon": "💎",
        "category": "special",
        "type": "special",
        "value": 1,
        "rarity": "epic",
    },
}

# Порядок ачивок для отображения
ACHIEVEMENT_ORDER = [
    "first_game", "ten_games", "twenty_games", "thirty_games", "fifty_games",
    "seventy_games", "hundred_games", "one_fifty_games", "two_hundred_games",
    "first_win", "five_wins", "ten_wins", "twenty_wins", "thirty_wins",
    "forty_wins", "fifty_wins", "seventy_wins", "hundred_wins",
    "elo_1400", "elo_1500", "elo_1550", "elo_1600", "elo_1650",
    "elo_1700", "elo_1750", "elo_1800", "elo_1900",
    "first_judge", "five_judged", "ten_judged", "twenty_judged", "fifty_judged",
    "sheriff_win", "mafia_win", "don_win",
    "pu_once", "pu_three", "pu_master", "pu_ten", "perfect_game",
]

# Редкости
RARITY = {
    "common": {"name": "Обычная", "icon": "⚪"},
    "rare": {"name": "Редкая", "icon": "🔵"},
    "epic": {"name": "Эпическая", "icon": "🟣"},
    "legendary": {"name": "Легендарная", "icon": "🟡"},
}


# ========== ФУНКЦИИ ==========

def get_achievements_kb(user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for cat_id, cat in CATEGORIES.items():
        builder.button(text=f"{cat['icon']} {cat['name']}", callback_data=f"ach_category:{cat_id}")
    builder.button(text="❌ Закрыть", callback_data="ach_close")
    builder.adjust(1)
    return builder.as_markup()


def get_category_kb(category_id: str, user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📖 Все категории", callback_data="ach_menu")
    builder.button(text="❌ Закрыть", callback_data="ach_close")
    builder.adjust(1)
    return builder.as_markup()


async def check_achievement(achievement_id: str, stats: dict) -> bool:
    ach = ACHIEVEMENTS.get(achievement_id)
    if not ach:
        return False
    cond_type = ach["type"]
    try:
        if cond_type == "games":
            return stats.get("games_played", 0) >= ach["value"]
        elif cond_type == "wins":
            return stats.get("games_won", 0) >= ach["value"]
        elif cond_type == "rating":
            return stats.get("elo", 0) >= ach["value"]
        elif cond_type == "special":
            if achievement_id in ["pu_once", "pu_three", "pu_master", "pu_ten"]:
                return stats.get("pu_count", 0) >= ach["value"]
        elif cond_type == "judged":
            return stats.get("judged_games", 0) >= ach["value"]
        elif cond_type == "role":
            role_name = ach["value"]
            role_stats = stats.get("roles", {}).get(role_name, {})
            return role_stats.get("wins", 0) >= 1
    except Exception as e:
        print(f"[ACHIEVEMENT] Error: {e}")
    return False


def get_achievements_by_category(user_achievements: List[str]) -> Dict:
    result = {}
    for cat_id, cat in CATEGORIES.items():
        result[cat_id] = {"name": cat["name"], "icon": cat["icon"], "achievements": []}
    for ach_id, ach in ACHIEVEMENTS.items():
        cat_id = ach["category"]
        result[cat_id]["achievements"].append({
            "id": ach_id,
            "name": ach["name"],
            "description": ach["description"],
            "icon": ach["icon"],
            "rarity": ach["rarity"],
            "earned": ach_id in user_achievements,
            "rarity_info": RARITY[ach["rarity"]]
        })
    return result


# ========== ХЕНДЛЕРЫ ==========

@router.callback_query(F.data == "achievements_menu")
async def achievements_menu_from_stats(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_achievements = await database.get_user_achievements(user_id)
    total = len(ACHIEVEMENTS)
    earned = len(user_achievements)
    progress = int(earned / total * 100) if total > 0 else 0
    text = (
        "📖 **КНИГА АЧИВОК**\n\n"
        f"🏆 Выполнено: {earned}/{total} ачивок\n"
        f"📊 Прогресс: {progress}%\n\n"
        "Выберите категорию для просмотра:"
    )
    await callback.message.answer(text, reply_markup=get_achievements_kb(user_id), parse_mode=ParseMode.MARKDOWN)
    await callback.answer()


@router.callback_query(F.data.startswith("ach_category:"))
async def show_achievements_by_category(callback: CallbackQuery):
    category_id = callback.data.split(":")[1]
    user_id = callback.from_user.id
    user_achievements = await database.get_user_achievements(user_id)
    categories_data = get_achievements_by_category(user_achievements)
    cat_data = categories_data.get(category_id)
    if not cat_data:
        await callback.answer("Категория не найдена")
        return
    text = f"{cat_data['icon']} **{cat_data['name']}**\n\n"
    for ach in cat_data["achievements"]:
        if ach["earned"]:
            status = "✅"
            rarity_icon = ""
        else:
            status = "❌"
            rarity_icon = ach["rarity_info"]["icon"]
        text += f"{status} {ach['icon']} **{ach['name']}** {rarity_icon}\n"
        text += f"   {ach['description']}\n\n"
    text += "\n---\n📊 **Легенда:**\n"
    for rarity_id, rarity in RARITY.items():
        text += f"{rarity['icon']} {rarity['name']}\n"
    await callback.message.edit_text(text, reply_markup=get_category_kb(category_id, user_id), parse_mode=ParseMode.MARKDOWN)
    await callback.answer()


@router.callback_query(F.data == "ach_menu")
async def back_to_achievements_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_achievements = await database.get_user_achievements(user_id)
    total = len(ACHIEVEMENTS)
    earned = len(user_achievements)
    progress = int(earned / total * 100) if total > 0 else 0
    text = (
        "📖 **КНИГА АЧИВОК**\n\n"
        f"🏆 Выполнено: {earned}/{total} ачивок\n"
        f"📊 Прогресс: {progress}%\n\n"
        "Выберите категорию для просмотра:"
    )
    await callback.message.edit_text(text, reply_markup=get_achievements_kb(user_id), parse_mode=ParseMode.MARKDOWN)
    await callback.answer()


@router.callback_query(F.data == "ach_close")
async def close_achievements(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()