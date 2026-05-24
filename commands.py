# main.py или handlers/commands.py

from aiogram.types import BotCommand

async def setup_bot_commands(bot):
    """
    Устанавливает команды для кнопки меню бота.
    """
    commands = [
        BotCommand(command="start", description="🚀 Запустить бота / Главное меню"),
        BotCommand(command="admin", description="🛠 Админ-панель (только для админов)"),
        # Вы можете добавить сюда и другие команды, например:
        # BotCommand(command="help", description="❓ Помощь"),
        # BotCommand(command="stats", description="📊 Статистика"),
    ]
    # Устанавливаем команды для всех пользователей
    await bot.set_my_commands(commands)
    print(f"✅ Установлено команд: {len(commands)}") 