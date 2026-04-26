# handlers/shop.py
from aiogram import Router, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder

import database

router = Router()

# Товары в магазине
SHOP_ITEMS = {
    "buy_role": {
        "name": "🎭 Купить роль на игру",
        "description": "Выбрать роль перед началом игры (Мирный/Мафия/Шериф/Дон)",
        "price": 10000,
        "type": "role",
        "icon": "🎭"
    },
    "order_music": {
        "name": "🎵 Заказ музыки",
        "description": "2 песни на вечер (раздача и договорённость)",
        "price": 5000,
        "type": "music",
        "icon": "🎵"
    },
    "free_evening": {
        "name": "🎟️ Бесплатный вечер",
        "description": "Один вечер игры бесплатно (освобождение от оплаты)",
        "price": 30000,
        "type": "free_evening",
        "icon": "🎟️"
    },
}


def get_shop_kb(user_tokens: int) -> InlineKeyboardMarkup:
    """Клавиатура магазина"""
    builder = InlineKeyboardBuilder()

    for item_id, item in SHOP_ITEMS.items():
        builder.button(
            text=f"{item['icon']} {item['name']} — {item['price']} 🪙",
            callback_data=f"shop_buy:{item_id}"
        )

    builder.button(text="🪙 Мои жетоны", callback_data="shop_my_tokens")
    builder.button(text="❌ Закрыть", callback_data="shop_close")
    builder.adjust(1)
    return builder.as_markup()


def get_confirm_kb(item_id: str, item_name: str, price: int) -> InlineKeyboardMarkup:
    """Клавиатура подтверждения покупки"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=f"shop_confirm:{item_id}")
    builder.button(text="❌ Отмена", callback_data="shop_back")
    builder.adjust(2)
    return builder.as_markup()


@router.message(F.text == "🛒 Магазин")
async def show_shop(message: types.Message):
    """Показывает магазин"""
    user_id = message.from_user.id
    tokens = await database.get_user_tokens(user_id)

    text = f"🛒 **МАГАЗИН ЖЕТОНОВ**\n\n"
    text += f"💰 У вас: **{tokens}** 🪙 жетонов\n\n"
    text += "**Доступные товары:**\n"

    for item_id, item in SHOP_ITEMS.items():
        text += f"\n• **{item['icon']} {item['name']}** — {item['price']} 🪙\n"
        text += f"  _{item['description']}_\n"

    text += "\n💡 Жетоны начисляются за:\n"
    text += "• Запись на игру (+500 вовремя, +400 позже)\n"
    text += "• Участие в игре (+100)\n"
    text += "• Победу (+100)\n"
    text += "• Доп. баллы (0.1 = 10 жетонов)\n"
    text += "• 0 фолов (+15)\n"
    text += "⚠️ Штрафы: фолы, техфолы, удаление, ППК\n"

    await message.answer(text, reply_markup=get_shop_kb(tokens), parse_mode=ParseMode.MARKDOWN)


@router.callback_query(F.data == "shop_my_tokens")
async def show_my_tokens(callback: types.CallbackQuery):
    """Показывает количество жетонов"""
    user_id = callback.from_user.id
    tokens = await database.get_user_tokens(user_id)

    await callback.answer(f"💰 У вас {tokens} жетонов", show_alert=True)


@router.callback_query(F.data.startswith("shop_buy:"))
async def buy_item_start(callback: types.CallbackQuery):
    """Начало покупки — запрос подтверждения"""
    item_id = callback.data.split(":")[1]
    user_id = callback.from_user.id

    item = SHOP_ITEMS.get(item_id)
    if not item:
        await callback.answer("❌ Товар не найден!", show_alert=True)
        return

    tokens = await database.get_user_tokens(user_id)

    if tokens < item["price"]:
        await callback.answer(
            f"❌ Не хватает жетонов! Нужно {item['price']}, у вас {tokens}",
            show_alert=True
        )
        return

    text = (
        f"🛒 **Подтверждение покупки**\n\n"
        f"Товар: {item['icon']} **{item['name']}**\n"
        f"💰 Цена: {item['price']} 🪙\n"
        f"📝 {item['description']}\n\n"
        f"У вас: {tokens} 🪙\n\n"
        f"После покупки жетоны будут списаны.\n"
        f"Подтверждаете?"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_confirm_kb(item_id, item["name"], item["price"]),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()


@router.callback_query(F.data.startswith("shop_confirm:"))
async def buy_item_confirm(callback: types.CallbackQuery):
    """Подтверждение покупки и выдача товара"""
    item_id = callback.data.split(":")[1]
    user_id = callback.from_user.id

    item = SHOP_ITEMS.get(item_id)
    if not item:
        await callback.answer("❌ Товар не найден!", show_alert=True)
        return

    # Проверяем баланс ещё раз
    tokens = await database.get_user_tokens(user_id)
    if tokens < item["price"]:
        await callback.answer(
            f"❌ Не хватает жетонов! Нужно {item['price']}, у вас {tokens}",
            show_alert=True
        )
        return

    # Списываем жетоны
    await database.add_tokens(user_id, -item["price"])

    # Логика выдачи товара
    if item["type"] == "role":
        await database.set_setting(f"bought_role_{user_id}", "1")
        await callback.answer(
            f"✅ Вы купили возможность выбрать роль!\n"
            f"Свяжитесь с судьёй перед игрой.",
            show_alert=True
        )
    elif item["type"] == "music":
        await database.set_setting(f"music_order_{user_id}", "1")
        await callback.answer(
            f"✅ Заказ музыки оформлен!\n"
            f"2 песни будут включены на следующем вечере.",
            show_alert=True
        )
    elif item["type"] == "free_evening":
        await database.set_setting(f"free_evening_{user_id}", "1")
        await callback.answer(
            f"✅ Вы купили бесплатный вечер!\n"
            f"При следующем посещении оплата не потребуется.\n"
            f"Сообщите администратору при рассылке счетов.",
            show_alert=True
        )

    new_tokens = tokens - item["price"]

    text = (
        f"🛒 **Покупка успешна!**\n\n"
        f"✅ {item['icon']} **{item['name']}** куплен!\n"
        f"💰 Списано: {item['price']} 🪙\n"
        f"💰 Осталось: {new_tokens} 🪙\n\n"
        f"📝 {item['description']}\n\n"
        f"Вернуться в магазин: /shop"
    )

    await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN)


@router.callback_query(F.data == "shop_back")
async def shop_back(callback: types.CallbackQuery):
    """Возврат в магазин"""
    user_id = callback.from_user.id
    tokens = await database.get_user_tokens(user_id)

    text = f"🛒 **МАГАЗИН ЖЕТОНОВ**\n\n"
    text += f"💰 У вас: **{tokens}** 🪙 жетонов\n\n"
    text += "**Доступные товары:**\n"

    for item_id, item in SHOP_ITEMS.items():
        text += f"\n• **{item['icon']} {item['name']}** — {item['price']} 🪙\n"
        text += f"  _{item['description']}_\n"

    await callback.message.edit_text(
        text,
        reply_markup=get_shop_kb(tokens),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()


@router.callback_query(F.data == "shop_close")
async def close_shop(callback: types.CallbackQuery):
    """Закрывает магазин и возвращает в главное меню"""
    await callback.message.delete()
    await callback.answer()


# ========== КОМАНДА /shop ==========

@router.message(F.text == "/shop")
async def cmd_shop(message: types.Message):
    """Альтернативный вход в магазин через команду"""
    user_id = message.from_user.id
    tokens = await database.get_user_tokens(user_id)

    text = f"🛒 **МАГАЗИН ЖЕТОНОВ**\n\n"
    text += f"💰 У вас: **{tokens}** 🪙 жетонов\n\n"
    text += "**Доступные товары:**\n"

    for item_id, item in SHOP_ITEMS.items():
        text += f"\n• **{item['icon']} {item['name']}** — {item['price']} 🪙\n"
        text += f"  _{item['description']}_\n"

    await message.answer(text, reply_markup=get_shop_kb(tokens), parse_mode=ParseMode.MARKDOWN)