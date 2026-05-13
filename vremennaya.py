import asyncio
import aiosqlite

DB_NAME = "mafia_crm.db"


async def add_protection_trigger():
    """Добавляет триггер для защиты данных игр"""
    async with aiosqlite.connect(DB_NAME) as conn:
        # Создаём таблицу для лога попыток взлома
        await conn.execute("""
                           CREATE TABLE IF NOT EXISTS security_log
                           (
                               id         INTEGER PRIMARY KEY AUTOINCREMENT,
                               timestamp  TEXT DEFAULT CURRENT_TIMESTAMP,
                               action     TEXT,
                               table_name TEXT,
                               details    TEXT
                           )
                           """)

        # Триггер на UPDATE для защиты полей
        await conn.execute("DROP TRIGGER IF EXISTS protect_game_data")
        await conn.execute("""
                           CREATE TRIGGER protect_game_data
                               BEFORE UPDATE
                               ON game_slots_history
                               FOR EACH ROW
                               WHEN (
                                   -- Защищаем эти поля от случайного изменения
                                   OLD.base_points != NEW.base_points OR
                                   OLD.bonus_points != NEW.bonus_points OR
                                   OLD.lh_points != NEW.lh_points OR
                                   OLD.will_protocol_points != NEW.will_protocol_points OR
                                   OLD.will_opinion_points != NEW.will_opinion_points OR
                                   OLD.dc_points != NEW.dc_points OR
                                   OLD.will_protocol_raw != NEW.will_protocol_raw OR
                                   OLD.will_opinion != NEW.will_opinion OR
                                   OLD.role != NEW.role OR
                                   OLD.team != NEW.team
                                   )
                           BEGIN
                               -- Логируем попытку изменения
                               INSERT INTO security_log (action, table_name, details)
                               VALUES ('PROTECTED_UPDATE', 'game_slots_history',
                                       'Попытка изменения защищённых полей. User not in editor mode.');

                               -- Блокируем изменение (можно закомментировать, если только логировать)
                               SELECT RAISE(FAIL, 'Изменение данных игры разрешено только через редактор!');
                           END
                           """)

        # Отдельный триггер, разрешающий обновление Эло
        await conn.execute("DROP TRIGGER IF EXISTS allow_elo_update")
        await conn.execute("""
                           CREATE TRIGGER allow_elo_update
                               BEFORE UPDATE
                               ON game_slots_history
                               FOR EACH ROW
                               WHEN (
                                        -- Разрешаем менять только Эло
                                        NEW.elo_change IS NOT OLD.elo_change OR
                                        NEW.new_elo IS NOT OLD.new_elo
                                        ) AND (
                                        -- Но другие поля не должны меняться
                                        OLD.base_points = NEW.base_points AND
                                        OLD.bonus_points = NEW.bonus_points AND
                                        OLD.role = NEW.role AND
                                        OLD.team = NEW.team
                                        )
                           BEGIN
                               -- Разрешаем, ничего не делаем
                               SELECT 1;
                           END
                           """)

        await conn.commit()
        print("✅ Триггеры защиты добавлены!")
        print("   - Изменение данных игр разрешено только через редактор")
        print("   - Обновление Эло разрешено автоматически")
        print("   - Попытки взлома логируются в security_log")


if __name__ == "__main__":
    asyncio.run(add_protection_trigger())