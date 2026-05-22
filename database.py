import json
import datetime
from typing import Optional, Tuple, List, Dict, Any, Union
from contextlib import asynccontextmanager
import asyncpg
import config

# ========== ПУЛ СОЕДИНЕНИЙ ==========
_db_pool = None

async def get_db_pool():
    """Создаёт пул соединений с PostgreSQL (Supabase)"""
    global _db_pool
    if _db_pool is None:
        _db_pool = await asyncpg.create_pool(
            config.DATABASE_URL,
            min_size=1,
            max_size=10,
            command_timeout=60
        )
        print("✅ Пул соединений с Supabase создан")
    return _db_pool


@asynccontextmanager
async def get_db():
    """Контекстный менеджер для соединения с БД (аналог SQLite версии)."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        yield conn


def _ensure_iso_date(date_str: str) -> str:
    """Умный конвертер в ISO формат (YYYY-MM-DD)."""
    if not date_str: 
        return date_str
    if "-" in date_str and len(date_str) == 10: 
        return date_str
    try:
        parts = date_str.split(".")
        day = parts[0].zfill(2)
        month = parts[1].zfill(2)
        year = parts[2] if len(parts) == 3 else str(datetime.datetime.now().year)
        return f"{year}-{month}-{day}"
    except:
        return date_str


def format_date_to_user(date_str: str) -> str:
    """Превращает 2026-05-13 в 13.05.2026"""
    if not date_str or '-' not in date_str:
        return date_str
    try:
        parts = date_str.split('-')
        if len(parts) == 3:
            return f"{parts[2]}.{parts[1]}.{parts[0]}"
        return date_str
    except Exception:
        return date_str


async def _ensure_columns():
    """Гарантирует наличие всех нужных колонок в существующих таблицах."""
    async with get_db() as conn:
        alters = [
            ("users", "games_played", "INTEGER DEFAULT 0"),
            ("users", "games_won", "INTEGER DEFAULT 0"),
            ("users", "points", "INTEGER DEFAULT 0"),
            ("users", "kicks", "INTEGER DEFAULT 0"),
            ("users", "ppk_causes", "INTEGER DEFAULT 0"),
            ("game_history", "game_number", "INTEGER"),
            ("game_history", "global_game_number", "INTEGER"),
            ("game_slots_history", "will_protocol_points", "REAL DEFAULT 0"),
            ("game_slots_history", "will_opinion_points", "REAL DEFAULT 0"),
            ("game_slots_history", "kick", "INTEGER DEFAULT 0"),
            ("game_slots_history", "ppk", "INTEGER DEFAULT 0"),
            ("game_slots_history", "technical_fouls", "INTEGER DEFAULT 0"),
            ("game_slots_history", "dc_points", "REAL DEFAULT 0"),
            ("game_slots_history", "pu", "INTEGER DEFAULT 0"),
            ("game_slots_history", "will_protocol_raw", "TEXT DEFAULT ''"),
            ("game_slots_history", "will_opinion", "TEXT DEFAULT ''"),
            ("game_slots_history", "game_number", "INTEGER DEFAULT 0"),
            ("game_slots_history", "alive", "INTEGER DEFAULT 1"),
            ("game_slots_history", "status_reason", "TEXT DEFAULT 'Жив'"),
            ("game_slots_history", "updated_by_editor", "INTEGER DEFAULT 0"),
        ]
        for table, col, col_type in alters:
            try:
                await conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
            except Exception:
                pass


# ========== 1. ИНИЦИАЛИЗАЦИЯ ==========
async def init_db():
    """Инициализация всех таблиц."""
    async with get_db() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS game_slots_history (
                id                   SERIAL PRIMARY KEY,
                game_date            TEXT,
                game_number          INTEGER DEFAULT 0,
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
                technical_fouls      INTEGER DEFAULT 0,
                pu                   INTEGER DEFAULT 0,
                will_protocol_raw    TEXT    DEFAULT '',
                will_opinion         TEXT    DEFAULT '',
                alive                INTEGER DEFAULT 1,
                status_reason        TEXT    DEFAULT 'Жив',
                updated_by_editor    INTEGER DEFAULT 0,
                fouls                INTEGER DEFAULT 0,
                elo_change           INTEGER DEFAULT 0,
                new_elo              INTEGER DEFAULT 1500
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id          INTEGER PRIMARY KEY,
                full_name        TEXT,
                username         TEXT,
                nickname         TEXT UNIQUE,
                debt             INTEGER DEFAULT 0,
                last_visit       TEXT,
                total_paid       INTEGER DEFAULT 0,
                kicks            INTEGER DEFAULT 0,
                ppk_causes       INTEGER DEFAULT 0,
                games_played     INTEGER DEFAULT 0,
                games_won        INTEGER DEFAULT 0,
                points           INTEGER DEFAULT 0,
                games_red        INTEGER DEFAULT 0,
                wins_red         INTEGER DEFAULT 0,
                games_black      INTEGER DEFAULT 0,
                wins_black       INTEGER DEFAULT 0,
                exp_level        TEXT,
                skill_level      TEXT,
                winrate_red      REAL DEFAULT 0,
                winrate_black    REAL DEFAULT 0,
                has_unpaid_session INTEGER DEFAULT 0,
                tokens           INTEGER DEFAULT 0,
                created_at       TIMESTAMP DEFAULT NOW()
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS evening_booking (
                user_id INTEGER PRIMARY KEY,
                status TEXT,
                date TEXT
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS evening_history (
                id        SERIAL PRIMARY KEY,
                date      TEXT,
                user_id   INTEGER,
                status    TEXT,
                full_name TEXT,
                nickname  TEXT,
                amount    INTEGER DEFAULT 0
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS evening_stats_messages (
                date TEXT PRIMARY KEY,
                chat_id INTEGER,
                message_id INTEGER
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS evening_status (
                date TEXT PRIMARY KEY,
                bills_sent INTEGER DEFAULT 0
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS game_history (
                id                 SERIAL PRIMARY KEY,
                game_date          TEXT,
                winner_label       TEXT,
                protocol_text      TEXT,
                game_number        INTEGER,
                global_game_number INTEGER,
                judge_id           INTEGER DEFAULT 0
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS night_kills_order (
                game_date TEXT,
                game_number INTEGER,
                kill_order TEXT,
                PRIMARY KEY (game_date, game_number)
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_achievements (
                user_id        INTEGER,
                achievement_id TEXT,
                earned_at      TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (user_id, achievement_id)
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bets_active (
                id          SERIAL PRIMARY KEY,
                game_id     INTEGER NOT NULL,
                game_number INTEGER NOT NULL,
                game_date   TEXT    NOT NULL,
                created_by  INTEGER NOT NULL,
                created_at  TIMESTAMP DEFAULT NOW(),
                closed      BOOLEAN DEFAULT FALSE,
                resolved    BOOLEAN DEFAULT FALSE,
                winner_team TEXT
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_bets (
                id               SERIAL PRIMARY KEY,
                user_id          INTEGER NOT NULL,
                bet_id           INTEGER NOT NULL,
                amount           INTEGER NOT NULL,
                predicted_winner TEXT    NOT NULL,
                created_at       TIMESTAMP DEFAULT NOW()
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id         SERIAL PRIMARY KEY,
                user_id    INTEGER,
                amount     REAL,
                type       TEXT,
                comment    TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS game_dates (
                date TEXT PRIMARY KEY,
                announcement_requested INTEGER DEFAULT 0
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS elo_ratings (
                user_id INTEGER PRIMARY KEY,
                elo INTEGER DEFAULT 1500,
                games_played INTEGER DEFAULT 0,
                games_won INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

    await _ensure_columns()
    await add_fouls_column()
    await create_elo_table()
    print("✅ База данных Supabase инициализирована")


# ========== 2. SETTINGS ==========
async def get_setting(key: str) -> Optional[str]:
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT value FROM settings WHERE key = $1", key)
        return row[0] if row else None


async def set_setting(key: str, value: Optional[str]):
    async with get_db() as conn:
        if value is None:
            await conn.execute("DELETE FROM settings WHERE key = $1", key)
        else:
            await conn.execute(
                "INSERT INTO settings (key, value) VALUES ($1, $2) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                key, value)


def _make_setting_funcs(key_prefix: str):
    async def getter() -> Optional[int]:
        val = await get_setting(key_prefix)
        return int(val) if val and val.isdigit() else None

    async def setter(num: int):
        await set_setting(key_prefix, str(num))

    return getter, setter


get_current_game_date = lambda: get_setting("current_game_date")
set_current_game_date = lambda d: set_setting("current_game_date", d)
get_current_game_number, set_current_game_number = _make_setting_funcs("current_game_number")
get_current_global_game_number, set_current_global_game_number = _make_setting_funcs("current_game_global_number")


async def get_current_game_judge_id() -> Optional[int]:
    val = await get_setting("current_game_judge_id")
    try:
        return int(val) if val is not None else None
    except ValueError:
        return None


async def set_current_game_judge_id(user_id: Optional[int]):
    await set_setting("current_game_judge_id", str(user_id) if user_id is not None else None)


async def get_current_game_judge_name() -> Optional[str]:
    return await get_setting("current_game_judge_name")


async def set_current_game_judge_name(name: Optional[str]):
    await set_setting("current_game_judge_name", name)


async def get_game_judges() -> List[int]:
    raw = await get_setting("game_judges")
    if not raw: return []
    try:
        data = json.loads(raw)
        return [int(x) for x in data if isinstance(x, (int, str))] if isinstance(data, list) else []
    except Exception:
        return []


async def _save_game_judges(judges: List[int]):
    await set_setting("game_judges", json.dumps(list(set(judges)), ensure_ascii=False))


async def is_game_judge(user_id: int) -> bool:
    judges = await get_game_judges()
    return user_id in judges


async def add_game_judge(user_id: int):
    judges = await get_game_judges()
    if user_id not in judges:
        judges.append(user_id)
        await _save_game_judges(judges)


async def remove_game_judge(user_id: int):
    judges = await get_game_judges()
    judges = [j for j in judges if j != user_id]
    await _save_game_judges(judges)


async def save_current_game_slots(slots: Dict[int, dict], metadata: dict = None):
    data_to_save = {"slots": slots, "metadata": metadata or {}}
    await set_setting("current_game_slots", json.dumps(data_to_save, ensure_ascii=False))


async def load_current_game_slots() -> Optional[Dict[int, dict]]:
    payload = await get_setting("current_game_slots")
    if not payload: return None
    return json.loads(payload).get("slots", {})


async def load_current_game_metadata() -> Optional[dict]:
    payload = await get_setting("current_game_slots")
    if not payload: return None
    return json.loads(payload).get("metadata", {})


# ========== 3. ПОЛЬЗОВАТЕЛИ ==========
async def add_or_update_user(user_id: int, username: Optional[str], full_name: str):
    async with get_db() as conn:
        await conn.execute(
            "INSERT INTO users (user_id, username, full_name) VALUES ($1, $2, $3) ON CONFLICT(user_id) DO UPDATE SET username = excluded.username, full_name = excluded.full_name",
            user_id, username, full_name)


async def get_user_profile(user_id: int) -> Optional[Tuple]:
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT full_name, nickname, debt, last_visit FROM users WHERE user_id = $1", user_id)
        return tuple(row) if row else None


async def update_nickname(user_id: int, nickname: str):
    async with get_db() as conn:
        await conn.execute("UPDATE users SET nickname = $1 WHERE user_id = $2", nickname, user_id)


async def get_all_users_stat() -> list:
    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT full_name, nickname, last_visit, debt, total_paid, kicks, ppk_causes FROM users")
        return [tuple(row) for row in rows]


async def get_user_brief(user_id: int) -> Optional[Tuple[str, str, str]]:
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT full_name, nickname, username FROM users WHERE user_id = $1", user_id)
        return tuple(row) if row else None


async def get_all_user_ids() -> list:
    async with get_db() as conn:
        rows = await conn.fetch("SELECT user_id FROM users")
        return [tuple(row) for row in rows]


async def increment_user_kicks(user_id: int):
    async with get_db() as conn:
        await conn.execute("UPDATE users SET kicks = kicks + 1 WHERE user_id = $1", user_id)


async def increment_user_ppk_causes(user_id: int):
    async with get_db() as conn:
        await conn.execute("UPDATE users SET ppk_causes = ppk_causes + 1 WHERE user_id = $1", user_id)


async def get_user_kicks(user_id: int) -> int:
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT kicks FROM users WHERE user_id = $1", user_id)
        return row[0] if row else 0


async def get_user_ppk_causes(user_id: int) -> int:
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT ppk_causes FROM users WHERE user_id = $1", user_id)
        return row[0] if row else 0


async def get_user_by_id(user_id: int) -> Optional[Tuple[int, str, str, str]]:
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT user_id, full_name, username, nickname FROM users WHERE user_id = $1", user_id)
        return tuple(row) if row else None


async def get_user_by_nickname(nickname: str) -> Optional[Tuple[int, str, str, str]]:
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT user_id, full_name, username, nickname FROM users WHERE nickname = $1", nickname)
        if row: return tuple(row)
        row = await conn.fetchrow("SELECT user_id, full_name, username, nickname FROM users WHERE full_name = $1", nickname)
        if row: return tuple(row)
        row = await conn.fetchrow("SELECT user_id, full_name, username, nickname FROM users WHERE nickname LIKE $1", f"%{nickname}%")
        return tuple(row) if row else None


async def get_all_users() -> list:
    async with get_db() as conn:
        rows = await conn.fetch("SELECT user_id, nickname, full_name FROM users")
        return [{"user_id": r[0], "nickname": r[1], "full_name": r[2]} for r in rows]


# ========== 4. ЗАПИСЬ НА ВЕЧЕР ==========
async def add_booking(user_id: int, status: str, date: str):
    async with get_db() as conn:
        await conn.execute(
            "INSERT INTO evening_booking (user_id, status, date) VALUES ($1, $2, $3) ON CONFLICT(user_id) DO UPDATE SET status = excluded.status, date = excluded.date",
            user_id, status, date)


async def get_all_players() -> List[Tuple[int]]:
    async with get_db() as conn:
        rows = await conn.fetch("SELECT user_id FROM evening_booking")
        return [tuple(row) for row in rows]


async def clear_bookings():
    async with get_db() as conn:
        await conn.execute("DELETE FROM evening_booking")


async def get_booked_players_detailed() -> list:
    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT COALESCE(users.full_name, 'ID: ' || evening_booking.user_id) AS full_name, users.username, users.nickname, evening_booking.status FROM evening_booking LEFT JOIN users ON evening_booking.user_id = users.user_id")
        return [tuple(row) for row in rows]


async def get_booked_players_for_game() -> list:
    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT e.user_id, COALESCE(u.full_name, 'Неизвестный') AS full_name, u.username, u.nickname, e.status FROM evening_booking e LEFT JOIN users u ON e.user_id = u.user_id WHERE e.status IN ('Вовремя', 'Позже')")
        return [tuple(row) for row in rows]


async def remove_booking(user_id: int):
    async with get_db() as conn:
        await conn.execute("DELETE FROM evening_booking WHERE user_id = $1", user_id)


async def has_booking(user_id: int) -> bool:
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT 1 FROM evening_booking WHERE user_id = $1 LIMIT 1", user_id)
        return row is not None


async def count_ontime_players_for_date(date_str: str) -> int:
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) FROM evening_booking WHERE date = $1 AND status = 'Вовремя'", date_str)
        return row[0] if row else 0


async def count_all_attending_for_date(date_str: str) -> int:
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) FROM evening_booking WHERE date = $1 AND status IN ('Вовремя', 'Позже')", date_str)
        return row[0] if row else 0


async def get_players_by_status_for_date(date_str: str, status: str) -> list:
    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT COALESCE(u.nickname, u.full_name, 'Без имени') AS name FROM evening_booking e LEFT JOIN users u ON e.user_id = u.user_id WHERE e.date = $1 AND e.status = $2 ORDER BY name",
            date_str, status)
        return [row[0] for row in rows]


async def get_all_bookings_for_date_ordered(date_str: str) -> List[Tuple[str, str]]:
    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT COALESCE(u.nickname, u.full_name, 'Без имени'), e.status FROM evening_booking e LEFT JOIN users u ON e.user_id = u.user_id WHERE e.date = $1 ORDER BY CASE e.status WHEN 'Вовремя' THEN 1 WHEN 'Позже' THEN 2 WHEN 'Не идёт' THEN 3 ELSE 4 END, name",
            date_str)
        return [tuple(row) for row in rows]


async def set_stats_message(date_str: str, chat_id: int, message_id: int):
    async with get_db() as conn:
        await conn.execute(
            "INSERT INTO evening_stats_messages (date, chat_id, message_id) VALUES ($1, $2, $3) ON CONFLICT(date) DO UPDATE SET chat_id = excluded.chat_id, message_id = excluded.message_id",
            date_str, chat_id, message_id)


async def get_stats_message(date_str: str) -> Optional[Tuple[int, int]]:
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT chat_id, message_id FROM evening_stats_messages WHERE date = $1", date_str)
        return tuple(row) if row else None


# ========== 5. ФИНАНСЫ ==========
async def log_transaction(user_id: int, amount: float, t_type: str, comment: str = ""):
    async with get_db() as conn:
        await conn.execute(
            "INSERT INTO transactions (user_id, amount, type, comment) VALUES ($1, $2, $3, $4)",
            user_id, amount, t_type, comment)


async def change_user_debt(user_id: int, delta: int):
    async with get_db() as conn:
        await conn.execute("UPDATE users SET debt = debt + $1 WHERE user_id = $2", delta, user_id)


async def set_user_debt(user_id: int, value: int):
    async with get_db() as conn:
        await conn.execute("UPDATE users SET debt = $1 WHERE user_id = $2", value, user_id)


async def get_user_debt(user_id: int) -> int:
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT debt FROM users WHERE user_id = $1", user_id)
        return row[0] if row and row[0] else 0


async def set_last_visit(user_id: int, date_str: str):
    async with get_db() as conn:
        await conn.execute("UPDATE users SET last_visit = $1 WHERE user_id = $2", date_str, user_id)


async def add_user_payment(user_id: int, amount: int):
    async with get_db() as conn:
        await conn.execute("UPDATE users SET total_paid = COALESCE(total_paid, 0) + $1 WHERE user_id = $2", amount, user_id)


async def get_debtors() -> list:
    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT full_name, nickname, username, debt, user_id FROM users WHERE debt < 0 ORDER BY debt ASC")
        return [tuple(row) for row in rows]


async def set_unpaid_session(user_id: int, value: int):
    async with get_db() as conn:
        await conn.execute("UPDATE users SET has_unpaid_session = $1 WHERE user_id = $2", value, user_id)


async def has_unpaid_session(user_id: int) -> bool:
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT has_unpaid_session FROM users WHERE user_id = $1", user_id)
        return bool(row and row[0])


async def set_last_evening_amount_for_user(user_id: int, amount: int):
    async with get_db() as conn:
        await conn.execute(
            "UPDATE evening_history SET amount = $1 WHERE id = (SELECT id FROM evening_history WHERE user_id = $2 ORDER BY id DESC LIMIT 1)",
            amount, user_id)


# ========== 6. ИСТОРИЯ ВЕЧЕРОВ ==========
async def archive_current_evening():
    date_to_archive = await get_setting("current_game_date")
    if not date_to_archive:
        date_to_archive = datetime.datetime.now().strftime("%Y-%m-%d")

    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT e.user_id, e.status, u.full_name, u.nickname FROM evening_booking e LEFT JOIN users u ON e.user_id = u.user_id")

        if rows:
            data_to_insert = []
            for r in rows:
                money = 100
                data_to_insert.append((date_to_archive, r['user_id'], r['status'], r['full_name'], r['nickname'], money))

            await conn.executemany(
                "INSERT INTO evening_history (date, user_id, status, full_name, nickname, amount) VALUES ($1, $2, $3, $4, $5, $6)",
                data_to_insert)

            for r in rows:
                if r['status'] in ("Вовремя", "Позже"):
                    await conn.execute("UPDATE users SET last_visit = $1 WHERE user_id = $2",
                                       f"{date_to_archive} 20:00", r['user_id'])

        await conn.execute("DELETE FROM evening_booking")


async def get_evening_financial_report(date_str: str) -> List[Dict]:
    search_date = _ensure_iso_date(date_str)
    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT u.nickname, u.full_name, (SELECT COUNT(*) FROM game_slots_history s WHERE s.user_id = h.user_id AND s.game_date = h.date) as real_games_count, h.user_id FROM evening_history h JOIN users u ON h.user_id = u.user_id WHERE h.date = $1 AND h.status IN ('Вовремя', 'Позже') ORDER BY u.nickname ASC",
            search_date)
        result = []
        for nickname, full_name, games, user_id in rows:
            result.append({"name": nickname or full_name or f"ID: {user_id}", "games": games if games > 0 else 1,
                           "amount": (games * 100) if games > 0 else 100})
        return result


async def get_evening_players(date_str: str) -> list:
    search_date = _ensure_iso_date(date_str)
    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT h.user_id, COALESCE(u.full_name, h.full_name), COALESCE(u.nickname, h.nickname), h.status, (SELECT COUNT(*) FROM game_slots_history s WHERE s.user_id = h.user_id AND s.game_date = h.date) as games_count FROM evening_history h LEFT JOIN users u ON h.user_id = u.user_id WHERE h.date = $1",
            search_date)
        return [(r[0], r[1], r[2], r[3], r[4]) for r in rows]


async def get_evenings_list(limit: int = 10) -> list:
    orgs = ("Чагин", "Матроскина", "Стаут", "Гриня", "Evgeniy Chagin", "Екатерина", "Di D", "Григорий Подколзин")
    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT date, COUNT(*) FROM evening_history WHERE status IN ('Вовремя', 'Позже') AND nickname NOT IN $1 AND full_name NOT IN $1 GROUP BY date ORDER BY id DESC LIMIT $2",
            orgs, limit)
        return [tuple(row) for row in rows]


async def get_top_players_by_visits(limit: int = 10) -> list:
    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT u.full_name, u.nickname, COUNT(h.id) FROM evening_history h LEFT JOIN users u ON h.user_id = u.user_id WHERE h.status IN ('Вовремя', 'Позже') GROUP BY h.user_id, u.full_name, u.nickname ORDER BY COUNT(h.id) DESC LIMIT $1",
            limit)
        return [tuple(row) for row in rows]


async def get_inactive_players(days: int = 30) -> list:
    async with get_db() as conn:
        rows = await conn.fetch("SELECT full_name, nickname, last_visit FROM users ORDER BY last_visit")
        return [tuple(row) for row in rows]


async def mark_evening_bills_sent(date_str: str):
    async with get_db() as conn:
        await conn.execute(
            "INSERT INTO evening_status (date, bills_sent) VALUES ($1, 1) ON CONFLICT(date) DO UPDATE SET bills_sent = 1",
            date_str)


async def is_evening_bills_sent(date_str: str) -> bool:
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT bills_sent FROM evening_status WHERE date = $1", date_str)
        return bool(row and row[0])


async def get_history_years():
    async with get_db() as conn:
        rows = await conn.fetch("SELECT DISTINCT TO_CHAR(date, 'YYYY') as year FROM evening_history ORDER BY year DESC")
        return [row[0] for row in rows]


async def get_history_months(year: str):
    orgs = ("Чагин", "Матроскина", "Стаут", "Гриня", "Evgeniy Chagin", "Екатерина", "Di D", "Григорий Подколзин")
    async with get_db() as conn:
        rows = await conn.fetch("""
            SELECT 
                TO_CHAR(h.date, 'MM') as month,
                SUM(
                    CASE 
                        WHEN (SELECT GREATEST(1, COUNT(*)) FROM game_slots_history s WHERE s.user_id = h.user_id AND s.game_date = h.date) >= 4 
                        THEN 400 
                        ELSE (SELECT GREATEST(1, COUNT(*)) FROM game_slots_history s WHERE s.user_id = h.user_id AND s.game_date = h.date) * 100 
                    END
                ) as total_sum
            FROM evening_history h
            LEFT JOIN users u ON h.user_id = u.user_id
            WHERE TO_CHAR(h.date, 'YYYY') = $1
              AND h.status IN ('Вовремя', 'Позже')
              AND COALESCE(u.nickname, h.nickname) NOT IN $2
              AND COALESCE(u.full_name, h.full_name) NOT IN $2
            GROUP BY month 
            ORDER BY month DESC
        """, year, orgs)
        return [tuple(row) for row in rows]


async def get_history_evenings(year: str, month: str):
    orgs = ("Чагин", "Матроскина", "Стаут", "Гриня", "Evgeniy Chagin", "Екатерина", "Di D", "Григорий Подколзин")
    async with get_db() as conn:
        rows = await conn.fetch("""
            SELECT 
                h.date, 
                COUNT(DISTINCT h.user_id),
                SUM(
                    CASE 
                        WHEN (SELECT GREATEST(1, COUNT(*)) FROM game_slots_history s WHERE s.user_id = h.user_id AND s.game_date = h.date) >= 4 
                        THEN 400 
                        ELSE (SELECT GREATEST(1, COUNT(*)) FROM game_slots_history s WHERE s.user_id = h.user_id AND s.game_date = h.date) * 100 
                    END
                ) as total_sum
            FROM evening_history h
            LEFT JOIN users u ON h.user_id = u.user_id
            WHERE TO_CHAR(h.date, 'YYYY') = $1
              AND TO_CHAR(h.date, 'MM') = $2
              AND h.status IN ('Вовремя', 'Позже')
              AND COALESCE(u.nickname, h.nickname) NOT IN $3
              AND COALESCE(u.full_name, h.full_name) NOT IN $3
            GROUP BY h.date 
            ORDER BY h.date DESC
        """, year, month, orgs)
        return [tuple(row) for row in rows]


# ========== 7. РЕЗУЛЬТАТЫ ИГР ==========
async def apply_game_result_to_users(slots: Dict[int, dict], winning_team: str):
    async with get_db() as conn:
        for slot in slots.values():
            uid, team = slot.get("user_id"), slot.get("team")
            if not uid or not team: 
                continue
            await conn.execute("UPDATE users SET games_played = COALESCE(games_played, 0) + 1 WHERE user_id = $1", uid)
            if team == winning_team:
                await conn.execute(
                    "UPDATE users SET games_won = COALESCE(games_won, 0) + 1, points = COALESCE(points, 0) + 1 WHERE user_id = $1",
                    uid)


async def get_user_game_counters(user_id: int) -> Optional[Dict[str, int]]:
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT 1 FROM users WHERE user_id = $1", user_id)
        if not row: 
            return None
        row2 = await conn.fetchrow(
            "SELECT COUNT(*) AS played, SUM(CASE WHEN base_points = 1 THEN 1 ELSE 0 END) AS won, SUM(base_points) AS points FROM game_slots_history WHERE user_id = $1",
            user_id)
        return {"games_played": row2[0] or 0, "games_won": row2[1] or 0, "points": row2[2] or 0}


async def get_user_roles_stats(user_id: int) -> List[Dict]:
    async with get_db() as conn:
        rows = await conn.fetch("""
            SELECT role,
                   COUNT(*)                                                                     AS games,
                   SUM(CASE WHEN base_points = 1 THEN 1 ELSE 0 END)                             AS wins,
                   SUM(base_points + bonus_points + lh_points + will_protocol_points +
                       will_opinion_points + dc_points)                                         AS total_points,
                   SUM(bonus_points)                                                            AS total_bonus,
                   SUM(lh_points)                                                               AS total_lh,
                   SUM(dc_points)                                                               AS total_negative,
                   AVG(will_protocol_points)                                                    AS protocol_avg,
                   SUM(CASE WHEN will_protocol_points > 0 THEN 1 ELSE 0 END)                    AS protocol_pos_count,
                   SUM(CASE WHEN will_protocol_points > 0 THEN will_protocol_points ELSE 0 END) AS protocol_pos_sum,
                   SUM(CASE WHEN will_protocol_points < 0 THEN 1 ELSE 0 END)                    AS protocol_neg_count,
                   SUM(CASE WHEN will_protocol_points < 0 THEN will_protocol_points ELSE 0 END) AS protocol_neg_sum,
                   AVG(will_opinion_points)                                                     AS opinion_avg,
                   SUM(CASE WHEN will_opinion_points > 0 THEN 1 ELSE 0 END)                     AS opinion_pos_count,
                   SUM(CASE WHEN will_opinion_points > 0 THEN will_opinion_points ELSE 0 END)   AS opinion_pos_sum,
                   SUM(CASE WHEN will_opinion_points < 0 THEN 1 ELSE 0 END)                     AS opinion_neg_count,
                   SUM(CASE WHEN will_opinion_points < 0 THEN will_opinion_points ELSE 0 END)   AS opinion_neg_sum,
                   SUM(kick)                                                                    AS total_kicks,
                   SUM(ppk)                                                                     AS total_ppk
            FROM game_slots_history
            WHERE user_id = $1
            GROUP BY role
        """, user_id)

    result = []
    for row in rows:
        role, games, wins, total_points, total_bonus, total_lh, total_negative, protocol_avg, protocol_pos_count, protocol_pos_sum, protocol_neg_count, protocol_neg_sum, opinion_avg, opinion_pos_count, opinion_pos_sum, opinion_neg_count, opinion_neg_sum, total_kicks, total_ppk = row
        games = games or 0
        if games:
            winrate = round(wins / games * 100, 1) if games else 0
            avg_points = round((total_points or 0) / games, 2)
        else:
            winrate = avg_points = 0.0

        result.append({
            "role": role or "Не задана", "games": games, "wins": wins or 0, "winrate": winrate,
            "avg_points": avg_points,
            "total_points": total_points or 0.0, "total_bonus": total_bonus or 0.0, "total_lh": total_lh or 0.0,
            "total_negative": total_negative or 0.0, "protocol_avg": round(protocol_avg or 0, 2),
            "protocol_pos_count": protocol_pos_count or 0,
            "protocol_pos_sum": round(protocol_pos_sum or 0, 2), "protocol_neg_count": protocol_neg_count or 0,
            "protocol_neg_sum": round(protocol_neg_sum or 0, 2),
            "opinion_avg": round(opinion_avg or 0, 2), "opinion_pos_count": opinion_pos_count or 0,
            "opinion_pos_sum": round(opinion_pos_sum or 0, 2),
            "opinion_neg_count": opinion_neg_count or 0, "opinion_neg_sum": round(opinion_neg_sum or 0, 2),
            "kicks": total_kicks or 0, "ppk_causes": total_ppk or 0,
        })
    return result

# ========== 8. ИСТОРИЯ ИГР ==========
async def save_game_history(game_date: str, winner_label: str, protocol_text: str, game_number: Optional[int] = None,
                            global_game_number: Optional[int] = None, judge_id: Optional[int] = None) -> int:
    search_date = _ensure_iso_date(game_date)
    async with get_db() as conn:
        row = await conn.fetchrow(
            "INSERT INTO game_history (game_date, winner_label, protocol_text, game_number, global_game_number, judge_id) VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
            search_date, winner_label, protocol_text, game_number, global_game_number, judge_id or 0)
        return row[0]


async def get_user_extra_stats(user_id: int) -> Dict[str, float]:
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT AVG(lh_points) AS avg_lh, SUM(kick) AS removed_count, SUM(technical_fouls) AS techfouls_total, SUM(ppk) AS ppk_guilty_count, SUM(pu) AS pu_count, SUM(fouls) AS fouls_total FROM game_slots_history WHERE user_id = $1",
            user_id)
    if not row: 
        return {"avg_lh": 0.0, "removed_count": 0, "techfouls_total": 0, "ppk_guilty_count": 0, "pu_count": 0, "fouls_total": 0}
    avg_lh, removed_count, techfouls_total, ppk_guilty_count, pu_count, fouls_total = row
    return {"avg_lh": float(avg_lh or 0.0), "removed_count": int(removed_count or 0),
            "techfouls_total": int(techfouls_total or 0), "ppk_guilty_count": int(ppk_guilty_count or 0),
            "pu_count": int(pu_count or 0), "fouls_total": int(fouls_total or 0)}


async def get_total_games_count() -> int:
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) FROM game_history")
        return row[0] if row else 0


async def _fetch_games(query: str, params: tuple = ()) -> List[Dict]:
    async with get_db() as conn:
        rows = await conn.fetch(query, *params)
    return [{"id": r[0], "game_date": r[1], "winner_label": r[2], "protocol_text": r[3], "game_number": r[4],
             "global_game_number": r[5], "judge_id": r[6] if len(r) > 6 else None} for r in rows]


async def get_games_by_date(game_date: str) -> List[Dict]:
    search_date = _ensure_iso_date(game_date)
    return await _fetch_games(
        "SELECT id, game_date, winner_label, protocol_text, game_number, global_game_number FROM game_history WHERE game_date = $1 ORDER BY id ASC",
        (search_date,))


async def get_last_games(limit: int = 10) -> List[Dict]:
    return await _fetch_games(
        "SELECT id, game_date, winner_label, protocol_text, game_number, global_game_number FROM game_history ORDER BY id DESC LIMIT $1",
        (limit,))


async def get_user_games(user_id: int, limit: int = 10) -> List[Dict]:
    async with get_db() as conn:
        dates_and_numbers = await conn.fetch(
            "SELECT DISTINCT game_date, game_number FROM game_slots_history WHERE user_id = $1 ORDER BY game_date DESC LIMIT $2",
            user_id, limit)
        if not dates_and_numbers: 
            return []
        games = []
        for game_date, game_number in dates_and_numbers:
            row = await conn.fetchrow(
                "SELECT id, game_date, winner_label, protocol_text, game_number, global_game_number FROM game_history WHERE game_date = $1 AND game_number = $2",
                game_date, game_number)
            if row: 
                games.append({"id": row[0], "game_date": row[1], "winner_label": row[2], "protocol_text": row[3],
                              "game_number": row[4], "global_game_number": row[5]})
        return games


async def get_all_game_dates() -> List[Tuple[str, int]]:
    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT game_date, COUNT(*) as games_count FROM game_history GROUP BY game_date ORDER BY game_date DESC")
        return [tuple(row) for row in rows]


# ========== 10. ДЕТАЛЬНАЯ РАБОТА С ИГРАМИ ==========
async def get_game_by_id(game_id: int) -> Optional[Dict]:
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT id, game_date, winner_label, protocol_text, game_number, global_game_number, judge_id FROM game_history WHERE id = $1",
            game_id)
        return dict(row) if row else None


async def get_game_slots_by_date(game_date: str, game_number: int = None) -> Optional[Dict[int, dict]]:
    search_date = _ensure_iso_date(game_date)
    query = "SELECT * FROM game_slots_history WHERE game_date = $1"
    params = [search_date]
    if game_number is not None:
        query += " AND game_number = $2"
        params.append(game_number)
    query += " ORDER BY slot_num ASC"

    async with get_db() as conn:
        rows = await conn.fetch(query, *params)
        if not rows: 
            return None

        slots = {}
        for r in rows:
            u_id = r['user_id']
            nickname = "Игрок"
            if u_id:
                u_row = await conn.fetchrow("SELECT nickname, full_name FROM users WHERE user_id = $1", u_id)
                if u_row:
                    nickname = u_row['nickname'] or u_row['full_name']

            slot_data = dict(r)
            slot_data['nickname'] = nickname
            slots[r['slot_num']] = slot_data
        return slots


async def save_game_slots_history(game_date: str, slots: Dict[int, dict], game_number: int = 0):
    search_date = _ensure_iso_date(game_date)
    async with get_db() as conn:
        for slot_num, s in slots.items():
            await conn.execute("""
                INSERT INTO game_slots_history (
                    game_date, game_number, user_id, slot_num, role, team,
                    base_points, bonus_points, lh_points,
                    will_protocol_points, will_opinion_points, dc_points,
                    kick, ppk, fouls, pu, will_protocol_raw, will_opinion,
                    alive, status_reason, elo_change, new_elo
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22)
            """,
                search_date, game_number, s.get('user_id'), slot_num, s.get('role'), s.get('team'),
                float(s.get('base_points', 0) or 0), float(s.get('bonus_points', 0) or 0),
                float(s.get('lh_points', 0) or 0),
                float(s.get('will_protocol_points', 0) or 0), float(s.get('will_opinion_points', 0) or 0),
                float(s.get('dc_points', 0) or 0),
                1 if s.get('kicked') or s.get('kick') else 0,
                1 if s.get('ppk') else 0,
                s.get('fouls', 0), 1 if s.get('pu_mark') or s.get('pu') else 0,
                s.get('will_protocol_raw', ''), s.get('will_opinion', ''),
                1 if s.get('alive', True) else 0, s.get('status_reason', 'Жив'),
                s.get('elo_change', 0), s.get('new_elo', 1500)
            )


async def update_game_outcome(game_id: int, winner_label: str):
    async with get_db() as conn:
        await conn.execute("UPDATE game_history SET winner_label = $1 WHERE id = $2", winner_label, game_id)


async def update_game_slot(game_date: str, game_num: int, slot_num: int, **kwargs):
    if not kwargs: 
        return
    search_date = _ensure_iso_date(game_date)
    cols = ", ".join([f"{k} = ${i+1}" for i, k in enumerate(kwargs.keys())])
    params = list(kwargs.values())
    sql = f"UPDATE game_slots_history SET {cols}, updated_by_editor = 1 WHERE game_date = ${len(params)+1} AND game_number = ${len(params)+2} AND slot_num = ${len(params)+3}"
    params.extend([search_date, game_num, slot_num])

    async with get_db() as conn:
        await conn.execute(sql, *params)


# ========== 11. АНОНСЫ СТОЛА И УБИЙСТВА ==========
async def get_announcement_requested(date: str) -> bool:
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT announcement_requested FROM game_dates WHERE date = $1", date)
        return bool(row and row[0]) if row else False


async def set_announcement_requested(date: str, requested: bool):
    async with get_db() as conn:
        await conn.execute(
            "INSERT INTO game_dates (date, announcement_requested) VALUES ($1, $2) ON CONFLICT(date) DO UPDATE SET announcement_requested = excluded.announcement_requested",
            date, 1 if requested else 0)


async def save_night_kills_order(game_date: str, game_number: int, night_kills_order: List[int]):
    search_date = _ensure_iso_date(game_date)
    async with get_db() as conn:
        await conn.execute(
            "INSERT INTO night_kills_order (game_date, game_number, kill_order) VALUES ($1, $2, $3) ON CONFLICT(game_date, game_number) DO UPDATE SET kill_order = excluded.kill_order",
            search_date, game_number, json.dumps(night_kills_order))


async def get_night_kills_order(game_date: str, game_number: int) -> List[int]:
    search_date = _ensure_iso_date(game_date)
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT kill_order FROM night_kills_order WHERE game_date = $1 AND game_number = $2", search_date, game_number)
        if row and row[0]: 
            return json.loads(row[0])
    return []


# ========== 12. РЕЙТИНГ, ФОЛЫ И ЭЛО ==========
async def get_user_fouls_stats(user_id: int) -> Dict[str, int]:
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT SUM(fouls) AS fouls_total, SUM(technical_fouls) AS techfouls_total, SUM(kick) AS kicks_total FROM game_slots_history WHERE user_id = $1",
            user_id)
    if not row or not any(row): 
        return {"fouls_total": 0, "techfouls_total": 0, "kicks_total": 0}
    return {"fouls_total": row[0] or 0, "techfouls_total": row[1] or 0, "kicks_total": row[2] or 0}


async def add_fouls_column():
    async with get_db() as conn:
        try:
            await conn.execute("ALTER TABLE game_slots_history ADD COLUMN fouls INTEGER DEFAULT 0")
        except Exception:
            pass


async def get_players_rating(limit: int = 50) -> List[Dict]:
    async with get_db() as conn:
        rows = await conn.fetch("""
            SELECT u.user_id,
                   u.full_name,
                   u.nickname,
                   COALESCE(SUM(s.base_points + s.bonus_points + s.lh_points +
                                s.will_protocol_points + s.will_opinion_points + s.dc_points), 0) AS total_points,
                   COUNT(DISTINCT s.game_number) AS games_played,
                   COUNT(DISTINCT CASE WHEN s.base_points = 1 THEN s.game_number END) AS games_won,
                   ROUND(AVG(s.base_points + s.bonus_points + s.lh_points + s.will_protocol_points +
                             s.will_opinion_points + s.dc_points), 2) AS avg_points,
                   SUM(CASE WHEN s.pu = 1 THEN 1 ELSE 0 END) AS pu_count,
                   SUM(s.kick) AS kicks,
                   SUM(s.ppk) AS ppk,
                   SUM(s.technical_fouls) AS techfouls
            FROM game_slots_history s
                     LEFT JOIN users u ON s.user_id = u.user_id
            WHERE u.user_id IS NOT NULL
            GROUP BY u.user_id, u.full_name, u.nickname
            HAVING games_played > 0
            ORDER BY total_points DESC, games_won DESC
            LIMIT $1
        """, limit)
    result = []
    for i, row in enumerate(rows, 1):
        result.append({"place": i, "user_id": row[0], "full_name": row[1], "nickname": row[2] or "ник не указан",
                       "total_points": round(row[3] or 0, 1), "games_played": row[4] or 0, "games_won": row[5] or 0,
                       "avg_points": row[6] or 0, "pu_count": row[7] or 0, "kicks": row[8] or 0, "ppk": row[9] or 0,
                       "techfouls": row[10] or 0})
    return result


async def create_elo_table():
    async with get_db() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS elo_ratings (
                user_id INTEGER PRIMARY KEY,
                elo INTEGER DEFAULT 1500,
                games_played INTEGER DEFAULT 0,
                games_won INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)


async def get_elo(user_id: int) -> int:
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT elo FROM elo_ratings WHERE user_id = $1", user_id)
        return row[0] if row else 1500


async def get_players_elo_rating(limit: int = 50) -> List[Dict]:
    async with get_db() as conn:
        rows = await conn.fetch("""
            SELECT u.user_id, u.nickname, u.full_name, e.elo, e.games_played, e.games_won
            FROM elo_ratings e
                     JOIN users u ON e.user_id = u.user_id
            WHERE e.games_played > 0
              AND e.updated_at >= NOW() - INTERVAL '21 days'
            ORDER BY e.elo DESC
            LIMIT $1
        """, limit)
    result = []
    for i, (user_id, nickname, full_name, elo, games_played, games_won) in enumerate(rows, 1):
        result.append({"place": i, "user_id": user_id, "nickname": nickname or full_name or "Неизвестный", "elo": elo,
                       "games_played": games_played, "games_won": games_won})
    return result


async def update_elo(user_id: int, delta: int):
    STARTING_ELO = 1500
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT 1 FROM elo_ratings WHERE user_id = $1", user_id)
        if row:
            await conn.execute("UPDATE elo_ratings SET elo = elo + $1, updated_at = NOW() WHERE user_id = $2", delta, user_id)
        else:
            await conn.execute("INSERT INTO elo_ratings (user_id, elo) VALUES ($1, $2)", user_id, STARTING_ELO + delta)


async def update_player_stats(user_id: int, team: str, won: bool):
    async with get_db() as conn:
        if team == "Красные":
            await conn.execute(
                "UPDATE users SET games_red = COALESCE(games_red, 0) + 1, wins_red = COALESCE(wins_red, 0) + $1 WHERE user_id = $2",
                1 if won else 0, user_id)
        else:
            await conn.execute(
                "UPDATE users SET games_black = COALESCE(games_black, 0) + 1, wins_black = COALESCE(wins_black, 0) + $1 WHERE user_id = $2",
                1 if won else 0, user_id)


async def update_player_statuses(user_id: int):
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT games_played, games_won, games_red, wins_red, games_black, wins_black FROM users WHERE user_id = $1",
            user_id)
        if not row: 
            return
        games_played, games_won, games_red, wins_red, games_black, wins_black = (row[i] or 0 for i in range(6))

    if games_played < 50:
        exp_level = "🟢 Новичок"
    elif games_played < 200:
        exp_level = "🔵 Умеет играть"
    elif games_played < 500:
        exp_level = "🟠 Опытный"
    else:
        exp_level = "🔴 Ветеран"

    winrate = (games_won / games_played * 100) if games_played > 0 else 0
    if winrate >= 48:
        skill_level = "🔥 Элитный"
    elif winrate >= 45:
        skill_level = "⭐ Высокий"
    elif winrate >= 40:
        skill_level = "📈 Средний"
    else:
        skill_level = "📉 Низкий"

    winrate_red = (wins_red / games_red * 100) if games_red > 0 else 0
    winrate_black = (wins_black / games_black * 100) if games_black > 0 else 0

    async with get_db() as conn:
        await conn.execute(
            "UPDATE users SET exp_level = $1, skill_level = $2, winrate_red = $3, winrate_black = $4 WHERE user_id = $5",
            exp_level, skill_level, round(winrate_red, 1), round(winrate_black, 1), user_id)


async def get_player_full_stats(user_id: int) -> Optional[Dict]:
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT full_name, nickname, debt, last_visit, COALESCE(elo, 1000) as elo, exp_level, skill_level, games_played, games_won, winrate_red, winrate_black, games_red, wins_red, games_black, wins_black FROM users WHERE user_id = $1",
            user_id)
        if not row: 
            return None
        elo = await get_elo(user_id)
        return {"full_name": row[0], "nickname": row[1], "debt": row[2], "last_visit": row[3], "elo": elo,
                "exp_level": row[5] or "🟢 Новичок", "skill_level": row[6] or "📉 Низкий", "games_played": row[7] or 0,
                "games_won": row[8] or 0, "winrate_red": row[9] or 0, "winrate_black": row[10] or 0,
                "games_red": row[11] or 0, "wins_red": row[12] or 0, "games_black": row[13] or 0,
                "wins_black": row[14] or 0}


# ========== 13. АЧИВКИ ==========
async def get_user_achievements(user_id: int) -> List[str]:
    async with get_db() as conn:
        rows = await conn.fetch("SELECT achievement_id FROM user_achievements WHERE user_id = $1", user_id)
        return [row[0] for row in rows]


async def add_user_achievement(user_id: int, achievement_id: str):
    async with get_db() as conn:
        await conn.execute("INSERT INTO user_achievements (user_id, achievement_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", user_id, achievement_id)


async def get_all_achievements() -> List[Tuple[str, str]]:
    try:
        from admin import ACHIEVEMENTS
        result = []
        for ach_id, ach in ACHIEVEMENTS.items(): 
            result.append((ach_id, ach["name"]))
        return result
    except ImportError:
        return []


# ========== 14. ЖЕТОНЫ ==========
async def get_user_tokens(user_id: int) -> int:
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT tokens FROM users WHERE user_id = $1", user_id)
        return row[0] if row else 0


async def add_tokens(user_id: int, amount: int, comment: str = "Игровые жетоны"):
    async with get_db() as conn:
        await conn.execute("UPDATE users SET tokens = tokens + $1 WHERE user_id = $2", amount, user_id)
        await conn.execute("INSERT INTO transactions (user_id, amount, type, comment) VALUES ($1, $2, 'tokens', $3)", user_id, amount, comment)


async def set_tokens(user_id: int, amount: int):
    async with get_db() as conn:
        await conn.execute("UPDATE users SET tokens = $1 WHERE user_id = $2", amount, user_id)


# ========== 15. СТАВКИ ==========
async def create_bet(game_id: int, game_number: int, game_date: str, created_by: int) -> int:
    search_date = _ensure_iso_date(game_date)
    async with get_db() as conn:
        row = await conn.fetchrow(
            "INSERT INTO bets_active (game_id, game_number, game_date, created_by) VALUES ($1, $2, $3, $4) RETURNING id",
            game_id, game_number, search_date, created_by)
        return row[0]


async def get_active_bet(game_id: int) -> Optional[Dict]:
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT id, game_id, game_number, game_date, created_by, created_at, closed, resolved, winner_team FROM bets_active WHERE game_id = $1 AND closed = FALSE AND resolved = FALSE",
            game_id)
        if row: 
            return {"id": row[0], "game_id": row[1], "game_number": row[2], "game_date": row[3],
                    "created_by": row[4], "created_at": row[5], "closed": row[6], "resolved": row[7],
                    "winner_team": row[8]}
    return None


async def close_bet(bet_id: int):
    async with get_db() as conn:
        await conn.execute("UPDATE bets_active SET closed = TRUE WHERE id = $1", bet_id)


async def resolve_bet(bet_id: int, winner_team: str):
    async with get_db() as conn:
        await conn.execute("UPDATE bets_active SET winner_team = $1, resolved = TRUE WHERE id = $2", winner_team, bet_id)


async def place_bet(user_id: int, bet_id: int, amount: int, predicted_winner: str) -> bool:
    try:
        async with get_db() as conn:
            await conn.execute("INSERT INTO user_bets (user_id, bet_id, amount, predicted_winner) VALUES ($1, $2, $3, $4)",
                               user_id, bet_id, amount, predicted_winner)
            return True
    except Exception:
        return False


async def get_user_bets_for_game(bet_id: int) -> List[Dict]:
    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT ub.user_id, ub.amount, ub.predicted_winner, u.nickname, u.full_name FROM user_bets ub JOIN users u ON ub.user_id = u.user_id WHERE ub.bet_id = $1",
            bet_id)
        return [{"user_id": row[0], "amount": row[1], "predicted_winner": row[2],
                 "nickname": row[3] or row[4] or str(row[0])} for row in rows]


async def get_bet_participants(bet_id: int) -> List[int]:
    async with get_db() as conn:
        rows = await conn.fetch("SELECT DISTINCT user_id FROM user_bets WHERE bet_id = $1", bet_id)
        return [row[0] for row in rows]


async def delete_bet(bet_id: int):
    async with get_db() as conn:
        await conn.execute("DELETE FROM user_bets WHERE bet_id = $1", bet_id)
        await conn.execute("DELETE FROM bets_active WHERE id = $1", bet_id)


async def get_team_avg_elo(game_id: int, team: str) -> float:
    async with get_db() as conn:
        game = await conn.fetchrow("SELECT game_date, game_number FROM game_history WHERE id = $1", game_id)
        if not game: 
            return 1500
        game_date, game_number = game
        rows = await conn.fetch(
            "SELECT COALESCE(e.elo, 1500) FROM game_slots_history s LEFT JOIN elo_ratings e ON s.user_id = e.user_id WHERE s.game_date = $1 AND s.game_number = $2 AND s.team = $3",
            game_date, game_number, team)
        elos = [row[0] for row in rows if row[0]]
        if not elos: 
            return 1500
        return sum(elos) / len(elos)


# ========== 16. СУДЬИ И СИНХРОНИЗАЦИЯ ==========
async def get_judged_games_count(user_id: int) -> int:
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) FROM game_history WHERE judge_id = $1", user_id)
        return row[0] if row else 0


async def recalc_all_stats():
    async with get_db() as conn:
        print("[STATS] Начало глобального пересчета...")
        await conn.execute("UPDATE users SET games_played = 0, games_won = 0, points = 0")
        rows = await conn.fetch(
            "SELECT user_id, COUNT(*) as games, SUM(CASE WHEN base_points >= 1 THEN 1 ELSE 0 END) as wins, SUM(base_points + bonus_points + lh_points + will_protocol_points + will_opinion_points + dc_points) as total_pts FROM game_slots_history WHERE user_id IS NOT NULL GROUP BY user_id")
        
        for user_id, games, wins, pts in rows:
            await conn.execute("UPDATE users SET games_played = $1, games_won = $2, points = $3 WHERE user_id = $4",
                               games, wins, pts, user_id)
            await conn.execute(
                "UPDATE elo_ratings SET games_played = $1, games_won = $2, updated_at = (SELECT MAX(game_date) FROM game_slots_history WHERE user_id = $3) WHERE user_id = $3",
                games, wins, user_id)
        print(f"[STATS] Пересчет завершен. Синхронизировано игроков: {len(rows)}")


async def refund_bets_for_game(game_id: int):
    async with get_db() as conn:
        rows = await conn.fetch("SELECT user_id, amount FROM bets WHERE game_id = $1", game_id)
        for user_id, amount in rows:
            await conn.execute("UPDATE users SET tokens = tokens + $1 WHERE user_id = $2", amount, user_id)
        await conn.execute("DELETE FROM bets WHERE game_id = $1", game_id)