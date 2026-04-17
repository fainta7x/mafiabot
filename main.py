# main.py
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

import config
from database import init_db
from handlers import start_profile, payment, booking, debug, game
import admin

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    storage = MemoryStorage()
    bot = Bot(token=config.TOKEN)
    dp = Dispatcher(storage=storage)

    # передаём bot в модули, где он нужен
    payment.setup_payment_handlers(bot)
    admin.setup_admin_handlers(bot)

    # регистрируем все роутеры
    dp.include_router(game.router)
    dp.include_router(start_profile.router)
    dp.include_router(payment.router)
    dp.include_router(booking.router)
    dp.include_router(admin.router)
    dp.include_router(debug.router)


    await init_db()
    logger.info("Бот успешно запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())