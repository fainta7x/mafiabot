import asyncio
import aiosqlite
from collections import defaultdict


# Логика расчета для одной игры
def calculate_game_earnings(slot: dict, is_win: bool) -> int:
    tokens = 0
    if is_win: tokens += 100

    total_bonus = (
            float(slot.get("bonus_points", 0)) +
            float(slot.get("lh_points", 0)) +
            float(slot.get("will_protocol_points", 0)) +
            float(slot.get("will_opinion_points", 0)) +
            float(slot.get("dc_points", 0))
    )
    tokens += int(total_bonus * 100)

    fouls = slot.get("fouls", 0)
    if fouls == 0:
        tokens += 15
    elif fouls == 1:
        tokens += 10
    elif fouls == 2:
        tokens += 5

    tech_fouls = slot.get("technical_fouls")
    if tech_fouls:
        if isinstance(tech_fouls, int): tokens -= tech_fouls * 30

    if slot.get("kick", False): tokens -= 100
    if slot.get("ppk", False): tokens -= 500
    return tokens


async def debug_player():
    target_name = "Диссонанс"

    async with aiosqlite.connect("mafia_crm.db") as db:
        # 1. Ищем ID игрока
        async with db.execute("SELECT user_id, tokens FROM users WHERE nickname = ?", (target_name,)) as cursor:
            user = await cursor.fetchone()

        if not user:
            print(f"Игрок '{target_name}' не найден в базе!")
            return

        user_id, current_tokens = user
        print(f"🔍 Детальный отчет для: {target_name} (ID: {user_id})")
        print(f"💰 Текущий баланс в БД: {current_tokens}\n")

        # 2. Выгружаем игры
        query = """
            SELECT s.game_date, s.game_number, s.base_points, s.bonus_points, s.lh_points, 
                   s.will_protocol_points, s.will_opinion_points, s.dc_points, 
                   s.fouls, s.technical_fouls, s.kick, s.ppk, s.team, h.winner_label
            FROM game_slots_history s
            LEFT JOIN game_history h ON s.game_date = h.game_date AND s.game_number = h.game_number
            WHERE s.user_id = ?
            ORDER BY s.game_date
        """
        async with db.execute(query, (user_id,)) as cursor:
            rows = await cursor.fetchall()

        evening_data = defaultdict(list)
        for row in rows:
            evening_data[row[0]].append(row)

        grand_total = 0
        for date, games in evening_data.items():
            print(f"📅 Вечер {date}:")
            evening_sum = 400  # База
            print(f"   • Выход на вечер: +400")

            for g in games:
                slot_data = {
                    "base_points": g[2], "bonus_points": g[3], "lh_points": g[4],
                    "will_protocol_points": g[5], "will_opinion_points": g[6],
                    "dc_points": g[7], "fouls": g[8], "technical_fouls": g[9],
                    "kick": g[10], "ppk": g[11], "team": g[12]
                }
                winner_label = g[13]
                is_win = (slot_data["team"] == "Красные" and (
                            "Красные" in str(winner_label) or "города" in str(winner_label).lower())) or \
                         (slot_data["team"] == "Чёрные" and (
                                     "Чёрные" in str(winner_label) or "мафии" in str(winner_label).lower()))

                game_earnings = calculate_game_earnings(slot_data, is_win)
                evening_sum += game_earnings
                print(f"   • Игра #{g[1]} ({slot_data['team']}): {game_earnings:+d} (Победа: {is_win})")

            print(f"   Итого за вечер: {evening_sum}")
            grand_total += evening_sum

        print(f"\n📊 Итого по расчетам: {grand_total}")
        print(f"⚖️ Разница с БД: {grand_total - current_tokens:+d}")


if __name__ == "__main__":
    asyncio.run(debug_player())