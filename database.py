import aiosqlite
from typing import Optional, Tuple, List

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
                has_unpaid_session INTEGER DEFAULT 0
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
        await conn.commit()



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
        SELECT IFNULL(users.full_name, 'Неизвестный') AS full_name,
               users.username,
               users.nickname,
               evening_booking.status
        FROM evening_booking
        LEFT JOIN users ON evening_booking.user_id = users.user_id
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
            # добавляем amount = 0 для каждой записи
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
    """
    Топ игроков по количеству посещённых вечеров.
    Считаем по evening_history: сколько раз user_id встречается (по сути, сколько раз был в списке вечера).
    Возвращаем: full_name, nickname, visits_count.
    """
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
    """
    Игроки, которые давно не были.
    Возвращаем: full_name, nickname, last_visit.
    """
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
    """
    Проставить сумму amount в последнюю запись evening_history для этого пользователя.
    Используем ORDER BY id DESC, чтобы взять самый свежий вечер.
    """
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
            """,
            (amount, user_id)
        )
        await conn.commit()


# ==== Подсчёт записанных на вечер ====


async def count_ontime_players_for_date(date_str: str) -> int:
    """
    Сколько игроков со статусом 'Вовремя' на указанную дату.
    """
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
    """
    Сколько игроков со статусом 'Вовремя' или 'Позже' на указанную дату.
    """
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
    """
    Игроки на конкретную дату и со статусом.
    Возвращаем: nickname (если есть) или full_name.
    """
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
    """
    Вернёт (chat_id, message_id) или None.
    """
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