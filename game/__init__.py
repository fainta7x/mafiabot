# game/__init__.py
from aiogram import Router

from . import slots, fouls_votes, night_roles

router = Router()
router.include_router(fouls_votes.router)
router.include_router(night_roles.router)
router.include_router(slots.router)

__all__ = ["router"]