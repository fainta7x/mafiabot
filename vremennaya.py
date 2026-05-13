import sqlite3


def confirm_games(user_id):
    conn = sqlite3.connect('mafia_crm.db')
    cursor = conn.cursor()

    print(f"🛠️ Начинаю подтверждение всех игр для ID {user_id}...")

    try:
        # Устанавливаем флаг подтверждения для всех игр этого игрока
        cursor.execute("""
                       UPDATE game_slots_history
                       SET updated_by_editor = 1
                       WHERE user_id = ?
                       """, (user_id,))

        updated_count = cursor.rowcount
        print(f"✅ В таблице game_slots_history подтверждено игр: {updated_count}")

        # На всякий случай обновим общее количество игр в elo_ratings,
        # чтобы боту не пришлось считать их заново
        cursor.execute("UPDATE elo_ratings SET games_played = 9 WHERE user_id = ?", (user_id,))

        conn.commit()
        print("\n🚀 Статус 'Подтверждено' установлен для всех 9 игр.")

    except Exception as e:
        conn.rollback()
        print(f"💥 Ошибка: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    confirm_games(5161632361)