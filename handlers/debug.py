# handlers/debug.py
from aiogram import Router
from aiogram.types import Message

router = Router()

@router.message()
async def debug_log(message: Message):
    print(
        "DEBUG:",
        "chat_id =", message.chat.id,
        "thread_id =", message.message_thread_id,
        "type =", message.chat.type,
        "text =", message.text,
    )