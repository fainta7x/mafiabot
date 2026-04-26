import asyncio
import aiosqlite
from game.text import build_protocol_text
from database import get_game_slots_by_date, get_game_by_id


async def regenerate_protocols():
    async with aiosqlite.connect("mafia_crm.db") as conn:
        async with conn.execute("SELECT id, game_date, game_number, winner_label FROM game_history") as cur:
            games = await cur.fetchall()

        for game_id, game_date, game_number, winner_label in games:
            print(f"Обновляем игру #{game_number}...")
            slots = await get_game_slots_by_date(game_date, game_number)
            if slots:
                new_protocol = await build_protocol_text(slots, winner_label=winner_label)
                await conn.execute(
                    "UPDATE game_history SET protocol_text = ? WHERE id = ?",
                    (new_protocol, game_id)
                )
        await conn.commit()
        print("✅ Все протоколы обновлены!")


asyncio.run(regenerate_protocols())