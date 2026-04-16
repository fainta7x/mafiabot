from aiogram import Router, F, types

router = Router()

@router.message(F.web_app_data)
async def handle_webapp_data(message: types.Message):
    await message.answer("Я получил данные из WebApp (пока не разбираю).")