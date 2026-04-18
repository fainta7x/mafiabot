from aiogram.fsm.state import StatesGroup, State


class GameCreateState(StatesGroup):
    editing_slots = State()
    waiting_fouls = State()
    waiting_nominees = State()
    waiting_votes = State()
    choosing_mafia = State()
    choosing_don = State()
    choosing_sheriff = State()
    waiting_kill_slot = State()          # номер убитого ночью
    waiting_night_suspects = State()     # подозреваемые от первой жертвы

    # Новое: ждём номер слота для очистки
    waiting_clear_slot_number = State()