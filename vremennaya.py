import sqlite3

DB_NAME = "mafia_crm.db"


def fix_database():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Ищем строки, где в колонке 'date' лежит длинное число (ID),
    # а в 'user_id' лежит что-то похожее на дату (например, "15.05")
    # Мы меняем их местами
    cursor.execute("""
        UPDATE evening_history 
        SET date = user_id, user_id = date 
        WHERE length(date) > 8 AND (user_id LIKE '%.%')
    """)

    count = cursor.rowcount
    conn.commit()
    conn.close()

    print(f"✅ База очищена. Исправлено записей: {count}")


if __name__ == "__main__":
    fix_database()