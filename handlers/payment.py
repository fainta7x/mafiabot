# handlers/payment.py
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
import keyboards
import database  # важно!

router = Router()
bot: Bot | None = None  # сюда положим экземпляр из main


def setup_payment_handlers(bot_instance: Bot):
    global bot
    bot = bot_instance


def payment_kb(user_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Я оплатил(а)", callback_data=f"check_{user_id}")
    return builder.as_markup()


@router.message(F.text == "💳 Оплатить", F.chat.type == "private")
async def pay_from_menu(message: Message):
    kb = payment_kb(message.from_user.id)
    await message.answer(
        f"💰 **Реквизиты для оплаты:**\n\n"
        f"📞 Номер: `{config.PHONE}`\n"
        f"🏦 Банк: {config.BANK}\n\n"
        f"После перевода нажмите кнопку ниже.",
        reply_markup=kb,
        parse_mode="Markdown"
    )


@router.callback_query(F.data.startswith("check_"))
async def to_admin(call: CallbackQuery):
    assert bot is not None
    try:
        u_id = int(call.data.replace("check_", ""))

        # проверяем, есть ли долг
        debt = await database.get_user_debt(u_id)
        if debt >= 0:
            await call.answer(
                "У вас нет долга за игры — оплата сейчас не требуется.",
                show_alert=True
            )
            return

        # Берём данные из БД
        info = await database.get_user_brief(u_id)
        if info:
            full_name, nickname, username = info
        else:
            full_name = call.from_user.full_name
            nickname = None
            username = call.from_user.username

        nick_part = f"Ник: {nickname}" if nickname else "Ник: не указан"
        user_part = f" (@{username})" if username else ""

        text = (
            "🔔 **Запрос оплаты!**\n"
            f"Игрок: {full_name}{user_part}\n"
            f"{nick_part}\n"
            f"ID: `{u_id}`"
        )

        # Отправляем ПЕРВОМУ админу из списка (или всем?)
        if config.ADMIN_IDS:
            await bot.send_message(
                config.ADMIN_IDS[0],  # берём первого админа
                text,
                reply_markup=keyboards.admin_pay_kb(u_id),
                parse_mode="Markdown"
            )
        await call.answer("Запрос отправлен администратору!", show_alert=True)
        await call.message.edit_reply_markup(reply_markup=None)
    except ValueError:
        await call.answer("Ошибка обработки запроса.", show_alert=True)


@router.callback_query(F.data == "pay_now")
async def pay_from_callback(call: CallbackQuery):
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


# ========== ОБРАБОТЧИКИ ДЛЯ АДМИНА (ПОДТВЕРЖДЕНИЕ/ОТКЛОНЕНИЕ ОПЛАТЫ) ==========

@router.callback_query(F.data.startswith("conf_"))
async def confirm_payment(callback: CallbackQuery):
    """Админ подтвердил оплату."""
    assert bot is not None

    # Проверяем, что админ
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("⛔ Недостаточно прав.", show_alert=True)
        return

    try:
        user_id = int(callback.data.replace("conf_", ""))

        # Обнуляем долг
        await database.set_user_debt(user_id, 0)
        await database.set_unpaid_session(user_id, 0)

        await callback.answer("✅ Оплата подтверждена!", show_alert=True)

        # Редактируем сообщение админа
        try:
            await callback.message.edit_text(
                callback.message.text + "\n\n✅ **Оплата подтверждена**",
                parse_mode="Markdown"
            )
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

        # Уведомляем игрока
        try:
            await bot.send_message(
                user_id,
                "✅ Ваша оплата подтверждена администратором! Спасибо!"
            )
        except Exception as e:
            print(f"[PAYMENT] Failed to notify user {user_id}: {e}")

    except ValueError:
        await callback.answer("Ошибка обработки.", show_alert=True)


@router.callback_query(F.data.startswith("decl_"))
async def decline_payment(callback: CallbackQuery):
    """Админ отклонил оплату."""
    assert bot is not None

    # Проверяем, что админ
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("⛔ Недостаточно прав.", show_alert=True)
        return

    try:
        user_id = int(callback.data.replace("decl_", ""))

        await callback.answer("❌ Оплата отклонена", show_alert=True)

        # Редактируем сообщение админа
        try:
            await callback.message.edit_text(
                callback.message.text + "\n\n❌ **Оплата отклонена**",
                parse_mode="Markdown"
            )
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

        # Уведомляем игрока
        try:
            await bot.send_message(
                user_id,
                "❌ Ваша оплата отклонена. Свяжитесь с администратором."
            )
        except Exception as e:
            print(f"[PAYMENT] Failed to notify user {user_id}: {e}")

    except ValueError:
        await callback.answer("Ошибка обработки.", show_alert=True)