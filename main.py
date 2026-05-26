import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.types import Update, FSInputFile
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web
import config
from database import init_db
from handlers import start_profile, payment, booking, profile, admin_judges
from handlers import achievements
from handlers import shop
import admin
from game import router as game_router  # игровой роутер
from commands import setup_bot_commands
import datetime
import database as db

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

bot = None
dp = None


async def on_startup():
    global bot, dp

    await init_db()
    logger.info("✅ БД инициализирована")

    await bot.delete_webhook(drop_pending_updates=True)

    await setup_bot_commands(bot)
    logger.info("✅ Команды для меню установлены!")

    webhook_url = f"{config.WEBHOOK_URL}/webhook"
    await bot.set_webhook(webhook_url, allowed_updates=["message", "callback_query"])
    logger.info(f"✅ Вебхук установлен: {webhook_url}")


async def on_shutdown():
    global bot
    await bot.delete_webhook()
    await bot.session.close()
    logger.info("✅ Бот остановлен")


async def handle_webhook(request):
    global dp, bot

    try:
        update_data = await request.json()
        update = Update(**update_data)
        await dp.feed_update(bot, update)
        return web.Response(status=200)
    except Exception as e:
        logger.error(f"Ошибка обработки вебхука: {e}", exc_info=True)
        return web.Response(status=200)


def setup_handlers():
    """Регистрация всех хендлеров и роутеров"""
    global dp, bot

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

    # 5. Ачивки
    dp.include_router(achievements.router)

    # 6. Магазин
    dp.include_router(shop.router)


# Автоматические бэкапы в 3:00
async def daily_backup_task():
    """Фоновая задача для ежедневного бэкапа в 3:00"""
    global bot
    
    while True:
        now = datetime.datetime.now()
        next_backup = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if now >= next_backup:
            next_backup += datetime.timedelta(days=1)
        
        wait_seconds = (next_backup - now).total_seconds()
        logger.info(f"⏰ Следующий бэкап через {wait_seconds/3600:.1f} часов")
        await asyncio.sleep(wait_seconds)
        
        if bot is None:
            logger.error("❌ Бот не инициализирован, бэкап не создан")
            continue
        
        backup_path = await db.create_backup_file()
        
        if backup_path:
            try:
                await bot.send_document(
                    config.BACKUP_ADMIN_ID, 
                    FSInputFile(backup_path),
                    caption="📁 **Ежедневный бэкап**\n\n"
                            f"📅 Дата: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')}",
                    parse_mode="Markdown"
                )
                logger.info(f"✅ Бэкап отправлен админу {config.BACKUP_ADMIN_ID}")
            except Exception as e:
                logger.error(f"❌ Ошибка отправки бэкапа: {e}")
            finally:
                await db.delete_temp_file(backup_path)


# Старт вебхуков для сервера
async def start_webhook():
    global bot, dp
    storage = MemoryStorage()
    bot = Bot(token=config.TOKEN)
    dp = Dispatcher(storage=storage)

    setup_handlers()

    asyncio.create_task(daily_backup_task())
    logger.info("✅ Задача ежедневного бэкапа запущена")

    app = web.Application()
    app.router.add_post("/webhook", handle_webhook)
    app.router.add_get("/health", lambda request: web.Response(text="OK"))
    app.on_startup.append(lambda _: on_startup())
    app.on_shutdown.append(lambda _: on_shutdown())

    port = int(os.environ.get("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()

    logger.info(f"🚀 Бот запущен на порту {port} в режиме webhook")
    logger.info(f"📍 Вебхук URL: {config.WEBHOOK_URL}/webhook")
    await asyncio.Event().wait()


async def start_polling(): #запуск в режиме polling (для локальной разработки)
    global bot, dp

    storage = MemoryStorage()
    bot = Bot(token=config.TOKEN)
    dp = Dispatcher(storage=storage)
    setup_handlers()

    await init_db()
    logger.info("✅ БД инициализирована")
    await bot.delete_webhook(drop_pending_updates=True)

    logger.info("🚀 Бот запущен в режиме polling (локально)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        USE_WEBHOOK = os.environ.get("USE_WEBHOOK", "False").lower() == "true"

        if USE_WEBHOOK:
            asyncio.run(start_webhook())
        else:
            asyncio.run(start_polling())

    except KeyboardInterrupt:
        print("❌ Бот выключен")