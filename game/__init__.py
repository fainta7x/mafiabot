# game/__init__.py

from aiogram import Router

from . import admin_actions
from . import day
from . import night
from . import edit_router

router = Router()
router.include_router(admin_actions.router)
router.include_router(day.router)
router.include_router(night.router)
router.include_router(edit_router.router)