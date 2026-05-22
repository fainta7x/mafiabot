from aiogram import Router
from . import create_game, fouls, score_editor, ppk, finish

router = Router()
router.include_router(create_game.router)
router.include_router(fouls.router)
router.include_router(score_editor.router)
router.include_router(ppk.router)
router.include_router(finish.router)