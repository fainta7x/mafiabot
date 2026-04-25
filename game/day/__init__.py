from aiogram import Router
from . import day

router = Router()
router.include_router(day.router)