# game/__init__.py
from aiogram import Router

from . import control
from . import day
from . import night

router = Router()

# СНАЧАЛА более специфичные роутеры (day/night),
# в КОНЦЕ — control с catch_all_in_game как fallback
router.include_router(day.router)
router.include_router(night.router)
router.include_router(control.router)

__all__ = ["router"]