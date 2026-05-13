import sqlite3

def repair_data():
    conn = sqlite3.connect('mafia_crm.db')
    cursor = conn.cursor()
    # Меняем местами значения в колонках date и user_id для всех записей с ID 23 и выше
    cursor.execute("""
        UPDATE evening_history 
        SET date = user_id, user_id = date 
        WHERE id >= 23
    """)
    conn.commit()
    print(f"✅ База данных исправлена! Затронуто строк: {cursor.rowcount}")
    conn.close()

if __name__ == "__main__":
    repair_data()