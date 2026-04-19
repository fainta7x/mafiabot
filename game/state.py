from aiogram.fsm.state import State, StatesGroup


class GameCreateState(StatesGroup):
    # ========== ОСНОВНЫЕ СОСТОЯНИЯ ИГРЫ ==========
    editing_slots = State()  # основное состояние игры
    waiting_kill_slot = State()  # ожидание номера убитого
    waiting_night_suspects = State()  # ожидание подозреваемых (ЛХ)
    waiting_will_protocol = State()  # ожидание текста протокола
    waiting_will_opinion = State()  # ожидание текста мнения
    waiting_clear_slot_number = State()  # ожидание номера слота для очистки
    waiting_fouls = State()  # ожидание номеров для фолов
    waiting_nominees = State()  # ожидание выставленных игроков
    waiting_votes = State()  # ожидание голосов

    # ========== РАЗДАЧА РОЛЕЙ ==========
    choosing_mafia = State()  # выбор двух мафий
    choosing_don = State()  # выбор дона
    choosing_sheriff = State()  # выбор шерифа

    # ========== НОВЫЕ СОСТОЯНИЯ ДЛЯ СОЗДАНИЯ ИГРЫ ==========
    editing_players_list = State()  # ручное редактирование списка игроков

    # ========== РЕЖИМ РЕДАКТИРОВАНИЯ ==========
    edit_mode_select_slot = State()  # выбор слота для редактирования
    edit_mode_menu = State()  # главное меню редактирования слота

    # Подрежимы редактирования
    edit_mode_role = State()  # выбор роли (через кнопки)
    edit_mode_status = State()  # выбор статуса (через кнопки)
    edit_mode_pu = State()  # подтверждение назначения ПУ
    edit_mode_lh = State()  # ввод номеров подозреваемых (ЛХ)
    edit_mode_protocol = State()  # ввод текста протокола (ПР)
    edit_mode_opinion = State()  # ввод текста мнения (МН)
    edit_mode_points = State()  # ввод очков за игру
    edit_mode_confirm_clear = State()  # подтверждение очистки слота

    # ========== НОВЫЕ РЕЖИМЫ ДЛЯ УДОБНОГО УПРАВЛЕНИЯ ==========

    # Режим управления убийствами
    kill_mode_select = State()  # выбор слота для убийства
    kill_mode_confirm = State()  # подтверждение убийства

    # Режим управления фолами
    foul_mode_select = State()  # выбор слота для фола
    foul_mode_value = State()  # +1 или -1
    foul_select = State()  # выбор игрока для фола
    foul_action = State()  # выбор действия (+1/-1)

    # Режим управления голосованием
    vote_mode_start = State()  # начало голосования
    vote_mode_collect = State()  # сбор голосов по номинациям

    # Режим управления ПУ (первый убитый)
    pu_mode_select = State()  # выбор ПУ
    pu_mode_suspects = State()  # ввод подозреваемых для ПУ

    # Режим управления номинацией (выставлением)
    nominate_mode_select = State()  # выбор выставляемых игроков

    # ========== НОВЫЕ СОСТОЯНИЯ ДЛЯ РЕДАКТОРА БАЛЛОВ ПОСЛЕ ИГРЫ ==========
    score_editor_select_player = State()  # выбор игрока для редактирования баллов
    score_editor_select_type = State()  # выбор типа баллов (Доп/ПР/МН)
    score_editor_select_value = State()  # выбор значения (+0.1, -0.5 и т.д.)

    # ========== НОВЫЕ СОСТОЯНИЯ ДЛЯ ВЫСТАВЛЕНИЯ ==========
    nominate_select = State()  # выбор игроков для выставления
    nominate_confirm = State()  # подтверждение выбора

    # ========== НОВЫЕ СОСТОЯНИЯ ДЛЯ ГОЛОСОВАНИЯ ==========
    vote_collect = State()  # сбор голосов по кандидатам
    vote_remaining = State()  # подсчёт оставшихся голосов

    # ========== НОВЫЕ СОСТОЯНИЯ ДЛЯ УБИЙСТВА ==========
    kill_select = State()  # выбор игрока для убийства
    kill_lh = State()  # ввод ЛХ (подозреваемых) для убитого
    kill_protocol = State()  # ввод текста протокола
    kill_opinion = State()  # ввод текста мнения