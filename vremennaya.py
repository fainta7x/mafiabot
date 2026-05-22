import sqlite3
from datetime import datetime

DB_NAME = "mafia_crm.db"


def normalize_dates():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Берем все уникальные даты, которые есть в истории
    cursor.execute("SELECT DISTINCT date FROM evening_history")
    dates = cursor.fetchall()

    count_fixed = 0

    for (date_val,) in dates:
        new_date = None
        date_str = str(date_val).strip()

        # 1. Если уже в формате YYYY-MM-DD (например, 2026-05-08)
        if len(date_str) == 10 and "-" in date_str:
            continue

            # 2. Если формат DD.MM (например, 15.05) -> добавляем 2026
        elif len(date_str) == 5 and "." in date_str:
            new_date = datetime.strptime(f"{date_str}.2026", "%d.%m.%Y").strftime("%Y-%m-%d")

        # 3. Если формат DD.MM.YYYY (например, 15.05.2026)
        elif len(date_str) == 10 and "." in date_str:
            new_date = datetime.strptime(date_str, "%d.%m.%Y").strftime("%Y-%m-%d")

        if new_date:
            cursor.execute("UPDATE evening_history SET date = ? WHERE date = ?", (new_date, date_str))
            count_fixed += cursor.rowcount
            print(f"Исправлено: {date_str} -> {new_date}")

    conn.commit()
    conn.close()
    print(f"\n✅ Готово! Всего исправлено записей: {count_fixed}")


if __name__ == "__main__":
    normalize_dates()