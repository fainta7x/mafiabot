# backfill_achievements.py
import asyncio
import aiosqlite
from achievements import ACHIEVEMENTS, ACHIEVEMENT_ORDER


async def get_user_stats(user_id: int) -> dict:
    """Собирает статистику игрока из БД"""
    async with aiosqlite.connect("mafia_crm.db") as conn:
        # Имя
        async with conn.execute("SELECT nickname, full_name FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            nickname = row[0] or row[1] if row else str(user_id)

        # Игровая статистика
        async with conn.execute("""
                                SELECT COALESCE(SUM(CASE WHEN base_points = 1 THEN 1 ELSE 0 END), 0) as wins,
                                       COUNT(*)                                                      as games
                                FROM game_slots_history
                                WHERE user_id = ?
                                """, (user_id,)) as cur:
            row = await cur.fetchone()
            wins, games = row

        # Эло
        async with conn.execute("SELECT elo FROM elo_ratings WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            elo = row[0] if row else 1500

        # ПУ
        async with conn.execute("SELECT COUNT(*) FROM game_slots_history WHERE user_id = ? AND pu = 1",
                                (user_id,)) as cur:
            row = await cur.fetchone()
            pu_count = row[0] if row else 0

        # Статистика по ролям
        async with conn.execute("""
                                SELECT role, SUM(CASE WHEN base_points = 1 THEN 1 ELSE 0 END) as wins
                                FROM game_slots_history
                                WHERE user_id = ?
                                GROUP BY role
                                """, (user_id,)) as cur:
            role_stats = {role: {"wins": wins} for role, wins in await cur.fetchall()}

        return {
            "nickname": nickname,
            "games_played": games,
            "games_won": wins,
            "elo": elo,
            "pu_count": pu_count,
            "roles": role_stats,
            "perfect_game_count": 0,  # пока не считаем
        }


def check_achievement(ach_id: str, stats: dict) -> bool:
    """Универсальная проверка ачивки"""
    ach = ACHIEVEMENTS.get(ach_id)
    if not ach:
        return False

    cond_type = ach.get("type")

    try:
        if cond_type == "games":
            return stats.get("games_played", 0) >= ach["value"]
        elif cond_type == "wins":
            return stats.get("games_won", 0) >= ach["value"]
        elif cond_type == "rating":
            return stats.get("elo", 0) >= ach["value"]
        elif cond_type == "special":
            if ach_id == "pu_master":
                return stats.get("pu_count", 0) >= ach["value"]
        elif cond_type == "role":
            role_name = ach["value"]
            return stats.get("roles", {}).get(role_name, {}).get("wins", 0) >= 1
    except:
        pass
    return False


async def backfill():
    async with aiosqlite.connect("mafia_crm.db") as conn:
        # Все игроки, у которых есть игры
        async with conn.execute("SELECT DISTINCT user_id FROM game_slots_history WHERE user_id IS NOT NULL") as cur:
            users = await cur.fetchall()

        print(f"Найдено игроков: {len(users)}")

        for (user_id,) in users:
            stats = await get_user_stats(user_id)
            print(f"\n👤 {stats['nickname']} (игр: {stats['games_played']}, побед: {stats['games_won']})")

            # Получаем уже выданные
            async with conn.execute("SELECT achievement_id FROM user_achievements WHERE user_id = ?",
                                    (user_id,)) as cur:
                existing = {row[0] for row in await cur.fetchall()}

            new = []
            for ach_id in ACHIEVEMENT_ORDER:
                if ach_id in existing:
                    continue
                if check_achievement(ach_id, stats):
                    new.append(ach_id)
                    print(f"  🎉 +{ACHIEVEMENTS[ach_id]['name']}")

            for ach_id in new:
                await conn.execute(
                    "INSERT INTO user_achievements (user_id, achievement_id) VALUES (?, ?)",
                    (user_id, ach_id)
                )
            await conn.commit()

        print("\n✅ Готово!")


if __name__ == "__main__":
    asyncio.run(backfill())