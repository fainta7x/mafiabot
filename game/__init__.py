# game/__init__.py

from aiogram import Router

from . import control
from . import day
from . import night
from .edit_router import router as edit_router

router = Router()

# СНАЧАЛА более специфичные роутеры (day/night),
# в КОНЦЕ — control с catch_all_in_game как fallback
router.include_router(day.router)
router.include_router(night.router)
router.include_router(control.router)
router.include_router(edit_router)

__all__ = ["router"]