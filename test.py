# test_connection.py
import asyncio
import asyncpg
import socket

# Принудительно используем IPv4
socket.setdefaulttimeout(10)

DATABASE_URL = "postgresql://postgres:Test1TestMafia@db.udhsmhlhzdkzsrwrhalp.supabase.co:5432/postgres?sslmode=require"

async def test():
    try:
        # Получаем IPv4 адрес
        ip = socket.gethostbyname("db.udhsmhlhzdkzsrwrhalp.supabase.co")
        print(f"IPv4 адрес: {ip}")
        
        # Подключаемся по IP
        conn = await asyncpg.connect(
            host=ip,
            port=5432,
            user="postgres",
            password="Test1TestMafia",
            database="postgres",
            ssl="require"
        )
        print("✅ Подключение успешно!")
        await conn.close()
    except Exception as e:
        print(f"❌ Ошибка: {e}")

asyncio.run(test())