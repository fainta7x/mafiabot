# full_diagnostic.py
import asyncio
import aiosqlite
from datetime import datetime

DB_NAME = "mafia_crm.db"


async def full_diagnostic():
    print("=" * 60)
    print("🔍 ПОЛНАЯ ДИАГНОСТИКА БОТА")
    print("=" * 60)

    async with aiosqlite.connect(DB_NAME) as conn:
        issues = []
        warnings = []

        # ========== 1. ПРОВЕРКА ТАБЛИЦ ==========
        print("\n📋 1. ПРОВЕРКА ТАБЛИЦ")
        required_tables = [
            "users", "game_history", "game_slots_history", "evening_booking",
            "evening_history", "settings", "elo_ratings", "user_achievements"
        ]
        async with conn.execute("SELECT name FROM sqlite_master WHERE type='table'") as cur:
            existing_tables = {row[0] for row in await cur.fetchall()}
        for table in required_tables:
            if table in existing_tables:
                print(f"   ✅ {table}")
            else:
                print(f"   ❌ ОТСУТСТВУЕТ: {table}")
                issues.append(f"Отсутствует таблица: {table}")

        # ========== 2. ПРОВЕРКА КОЛОНОК В users ==========
        print("\n👤 2. ПРОВЕРКА ТАБЛИЦЫ users")
        required_user_cols = [
            "user_id", "nickname", "games_played", "games_won", "tokens", "debt"
        ]
        async with conn.execute("PRAGMA table_info(users)") as cur:
            user_cols = {row[1] for row in await cur.fetchall()}
        for col in required_user_cols:
            if col in user_cols:
                print(f"   ✅ {col}")
            else:
                print(f"   ⚠️ ОТСУТСТВУЕТ: {col}")
                warnings.append(f"В таблице users нет колонки: {col}")

        # ========== 3. ПРОВЕРКА ПОЛЬЗОВАТЕЛЕЙ ==========
        print("\n👥 3. ПРОВЕРКА ПОЛЬЗОВАТЕЛЕЙ")
        async with conn.execute("SELECT COUNT(*) FROM users") as cur:
            user_count = (await cur.fetchone())[0]
            print(f"   👤 Всего пользователей: {user_count}")

        async with conn.execute("SELECT user_id, nickname, tokens FROM users ORDER BY tokens DESC LIMIT 5") as cur:
            top_tokens = await cur.fetchall()
            if top_tokens:
                print("   💰 Топ по жетонам:")
                for uid, nick, tokens in top_tokens:
                    print(f"      • {nick or uid}: {tokens or 0} жетонов")

        # ========== 4. ПРОВЕРКА ИГР ==========
        print("\n🎮 4. ПРОВЕРКА ИГР")
        async with conn.execute("SELECT COUNT(*) FROM game_history") as cur:
            games_count = (await cur.fetchone())[0]
            print(f"   📊 Всего игр: {games_count}")

        # Проверка игр без победителя
        async with conn.execute("SELECT id, game_number, winner_label FROM game_history WHERE winner_label IS NULL OR winner_label = ''") as cur:
            no_winner = await cur.fetchall()
            if no_winner:
                print(f"   ⚠️ Игр без победителя: {len(no_winner)}")
                for gid, num, _ in no_winner:
                    print(f"      • Игра #{num} (ID: {gid})")
                warnings.append(f"{len(no_winner)} игр без победителя")

        # ========== 5. ПРОВЕРКА НЕСООТВЕТСТВИЙ ПОБЕД ==========
        print("\n🏆 5. ПРОВЕРКА ПОБЕД")
        async with conn.execute("""
            SELECT u.user_id, u.nickname, u.games_won as users_wins,
                   (SELECT COUNT(*) FROM game_slots_history WHERE user_id = u.user_id AND base_points = 1) as real_wins
            FROM users u
            WHERE u.games_played > 0
        """) as cur:
            rows = await cur.fetchall()
            mismatches = 0
            for uid, nick, users_wins, real_wins in rows:
                if users_wins != real_wins:
                    mismatches += 1
                    print(f"   ⚠️ {nick or uid}: users={users_wins}, реально={real_wins}")
                    warnings.append(f"Расхождение побед у {nick or uid}: users={users_wins}, реально={real_wins}")
            if mismatches == 0:
                print("   ✅ Все победы совпадают")

        # ========== 6. ПРОВЕРКА АЧИВОК ==========
        print("\n🏅 6. ПРОВЕРКА АЧИВОК")
        async with conn.execute("SELECT COUNT(*) FROM user_achievements") as cur:
            ach_count = (await cur.fetchone())[0]
            print(f"   📖 Всего выдано ачивок: {ach_count}")

        async with conn.execute("""
            SELECT u.nickname, COUNT(ua.achievement_id) as ach_count
            FROM users u
            LEFT JOIN user_achievements ua ON u.user_id = ua.user_id
            WHERE u.games_played > 0
            GROUP BY u.user_id
            ORDER BY ach_count DESC
            LIMIT 5
        """) as cur:
            top_ach = await cur.fetchall()
            if top_ach:
                print("   🏆 Топ по ачивкам:")
                for nick, count in top_ach:
                    print(f"      • {nick or 'Неизвестный'}: {count}")

        # ========== 7. ПРОВЕРКА ЖЕТОНОВ ==========
        print("\n💰 7. ПРОВЕРКА ЖЕТОНОВ")
        async with conn.execute("SELECT COUNT(*) FROM users WHERE tokens > 0") as cur:
            tokens_users = (await cur.fetchone())[0]
            print(f"   💰 Игроков с жетонами: {tokens_users}")

        async with conn.execute("SELECT SUM(tokens) FROM users") as cur:
            total_tokens = (await cur.fetchone())[0] or 0
            print(f"   💰 Всего жетонов в системе: {total_tokens}")

        # ========== 8. ПРОВЕРКА СТАВОК ==========
        print("\n📊 8. ПРОВЕРКА СТАВОК")
        async with conn.execute("SELECT COUNT(*) FROM bets_active WHERE resolved = 0") as cur:
            active_bets = (await cur.fetchone())[0]
            print(f"   ❓ Активных ставок: {active_bets}")

        async with conn.execute("SELECT COUNT(*) FROM user_bets") as cur:
            total_bets = (await cur.fetchone())[0]
            print(f"   💸 Всего сделано ставок: {total_bets}")

        # ========== 9. ПРОВЕРКА СУДЕЙ ==========
        print("\n⚖️ 9. ПРОВЕРКА СУДЕЙ")
        async with conn.execute("SELECT COUNT(*) FROM game_history WHERE judge_id IS NOT NULL AND judge_id > 0") as cur:
            games_with_judge = (await cur.fetchone())[0]
            print(f"   📋 Игр с назначенным судьёй: {games_with_judge}")

        # ========== 10. ПРОВЕРКА ОШИБОК В ДАННЫХ ==========
        print("\n🐛 10. ПРОВЕРКА ОШИБОК В ДАННЫХ")
        async with conn.execute("SELECT COUNT(*) FROM game_slots_history WHERE user_id IS NULL OR user_id <= 0") as cur:
            null_users = (await cur.fetchone())[0]
            if null_users > 0:
                print(f"   ⚠️ Слотов без привязки к пользователю: {null_users}")
                warnings.append(f"{null_users} слотов без user_id")

        async with conn.execute("SELECT COUNT(*) FROM game_slots_history WHERE role IS NULL OR role = ''") as cur:
            null_roles = (await cur.fetchone())[0]
            if null_roles > 0:
                print(f"   ⚠️ Слотов без роли: {null_roles}")
                warnings.append(f"{null_roles} слотов без роли")

        # ========== 11. ПРОВЕРКА АКТИВНОЙ ИГРЫ ==========
        print("\n🎲 11. ПРОВЕРКА АКТИВНОЙ ИГРЫ")
        game_active = await conn.execute("SELECT value FROM settings WHERE key = 'game_active'")
        active = await game_active.fetchone()
        if active and active[0] == "1":
            print("   ⚠️ Есть активная незавершённая игра!")
            warnings.append("Есть активная незавершённая игра")
        else:
            print("   ✅ Активных игр нет")

        # ========== 12. ПРОВЕРКА evening_archived ==========
        print("\n📅 12. ПРОВЕРКА СТАТУСА ВЕЧЕРА")
        archived = await conn.execute("SELECT value FROM settings WHERE key = 'evening_archived'")
        arch = await archived.fetchone()
        if arch and arch[0] == "1":
            print("   📅 Вечер архивирован")
        else:
            print("   📅 Вечер не архивирован")

        # ========== ИТОГИ ==========
        print("\n" + "=" * 60)
        print("📊 ИТОГИ ДИАГНОСТИКИ")
        print("=" * 60)

        if issues:
            print(f"\n❌ НАЙДЕНЫ ОШИБКИ ({len(issues)}):")
            for issue in issues:
                print(f"   • {issue}")
        else:
            print("\n✅ КРИТИЧЕСКИХ ОШИБОК НЕТ")

        if warnings:
            print(f"\n⚠️ ПРЕДУПРЕЖДЕНИЯ ({len(warnings)}):")
            for warning in warnings:
                print(f"   • {warning}")
        else:
            print("\n✅ ПРЕДУПРЕЖДЕНИЙ НЕТ")

        print("\n" + "=" * 60)

        # Рекомендации
        if active and active[0] == "1":
            print("\n💡 РЕКОМЕНДАЦИИ:")
            print("   • Завершите активную игру через кнопку 'Завершить'")
            print("   • Если игра была отменена, используйте 'Остановить'")

        if mismatches > 0:
            print("\n💡 РЕКОМЕНДАЦИИ:")
            print("   • Запустите скрипт sync_wins.py для синхронизации побед")

        print("\n✅ Диагностика завершена!")


async def check_elo_rating():
    """Проверка корректности рейтинга Эло"""
    print("\n" + "=" * 60)
    print("📊 ПРОВЕРКА РЕЙТИНГА ЭЛО")
    print("=" * 60)

    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute("""
            SELECT u.nickname, e.elo, e.games_played, e.games_won
            FROM elo_ratings e
            JOIN users u ON e.user_id = u.user_id
            ORDER BY e.elo DESC
            LIMIT 10
        """) as cur:
            rows = await cur.fetchall()
            print("\n   🏆 ТОП-10 РЕЙТИНГА ЭЛО:")
            for i, (nick, elo, games, wins) in enumerate(rows, 1):
                print(f"      {i}. {nick or 'Неизвестный'}: {elo} ({games} игр, {wins} побед)")

        # Проверка среднего Эло
        async with conn.execute("SELECT AVG(elo) FROM elo_ratings") as cur:
            avg_elo = (await cur.fetchone())[0] or 0
            print(f"\n   📊 Средний Эло: {avg_elo:.0f} (норма ~1500)")

        if avg_elo < 1400 or avg_elo > 1600:
            print("   ⚠️ Средний Эло сильно отклоняется от 1500")
        else:
            print("   ✅ Средний Эло в норме")


if __name__ == "__main__":
    print("🔍 ЗАПУСК ПОЛНОЙ ДИАГНОСТИКИ...\n")
    asyncio.run(full_diagnostic())
    asyncio.run(check_elo_rating())