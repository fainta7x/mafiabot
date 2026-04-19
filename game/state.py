from aiogram.fsm.state import State, StatesGroup


class GameCreateState(StatesGroup):
    editing_slots = State()
    waiting_kill_slot = State()
    waiting_night_suspects = State()
    waiting_will_protocol = State()
    waiting_will_opinion = State()
    waiting_clear_slot_number = State()
    waiting_fouls = State()
    waiting_nominees = State()
    waiting_votes = State()
    choosing_mafia = State()
    choosing_don = State()
    choosing_sheriff = State()

    # Новые состояния для режима редактирования
    edit_mode_select_slot = State()  # выбор слота для редактирования
    edit_mode_menu = State()  # меню редактирования слота
    edit_mode_lh = State()  # ввод ЛХ
    edit_mode_protocol = State()  # ввод ПР
    edit_mode_opinion = State()  # ввод МН
    edit_mode_role = State()  # выбор роли