# game/__init__.py

from aiogram import Router

from . import control
from . import day
from . import night
from .edit_router import router as edit_router

router = Router()

# СНАЧАЛА более специфичные роутеры
router.include_router(edit_router)      # ← ПЕРВЫМ! Режим редактирования
router.include_router(day.router)       # дневные хендлеры
router.include_router(night.router)     # ночные хендлеры
router.include_router(control.router)   # ← ПОСЛЕДНИМ! catch-all как fallback

__all__ = ["router"]