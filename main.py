import asyncio
import logging

from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.types import Update
from aiogram.fsm.storage.memory import MemoryStorage

import config
from database import init_db
from handlers import start_profile, payment, booking, profile, admin_judges
import admin
from game import router as game_router  # игровой роутер
from commands import setup_bot_commands


class MyLoggerMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Update, data):
        if event.message:
            user = event.message.from_user
            print(
                f"📩 СООБЩЕНИЕ | {user.full_name} (@{user.username}) "
                f"| ID: {user.id} | Текст: {event.message.text}"
            )
        elif event.callback_query:
            user = event.callback_query.from_user
            print(
                f"🔘 КНОПКА | {user.full_name} (@{user.username}) "
                f"| Нажал: {event.callback_query.data}"
            )
        return await handler(event, data)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    storage = MemoryStorage()
    bot = Bot(token=config.TOKEN)
    dp = Dispatcher(storage=storage)

    # Логгер (перехватывает все апдейты)
    dp.update.outer_middleware(MyLoggerMiddleware())

    # Передаём bot в модули, где он нужен
    payment.setup_payment_handlers(bot)
    admin.setup_admin_handlers(bot)

    # ========== РЕГИСТРАЦИЯ РОУТЕРОВ (ВАЖНЫЙ ПОРЯДОК!) ==========

    # 1. Сначала самые специфичные хендлеры с фильтрами
    dp.include_router(admin_judges.router)  # управление судьями
    dp.include_router(admin.router)  # админ-панель

    # 2. Пользовательские хендлеры
    dp.include_router(start_profile.router)  # /start
    dp.include_router(profile.router)  # профиль
    dp.include_router(payment.router)  # оплата
    dp.include_router(booking.router)  # запись на игру

    # 3. Игровые роутеры
    dp.include_router(game_router)  # игровая логика

    # 4. Дебаг-роутер (обычно без фильтров, в самом конце)
    # dp.include_router(debug.router)            # раскомментируйте, если файл существует

    # Команды меню
    await setup_bot_commands(bot)
    logger.info("✅ Команды для меню установлены!")

    # Инициализация БД
    await init_db()
    logger.info("✅ БД инициализирована")

    logger.info("🚀 Бот успешно запущен!")

    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("❌ Бот выключен")