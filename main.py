import asyncio
import logging

from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.types import Update
from aiogram.fsm.storage.memory import MemoryStorage

import config
from database import init_db
from handlers import start_profile, payment, booking, debug, profile
import admin
from game import router as game_router
from commands import setup_bot_commands  # ← ДОБАВИТЬ импорт

# 1. Описываем класс логгера ВНЕ функции main, чтобы Python его видел
class MyLoggerMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Update, data):
        if event.message:
            user = event.message.from_user
            # Добавили @username в вывод
            print(f"📩 СООБЩЕНИЕ | {user.full_name} (@{user.username}) | ID: {user.id} | Текст: {event.message.text}")
        elif event.callback_query:
            user = event.callback_query.from_user
            print(f"🔘 КНОПКА | {user.full_name} (@{user.username}) | Нажал: {event.callback_query.data}")
        return await handler(event, data)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    storage = MemoryStorage()
    bot = Bot(token=config.TOKEN)
    dp = Dispatcher(storage=storage)

    # 2. Регистрируем логгер СРАЗУ после создания dp
    dp.update.outer_middleware(MyLoggerMiddleware())

    # Передаём bot в модули, где он нужен
    payment.setup_payment_handlers(bot)
    admin.setup_admin_handlers(bot)

    # Регистрируем все роутеры (по одному разу)
    dp.include_router(game_router)
    dp.include_router(start_profile.router)
    dp.include_router(profile.router)
    dp.include_router(payment.router)
    dp.include_router(booking.router)
    dp.include_router(admin.router)
    dp.include_router(debug.router)

    # ========== ДОБАВИТЬ: Устанавливаем команды для кнопки меню ==========
    await setup_bot_commands(bot)
    logger.info("✅ Команды для меню установлены!")

    await init_db()
    logger.info("Бот успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот выключен")