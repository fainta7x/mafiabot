from aiogram import Router
from . import night

router = Router()
router.include_router(night.router)