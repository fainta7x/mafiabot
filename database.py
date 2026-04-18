import aiosqlite
import json
from typing import Optional, Tuple, List, Dict

DB_NAME = "mafia_crm.db"


async def init_db():
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id    INTEGER PRIMARY KEY,
                username   TEXT,
                full_name  TEXT,
                nickname   TEXT DEFAULT 'Не установлен',
                balance    INTEGER DEFAULT 0,
                debt       INTEGER DEFAULT 0,
                last_visit TEXT DEFAULT '-',
                total_paid INTEGER DEFAULT 0,
                has_unpaid_session INTEGER DEFAULT 0,
                games_played INTEGER DEFAULT 0,
                games_won    INTEGER DEFAULT 0,
                points       INTEGER DEFAULT 0
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS evening_booking (
                user_id INTEGER PRIMARY KEY,
                status  TEXT,
                date    TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS evening_history (
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
            CREATE TABLE IF NOT EXISTS evening_stats_messages (
                date        TEXT PRIMARY KEY,
                chat_id     INTEGER,
                message_id  INTEGER
            )
        """)
        # Таблица статуса вечера: открыт/закрыт (счета разосланы)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS evening_status (
                date       TEXT PRIMARY KEY,
                bills_sent INTEGER DEFAULT 0
            )
        """)

        # Таблица общих настроек/флагов (в т.ч. для игры)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # История игровых слотов для статистики по ролям и очкам
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS game_slots_history (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                game_date             TEXT,
                user_id               INTEGER,
                slot_num              INTEGER,
                role                  TEXT,
                team                  TEXT,
                base_points           REAL DEFAULT 0,
                bonus_points          REAL DEFAULT 0,
                lh_points             REAL DEFAULT 0,
                will_protocol_points  REAL DEFAULT 0,
                will_opinion_points   REAL DEFAULT 0
            )
        """)

        # Таблица истории игр с протоколами + номера игр
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS game_history (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                game_date          TEXT,
                winner_label       TEXT,
                protocol_text      TEXT,
                game_number        INTEGER,   -- номер игры в этот вечер
                global_game_number INTEGER    -- глобальный номер игры
            )
        """)

        # --- Расширяем старую таблицу users (если поля ещё не были) ---
        try:
            await conn.execute(
                "ALTER TABLE users ADD COLUMN games_played INTEGER DEFAULT 0"
            )
        except Exception:
            pass

        try:
            await conn.execute(
                "ALTER TABLE users ADD COLUMN games_won INTEGER DEFAULT 0"
            )
        except Exception:
            pass

        try:
            await conn.execute(
                "ALTER TABLE users ADD COLUMN points INTEGER DEFAULT 0"
            )
        except Exception:
            pass

        # --- Расширяем старую game_history (если нет новых колонок) ---
        try:
            await conn.execute(
                "ALTER TABLE game_history ADD COLUMN game_number INTEGER"
            )
        except Exception:
            pass

        try:
            await conn.execute(
                "ALTER TABLE game_history ADD COLUMN global_game_number INTEGER"
            )
        except Exception:
            pass

        # --- Расширяем старую game_slots_history (если нет новых колонок ПР/МН) ---
        try:
            await conn.execute(
                "ALTER TABLE game_slots_history ADD COLUMN will_protocol_points REAL DEFAULT 0"
            )
        except Exception:
            pass

        try:
            await conn.execute(
                "ALTER TABLE game_slots_history ADD COLUMN will_opinion_points REAL DEFAULT 0"
            )
        except Exception:
            pass

        await conn.commit()


# ===== SETTINGS (общие флаги/JSON) =====

async def get_setting(key: str) -> Optional[str]:
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def set_setting(key: str, value: Optional[str]):
    async with aiosqlite.connect(DB_NAME) as conn:
        if value is None:
            await conn.execute(
                "DELETE FROM settings WHERE key = ?",
                (key,)
            )
        else:
            await conn.execute(
                """
                INSERT INTO settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value)
            )
        await conn.commit()


# Удобные обёртки для даты/номеров текущей игры (вечера)

async def set_current_game_date(date_str: str):
    await set_setting("current_game_date", date_str)


async def get_current_game_date() -> Optional[str]:
    return await get_setting("current_game_date")


async def set_current_game_number(num: int):
    await set_setting("current_game_number", str(num))


async def get_current_game_number() -> Optional[int]:
    val = await get_setting("current_game_number")
    if not val:
        return None
    try:
        return int(val)
    except ValueError:
        return None


async def set_current_global_game_number(num: int):
    await set_setting("current_game_global_number", str(num))


async def get_current_global_game_number() -> Optional[int]:
    val = await get_setting("current_game_global_number")
    if not val:
        return None
    try:
        return int(val)
    except ValueError:
        return None


# Сохранение/загрузка текущих игровых слотов как JSON

async def save_current_game_slots(slots: Dict[int, dict]):
    payload = json.dumps(slots, ensure_ascii=False)
    await set_setting("current_game_slots", payload)


async def load_current_game_slots() -> Optional[Dict[int, dict]]:
    """
    Загружаем слоты игры из settings.key='current_game_slots'.
    Возвращаем dict[int, dict] или None.
    """
    payload = await get_setting("current_game_slots")
    if not payload:
        return None
    raw = json.loads(payload)
    return {int(k): v for k, v in raw.items()}


# ===== Пользователи и профиль =====

async def add_or_update_user(user_id: int, username: Optional[str], full_name: str):
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute(
            """INSERT INTO users (user_id, username, full_name)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
               username = excluded.username,
               full_name = excluded.full_name""",
            (user_id, username, full_name)
        )
        await conn.commit()


async def get_user_profile(user_id: int) -> Optional[Tuple]:
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(
            "SELECT full_name, nickname, debt, last_visit FROM users WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            return await cursor.fetchone()


async def update_nickname(user_id: int, nickname: str):
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute(
            "UPDATE users SET nickname = ? WHERE user_id = ?",
            (nickname, user_id)
        )
        await conn.commit()


async def add_booking(user_id: int, status: str, date: str):
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO evening_booking (user_id, status, date) VALUES (?, ?, ?)",
            (user_id, status, date)
        )
        await conn.commit()


async def get_all_players() -> List[Tuple[int]]:
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute("SELECT user_id FROM evening_booking") as cursor:
            return await cursor.fetchall()


async def clear_bookings():
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("DELETE FROM evening_booking")
        await conn.commit()


async def get_booked_players_detailed() -> list:
    query = """
        SELECT 
            COALESCE(users.full_name, 'ID: ' || evening_booking.user_id) AS full_name,
            users.username,
            users.nickname,
            evening_booking.status
        FROM evening_booking
        LEFT JOIN users ON evening_booking.user_id = users.user_id
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(query) as cursor:
            return await cursor.fetchall()


async def get_booked_players_for_game() -> list:
    """
    Игроки, записанные на вечер и реально участвующие в игре:
    только со статусами 'Вовремя' и 'Позже'.

    Возвращаем: user_id, full_name, username, nickname, status.
    """
    query = """
    SELECT 
        e.user_id,
        IFNULL(u.full_name, 'Неизвестный') AS full_name,
        u.username,
        u.nickname,
        e.status
    FROM evening_booking e
    LEFT JOIN users u ON e.user_id = u.user_id
    WHERE e.status IN ('Вовремя', 'Позже')
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(query) as cursor:
            return await cursor.fetchall()


async def get_all_users_stat() -> list:
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(
            "SELECT full_name, nickname, last_visit, debt, total_paid FROM users"
        ) as cursor:
            return await cursor.fetchall()


async def get_user_brief(user_id: int) -> Optional[Tuple[str, str, str]]:
    """
    Короткая инфа по пользователю: full_name, nickname, username.
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(
            "SELECT full_name, nickname, username FROM users WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            return await cursor.fetchone()


# ==== Долг и оплаты ====

async def change_user_debt(user_id: int, delta: int):
    """Прибавить/убавить долг относительно текущего значения."""
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute(
            "UPDATE users SET debt = debt + ? WHERE user_id = ?",
            (delta, user_id)
        )
        await conn.commit()


async def set_user_debt(user_id: int, value: int):
    """Установить долг в конкретное значение."""
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute(
            "UPDATE users SET debt = ? WHERE user_id = ?",
            (value, user_id)
        )
        await conn.commit()


async def set_last_visit(user_id: int, date_str: str):
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute(
            "UPDATE users SET last_visit = ? WHERE user_id = ?",
            (date_str, user_id)
        )
        await conn.commit()


async def add_user_payment(user_id: int, amount: int):
    """Увеличить сумму всех оплат пользователя на amount."""
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute(
            "UPDATE users SET total_paid = COALESCE(total_paid, 0) + ? WHERE user_id = ?",
            (amount, user_id)
        )
        await conn.commit()


async def get_all_user_ids() -> list:
    """Все пользователи из таблицы users (для анонсов)."""
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute("SELECT user_id FROM users") as cursor:
            return await cursor.fetchall()


async def remove_booking(user_id: int):
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute(
            "DELETE FROM evening_booking WHERE user_id = ?",
            (user_id,)
        )
        await conn.commit()


async def has_booking(user_id: int) -> bool:
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(
            "SELECT 1 FROM evening_booking WHERE user_id = ? LIMIT 1",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row is not None


async def get_user_debt(user_id: int) -> int:
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(
            "SELECT debt FROM users WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return 0
            return row[0] or 0


# ==== История вечеров ====

async def archive_current_evening():
    """
    Перенести все текущие записи из evening_booking в evening_history и очистить список.
    amount ставим 0, реальные суммы проставим при подтверждении оплаты.
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        query = """
            SELECT e.date,
                   e.user_id,
                   e.status,
                   u.full_name,
                   u.nickname
            FROM evening_booking e
            LEFT JOIN users u ON e.user_id = u.user_id
        """
        async with conn.execute(query) as cursor:
            rows = await cursor.fetchall()

        if rows:
            rows_with_amount = [(*row, 0) for row in rows]
            await conn.executemany(
                """
                INSERT INTO evening_history (date, user_id, status, full_name, nickname, amount)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows_with_amount
            )

        await conn.execute("DELETE FROM evening_booking")
        await conn.commit()


async def get_evenings_list(limit: int = 10) -> list:
    """
    Последние вечера из history: дата + количество игроков.
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(
            """
            SELECT date, COUNT(*) as players_count
            FROM evening_history
            GROUP BY date
            ORDER BY date DESC
            LIMIT ?
            """,
            (limit,)
        ) as cursor:
            return await cursor.fetchall()


async def get_evening_players(date_str: str) -> list:
    """
    Игроки конкретного вечера по дате.
    Возвращаем: full_name, nickname, status, amount.
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(
            """
            SELECT full_name, nickname, status, amount
            FROM evening_history
            WHERE date = ?
            ORDER BY full_name
            """,
            (date_str,)
        ) as cursor:
            return await cursor.fetchall()


async def get_debtors() -> list:
    """
    Игроки с неоплаченным сыгранным вечером.
    Возвращаем: full_name, nickname, username, debt, user_id.
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(
            """
            SELECT full_name, nickname, username, debt, user_id
            FROM users
            WHERE has_unpaid_session = 1
            ORDER BY full_name
            """
        ) as cursor:
            return await cursor.fetchall()


async def set_unpaid_session(user_id: int, value: int):
    """
    value: 0 или 1 — есть ли у пользователя неоплаченный состоявшийся вечер.
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute(
            "UPDATE users SET has_unpaid_session = ? WHERE user_id = ?",
            (value, user_id)
        )
        await conn.commit()


async def has_unpaid_session(user_id: int) -> bool:
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(
            "SELECT has_unpaid_session FROM users WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return bool(row and row[0])


# ==== Статистика игроков ====

async def get_top_players_by_visits(limit: int = 10) -> list:
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(
            """
            SELECT u.full_name,
                   u.nickname,
                   COUNT(h.id) AS visits_count
            FROM evening_history h
            LEFT JOIN users u ON h.user_id = u.user_id
            GROUP BY h.user_id
            ORDER BY visits_count DESC
            LIMIT ?
            """,
            (limit,)
        ) as cursor:
            return await cursor.fetchall()


async def get_inactive_players(days: int = 30) -> list:
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(
            """
            SELECT full_name, nickname, last_visit
            FROM users
            ORDER BY last_visit
            """
        ) as cursor:
            return await cursor.fetchall()


async def set_last_evening_amount_for_user(user_id: int, amount: int):
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute(
            """
            UPDATE evening_history
            SET amount = ?
            WHERE id = (
                SELECT id
                FROM evening_history
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT 1
            )
            """
            , (amount, user_id)
        )
        await conn.commit()


# ==== Подсчёт записанных на вечер ====

async def count_ontime_players_for_date(date_str: str) -> int:
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(
            """
            SELECT COUNT(*)
            FROM evening_booking
            WHERE date = ? AND status = 'Вовремя'
            """,
            (date_str,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def count_all_attending_for_date(date_str: str) -> int:
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(
            """
            SELECT COUNT(*)
            FROM evening_booking
            WHERE date = ?
              AND status IN ('Вовремя', 'Позже')
            """,
            (date_str,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def get_players_by_status_for_date(date_str: str, status: str) -> list:
    query = """
        SELECT 
            COALESCE(u.nickname, u.full_name, 'Без имени') AS name
        FROM evening_booking e
        LEFT JOIN users u ON e.user_id = u.user_id
        WHERE e.date = ? AND e.status = ?
        ORDER BY name
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(query, (date_str, status)) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


async def get_all_bookings_for_date_ordered(date_str: str) -> list[tuple]:
    query = """
        SELECT 
            COALESCE(u.nickname, u.full_name, 'Без имени') AS name,
            e.status
        FROM evening_booking e
        LEFT JOIN users u ON e.user_id = u.user_id
        WHERE e.date = ?
        ORDER BY 
            CASE e.status
                WHEN 'Вовремя' THEN 1
                WHEN 'Позже'   THEN 2
                WHEN 'Не идёт' THEN 3
                ELSE 4
            END,
            name
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(query, (date_str,)) as cursor:
            return await cursor.fetchall()


async def set_stats_message(date_str: str, chat_id: int, message_id: int):
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute(
            """
            INSERT OR REPLACE INTO evening_stats_messages (date, chat_id, message_id)
            VALUES (?, ?, ?)
            """,
            (date_str, chat_id, message_id)
        )
        await conn.commit()


async def get_stats_message(date_str: str) -> Optional[Tuple[int, int]]:
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(
            """
            SELECT chat_id, message_id
            FROM evening_stats_messages
            WHERE date = ?
            """,
            (date_str,)
        ) as cursor:
            row = await cursor.fetchone()
            return row if row else None


# ==== Статус вечера (счета разосланы / запись закрыта) ====

async def mark_evening_bills_sent(date_str: str):
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute(
            """
            INSERT INTO evening_status (date, bills_sent)
            VALUES (?, 1)
            ON CONFLICT(date) DO UPDATE SET bills_sent = 1
            """,
            (date_str,)
        )
        await conn.commit()


async def is_evening_bills_sent(date_str: str) -> bool:
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(
            "SELECT bills_sent FROM evening_status WHERE date = ?",
            (date_str,)
        ) as cursor:
            row = await cursor.fetchone()
            return bool(row and row[0])


# ==== Результат игры: начисление очков игрокам ====

async def apply_game_result_to_users(slots: Dict[int, dict], winning_team: str) -> None:
    async with aiosqlite.connect(DB_NAME) as conn:
        for slot_data in slots.values():
            user_id = slot_data.get("user_id")
            team = slot_data.get("team")
            if not user_id or not team:
                continue

            await conn.execute(
                "UPDATE users SET games_played = COALESCE(games_played, 0) + 1 WHERE user_id = ?",
                (user_id,)
            )

            if team == winning_team:
                await conn.execute(
                    """
                    UPDATE users
                    SET games_won = COALESCE(games_won, 0) + 1,
                        points = COALESCE(points, 0) + 1
                    WHERE user_id = ?
                    """,
                    (user_id,)
                )

        await conn.commit()


# ==== Личная статистика по играм ====

async def get_user_game_counters(user_id: int) -> Optional[Dict[str, int]]:
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(
            """
            SELECT games_played, games_won, points
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            games_played, games_won, points = row
            return {
                "games_played": games_played or 0,
                "games_won": games_won or 0,
                "points": points or 0,
            }


# ==== История слотов для статистики по ролям ====

async def save_game_slots_history(game_date: str, slots):
    """
    Принимает либо dict[int, dict], либо list[dict].
    Внутри всегда работает как по (slot_num, slot_dict).
    """
    # Нормализуем в iterable[(slot_num, slot_dict)]
    if isinstance(slots, dict):
        iterable = list(slots.items())
    elif isinstance(slots, list):
        iterable = []
        for idx, slot in enumerate(slots, start=1):
            if not isinstance(slot, dict):
                continue
            slot_num = slot.get("slot_num", idx)
            iterable.append((slot_num, slot))
    else:
        return

    rows = []
    for slot_num, slot in iterable:
        if not isinstance(slot, dict):
            continue

        user_id = slot.get("user_id")
        role = slot.get("role")
        team = slot.get("team")
        base_points = float(slot.get("base_points", 0.0) or 0.0)
        bonus_points = float(slot.get("bonus_points", 0.0) or 0.0)
        lh_points = float(slot.get("lh_points", 0.0) or 0.0)
        will_protocol_points = float(slot.get("will_protocol_points", 0.0) or 0.0)
        will_opinion_points = float(slot.get("will_opinion_points", 0.0) or 0.0)

        rows.append(
            (
                game_date,
                user_id,
                slot_num,
                role,
                team,
                base_points,
                bonus_points,
                lh_points,
                will_protocol_points,
                will_opinion_points,
            )
        )

    if not rows:
        return

    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.executemany(
            """
            INSERT INTO game_slots_history (
                game_date,
                user_id,
                slot_num,
                role,
                team,
                base_points,
                bonus_points,
                lh_points,
                will_protocol_points,
                will_opinion_points
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        await conn.commit()


async def get_user_roles_stats(user_id: int) -> List[Dict]:
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(
            """
            SELECT
                role,
                COUNT(*) AS games,
                SUM(CASE WHEN base_points = 1 THEN 1 ELSE 0 END) AS wins,
                SUM(base_points + bonus_points + lh_points
                    + will_protocol_points + will_opinion_points) AS total_points,
                SUM(bonus_points) AS total_bonus,
                SUM(lh_points) AS total_lh,
                SUM(
                    CASE
                        WHEN (bonus_points + lh_points) < 0
                        THEN (bonus_points + lh_points)
                        ELSE 0
                    END
                ) AS total_negative,

                -- ПР: средний, плюсы/минусы
                AVG(will_protocol_points) AS protocol_avg,
                SUM(CASE WHEN will_protocol_points > 0 THEN 1 ELSE 0 END) AS protocol_pos_count,
                SUM(CASE WHEN will_protocol_points > 0 THEN will_protocol_points ELSE 0 END) AS protocol_pos_sum,
                SUM(CASE WHEN will_protocol_points < 0 THEN 1 ELSE 0 END) AS protocol_neg_count,
                SUM(CASE WHEN will_protocol_points < 0 THEN will_protocol_points ELSE 0 END) AS protocol_neg_sum,

                -- МН: средний, плюсы/минусы
                AVG(will_opinion_points) AS opinion_avg,
                SUM(CASE WHEN will_opinion_points > 0 THEN 1 ELSE 0 END) AS opinion_pos_count,
                SUM(CASE WHEN will_opinion_points > 0 THEN will_opinion_points ELSE 0 END) AS opinion_pos_sum,
                SUM(CASE WHEN will_opinion_points < 0 THEN 1 ELSE 0 END) AS opinion_neg_count,
                SUM(CASE WHEN will_opinion_points < 0 THEN will_opinion_points ELSE 0 END) AS opinion_neg_sum

            FROM game_slots_history
            WHERE user_id = ?
            GROUP BY role
            """,
            (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()

    result: List[Dict] = []
    for row in rows:
        (
            role,
            games,
            wins,
            total_points,
            total_bonus,
            total_lh,
            total_negative,
            protocol_avg,
            protocol_pos_count,
            protocol_pos_sum,
            protocol_neg_count,
            protocol_neg_sum,
            opinion_avg,
            opinion_pos_count,
            opinion_pos_sum,
            opinion_neg_count,
            opinion_neg_sum,
        ) = row

        games = games or 0
        wins = wins or 0
        total_points = total_points or 0.0
        total_bonus = total_bonus or 0.0
        total_lh = total_lh or 0.0
        total_negative = total_negative or 0.0

        protocol_avg = protocol_avg or 0.0
        protocol_pos_count = protocol_pos_count or 0
        protocol_pos_sum = protocol_pos_sum or 0.0
        protocol_neg_count = protocol_neg_count or 0
        protocol_neg_sum = protocol_neg_sum or 0.0

        opinion_avg = opinion_avg or 0.0
        opinion_pos_count = opinion_pos_count or 0
        opinion_pos_sum = opinion_pos_sum or 0.0
        opinion_neg_count = opinion_neg_count or 0
        opinion_neg_sum = opinion_neg_sum or 0.0

        if games > 0:
            winrate = round(wins / games * 100, 1)
            avg_points = round(total_points / games, 2)
        else:
            winrate = 0.0
            avg_points = 0.0

        result.append(
            {
                "role": role or "Не задана",
                "games": games,
                "wins": wins,
                "winrate": winrate,
                "avg_points": avg_points,
                "total_points": total_points,
                "total_bonus": total_bonus,
                "total_lh": total_lh,
                "total_negative": total_negative,
                "protocol_avg": round(protocol_avg, 2),
                "protocol_pos_count": protocol_pos_count,
                "protocol_pos_sum": round(protocol_pos_sum, 2),
                "protocol_neg_count": protocol_neg_count,
                "protocol_neg_sum": round(protocol_neg_sum, 2),
                "opinion_avg": round(opinion_avg, 2),
                "opinion_pos_count": opinion_pos_count,
                "opinion_pos_sum": round(opinion_pos_sum, 2),
                "opinion_neg_count": opinion_neg_count,
                "opinion_neg_sum": round(opinion_neg_sum, 2),
            }
        )

    return result


# ==== История игр и протоколов ====

async def save_game_history(
    game_date: str,
    winner_label: str,
    protocol_text: str,
    game_number: Optional[int] = None,
    global_game_number: Optional[int] = None,
) -> int:
    """
    Сохраняет итоговый протокол игры в историю game_history.
    Возвращает id вставленной игры.
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute(
            """
            INSERT INTO game_history (
                game_date, winner_label, protocol_text, game_number, global_game_number
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (game_date, winner_label, protocol_text, game_number, global_game_number)
        )
        await conn.commit()
        return cursor.lastrowid


async def get_total_games_count() -> int:
    """
    Общее количество игр в истории (для глобальной нумерации).
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute("SELECT COUNT(*) FROM game_history") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def get_games_by_date(game_date: str) -> List[Dict]:
    """
    Все игры за конкретную дату (вечер).
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(
            """
            SELECT id, game_date, winner_label, protocol_text, game_number, global_game_number
            FROM game_history
            WHERE game_date = ?
            ORDER BY id ASC
            """,
            (game_date,)
        ) as cursor:
            rows = await cursor.fetchall()

    result: List[Dict] = []
    for row in rows:
        gid, date_str, winner_label, protocol_text, game_number, global_number = row
        result.append(
            {
                "id": gid,
                "game_date": date_str,
                "winner_label": winner_label,
                "protocol_text": protocol_text,
                "game_number": game_number,
                "global_game_number": global_number,
            }
        )
    return result


async def get_last_games(limit: int = 10) -> List[Dict]:
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(
            """
            SELECT id, game_date, winner_label, protocol_text, game_number, global_game_number
            FROM game_history
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,)
        ) as cursor:
            rows = await cursor.fetchall()

    result: List[Dict] = []
    for row in rows:
        gid, date_str, winner_label, protocol_text, game_number, global_number = row
        result.append(
            {
                "id": gid,
                "game_date": date_str,
                "winner_label": winner_label,
                "protocol_text": protocol_text,
                "game_number": game_number,
                "global_game_number": global_number,
            }
        )
    return result


async def get_user_games(user_id: int, limit: int = 10) -> List[Dict]:
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(
            """
            SELECT DISTINCT game_date
            FROM game_slots_history
            WHERE user_id = ?
            ORDER BY game_date DESC
            LIMIT ?
            """,
            (user_id, limit)
        ) as cursor:
            date_rows = await cursor.fetchall()

        dates = [row[0] for row in date_rows if row[0] is not None]
        if not dates:
            return []

        placeholders = ",".join("?" for _ in dates)
        query = f"""
            SELECT id, game_date, winner_label, protocol_text, game_number, global_game_number
            FROM game_history
            WHERE game_date IN ({placeholders})
            ORDER BY id DESC
        """
        async with conn.execute(query, dates) as cursor:
            rows = await cursor.fetchall()

    result: List[Dict] = []
    for row in rows:
        gid, date_str, winner_label, protocol_text, game_number, global_number = row
        result.append(
            {
                "id": gid,
                "game_date": date_str,
                "winner_label": winner_label,
                "protocol_text": protocol_text,
                "game_number": game_number,
                "global_game_number": global_number,
            }
        )
    return result


async def get_game_by_id(game_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_NAME) as conn:
        async with conn.execute(
            """
            SELECT id, game_date, winner_label, protocol_text, game_number, global_game_number
            FROM game_history
            WHERE id = ?
            """,
            (game_id,)
        ) as cursor:
            row = await cursor.fetchone()

    if not row:
        return None

    gid, date_str, winner_label, protocol_text, game_number, global_number = row
    return {
        "id": gid,
        "game_date": date_str,
        "winner_label": winner_label,
        "protocol_text": protocol_text,
        "game_number": game_number,
        "global_game_number": global_number,
    }