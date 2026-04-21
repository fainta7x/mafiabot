import json
from typing import Optional, Tuple, List, Dict, Any, Union
from contextlib import asynccontextmanager
import aiosqlite

DB_NAME = "mafia_crm.db"


# ========== УТИЛИТЫ ДЛЯ РАБОТЫ С БД ==========
@asynccontextmanager
async def get_db():
    """Контекстный менеджер для соединения с БД."""
    async with aiosqlite.connect(DB_NAME) as conn:
        yield conn


async def _ensure_columns():
    """Гарантирует наличие всех нужных колонок в существующих таблицах."""
    alters = [
        ("users", ["games_played", "games_won", "points"], "INTEGER DEFAULT 0"),
        ("users", ["kicks", "ppk_causes"], "INTEGER DEFAULT 0"),
        ("game_history", ["game_number", "global_game_number"], "INTEGER"),
        ("game_slots_history", ["will_protocol_points", "will_opinion_points"], "REAL DEFAULT 0"),
        ("game_slots_history", ["kick", "ppk", "technical_fouls"], "INTEGER DEFAULT 0"),
        ("game_slots_history", ["dc_points"], "REAL DEFAULT 0"),  # НОВАЯ КОЛОНКА
    ]
    async with get_db() as conn:
        for table, cols, col_type in alters:
            for col in cols:
                try:
                    await conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                except Exception:
                    pass
        await conn.commit()


# ========== 1. ИНИЦИАЛИЗАЦИЯ ==========
async def init_db():
    """Инициализация всех таблиц."""
    async with get_db() as conn:
        # Основные таблицы
        await conn.execute("""
                           CREATE TABLE IF NOT EXISTS game_slots_history
                           (
                               id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                               game_date            TEXT,
                               user_id              INTEGER,
                               slot_num             INTEGER,
                               role                 TEXT,
                               team                 TEXT,
                               base_points          REAL    DEFAULT 0,
                               bonus_points         REAL    DEFAULT 0,
                               lh_points            REAL    DEFAULT 0,
                               will_protocol_points REAL    DEFAULT 0,
                               will_opinion_points  REAL    DEFAULT 0,
                               dc_points            REAL    DEFAULT 0,
                               kick                 INTEGER DEFAULT 0,
                               ppk                  INTEGER DEFAULT 0,
                               technical_fouls      INTEGER DEFAULT 0
                           )
                           """)
        await conn.execute("""
                           CREATE TABLE IF NOT EXISTS evening_booking
                           (
                               user_id INTEGER PRIMARY KEY,
                               status  TEXT,
                               date    TEXT
                           )
                           """)
        await conn.execute("""
                           CREATE TABLE IF NOT EXISTS evening_history
                           (
                               id        INTEGER PRIMARY KEY AUTOINCREMENT,
                               date      TEXT,
                               user_id   INTEGER,
                               status    TEXT,
                               full_name TEXT,
                               nickname  TEXT,
                               amount    INTEGER DEFAULT 0
                           )
                           """)
        await conn.execute("""
                           CREATE TABLE IF NOT EXISTS evening_stats_messages
                           (
                               date       TEXT PRIMARY KEY,
                               chat_id    INTEGER,
                               message_id INTEGER
                           )
                           """)
        await conn.execute("""
                           CREATE TABLE IF NOT EXISTS evening_status
                           (
                               date       TEXT PRIMARY KEY,
                               bills_sent INTEGER DEFAULT 0
                           )
                           """)
        await conn.execute("""
                           CREATE TABLE IF NOT EXISTS settings
                           (
                               key   TEXT PRIMARY KEY,
                               value TEXT
                           )
                           """)
        await conn.execute("""
                           CREATE TABLE IF NOT EXISTS game_slots_history
                           (
                               id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                               game_date            TEXT,
                               user_id              INTEGER,
                               slot_num             INTEGER,
                               role                 TEXT,
                               team                 TEXT,
                               base_points          REAL DEFAULT 0,
                               bonus_points         REAL DEFAULT 0,
                               lh_points            REAL DEFAULT 0,
                               will_protocol_points REAL DEFAULT 0,
                               will_opinion_points  REAL DEFAULT 0,
                               kick                 INTEGER DEFAULT 0,
                               ppk                  INTEGER DEFAULT 0,
                               technical_fouls      INTEGER DEFAULT 0
                           )
                           """)
        await conn.execute("""
                           CREATE TABLE IF NOT EXISTS game_history
                           (
                               id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                               game_date          TEXT,
                               winner_label       TEXT,
                               protocol_text      TEXT,
                               game_number        INTEGER,
                               global_game_number INTEGER
                           )
                           """)
        await conn.commit()
    await _ensure_columns()


# ========== 2. SETTINGS (обобщённые функции) ==========
async def get_setting(key: str) -> Optional[str]:
    async with get_db() as conn:
        async with conn.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def set_setting(key: str, value: Optional[str]):
    async with get_db() as conn:
        if value is None:
            await conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        else:
            await conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value)
            )
        await conn.commit()


def _make_setting_funcs(key_prefix: str):
    """Фабрика функций для get/set числовых настроек."""

    async def getter() -> Optional[int]:
        val = await get_setting(key_prefix)
        return int(val) if val and val.isdigit() else None

    async def setter(num: int):
        await set_setting(key_prefix, str(num))

    return getter, setter


get_current_game_date, set_current_game_date = lambda: get_setting("current_game_date"), lambda d: set_setting(
    "current_game_date", d)
get_current_game_number, set_current_game_number = _make_setting_funcs("current_game_number")
get_current_global_game_number, set_current_global_game_number = _make_setting_funcs("current_game_global_number")


async def save_current_game_slots(slots: Dict[int, dict], metadata: dict = None):
    """Сохраняет слоты и метаданные игры в БД."""
    data_to_save = {
        "slots": slots,
        "metadata": metadata or {}
    }
    await set_setting("current_game_slots", json.dumps(data_to_save, ensure_ascii=False))


async def load_current_game_slots() -> Optional[Dict[int, dict]]:
    """Загружает слоты игры из БД."""
    payload = await get_setting("current_game_slots")
    if not payload:
        return None
    data = json.loads(payload)
    return data.get("slots", {})


async def load_current_game_metadata() -> Optional[dict]:
    """Загружает метаданные игры из БД."""
    payload = await get_setting("current_game_slots")
    if not payload:
        return None
    data = json.loads(payload)
    return data.get("metadata", {})


# ========== 3. ПОЛЬЗОВАТЕЛИ ==========
async def add_or_update_user(user_id: int, username: Optional[str], full_name: str):
    async with get_db() as conn:
        await conn.execute(
            "INSERT INTO users (user_id, username, full_name) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET username = excluded.username, full_name = excluded.full_name",
            (user_id, username, full_name)
        )
        await conn.commit()


async def get_user_profile(user_id: int) -> Optional[Tuple]:
    async with get_db() as conn:
        async with conn.execute("SELECT full_name, nickname, debt, last_visit FROM users WHERE user_id = ?",
                                (user_id,)) as cur:
            return await cur.fetchone()


async def update_nickname(user_id: int, nickname: str):
    async with get_db() as conn:
        await conn.execute("UPDATE users SET nickname = ? WHERE user_id = ?", (nickname, user_id))
        await conn.commit()


async def get_all_users_stat() -> list:
    async with get_db() as conn:
        async with conn.execute("SELECT full_name, nickname, last_visit, debt, total_paid, kicks, ppk_causes FROM users") as cur:
            return await cur.fetchall()


async def get_user_brief(user_id: int) -> Optional[Tuple[str, str, str]]:
    async with get_db() as conn:
        async with conn.execute("SELECT full_name, nickname, username FROM users WHERE user_id = ?", (user_id,)) as cur:
            return await cur.fetchone()


async def get_all_user_ids() -> list:
    async with get_db() as conn:
        async with conn.execute("SELECT user_id FROM users") as cur:
            return await cur.fetchall()


async def increment_user_kicks(user_id: int):
    """Увеличивает счётчик удалений игрока."""
    async with get_db() as conn:
        await conn.execute("UPDATE users SET kicks = kicks + 1 WHERE user_id = ?", (user_id,))
        await conn.commit()


async def increment_user_ppk_causes(user_id: int):
    """Увеличивает счётчик ППК игрока."""
    async with get_db() as conn:
        await conn.execute("UPDATE users SET ppk_causes = ppk_causes + 1 WHERE user_id = ?", (user_id,))
        await conn.commit()


async def get_user_kicks(user_id: int) -> int:
    """Возвращает количество удалений игрока."""
    async with get_db() as conn:
        async with conn.execute("SELECT kicks FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def get_user_ppk_causes(user_id: int) -> int:
    """Возвращает количество ППК игрока."""
    async with get_db() as conn:
        async with conn.execute("SELECT ppk_causes FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


# ========== НОВАЯ ФУНКЦИЯ: ПОИСК ПОЛЬЗОВАТЕЛЯ ПО НИКУ ==========
async def get_user_by_nickname(nickname: str) -> Optional[Tuple[int, str, str, str]]:
    """
    Ищет пользователя по нику или полному имени.
    Возвращает (user_id, full_name, username, nickname) или None.
    """
    async with get_db() as conn:
        # Ищем по нику (точное совпадение)
        async with conn.execute(
                "SELECT user_id, full_name, username, nickname FROM users WHERE nickname = ?",
                (nickname,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                return row

        # Если не нашли, ищем по полному имени (точное совпадение)
        async with conn.execute(
                "SELECT user_id, full_name, username, nickname FROM users WHERE full_name = ?",
                (nickname,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                return row

        # Если не нашли, ищем по частичному совпадению в нике
        async with conn.execute(
                "SELECT user_id, full_name, username, nickname FROM users WHERE nickname LIKE ?",
                (f"%{nickname}%",)
        ) as cur:
            row = await cur.fetchone()
            if row:
                return row

        return None


# ========== 4. ЗАПИСЬ НА ВЕЧЕР ==========
async def add_booking(user_id: int, status: str, date: str):
    async with get_db() as conn:
        await conn.execute("INSERT OR REPLACE INTO evening_booking (user_id, status, date) VALUES (?, ?, ?)",
                           (user_id, status, date))
        await conn.commit()


async def get_all_players() -> List[Tuple[int]]:
    async with get_db() as conn:
        async with conn.execute("SELECT user_id FROM evening_booking") as cur:
            return await cur.fetchall()


async def clear_bookings():
    async with get_db() as conn:
        await conn.execute("DELETE FROM evening_booking")
        await conn.commit()


async def get_booked_players_detailed() -> list:
    async with get_db() as conn:
        async with conn.execute("""
                                SELECT COALESCE(users.full_name, 'ID: ' || evening_booking.user_id) AS full_name,
                                       users.username,
                                       users.nickname,
                                       evening_booking.status
                                FROM evening_booking
                                         LEFT JOIN users ON evening_booking.user_id = users.user_id
                                """) as cur:
            return await cur.fetchall()


async def get_booked_players_for_game() -> list:
    async with get_db() as conn:
        async with conn.execute("""
                                SELECT e.user_id,
                                       IFNULL(u.full_name, 'Неизвестный') AS full_name,
                                       u.username,
                                       u.nickname,
                                       e.status
                                FROM evening_booking e
                                         LEFT JOIN users u ON e.user_id = u.user_id
                                WHERE e.status IN ('Вовремя', 'Позже')
                                """) as cur:
            return await cur.fetchall()


async def remove_booking(user_id: int):
    async with get_db() as conn:
        await conn.execute("DELETE FROM evening_booking WHERE user_id = ?", (user_id,))
        await conn.commit()


async def has_booking(user_id: int) -> bool:
    async with get_db() as conn:
        async with conn.execute("SELECT 1 FROM evening_booking WHERE user_id = ? LIMIT 1", (user_id,)) as cur:
            return await cur.fetchone() is not None


async def count_ontime_players_for_date(date_str: str) -> int:
    async with get_db() as conn:
        async with conn.execute("SELECT COUNT(*) FROM evening_booking WHERE date = ? AND status = 'Вовремя'",
                                (date_str,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def count_all_attending_for_date(date_str: str) -> int:
    async with get_db() as conn:
        async with conn.execute(
                "SELECT COUNT(*) FROM evening_booking WHERE date = ? AND status IN ('Вовремя', 'Позже')",
                (date_str,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def get_players_by_status_for_date(date_str: str, status: str) -> list:
    async with get_db() as conn:
        async with conn.execute("""
                                SELECT COALESCE(u.nickname, u.full_name, 'Без имени') AS name
                                FROM evening_booking e
                                         LEFT JOIN users u ON e.user_id = u.user_id
                                WHERE e.date = ?
                                  AND e.status = ?
                                ORDER BY name
                                """, (date_str, status)) as cur:
            return [row[0] for row in await cur.fetchall()]


async def get_all_bookings_for_date_ordered(date_str: str) -> List[Tuple[str, str]]:
    async with get_db() as conn:
        async with conn.execute("""
                                SELECT COALESCE(u.nickname, u.full_name, 'Без имени'), e.status
                                FROM evening_booking e
                                         LEFT JOIN users u ON e.user_id = u.user_id
                                WHERE e.date = ?
                                ORDER BY CASE e.status
                                             WHEN 'Вовремя' THEN 1
                                             WHEN 'Позже' THEN 2
                                             WHEN 'Не идёт' THEN 3
                                             ELSE 4 END, name
                                """, (date_str,)) as cur:
            return await cur.fetchall()


async def set_stats_message(date_str: str, chat_id: int, message_id: int):
    async with get_db() as conn:
        await conn.execute("INSERT OR REPLACE INTO evening_stats_messages (date, chat_id, message_id) VALUES (?, ?, ?)",
                           (date_str, chat_id, message_id))
        await conn.commit()


async def get_stats_message(date_str: str) -> Optional[Tuple[int, int]]:
    async with get_db() as conn:
        async with conn.execute("SELECT chat_id, message_id FROM evening_stats_messages WHERE date = ?",
                                (date_str,)) as cur:
            return await cur.fetchone()


# ========== 5. ФИНАНСЫ ==========
async def change_user_debt(user_id: int, delta: int):
    async with get_db() as conn:
        await conn.execute("UPDATE users SET debt = debt + ? WHERE user_id = ?", (delta, user_id))
        await conn.commit()


async def set_user_debt(user_id: int, value: int):
    async with get_db() as conn:
        await conn.execute("UPDATE users SET debt = ? WHERE user_id = ?", (value, user_id))
        await conn.commit()


async def get_user_debt(user_id: int) -> int:
    async with get_db() as conn:
        async with conn.execute("SELECT debt FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row and row[0] else 0


async def set_last_visit(user_id: int, date_str: str):
    async with get_db() as conn:
        await conn.execute("UPDATE users SET last_visit = ? WHERE user_id = ?", (date_str, user_id))
        await conn.commit()


async def add_user_payment(user_id: int, amount: int):
    async with get_db() as conn:
        await conn.execute("UPDATE users SET total_paid = COALESCE(total_paid, 0) + ? WHERE user_id = ?",
                           (amount, user_id))
        await conn.commit()


async def get_debtors() -> list:
    async with get_db() as conn:
        async with conn.execute(
                "SELECT full_name, nickname, username, debt, user_id FROM users WHERE has_unpaid_session = 1 ORDER BY full_name") as cur:
            return await cur.fetchall()


async def set_unpaid_session(user_id: int, value: int):
    async with get_db() as conn:
        await conn.execute("UPDATE users SET has_unpaid_session = ? WHERE user_id = ?", (value, user_id))
        await conn.commit()


async def has_unpaid_session(user_id: int) -> bool:
    async with get_db() as conn:
        async with conn.execute("SELECT has_unpaid_session FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return bool(row and row[0])


async def set_last_evening_amount_for_user(user_id: int, amount: int):
    async with get_db() as conn:
        await conn.execute("""
                           UPDATE evening_history
                           SET amount = ?
                           WHERE id = (SELECT id FROM evening_history WHERE user_id = ? ORDER BY id DESC LIMIT 1)
                           """, (amount, user_id))
        await conn.commit()


# ========== 6. ИСТОРИЯ ВЕЧЕРОВ ==========
async def archive_current_evening():
    async with get_db() as conn:
        async with conn.execute(
                "SELECT e.date, e.user_id, e.status, u.full_name, u.nickname FROM evening_booking e LEFT JOIN users u ON e.user_id = u.user_id") as cur:
            rows = await cur.fetchall()
        if rows:
            await conn.executemany(
                "INSERT INTO evening_history (date, user_id, status, full_name, nickname, amount) VALUES (?, ?, ?, ?, ?, 0)",
                rows)
        await conn.execute("DELETE FROM evening_booking")
        await conn.commit()


async def get_evenings_list(limit: int = 10) -> list:
    async with get_db() as conn:
        async with conn.execute("SELECT date, COUNT(*) FROM evening_history GROUP BY date ORDER BY date DESC LIMIT ?",
                                (limit,)) as cur:
            return await cur.fetchall()


async def get_evening_players(date_str: str) -> list:
    async with get_db() as conn:
        async with conn.execute(
                "SELECT full_name, nickname, status, amount FROM evening_history WHERE date = ? ORDER BY full_name",
                (date_str,)) as cur:
            return await cur.fetchall()


async def get_top_players_by_visits(limit: int = 10) -> list:
    async with get_db() as conn:
        async with conn.execute("""
                                SELECT u.full_name, u.nickname, COUNT(h.id)
                                FROM evening_history h
                                         LEFT JOIN users u ON h.user_id = u.user_id
                                GROUP BY h.user_id
                                ORDER BY COUNT(h.id) DESC
                                LIMIT ?
                                """, (limit,)) as cur:
            return await cur.fetchall()


async def get_inactive_players(days: int = 30) -> list:
    async with get_db() as conn:
        async with conn.execute("SELECT full_name, nickname, last_visit FROM users ORDER BY last_visit") as cur:
            return await cur.fetchall()


async def mark_evening_bills_sent(date_str: str):
    async with get_db() as conn:
        await conn.execute(
            "INSERT INTO evening_status (date, bills_sent) VALUES (?, 1) ON CONFLICT(date) DO UPDATE SET bills_sent = 1",
            (date_str,))
        await conn.commit()


async def is_evening_bills_sent(date_str: str) -> bool:
    async with get_db() as conn:
        async with conn.execute("SELECT bills_sent FROM evening_status WHERE date = ?", (date_str,)) as cur:
            row = await cur.fetchone()
            return bool(row and row[0])


# ========== 7. РЕЗУЛЬТАТЫ ИГР ==========
async def apply_game_result_to_users(slots: Dict[int, dict], winning_team: str):
    async with get_db() as conn:
        for slot in slots.values():
            uid, team = slot.get("user_id"), slot.get("team")
            if not uid or not team:
                continue
            await conn.execute("UPDATE users SET games_played = COALESCE(games_played, 0) + 1 WHERE user_id = ?",
                               (uid,))
            if team == winning_team:
                await conn.execute(
                    "UPDATE users SET games_won = COALESCE(games_won, 0) + 1, points = COALESCE(points, 0) + 1 WHERE user_id = ?",
                    (uid,))
        await conn.commit()


async def get_user_game_counters(user_id: int) -> Optional[Dict[str, int]]:
    async with get_db() as conn:
        async with conn.execute("SELECT games_played, games_won, points FROM users WHERE user_id = ?",
                                (user_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return {"games_played": row[0] or 0, "games_won": row[1] or 0, "points": row[2] or 0}


async def save_game_slots_history(game_date: str, slots: Union[Dict[int, dict], List[dict]]):
    """Сохраняет историю слотов игры."""
    if isinstance(slots, dict):
        items = list(slots.items())
    elif isinstance(slots, list):
        items = [(idx, slot) for idx, slot in enumerate(slots, 1) if isinstance(slot, dict)]
    else:
        return

    rows = []
    for slot_num, slot in items:
        if not isinstance(slot, dict):
            continue
        rows.append((
            game_date,
            slot.get("user_id"),
            slot_num,
            slot.get("role"),
            slot.get("team"),
            float(slot.get("base_points", 0) or 0),
            float(slot.get("bonus_points", 0) or 0),
            float(slot.get("lh_points", 0) or 0),
            float(slot.get("will_protocol_points", 0) or 0),
            float(slot.get("will_opinion_points", 0) or 0),
            float(slot.get("dc_points", 0) or 0),
            1 if slot.get("kicked", False) else 0,
            1 if slot.get("ppk", False) else 0,
            len([t for t in slot.get("technical_fouls", []) if t])
        ))
    if rows:
        async with get_db() as conn:
            await conn.executemany("""
                INSERT INTO game_slots_history (
                    game_date, user_id, slot_num, role, team,
                    base_points, bonus_points, lh_points,
                    will_protocol_points, will_opinion_points,
                    dc_points, kick, ppk, technical_fouls
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
            await conn.commit()


async def get_user_roles_stats(user_id: int) -> List[Dict]:
    """Статистика по ролям пользователя."""
    async with get_db() as conn:
        async with conn.execute("""
            SELECT role,
                   COUNT(*) AS games,
                   SUM(CASE WHEN base_points = 1 THEN 1 ELSE 0 END) AS wins,
                   SUM(base_points + bonus_points + lh_points + will_protocol_points + will_opinion_points + dc_points) AS total_points,
                   SUM(bonus_points) AS total_bonus,
                   SUM(lh_points) AS total_lh,
                   SUM(CASE WHEN (bonus_points + lh_points + dc_points) < 0 THEN bonus_points + lh_points + dc_points ELSE 0 END) AS total_negative,
                   AVG(will_protocol_points) AS protocol_avg,
                   SUM(CASE WHEN will_protocol_points > 0 THEN 1 ELSE 0 END) AS protocol_pos_count,
                   SUM(CASE WHEN will_protocol_points > 0 THEN will_protocol_points ELSE 0 END) AS protocol_pos_sum,
                   SUM(CASE WHEN will_protocol_points < 0 THEN 1 ELSE 0 END) AS protocol_neg_count,
                   SUM(CASE WHEN will_protocol_points < 0 THEN will_protocol_points ELSE 0 END) AS protocol_neg_sum,
                   AVG(will_opinion_points) AS opinion_avg,
                   SUM(CASE WHEN will_opinion_points > 0 THEN 1 ELSE 0 END) AS opinion_pos_count,
                   SUM(CASE WHEN will_opinion_points > 0 THEN will_opinion_points ELSE 0 END) AS opinion_pos_sum,
                   SUM(CASE WHEN will_opinion_points < 0 THEN 1 ELSE 0 END) AS opinion_neg_count,
                   SUM(CASE WHEN will_opinion_points < 0 THEN will_opinion_points ELSE 0 END) AS opinion_neg_sum,
                   SUM(kick) AS total_kicks,
                   SUM(ppk) AS total_ppk
            FROM game_slots_history
            WHERE user_id = ?
            GROUP BY role
        """, (user_id,)) as cur:
            rows = await cur.fetchall()

    result = []
    for row in rows:
        role, games, wins, total_points, total_bonus, total_lh, total_negative, \
            protocol_avg, protocol_pos_count, protocol_pos_sum, protocol_neg_count, protocol_neg_sum, \
            opinion_avg, opinion_pos_count, opinion_pos_sum, opinion_neg_count, opinion_neg_sum, \
            total_kicks, total_ppk = row

        games = games or 0
        if games:
            winrate = round(wins / games * 100, 1) if games else 0
            avg_points = round((total_points or 0) / games, 2)
        else:
            winrate = avg_points = 0.0

        result.append({
            "role": role or "Не задана",
            "games": games,
            "wins": wins or 0,
            "winrate": winrate,
            "avg_points": avg_points,
            "total_points": total_points or 0.0,
            "total_bonus": total_bonus or 0.0,
            "total_lh": total_lh or 0.0,
            "total_negative": total_negative or 0.0,
            "protocol_avg": round(protocol_avg or 0, 2),
            "protocol_pos_count": protocol_pos_count or 0,
            "protocol_pos_sum": round(protocol_pos_sum or 0, 2),
            "protocol_neg_count": protocol_neg_count or 0,
            "protocol_neg_sum": round(protocol_neg_sum or 0, 2),
            "opinion_avg": round(opinion_avg or 0, 2),
            "opinion_pos_count": opinion_pos_count or 0,
            "opinion_pos_sum": round(opinion_pos_sum or 0, 2),
            "opinion_neg_count": opinion_neg_count or 0,
            "opinion_neg_sum": round(opinion_neg_sum or 0, 2),
            "kicks": total_kicks or 0,
            "ppk_causes": total_ppk or 0,
        })
    return result


# ========== 8. ИСТОРИЯ ИГР ==========
async def save_game_history(game_date: str, winner_label: str, protocol_text: str,
                            game_number: Optional[int] = None, global_game_number: Optional[int] = None) -> int:
    async with get_db() as conn:
        cur = await conn.execute("""
                                 INSERT INTO game_history (game_date, winner_label, protocol_text, game_number,
                                                           global_game_number)
                                 VALUES (?, ?, ?, ?, ?)
                                 """, (game_date, winner_label, protocol_text, game_number, global_game_number))
        await conn.commit()
        return cur.lastrowid


async def get_total_games_count() -> int:
    async with get_db() as conn:
        async with conn.execute("SELECT COUNT(*) FROM game_history") as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def _fetch_games(query: str, params: tuple = ()) -> List[Dict]:
    """Вспомогательная функция для получения игр."""
    async with get_db() as conn:
        async with conn.execute(query, params) as cur:
            rows = await cur.fetchall()
    return [{"id": r[0], "game_date": r[1], "winner_label": r[2], "protocol_text": r[3],
             "game_number": r[4], "global_game_number": r[5]} for r in rows]


async def get_games_by_date(game_date: str) -> List[Dict]:
    return await _fetch_games(
        "SELECT id, game_date, winner_label, protocol_text, game_number, global_game_number FROM game_history WHERE game_date = ? ORDER BY id ASC",
        (game_date,)
    )


async def get_last_games(limit: int = 10) -> List[Dict]:
    return await _fetch_games(
        "SELECT id, game_date, winner_label, protocol_text, game_number, global_game_number FROM game_history ORDER BY id DESC LIMIT ?",
        (limit,)
    )


async def get_user_games(user_id: int, limit: int = 10) -> List[Dict]:
    async with get_db() as conn:
        async with conn.execute(
                "SELECT DISTINCT game_date FROM game_slots_history WHERE user_id = ? ORDER BY game_date DESC LIMIT ?",
                (user_id, limit)) as cur:
            dates = [row[0] for row in await cur.fetchall() if row[0]]
        if not dates:
            return []
        placeholders = ",".join("?" for _ in dates)
        return await _fetch_games(f"""
            SELECT id, game_date, winner_label, protocol_text, game_number, global_game_number
            FROM game_history WHERE game_date IN ({placeholders}) ORDER BY id DESC
        """, tuple(dates))


async def get_game_by_id(game_id: int) -> Optional[Dict]:
    games = await _fetch_games(
        "SELECT id, game_date, winner_label, protocol_text, game_number, global_game_number FROM game_history WHERE id = ?",
        (game_id,))
    return games[0] if games else None


async def get_game_slots_by_date(game_date: str) -> Optional[Dict[int, dict]]:
    """
    Восстанавливает слоты игры из game_slots_history по дате игры.
    Возвращает словарь слотов в том же формате, что и в игре.
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(
                """
                SELECT user_id,
                       slot_num,
                       role,
                       team,
                       base_points,
                       bonus_points,
                       lh_points,
                       will_protocol_points,
                       will_opinion_points,
                       kick,
                       ppk,
                       technical_fouls
                FROM game_slots_history
                WHERE game_date = ?
                ORDER BY slot_num
                """,
                (game_date,),
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        return None

    slots = {}
    for row in rows:
        (user_id, slot_num, role, team,
         base_points, bonus_points, lh_points,
         protocol_points, opinion_points, kick, ppk, tech_fouls) = row

        # Получаем ник пользователя
        nickname = None
        full_name = None
        username = None
        if user_id:
            profile = await get_user_profile(user_id)
            if profile:
                full_name, nickname, _, _ = profile

        slots[slot_num] = {
            "user_id": user_id,
            "full_name": full_name,
            "nickname": nickname or f"Игрок {slot_num}",
            "username": username,
            "role": role or "Не задана",
            "team": team,
            "base_points": base_points or 0,
            "bonus_points": bonus_points or 0,
            "lh_points": lh_points or 0,
            "will_protocol_points": protocol_points or 0,
            "will_opinion_points": opinion_points or 0,
            "alive": True,
            "status_reason": "Жив",
            "fouls": 0,
            "nominated": False,
            "votes": 0,
            "night_suspects": [],
            "pu_mark": False,
            "will_protocol_raw": "",
            "will_opinion": "",
            "kick": kick or 0,
            "ppk": ppk or 0,
            "technical_fouls": tech_fouls or 0,
        }

    return slots