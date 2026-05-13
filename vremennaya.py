import asyncio
import aiosqlite

DB_NAME = "mafia_crm.db"


async def recalc_all_tokens():
    print("🔄 Начинаю глобальный пересчет жетонов по новым правилам...\n")

    async with aiosqlite.connect(DB_NAME) as conn:
        conn.row_factory = aiosqlite.Row

        # Получаем всех игроков
        async with conn.execute("SELECT user_id, nickname, full_name, tokens FROM users") as cur:
            users = await cur.fetchall()

        for user in users:
            uid = user['user_id']
            name = user['nickname'] or user['full_name'] or f"ID:{uid}"
            calc_tokens = 0

            # 1. Жетоны за вечера (по 400 за каждый вечер, где сыграна хотя бы 1 игра)
            # COUNT(DISTINCT game_date) считает уникальные дни, когда игрок садился за стол
            async with conn.execute(
                    "SELECT COUNT(DISTINCT game_date) as ev_count FROM game_slots_history WHERE user_id = ?",
                    (uid,)) as cur:
                ev_row = await cur.fetchone()
                evenings_played = ev_row['ev_count'] or 0
                calc_tokens += evenings_played * 400

            # 2. Жетоны за судейство (100 за игру)
            async with conn.execute("SELECT COUNT(*) as j_count FROM game_history WHERE judge_id = ?", (uid,)) as cur:
                judge_row = await cur.fetchone()
                calc_tokens += (judge_row['j_count'] * 100)

            # 3. Жетоны за сами игры
            query = """
                    SELECT s.team, \
                           s.base_points, \
                           s.bonus_points, \
                           s.lh_points,
                           s.will_protocol_points, \
                           s.will_opinion_points, \
                           s.dc_points,
                           s.fouls, \
                           s.technical_fouls, \
                           s.kick, \
                           s.ppk,
                           g.winner_label
                    FROM game_slots_history s
                             JOIN game_history g ON s.game_date = g.game_date AND s.game_number = g.game_number
                    WHERE s.user_id = ? \
                    """
            async with conn.execute(query, (uid,)) as cur:
                slots = await cur.fetchall()

            for s in slots:
                game_tokens = 0
                # За участие
                game_tokens += 100

                # За победу
                is_win = (s['team'] == 'Красные' and s['winner_label'] == 'Победа города') or \
                         (s['team'] == 'Чёрные' and s['winner_label'] == 'Победа мафии')
                if is_win:
                    game_tokens += 100

                # За допы
                total_bonus = (s['bonus_points'] or 0) + (s['lh_points'] or 0) + \
                              (s['will_protocol_points'] or 0) + (s['will_opinion_points'] or 0) + \
                              (s['dc_points'] or 0)
                game_tokens += int(total_bonus * 100)

                # За фолы
                f = s['fouls'] or 0
                if f == 0:
                    game_tokens += 15
                elif f == 1:
                    game_tokens += 10
                elif f == 2:
                    game_tokens += 5

                # Штраф за техфолы
                tf = s['technical_fouls'] or 0
                game_tokens -= (tf * 30)

                # Штраф за удаление и ППК
                if s['kick']: game_tokens -= 100
                if s['ppk']: game_tokens -= 500

                # Лимит -1000 на игру
                calc_tokens += max(game_tokens, -1000)

            # --- ОБНОВЛЕНИЕ БАЗЫ ---
            old_tokens = user['tokens'] or 0

            # Записываем новое, математически идеальное значение
            await conn.execute("UPDATE users SET tokens = ? WHERE user_id = ?", (calc_tokens, uid))

            if old_tokens != calc_tokens:
                diff = calc_tokens - old_tokens
                print(f"🔄 {name}: {old_tokens} 🪙  ➡️  {calc_tokens} 🪙 (Разница: {diff:+d})")
            else:
                print(f"✅ {name}: {calc_tokens} 🪙 (без изменений)")

        # Подтверждаем изменения
        await conn.commit()
        print("\n✅ Глобальный пересчет завершен! База данных обновлена.")


if __name__ == "__main__":
    asyncio.run(recalc_all_tokens())