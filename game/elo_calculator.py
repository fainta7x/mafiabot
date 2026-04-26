"""
Модуль для расчёта Эло в реальном времени при сохранении игры
"""

import math
from typing import List, Dict, Any

# Константы
STARTING_ELO = 1500
K_FACTOR = 32
BONUS_TO_ELO_RATIO = 10  # 0.1 доп. балла = 1 очко Эло
MIN_TEAM_SIZE_FOR_CARRY = 2


def expected_score(player_elo: float, opponent_elo: float) -> float:
    """Ожидаемый результат по формуле Эло"""
    return 1 / (1 + 10 ** ((opponent_elo - player_elo) / 400))


def get_role_coefficient(team: str, is_win: bool) -> float:
    """Ролевой коэффициент"""
    if is_win:
        return 1.2 if team == "Красные" else 0.9
    else:
        return 0.9 if team == "Красные" else 1.1


def calculate_carry_modifier(player_elo: float, team_elos: List[float], is_win: bool) -> float:
    """Carry-модификатор"""
    if len(team_elos) < MIN_TEAM_SIZE_FOR_CARRY:
        return 1.0

    team_avg = sum(team_elos) / len(team_elos)
    diff = player_elo - team_avg
    normalized = min(1.0, max(-1.0, diff / 200))

    if is_win:
        if diff > 0:
            bonus = normalized * 0.3
            return 1 + bonus
        else:
            penalty = abs(normalized) * 0.2
            return 1 - penalty
    else:
        if diff > 0:
            penalty = normalized * 0.4
            return 1 - penalty
        else:
            relief = abs(normalized) * 0.2
            return 1 + relief


def calculate_bonus_elo_impact(slot: dict) -> float:
    """Рассчитывает влияние доп. баллов на Эло"""
    total_bonus = (
            slot.get("bonus_points", 0) +
            slot.get("lh_points", 0) +
            slot.get("will_protocol_points", 0) +
            slot.get("will_opinion_points", 0) +
            slot.get("dc_points", 0)
    )
    return total_bonus * BONUS_TO_ELO_RATIO


async def calculate_elo_for_game(slots: dict, winning_team: str, get_elo_func) -> Dict[int, Dict[str, int]]:
    """
    Рассчитывает новое Эло для всех игроков в игре

    Параметры:
    - slots: словарь слотов игры
    - winning_team: "Красные" или "Чёрные"
    - get_elo_func: асинхронная функция для получения текущего Эло по user_id

    Возвращает:
    - словарь {slot_num: {"old_elo": int, "new_elo": int, "delta": int, "bonus_delta": int}}
    """

    # Собираем игроков с их текущим Эло
    players = []
    for slot_num, slot in slots.items():
        if slot.get("user_id") and slot.get("user_id") > 0:
            user_id = slot["user_id"]
            current_elo = await get_elo_func(user_id)
            players.append({
                "slot_num": slot_num,
                "user_id": user_id,
                "team": slot.get("team"),
                "current_elo": current_elo,
                "bonus_points": slot.get("bonus_points", 0),
                "lh_points": slot.get("lh_points", 0),
                "will_protocol_points": slot.get("will_protocol_points", 0),
                "will_opinion_points": slot.get("will_opinion_points", 0),
                "dc_points": slot.get("dc_points", 0),
            })

    if len(players) < 4:
        return {}

    # Разделяем по командам
    red_players = [p for p in players if p["team"] == "Красные"]
    black_players = [p for p in players if p["team"] == "Чёрные"]

    if not red_players or not black_players:
        return {}

    red_elos = [p["current_elo"] for p in red_players]
    black_elos = [p["current_elo"] for p in black_players]

    result = {}

    for player in players:
        is_win = (player["team"] == winning_team)
        old_elo = player["current_elo"]

        # Соперники
        opponent_elos = black_elos if player["team"] == "Красные" else red_elos
        opponent_avg = sum(opponent_elos) / len(opponent_elos)

        # Ожидаемый результат
        expected = expected_score(old_elo, opponent_avg)
        actual = 1.0 if is_win else 0.0

        # Базовая дельта
        raw_delta = K_FACTOR * (actual - expected)

        # Модификаторы
        role_mod = get_role_coefficient(player["team"], is_win)
        team_elos = red_elos if player["team"] == "Красные" else black_elos
        carry_mod = calculate_carry_modifier(old_elo, team_elos, is_win)

        # Игровая дельта
        game_delta = int(round(raw_delta * role_mod * carry_mod))

        # Бонусная дельта (доп. баллы)
        bonus_impact = calculate_bonus_elo_impact(player)
        bonus_delta = int(round(bonus_impact))

        # Общая дельта
        total_delta = game_delta + bonus_delta
        new_elo = old_elo + total_delta

        result[player["slot_num"]] = {
            "old_elo": old_elo,
            "new_elo": new_elo,
            "game_delta": game_delta,
            "bonus_delta": bonus_delta,
            "total_delta": total_delta
        }

    return result