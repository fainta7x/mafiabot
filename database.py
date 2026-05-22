import json
import datetime
from typing import Optional, Tuple, List, Dict, Any, Union
from contextlib import asynccontextmanager
import aiosqlite

DB_NAME = "mafia_crm.db"


# ========== УТИЛИТЫ ДЛЯ РАБОТЫ С БД ==========
@asynccontextmanager
async def get_db():
    """Контекстный менеджер для соединения с БД."""
    async with aiosqlite.connect(DB_NAME) as conn:
        # Позволяет обращаться и по индексу row[0], и по ключу row['name'] - ничего не сломается!
        conn.row_factory = aiosqlite.Row
        yield conn


def _ensure_iso_date(date_str: str) -> str:
    """Умный конвертер в ISO формат (YYYY-MM-DD)."""
    if not date_str: return date_str
    if "-" in date_str and len(date_str) == 10: return date_str
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
    alters = [
        ("users", ["games_played", "games_won", "points"], "INTEGER DEFAULT 0"),
        ("users", ["kicks", "ppk_causes"], "INTEGER DEFAULT 0"),
        ("game_history", ["game_number", "global_game_number"], "INTEGER"),
        ("game_slots_history", ["will_protocol_points", "will_opinion_points"], "REAL DEFAULT 0"),
        ("game_slots_history", ["kick", "ppk", "technical_fouls"], "INTEGER DEFAULT 0"),
        ("game_slots_history", ["dc_points"], "REAL DEFAULT 0"),
        ("game_slots_history", ["pu"], "INTEGER DEFAULT 0"),
        ("game_slots_history", ["will_protocol_raw", "will_opinion"], "TEXT DEFAULT ''"),
        ("game_slots_history", ["game_number"], "INTEGER DEFAULT 0"),
        ("game_slots_history", ["alive"], "INTEGER DEFAULT 1"),
        ("game_slots_history", ["status_reason"], "TEXT DEFAULT 'Жив'"),
        ("game_slots_history", ["updated_by_editor"], "INTEGER DEFAULT 0"),
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
        await conn.execute("""
                           CREATE TABLE IF NOT EXISTS game_slots_history
                           (
                               id                   INTEGER PRIMARY KEY AUTOINCREMENT,
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
                               updated_by_editor    INTEGER DEFAULT 0
                           )
                           """)
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS evening_booking (user_id INTEGER PRIMARY KEY, status TEXT, date TEXT)")
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
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS evening_stats_messages (date TEXT PRIMARY KEY, chat_id INTEGER, message_id INTEGER)")
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS evening_status (date TEXT PRIMARY KEY, bills_sent INTEGER DEFAULT 0)")
        await conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        await conn.execute("""
                           CREATE TABLE IF NOT EXISTS game_history
                           (
                               id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                               game_date          TEXT,
                               winner_label       TEXT,
                               protocol_text      TEXT,
                               game_number        INTEGER,
                               global_game_number INTEGER,
                               judge_id           INTEGER DEFAULT 0
                           )
                           """)
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS night_kills_order (game_date TEXT, game_number INTEGER, kill_order TEXT, PRIMARY KEY (game_date, game_number))")
        await conn.execute("""
                           CREATE TABLE IF NOT EXISTS user_achievements
                           (
                               user_id        INTEGER,
                               achievement_id TEXT,
                               earned_at      TEXT DEFAULT CURRENT_TIMESTAMP,
                               PRIMARY KEY (user_id, achievement_id),
                               FOREIGN KEY (user_id) REFERENCES users (user_id)
                           )
                           """)
        await conn.execute("""
                           CREATE TABLE IF NOT EXISTS bets_active
                           (
                               id          INTEGER PRIMARY KEY AUTOINCREMENT,
                               game_id     INTEGER NOT NULL,
                               game_number INTEGER NOT NULL,
                               game_date   TEXT    NOT NULL,
                               created_by  INTEGER NOT NULL,
                               created_at  TEXT    DEFAULT CURRENT_TIMESTAMP,
                               closed      BOOLEAN DEFAULT 0,
                               resolved    BOOLEAN DEFAULT 0,
                               winner_team TEXT,
                               FOREIGN KEY (game_id) REFERENCES game_history (id)
                           )
                           """)
        await conn.execute("""
                           CREATE TABLE IF NOT EXISTS user_bets
                           (
                               id               INTEGER PRIMARY KEY AUTOINCREMENT,
                               user_id          INTEGER NOT NULL,
                               bet_id           INTEGER NOT NULL,
                               amount           INTEGER NOT NULL,
                               predicted_winner TEXT    NOT NULL,
                               created_at       TEXT DEFAULT CURRENT_TIMESTAMP,
                               FOREIGN KEY (user_id) REFERENCES users (user_id),
                               FOREIGN KEY (bet_id) REFERENCES bets_active (id)
                           )
                           """)
        await conn.execute("""
                           CREATE TABLE IF NOT EXISTS transactions
                           (
                               id         INTEGER PRIMARY KEY AUTOINCREMENT,
                               user_id    INTEGER,
                               amount     REAL,
                               type       TEXT,
                               comment    TEXT,
                               created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                               FOREIGN KEY (user_id) REFERENCES users (user_id)
                           )
                           """)
        await conn.execute("""
                           CREATE TRIGGER IF NOT EXISTS prevent_direct_update
                               BEFORE UPDATE
                               ON game_slots_history
                               FOR EACH ROW
                               WHEN NEW.updated_by_editor != 1 AND (OLD.role != NEW.role OR OLD.team != NEW.team OR
                                                                    OLD.base_points != NEW.base_points OR
                                                                    OLD.bonus_points != NEW.bonus_points OR
                                                                    OLD.lh_points != NEW.lh_points OR
                                                                    OLD.will_protocol_points !=
                                                                    NEW.will_protocol_points OR
                                                                    OLD.will_opinion_points !=
                                                                    NEW.will_opinion_points OR
                                                                    OLD.dc_points != NEW.dc_points OR
                                                                    OLD.kick != NEW.kick OR OLD.ppk != NEW.ppk OR
                                                                    OLD.technical_fouls != NEW.technical_fouls OR
                                                                    OLD.pu != NEW.pu OR OLD.alive != NEW.alive OR
                                                                    OLD.status_reason != NEW.status_reason OR
                                                                    OLD.fouls != NEW.fouls)
                           BEGIN
                               SELECT RAISE(ABORT, 'Изменение данных игры разрешено только через редактор!');
                           END;
                           """)
        await conn.commit()

    await _ensure_columns()
    await add_fouls_column()
    await create_elo_table()


# ========== 2. SETTINGS ==========
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
                (key, value))
        await conn.commit()


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
            "INSERT INTO users (user_id, username, full_name) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET username = excluded.username, full_name = excluded.full_name",
            (user_id, username, full_name))
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
        async with conn.execute(
                "SELECT full_name, nickname, last_visit, debt, total_paid, kicks, ppk_causes FROM users") as cur:
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
    async with get_db() as conn:
        await conn.execute("UPDATE users SET kicks = kicks + 1 WHERE user_id = ?", (user_id,))
        await conn.commit()


async def increment_user_ppk_causes(user_id: int):
    async with get_db() as conn:
        await conn.execute("UPDATE users SET ppk_causes = ppk_causes + 1 WHERE user_id = ?", (user_id,))
        await conn.commit()


async def get_user_kicks(user_id: int) -> int:
    async with get_db() as conn:
        async with conn.execute("SELECT kicks FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def get_user_ppk_causes(user_id: int) -> int:
    async with get_db() as conn:
        async with conn.execute("SELECT ppk_causes FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def get_user_by_id(user_id: int) -> Optional[Tuple[int, str, str, str]]:
    async with get_db() as conn:
        async with conn.execute("SELECT user_id, full_name, username, nickname FROM users WHERE user_id = ?",
                                (user_id,)) as cur:
            return await cur.fetchone()


async def get_user_by_nickname(nickname: str) -> Optional[Tuple[int, str, str, str]]:
    async with get_db() as conn:
        async with conn.execute("SELECT user_id, full_name, username, nickname FROM users WHERE nickname = ?",
                                (nickname,)) as cur:
            row = await cur.fetchone()
            if row: return row
        async with conn.execute("SELECT user_id, full_name, username, nickname FROM users WHERE full_name = ?",
                                (nickname,)) as cur:
            row = await cur.fetchone()
            if row: return row
        async with conn.execute("SELECT user_id, full_name, username, nickname FROM users WHERE nickname LIKE ?",
                                (f"%{nickname}%",)) as cur:
            row = await cur.fetchone()
            if row: return row
        return None


async def get_all_users() -> list:
    async with get_db() as conn:
        async with conn.execute("SELECT user_id, nickname, full_name FROM users") as cur:
            rows = await cur.fetchall()
    return [{"user_id": r[0], "nickname": r[1], "full_name": r[2]} for r in rows]


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
        async with conn.execute(
                "SELECT COALESCE(users.full_name, 'ID: ' || evening_booking.user_id) AS full_name, users.username, users.nickname, evening_booking.status FROM evening_booking LEFT JOIN users ON evening_booking.user_id = users.user_id") as cur:
            return await cur.fetchall()


async def get_booked_players_for_game() -> list:
    async with get_db() as conn:
        async with conn.execute(
                "SELECT e.user_id, COALESCE(u.full_name, 'Неизвестный') AS full_name, u.username, u.nickname, e.status FROM evening_booking e LEFT JOIN users u ON e.user_id = u.user_id WHERE e.status IN ('Вовремя', 'Позже')") as cur:
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
        async with conn.execute(
                "SELECT COALESCE(u.nickname, u.full_name, 'Без имени') AS name FROM evening_booking e LEFT JOIN users u ON e.user_id = u.user_id WHERE e.date = ? AND e.status = ? ORDER BY name",
                (date_str, status)) as cur:
            return [row[0] for row in await cur.fetchall()]


async def get_all_bookings_for_date_ordered(date_str: str) -> List[Tuple[str, str]]:
    async with get_db() as conn:
        async with conn.execute(
                "SELECT COALESCE(u.nickname, u.full_name, 'Без имени'), e.status FROM evening_booking e LEFT JOIN users u ON e.user_id = u.user_id WHERE e.date = ? ORDER BY CASE e.status WHEN 'Вовремя' THEN 1 WHEN 'Позже' THEN 2 WHEN 'Не идёт' THEN 3 ELSE 4 END, name",
                (date_str,)) as cur:
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
async def log_transaction(user_id: int, amount: float, t_type: str, comment: str = ""):
    async with get_db() as conn:
        await conn.execute("INSERT INTO transactions (user_id, amount, type, comment) VALUES (?, ?, ?, ?)",
                           (user_id, amount, t_type, comment))
        await conn.commit()


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
                "SELECT full_name, nickname, username, debt, user_id FROM users WHERE debt < 0 ORDER BY debt ASC") as cur:
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
        await conn.execute(
            "UPDATE evening_history SET amount = ? WHERE id = (SELECT id FROM evening_history WHERE user_id = ? ORDER BY id DESC LIMIT 1)",
            (amount, user_id))
        await conn.commit()


# ========== 6. ИСТОРИЯ ВЕЧЕРОВ ==========
async def archive_current_evening():
    # 1. Сначала узнаем правильную дату текущего игрового вечера из настроек
    # Это гарантирует, что мы запишем именно дату, а не ID или мусор
    date_to_archive = await get_setting("current_game_date")
    if not date_to_archive:
        date_to_archive = datetime.now().strftime("%Y-%m-%d")

    async with get_db() as conn:
        # 2. Выбираем только то, что нужно (без даты из booking, она нам не нужна)
        async with conn.execute(
                "SELECT e.user_id, e.status, u.full_name, u.nickname FROM evening_booking e LEFT JOIN users u ON e.user_id = u.user_id") as cur:
            rows = await cur.fetchall()

        if rows:
            # Четко указываем поля и значения в правильном порядке
            # ВНИМАНИЕ: Если твоя таблица создана как (date, user_id...),
            # то порядок должен быть именно таким:
            data_to_insert = []
            for r in rows:
                # Здесь мы предполагаем, что за "Вовремя/Позже" берем 100₽
                money = 100
                data_to_insert.append(
                    (date_to_archive, r['user_id'], r['status'], r['full_name'], r['nickname'], money))


            # Добавляем названия столбцов в запрос, чтобы SQLite не перепутал их
            await conn.executemany(
                "INSERT INTO evening_history (date, user_id, status, full_name, nickname, amount) VALUES (?, ?, ?, ?, ?, ?)",
                data_to_insert)

            # 4. Обновляем время последнего визита
            for r in rows:
                if r['status'] in ("Вовремя", "Позже"):
                    await conn.execute("UPDATE users SET last_visit = ? WHERE user_id = ?",
                                       (f"{date_to_archive} 20:00", r['user_id']))

        # 5. Очищаем текущую запись
        await conn.execute("DELETE FROM evening_booking")
        await conn.commit()


async def get_evening_financial_report(date_str: str) -> List[Dict]:
    search_date = _ensure_iso_date(date_str)
    async with get_db() as conn:
        async with conn.execute(
                "SELECT u.nickname, u.full_name, (SELECT COUNT(*) FROM game_slots_history s WHERE s.user_id = h.user_id AND s.game_date = h.date) as real_games_count, h.user_id FROM evening_history h JOIN users u ON h.user_id = u.user_id WHERE h.date = ? AND h.status IN ('Вовремя', 'Позже') ORDER BY u.nickname ASC",
                (search_date,)) as cur:
            rows = await cur.fetchall()
            result = []
            for nickname, full_name, games, user_id in rows:
                result.append({"name": nickname or full_name or f"ID: {user_id}", "games": games if games > 0 else 1,
                               "amount": (games * 100) if games > 0 else 100})
            return result


async def get_evening_players(date_str: str) -> list:
    search_date = _ensure_iso_date(date_str)
    async with get_db() as conn:
        async with conn.execute(
                "SELECT h.user_id, COALESCE(u.full_name, h.full_name), COALESCE(u.nickname, h.nickname), h.status, (SELECT COUNT(*) FROM game_slots_history s WHERE s.user_id = h.user_id AND s.game_date = h.date) as games_count FROM evening_history h LEFT JOIN users u ON h.user_id = u.user_id WHERE h.date = ?",
                (search_date,)) as cur:
            rows = await cur.fetchall()
            return [(r[0], r[1], r[2], r[3], r[4]) for r in rows]


async def get_evenings_list(limit: int = 10) -> list:
    orgs = ("Чагин", "Матроскина", "Стаут", "Гриня", "Evgeniy Chagin", "Екатерина", "Di D", "Григорий Подколзин")

    # Мы используем вложенный запрос для расчета игр (games_count) и сразу считаем стоимость
    # Логика: если игр >= 4, то 400. Если игр < 4 (или 0), то игры * 100 (минимум 1 игра).
    query = f"""
        SELECT 
            h.date, 
            COUNT(DISTINCT h.user_id),
            SUM(
                CASE 
                    WHEN (SELECT MAX(1, COUNT(*)) FROM game_slots_history s WHERE s.user_id = h.user_id AND s.game_date = h.date) >= 4 
                    THEN 400 
                    ELSE (SELECT MAX(1, COUNT(*)) FROM game_slots_history s WHERE s.user_id = h.user_id AND s.game_date = h.date) * 100 
                END
            ) as total_sum
        FROM evening_history h 
        WHERE h.status IN ('Вовремя', 'Позже') 
          AND h.nickname NOT IN {orgs} 
          AND h.full_name NOT IN {orgs} 
        GROUP BY h.date 
        ORDER BY h.date DESC 
        LIMIT ?
    """

    async with get_db() as conn:
        async with conn.execute(query, (limit,)) as cur:
            return await cur.fetchall()


async def get_top_players_by_visits(limit: int = 10) -> list:
    async with get_db() as conn:
        async with conn.execute(
                "SELECT u.full_name, u.nickname, COUNT(h.id) FROM evening_history h LEFT JOIN users u ON h.user_id = u.user_id WHERE h.status IN ('Вовремя', 'Позже') GROUP BY h.user_id ORDER BY COUNT(h.id) DESC LIMIT ?",
                (limit,)) as cur:
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

# 1. Получаем список годов
async def get_history_years():
    async with get_db() as conn:
        async with conn.execute("SELECT DISTINCT strftime('%Y', date) as year FROM evening_history ORDER BY year DESC") as cur:
            return [row[0] for row in await cur.fetchall()]

# 2. Получаем месяцы для конкретного года + считаем сумму за месяц
async def get_history_months(year: str):
    orgs = ("Чагин", "Матроскина", "Стаут", "Гриня", "Evgeniy Chagin", "Екатерина", "Di D", "Григорий Подколзин")
    orgs_formatted = ", ".join([f"'{o}'" for o in orgs])

    async with get_db() as conn:
        # Добавляем LEFT JOIN и фильтр NOT IN, как в списке вечеров
        query = f"""
            SELECT 
                strftime('%m', h.date) as month,
                SUM(
                    CASE 
                        WHEN (SELECT MAX(1, COUNT(*)) FROM game_slots_history s WHERE s.user_id = h.user_id AND s.game_date = h.date) >= 4 
                        THEN 400 
                        ELSE (SELECT MAX(1, COUNT(*)) FROM game_slots_history s WHERE s.user_id = h.user_id AND s.game_date = h.date) * 100 
                    END
                ) as total_sum
            FROM evening_history h
            LEFT JOIN users u ON h.user_id = u.user_id
            WHERE strftime('%Y', h.date) = ? 
              AND h.status IN ('Вовремя', 'Позже')
              AND COALESCE(u.nickname, h.nickname) NOT IN ({orgs_formatted})
              AND COALESCE(u.full_name, h.full_name) NOT IN ({orgs_formatted})
            GROUP BY month 
            ORDER BY month DESC
        """
        async with conn.execute(query, (year,)) as cur:
            return await cur.fetchall()

# 3. Получаем вечера для конкретного месяца (твой текущий запрос, фильтруем по году и месяцу)
async def get_history_evenings(year: str, month: str):
    # Список исключений (должен совпадать с тем, что в admin.py)
    orgs = ("Чагин", "Матроскина", "Стаут", "Гриня", "Evgeniy Chagin", "Екатерина", "Di D", "Григорий Подколзин")

    # Форматируем список для SQL (в кавычках через запятую)
    orgs_formatted = ", ".join([f"'{o}'" for o in orgs])

    async with get_db() as conn:
        # Используем логику:
        # 1. Считаем игры: MAX(1, кол-во записей)
        # 2. Считаем деньги: если >= 4 игры, то 400, иначе игры * 100
        # 3. Фильтруем организаторов (NOT IN)
        query = f"""
            SELECT 
                h.date, 
                COUNT(DISTINCT h.user_id),
                SUM(
                    CASE 
                        WHEN (SELECT MAX(1, COUNT(*)) FROM game_slots_history s WHERE s.user_id = h.user_id AND s.game_date = h.date) >= 4 
                        THEN 400 
                        ELSE (SELECT MAX(1, COUNT(*)) FROM game_slots_history s WHERE s.user_id = h.user_id AND s.game_date = h.date) * 100 
                    END
                ) as total_sum
            FROM evening_history h
            LEFT JOIN users u ON h.user_id = u.user_id
            WHERE strftime('%Y', h.date) = ? 
              AND strftime('%m', h.date) = ? 
              AND h.status IN ('Вовремя', 'Позже')
              AND COALESCE(u.nickname, h.nickname) NOT IN ({orgs_formatted})
              AND COALESCE(u.full_name, h.full_name) NOT IN ({orgs_formatted})
            GROUP BY h.date 
            ORDER BY h.date DESC
        """
        async with conn.execute(query, (year, month)) as cur:
            return await cur.fetchall()

# ========== 7. РЕЗУЛЬТАТЫ ИГР ==========
async def apply_game_result_to_users(slots: Dict[int, dict], winning_team: str):
    async with get_db() as conn:
        for slot in slots.values():
            uid, team = slot.get("user_id"), slot.get("team")
            if not uid or not team: continue
            await conn.execute("UPDATE users SET games_played = COALESCE(games_played, 0) + 1 WHERE user_id = ?",
                               (uid,))
            if team == winning_team:
                await conn.execute(
                    "UPDATE users SET games_won = COALESCE(games_won, 0) + 1, points = COALESCE(points, 0) + 1 WHERE user_id = ?",
                    (uid,))
        await conn.commit()


async def get_user_game_counters(user_id: int) -> Optional[Dict[str, int]]:
    async with get_db() as conn:
        async with conn.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)) as cur:
            if not await cur.fetchone(): return None
        async with conn.execute(
                "SELECT COUNT(*) AS played, SUM(CASE WHEN base_points = 1 THEN 1 ELSE 0 END) AS won, SUM(base_points) AS points FROM game_slots_history WHERE user_id = ?",
                (user_id,)) as cur:
            row = await cur.fetchone()
            return {"games_played": row[0] or 0, "games_won": row[1] or 0, "points": row[2] or 0}


async def get_user_roles_stats(user_id: int) -> List[Dict]:
    async with get_db() as conn:
        async with conn.execute("""
                                SELECT role,
                                       COUNT(*)                                                                     AS games,
                                       SUM(CASE WHEN base_points = 1 THEN 1 ELSE 0 END)                             AS wins,
                                       SUM(base_points + bonus_points + lh_points + will_protocol_points +
                                           will_opinion_points +
                                           dc_points)                                                               AS total_points,
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
                                WHERE user_id = ?
                                GROUP BY role
                                """, (user_id,)) as cur:
            rows = await cur.fetchall()

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
        cur = await conn.execute(
            "INSERT INTO game_history (game_date, winner_label, protocol_text, game_number, global_game_number, judge_id) VALUES (?, ?, ?, ?, ?, ?)",
            (search_date, winner_label, protocol_text, game_number, global_game_number, judge_id or 0))
        await conn.commit()
        return cur.lastrowid


async def get_user_extra_stats(user_id: int) -> Dict[str, float]:
    async with get_db() as conn:
        async with conn.execute(
                "SELECT AVG(lh_points) AS avg_lh, SUM(kick) AS removed_count, SUM(technical_fouls) AS techfouls_total, SUM(ppk) AS ppk_guilty_count, SUM(pu) AS pu_count, SUM(fouls) AS fouls_total FROM game_slots_history WHERE user_id = ?",
                (user_id,)) as cur:
            row = await cur.fetchone()
    if not row: return {"avg_lh": 0.0, "removed_count": 0, "techfouls_total": 0, "ppk_guilty_count": 0, "pu_count": 0,
                        "fouls_total": 0}
    avg_lh, removed_count, techfouls_total, ppk_guilty_count, pu_count, fouls_total = row
    return {"avg_lh": float(avg_lh or 0.0), "removed_count": int(removed_count or 0),
            "techfouls_total": int(techfouls_total or 0), "ppk_guilty_count": int(ppk_guilty_count or 0),
            "pu_count": int(pu_count or 0), "fouls_total": int(fouls_total or 0)}


async def get_total_games_count() -> int:
    async with get_db() as conn:
        async with conn.execute("SELECT COUNT(*) FROM game_history") as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def _fetch_games(query: str, params: tuple = ()) -> List[Dict]:
    async with get_db() as conn:
        async with conn.execute(query, params) as cur:
            rows = await cur.fetchall()
    return [{"id": r[0], "game_date": r[1], "winner_label": r[2], "protocol_text": r[3], "game_number": r[4],
             "global_game_number": r[5], "judge_id": r[6] if len(r) > 6 else None} for r in rows]


async def get_games_by_date(game_date: str) -> List[Dict]:
    search_date = _ensure_iso_date(game_date)
    return await _fetch_games(
        "SELECT id, game_date, winner_label, protocol_text, game_number, global_game_number FROM game_history WHERE game_date = ? ORDER BY id ASC",
        (search_date,))


async def get_last_games(limit: int = 10) -> List[Dict]:
    return await _fetch_games(
        "SELECT id, game_date, winner_label, protocol_text, game_number, global_game_number FROM game_history ORDER BY id DESC LIMIT ?",
        (limit,))


async def get_user_games(user_id: int, limit: int = 10) -> List[Dict]:
    async with get_db() as conn:
        async with conn.execute(
                "SELECT DISTINCT game_date, game_number FROM game_slots_history WHERE user_id = ? ORDER BY game_date DESC LIMIT ?",
                (user_id, limit)) as cur:
            dates_and_numbers = await cur.fetchall()
        if not dates_and_numbers: return []
        games = []
        for game_date, game_number in dates_and_numbers:
            async with conn.execute(
                    "SELECT id, game_date, winner_label, protocol_text, game_number, global_game_number FROM game_history WHERE game_date = ? AND game_number = ?",
                    (game_date, game_number)) as cur2:
                row = await cur2.fetchone()
                if row: games.append(
                    {"id": row[0], "game_date": row[1], "winner_label": row[2], "protocol_text": row[3],
                     "game_number": row[4], "global_game_number": row[5]})
        return games


async def get_all_game_dates() -> List[Tuple[str, int]]:
    async with get_db() as conn:
        async with conn.execute(
                "SELECT game_date, COUNT(*) as games_count FROM game_history GROUP BY game_date ORDER BY game_date DESC") as cur:
            return await cur.fetchall()


# ========== 10. ДЕТАЛЬНАЯ РАБОТА С ИГРАМИ (ДЛЯ РЕДАКТОРА И ПРОФИЛЯ) ==========
async def get_game_by_id(game_id: int) -> Optional[Dict]:
    """Возвращает данные конкретной игры по её ID."""
    async with get_db() as conn:
        async with conn.execute(
                "SELECT id, game_date, winner_label, protocol_text, game_number, global_game_number, judge_id FROM game_history WHERE id = ?",
                (game_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_game_slots_by_date(game_date: str, game_number: int = None) -> Optional[Dict[int, dict]]:
    """Загружает все 10 слотов игры для отображения или редактирования."""
    search_date = _ensure_iso_date(game_date)
    query = "SELECT * FROM game_slots_history WHERE game_date = ?"
    params = [search_date]
    if game_number is not None:
        query += " AND game_number = ?"
        params.append(game_number)
    query += " ORDER BY slot_num ASC"

    async with get_db() as conn:
        async with conn.execute(query, params) as cur:
            rows = await cur.fetchall()
            if not rows: return None

            slots = {}
            for r in rows:
                u_id = r['user_id']
                nickname = "Игрок"
                if u_id:
                    async with conn.execute("SELECT nickname, full_name FROM users WHERE user_id = ?",
                                            (u_id,)) as u_cur:
                        u_row = await u_cur.fetchone()
                        if u_row:
                            nickname = u_row['nickname'] or u_row['full_name']

                slot_data = dict(r)
                slot_data['nickname'] = nickname
                slots[r['slot_num']] = slot_data
            return slots


async def save_game_slots_history(game_date: str, slots: Dict[int, dict], game_number: int = 0):
    """Массовое сохранение слотов игры (10 штук за раз)."""
    search_date = _ensure_iso_date(game_date)
    rows = []
    for slot_num, s in slots.items():
        rows.append((
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
        ))

    async with get_db() as conn:
        await conn.executemany("""
                               INSERT INTO game_slots_history (game_date, game_number, user_id, slot_num, role, team,
                                                               base_points, bonus_points, lh_points,
                                                               will_protocol_points, will_opinion_points, dc_points,
                                                               kick, ppk, fouls, pu, will_protocol_raw, will_opinion,
                                                               alive, status_reason, elo_change, new_elo)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                               """, rows)
        await conn.commit()


async def update_game_outcome(game_id: int, winner_label: str):
    """Обновляет результат игры (кто победил)."""
    async with get_db() as conn:
        await conn.execute("UPDATE game_history SET winner_label = ? WHERE id = ?", (winner_label, game_id))
        await conn.commit()


async def update_game_slot(game_date: str, game_num: int, slot_num: int, **kwargs):
    """Универсальная функция обновления слота через редактор (обходит триггер)."""
    if not kwargs: return
    search_date = _ensure_iso_date(game_date)
    cols = ", ".join([f"{k} = ?" for k in kwargs.keys()])
    params = list(kwargs.values())
    sql = f"UPDATE game_slots_history SET {cols}, updated_by_editor = 1 WHERE game_date = ? AND game_number = ? AND slot_num = ?"
    params.extend([search_date, game_num, slot_num])

    async with get_db() as conn:
        await conn.execute(sql, params)
        await conn.commit()


# ========== 11. АНОНСЫ СТОЛА И УБИЙСТВА ==========
async def get_announcement_requested(date: str) -> bool:
    async with get_db() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS game_dates (date TEXT PRIMARY KEY, announcement_requested INTEGER DEFAULT 0)")
        await conn.commit()
        async with conn.execute("SELECT announcement_requested FROM game_dates WHERE date = ?", (date,)) as cur:
            row = await cur.fetchone()
            return bool(row and row[0]) if row else False


async def set_announcement_requested(date: str, requested: bool):
    async with get_db() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS game_dates (date TEXT PRIMARY KEY, announcement_requested INTEGER DEFAULT 0)")
        await conn.execute(
            "INSERT INTO game_dates (date, announcement_requested) VALUES (?, ?) ON CONFLICT(date) DO UPDATE SET announcement_requested = excluded.announcement_requested",
            (date, 1 if requested else 0))
        await conn.commit()


async def save_night_kills_order(game_date: str, game_number: int, night_kills_order: List[int]):
    search_date = _ensure_iso_date(game_date)
    async with get_db() as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO night_kills_order (game_date, game_number, kill_order) VALUES (?, ?, ?)",
            (search_date, game_number, json.dumps(night_kills_order)))
        await conn.commit()


async def get_night_kills_order(game_date: str, game_number: int) -> List[int]:
    search_date = _ensure_iso_date(game_date)
    async with get_db() as conn:
        async with conn.execute("SELECT kill_order FROM night_kills_order WHERE game_date = ? AND game_number = ?",
                                (search_date, game_number)) as cur:
            row = await cur.fetchone()
            if row and row[0]: return json.loads(row[0])
    return []


# ========== 12. РЕЙТИНГ, ФОЛЫ И ЭЛО ==========
async def get_user_fouls_stats(user_id: int) -> Dict[str, int]:
    async with get_db() as conn:
        async with conn.execute(
                "SELECT SUM(fouls) AS fouls_total, SUM(technical_fouls) AS techfouls_total, SUM(kick) AS kicks_total FROM game_slots_history WHERE user_id = ?",
                (user_id,)) as cur:
            row = await cur.fetchone()
    if not row or not any(row): return {"fouls_total": 0, "techfouls_total": 0, "kicks_total": 0}
    return {"fouls_total": row[0] or 0, "techfouls_total": row[1] or 0, "kicks_total": row[2] or 0}


async def add_fouls_column():
    async with get_db() as conn:
        try:
            await conn.execute("ALTER TABLE game_slots_history ADD COLUMN fouls INTEGER DEFAULT 0")
            await conn.commit()
        except Exception:
            pass


async def get_players_rating(limit: int = 50) -> List[Dict]:
    async with get_db() as conn:
        async with conn.execute("""
                                SELECT u.user_id,
                                       u.full_name,
                                       u.nickname,
                                       COALESCE(SUM(s.base_points + s.bonus_points + s.lh_points +
                                                    s.will_protocol_points + s.will_opinion_points + s.dc_points),
                                                0)                                                        AS total_points,
                                       COUNT(DISTINCT s.game_number)                                      AS games_played,
                                       COUNT(DISTINCT CASE WHEN s.base_points = 1 THEN s.game_number END) AS games_won,
                                       ROUND(AVG(s.base_points + s.bonus_points + s.lh_points + s.will_protocol_points +
                                                 s.will_opinion_points + s.dc_points), 2)                 AS avg_points,
                                       SUM(CASE WHEN s.pu = 1 THEN 1 ELSE 0 END)                          AS pu_count,
                                       SUM(s.kick)                                                        AS kicks,
                                       SUM(s.ppk)                                                         AS ppk,
                                       SUM(s.technical_fouls)                                             AS techfouls
                                FROM game_slots_history s
                                         LEFT JOIN users u ON s.user_id = u.user_id
                                WHERE u.user_id IS NOT NULL
                                GROUP BY u.user_id, u.full_name, u.nickname
                                HAVING games_played > 0
                                ORDER BY total_points DESC, games_won DESC
                                LIMIT ?
                                """, (limit,)) as cur:
            rows = await cur.fetchall()
    result = []
    for i, row in enumerate(rows, 1):
        result.append({"place": i, "user_id": row[0], "full_name": row[1], "nickname": row[2] or "ник не указан",
                       "total_points": round(row[3] or 0, 1), "games_played": row[4] or 0, "games_won": row[5] or 0,
                       "avg_points": row[6] or 0, "pu_count": row[7] or 0, "kicks": row[8] or 0, "ppk": row[9] or 0,
                       "techfouls": row[10] or 0})
    return result


async def create_elo_table():
    async with get_db() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS elo_ratings (user_id INTEGER PRIMARY KEY, elo INTEGER DEFAULT 1000, games_played INTEGER DEFAULT 0, games_won INTEGER DEFAULT 0, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users(user_id))")
        await conn.commit()


async def get_elo(user_id: int) -> int:
    async with get_db() as conn:
        async with conn.execute("SELECT elo FROM elo_ratings WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 1500


async def get_players_elo_rating(limit: int = 50) -> List[Dict]:
    async with get_db() as conn:
        async with conn.execute("""
                                SELECT u.user_id, u.nickname, u.full_name, e.elo, e.games_played, e.games_won
                                FROM elo_ratings e
                                         JOIN users u ON e.user_id = u.user_id
                                WHERE e.games_played > 0
                                  AND e.updated_at >= date('now', '-21 days')
                                ORDER BY e.elo DESC
                                LIMIT ?
                                """, (limit,)) as cur:
            rows = await cur.fetchall()
    result = []
    for i, (user_id, nickname, full_name, elo, games_played, games_won) in enumerate(rows, 1):
        result.append({"place": i, "user_id": user_id, "nickname": nickname or full_name or "Неизвестный", "elo": elo,
                       "games_played": games_played, "games_won": games_won})
    return result


async def update_elo(user_id: int, delta: int):
    STARTING_ELO = 1500
    async with get_db() as conn:
        async with conn.execute("SELECT 1 FROM elo_ratings WHERE user_id = ?", (user_id,)) as cur:
            exists = await cur.fetchone()
        if exists:
            await conn.execute("UPDATE elo_ratings SET elo = elo + ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                               (delta, user_id))
        else:
            await conn.execute("INSERT INTO elo_ratings (user_id, elo) VALUES (?, ?)", (user_id, STARTING_ELO + delta))
        await conn.commit()


async def update_player_stats(user_id: int, team: str, won: bool):
    async with get_db() as conn:
        if team == "Красные":
            await conn.execute(
                "UPDATE users SET games_red = COALESCE(games_red, 0) + 1, wins_red = COALESCE(wins_red, 0) + ? WHERE user_id = ?",
                (1 if won else 0, user_id))
        else:
            await conn.execute(
                "UPDATE users SET games_black = COALESCE(games_black, 0) + 1, wins_black = COALESCE(wins_black, 0) + ? WHERE user_id = ?",
                (1 if won else 0, user_id))
        await conn.commit()


async def update_player_statuses(user_id: int):
    async with get_db() as conn:
        async with conn.execute(
                "SELECT games_played, games_won, games_red, wins_red, games_black, wins_black FROM users WHERE user_id = ?",
                (user_id,)) as cur:
            row = await cur.fetchone()
            if not row: return
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

        await conn.execute(
            "UPDATE users SET exp_level = ?, skill_level = ?, winrate_red = ?, winrate_black = ? WHERE user_id = ?",
            (exp_level, skill_level, round(winrate_red, 1), round(winrate_black, 1), user_id))
        await conn.commit()


async def get_player_full_stats(user_id: int) -> Optional[Dict]:
    async with get_db() as conn:
        async with conn.execute(
                "SELECT full_name, nickname, debt, last_visit, COALESCE(elo, 1000) as elo, exp_level, skill_level, games_played, games_won, winrate_red, winrate_black, games_red, wins_red, games_black, wins_black FROM users WHERE user_id = ?",
                (user_id,)) as cur:
            row = await cur.fetchone()
            if not row: return None
        elo = await get_elo(user_id)
        return {"full_name": row[0], "nickname": row[1], "debt": row[2], "last_visit": row[3], "elo": elo,
                "exp_level": row[5] or "🟢 Новичок", "skill_level": row[6] or "📉 Низкий", "games_played": row[7] or 0,
                "games_won": row[8] or 0, "winrate_red": row[9] or 0, "winrate_black": row[10] or 0,
                "games_red": row[11] or 0, "wins_red": row[12] or 0, "games_black": row[13] or 0,
                "wins_black": row[14] or 0}


# ========== 13. АЧИВКИ ==========
async def get_user_achievements(user_id: int) -> List[str]:
    async with get_db() as conn:
        async with conn.execute("SELECT achievement_id FROM user_achievements WHERE user_id = ?", (user_id,)) as cur:
            rows = await cur.fetchall()
            return [row[0] for row in rows]


async def add_user_achievement(user_id: int, achievement_id: str):
    async with get_db() as conn:
        await conn.execute("INSERT OR IGNORE INTO user_achievements (user_id, achievement_id) VALUES (?, ?)",
                           (user_id, achievement_id))
        await conn.commit()


async def get_all_achievements() -> List[Tuple[str, str]]:
    from admin import ACHIEVEMENTS  # Заглушка, если ACHIEVEMENTS хранится в admin.py
    result = []
    for ach_id, ach in ACHIEVEMENTS.items(): result.append((ach_id, ach["name"]))
    return result


# ========== 14. ЖЕТОНЫ ==========
async def get_user_tokens(user_id: int) -> int:
    """Возвращает текущий баланс жетонов игрока."""
    async with get_db() as conn:
        async with conn.execute("SELECT tokens FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

async def add_tokens(user_id: int, amount: int, comment: str = "Игровые жетоны"):
    """Добавляет жетоны игроку и автоматически записывает чек в транзакции."""
    async with get_db() as conn:
        # 1. Меняем баланс
        await conn.execute(
            "UPDATE users SET tokens = tokens + ? WHERE user_id = ?",
            (amount, user_id)
        )
        # 2. Записываем чек в историю
        await conn.execute(
            "INSERT INTO transactions (user_id, amount, type, comment) VALUES (?, ?, ?, ?)",
            (user_id, amount, 'tokens', comment)
        )
        await conn.commit()

async def set_tokens(user_id: int, amount: int):
    """Жестко устанавливает баланс жетонов (например, при сбросе)."""
    async with get_db() as conn:
        await conn.execute("UPDATE users SET tokens = ? WHERE user_id = ?", (amount, user_id))
        await conn.commit()


# ========== 15. СТАВКИ ==========
async def create_bet(game_id: int, game_number: int, game_date: str, created_by: int) -> int:
    search_date = _ensure_iso_date(game_date)
    async with get_db() as conn:
        cur = await conn.execute(
            "INSERT INTO bets_active (game_id, game_number, game_date, created_by) VALUES (?, ?, ?, ?)",
            (game_id, game_number, search_date, created_by))
        await conn.commit()
        return cur.lastrowid


async def get_active_bet(game_id: int) -> Optional[Dict]:
    async with get_db() as conn:
        async with conn.execute(
                "SELECT id, game_id, game_number, game_date, created_by, created_at, closed, resolved, winner_team FROM bets_active WHERE game_id = ? AND closed = 0 AND resolved = 0",
                (game_id,)) as cur:
            row = await cur.fetchone()
            if row: return {"id": row[0], "game_id": row[1], "game_number": row[2], "game_date": row[3],
                            "created_by": row[4], "created_at": row[5], "closed": row[6], "resolved": row[7],
                            "winner_team": row[8]}
    return None


async def close_bet(bet_id: int):
    async with get_db() as conn:
        await conn.execute("UPDATE bets_active SET closed = 1 WHERE id = ?", (bet_id,))
        await conn.commit()


async def resolve_bet(bet_id: int, winner_team: str):
    async with get_db() as conn:
        await conn.execute("UPDATE bets_active SET winner_team = ?, resolved = 1 WHERE id = ?", (winner_team, bet_id))
        await conn.commit()


async def place_bet(user_id: int, bet_id: int, amount: int, predicted_winner: str) -> bool:
    try:
        async with get_db() as conn:
            await conn.execute("INSERT INTO user_bets (user_id, bet_id, amount, predicted_winner) VALUES (?, ?, ?, ?)",
                               (user_id, bet_id, amount, predicted_winner))
            await conn.commit()
            return True
    except Exception:
        return False


async def get_user_bets_for_game(bet_id: int) -> List[Dict]:
    async with get_db() as conn:
        async with conn.execute(
                "SELECT ub.user_id, ub.amount, ub.predicted_winner, u.nickname, u.full_name FROM user_bets ub JOIN users u ON ub.user_id = u.user_id WHERE ub.bet_id = ?",
                (bet_id,)) as cur:
            rows = await cur.fetchall()
            return [{"user_id": row[0], "amount": row[1], "predicted_winner": row[2],
                     "nickname": row[3] or row[4] or str(row[0])} for row in rows]


async def get_bet_participants(bet_id: int) -> List[int]:
    async with get_db() as conn:
        async with conn.execute("SELECT DISTINCT user_id FROM user_bets WHERE bet_id = ?", (bet_id,)) as cur:
            rows = await cur.fetchall()
            return [row[0] for row in rows]


async def delete_bet(bet_id: int):
    async with get_db() as conn:
        await conn.execute("DELETE FROM user_bets WHERE bet_id = ?", (bet_id,))
        await conn.execute("DELETE FROM bets_active WHERE id = ?", (bet_id,))
        await conn.commit()


async def get_team_avg_elo(game_id: int, team: str) -> float:
    async with get_db() as conn:
        async with conn.execute("SELECT game_date, game_number FROM game_history WHERE id = ?", (game_id,)) as cur:
            game = await cur.fetchone()
            if not game: return 1500
            game_date, game_number = game
        async with conn.execute(
                "SELECT COALESCE(e.elo, 1500) FROM game_slots_history s LEFT JOIN elo_ratings e ON s.user_id = e.user_id WHERE s.game_date = ? AND s.game_number = ? AND s.team = ?",
                (game_date, game_number, team)) as cur:
            rows = await cur.fetchall()
            elos = [row[0] for row in rows if row[0]]
            if not elos: return 1500
            return sum(elos) / len(elos)


# ========== 16. СУДЬИ И СИНХРОНИЗАЦИЯ ==========
async def get_judged_games_count(user_id: int) -> int:
    async with get_db() as conn:
        async with conn.execute("SELECT COUNT(*) FROM game_history WHERE judge_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def recalc_all_stats():
    async with get_db() as conn:
        print("[STATS] Начало глобального пересчета...")
        await conn.execute("UPDATE users SET games_played = 0, games_won = 0, points = 0")
        async with conn.execute(
                "SELECT user_id, COUNT(*) as games, SUM(CASE WHEN base_points >= 1 THEN 1 ELSE 0 END) as wins, SUM(base_points + bonus_points + lh_points + will_protocol_points + will_opinion_points + dc_points) as total_pts FROM game_slots_history WHERE user_id IS NOT NULL GROUP BY user_id") as cur:
            stats = await cur.fetchall()

        for user_id, games, wins, pts in stats:
            await conn.execute("UPDATE users SET games_played = ?, games_won = ?, points = ? WHERE user_id = ?",
                               (games, wins, pts, user_id))
            await conn.execute(
                "UPDATE elo_ratings SET games_played = ?, games_won = ?, updated_at = (SELECT MAX(game_date) FROM game_slots_history WHERE user_id = ?) WHERE user_id = ?",
                (games, wins, user_id, user_id))
        await conn.commit()
        print(f"[STATS] Пересчет завершен. Синхронизировано игроков: {len(stats)}")


async def refund_bets_for_game(game_id: int):
    async with get_db() as conn:
        # 1. Получаем все ставки на эту игру
        async with conn.execute("SELECT user_id, amount FROM bets WHERE game_id = ?", (game_id,)) as cur:
            bets = await cur.fetchall()

        for user_id, amount in bets:
            # 2. Возвращаем жетоны
            await conn.execute("UPDATE users SET tokens = tokens + ? WHERE user_id = ?", (amount, user_id))

        # 3. Удаляем записи о ставках
        await conn.execute("DELETE FROM bets WHERE game_id = ?", (game_id,))
        await conn.commit()

