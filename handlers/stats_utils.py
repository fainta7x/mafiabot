from typing import Dict, Optional, List

import database

# =========================================================
# STATS_UTILS — ЛИЧНАЯ И ИГРОВАЯ СТАТИСТИКА
#
# ОГЛАВЛЕНИЕ:
# 1. ЛИЧНАЯ СТАТИСТИКА ИГРОКА
#    - build_user_stats_text              — общий текст по игроку
#    - build_user_stats_data              — данные для картинки профиля
#    - _aggregate_pr_mn_and_negative      — суммарные ПР/МН и минуса
#    - _format_roles_stats                — разрез по ролям
#
# 2. ИСТОРИЯ ИГР (ПО ВСЕМ / ПО ИГРОКУ)
#    - build_all_games_history_text       — последние игры (все)
#    - build_user_games_history_text      — игры конкретного игрока
# =========================================================


# =========================================================
# 1. ЛИЧНАЯ СТАТИСТИКА ИГРОКА
# =========================================================

async def build_user_stats_data(user_id: int) -> dict:
    """
    ВРЕМЕННАЯ заглушка, чтобы заработала картинка профиля.
    Потом заменим на реальный расчёт по БД.
    """
    # Пытаемся вытащить ник из профиля
    user_profile = await database.get_user_profile(user_id)
    # get_user_profile у тебя возвращает (name, nick, debt, visit)
    if user_profile:
        _, nick, _, _ = user_profile
    else:
        nick = None

    nickname = nick or f"Player {user_id}"
    nickname = f"{nickname} ({user_id})"

    return {
        "nickname": nickname,

        "games_played": 47,
        "games_won": 25,
        "winrate": 53.2,
        "win_points_sum": 25,
        "avg_points": 0.53,

        "pr_avg": -0.02,
        "pr_minus_count": 3,
        "pr_minus_sum": -1.30,
        "pr_plus_count": 1,
        "pr_plus_sum": 0.40,

        "mn_avg": 0.00,
        "mn_minus_count": 1,
        "mn_minus_sum": -0.20,
        "mn_plus_count": 1,
        "mn_plus_sum": 0.40,

        "discipline_minus_sum": 0.0,

        "roles": {
            "Дон": {
                "games": 11,
                "wins": 4,
                "winrate": 36.4,
                "avg_points": 0.41,
                "bonus_sum": 0.5,
                "lh_sum": 0.0,
            },
            "Мафия": {
                "games": 16,
                "wins": 9,
                "winrate": 56.2,
                "avg_points": 0.61,
                "bonus_sum": 0.4,
                "lh_sum": 0.0,
            },
            "Мирный": {
                "games": 7,
                "wins": 6,
                "winrate": 85.7,
                "avg_points": 1.09,
                "bonus_sum": 0.0,
                "lh_sum": 1.2,
            },
            "Не задана": {
                "games": 5,
                "wins": 0,
                "winrate": 0.0,
                "avg_points": 0.0,
                "bonus_sum": 0.0,
                "lh_sum": 0.0,
            },
            "Шериф": {
                "games": 7,
                "wins": 4,
                "winrate": 57.1,
                "avg_points": 0.97,
                "bonus_sum": 0.3,
                "lh_sum": 3.6,
            },
        },
    }


async def build_user_stats_text(user_id: int) -> str:
    """
    Собирает текст личной статистики игрока.

    Источники:
      - таблица users:
          * games_played, games_won, points
      - таблица game_slots_history:
          * агрегированные ПР/МН
          * дисциплинарные минуса (total_negative)
          * статистика по ролям

    Формат:
      📊 Твоя статистика по играм:
      • ...
      • ...
      <ПР/МН>
      <Минуса>
      🎭 Статистика по ролям:
      ...
    """
    counters: Optional[Dict[str, int]] = await database.get_user_game_counters(user_id)
    roles_stats = await database.get_user_roles_stats(user_id)

    lines: List[str] = []

    # === Общая статистика по играм (users) ===
    if not counters or counters["games_played"] == 0:
        lines.append("📊 У тебя пока нет сыгранных игр в общей статистике.")
        return "\n".join(lines)

    games_played = counters["games_played"]
    games_won = counters["games_won"]
    points = counters["points"]

    winrate = round(games_won / games_played * 100, 1) if games_played > 0 else 0.0
    avg_points = round(points / games_played, 2) if games_played > 0 else 0.0

    lines.append("📊 Твоя статистика по играм:\n")
    lines.append(f"• Сыграно игр: {games_played}")
    lines.append(f"• Выиграно: {games_won}")
    lines.append(f"• Винрейт: {winrate}%")
    lines.append("")
    lines.append(f"• Баллов за победы (суммарно): {points}")
    lines.append(f"• Средний балл за игру: {avg_points}")

    # === Агрегированные ПР/МН и дисциплинарные минуса по всем ролям ===
    if roles_stats:
        (
            pr_avg_all,
            pr_neg_count_all,
            pr_neg_sum_all,
            pr_pos_count_all,
            pr_pos_sum_all,
            mn_avg_all,
            mn_neg_count_all,
            mn_neg_sum_all,
            mn_pos_count_all,
            mn_pos_sum_all,
            total_negative_all,
        ) = _aggregate_pr_mn_and_negative(roles_stats)

        lines.append("")
        lines.append(f"• Протокол (ПР): ср. балл {pr_avg_all:.2f}")
        lines.append(
            f"  Минусовой: {pr_neg_count_all} раз (сумма минусов {pr_neg_sum_all:.2f})"
        )
        lines.append(
            f"  Плюсовой: {pr_pos_count_all} раз (сумма плюсов {pr_pos_sum_all:.2f})"
        )
        lines.append("")
        lines.append(f"• Мнение (МН): ср. балл {mn_avg_all:.2f}")
        lines.append(
            f"  Минусовой: {mn_neg_count_all} раз (сумма минусов {mn_neg_sum_all:.2f})"
        )
        lines.append(
            f"  Плюсовой: {mn_pos_count_all} раз (сумма плюсов {mn_pos_sum_all:.2f})"
        )
        lines.append("")
        lines.append(f"• Минуса дисциплинарные (суммарно): {total_negative_all:.1f}")

    # === Статистика по ролям ===
    if roles_stats:
        lines.append("")
        lines.append(_format_roles_stats(roles_stats))
    else:
        lines.append("")
        lines.append(
            "🎭 Пока нет данных по ролям — ещё не сохранено ни одной завершённой игры в историю слотов."
        )

    return "\n".join(lines)


def _aggregate_pr_mn_and_negative(roles_stats: List[Dict]) -> tuple:
    """
    Агрегируем ПР/МН и дисциплинарные минуса по всем ролям.

    На вход:
      roles_stats — список словарей по каждой роли (из get_user_roles_stats).

    Возвращаем кортеж:
      (
          pr_avg_all,              # средний ПР по всем играм
          pr_neg_count_all,        # сколько раз ПР был минусовым
          pr_neg_sum_all,          # суммарный минус по ПР
          pr_pos_count_all,        # сколько раз ПР был плюсовым
          pr_pos_sum_all,          # суммарный плюс по ПР
          mn_avg_all,              # средний МН по всем играм
          mn_neg_count_all,        # сколько раз МН был минусовым
          mn_neg_sum_all,          # суммарный минус по МН
          mn_pos_count_all,        # сколько раз МН был плюсовым
          mn_pos_sum_all,          # суммарный плюс по МН
          total_negative_all,      # дисциплинарные минуса (bonus+lh<0) по всем ролям
      )
    """
    total_pr_points = 0.0
    total_pr_events = 0

    pr_neg_count_all = 0
    pr_neg_sum_all = 0.0
    pr_pos_count_all = 0
    pr_pos_sum_all = 0.0

    total_mn_points = 0.0
    total_mn_events = 0

    mn_neg_count_all = 0
    mn_neg_sum_all = 0.0
    mn_pos_count_all = 0
    mn_pos_sum_all = 0.0

    total_negative_all = 0.0

    for r in roles_stats:
        games = r["games"]

        # ПР
        pr_avg = r.get("protocol_avg", 0.0)
        pr_neg_count = r.get("protocol_neg_count", 0)
        pr_neg_sum = r.get("protocol_neg_sum", 0.0)
        pr_pos_count = r.get("protocol_pos_count", 0)
        pr_pos_sum = r.get("protocol_pos_sum", 0.0)

        # Переводим средний ПР по роли в суммарный: avg * игр
        total_pr_points += pr_avg * games
        total_pr_events += games

        pr_neg_count_all += pr_neg_count
        pr_neg_sum_all += pr_neg_sum
        pr_pos_count_all += pr_pos_count
        pr_pos_sum_all += pr_pos_sum

        # МН
        mn_avg = r.get("opinion_avg", 0.0)
        mn_neg_count = r.get("opinion_neg_count", 0)
        mn_neg_sum = r.get("opinion_neg_sum", 0.0)
        mn_pos_count = r.get("opinion_pos_count", 0)
        mn_pos_sum = r.get("opinion_pos_sum", 0.0)

        total_mn_points += mn_avg * games
        total_mn_events += games

        mn_neg_count_all += mn_neg_count
        mn_neg_sum_all += mn_neg_sum
        mn_pos_count_all += mn_pos_count
        mn_pos_sum_all += mn_pos_sum

        # Дисциплинарные минуса (из поля total_negative)
        total_negative_all += r.get("total_negative", 0.0)

    pr_avg_all = round(total_pr_points / total_pr_events, 2) if total_pr_events > 0 else 0.0
    mn_avg_all = round(total_mn_points / total_mn_events, 2) if total_mn_events > 0 else 0.0

    return (
        pr_avg_all,
        pr_neg_count_all,
        pr_neg_sum_all,
        pr_pos_count_all,
        pr_pos_sum_all,
        mn_avg_all,
        mn_neg_count_all,
        mn_neg_sum_all,
        mn_pos_count_all,
        mn_pos_sum_all,
        total_negative_all,
    )


def _format_roles_stats(roles_stats: List[Dict]) -> str:
    """
    Форматирует статистику по ролям в многострочный текст.

    На вход:
      roles_stats — список словарей с ключами:
        role, games, wins, winrate, avg_points,
        total_bonus, total_lh, ...

    Вывод:
      🎭 Статистика по ролям:
      Роль:
        • Игр: ...
        • Побед: ...
        • Средний балл: ...
        • Допы (суммарно): ...
        • ЛХ (суммарно): ...   # только для красных / не задана
    """
    lines: List[str] = []
    lines.append("🎭 Статистика по ролям:\n")

    for r in roles_stats:
        role = r["role"]
        games = r["games"]
        wins = r["wins"]
        winrate = r["winrate"]
        avg_points = r["avg_points"]
        total_bonus = r["total_bonus"]
        total_lh = r["total_lh"]

        lines.append(
            f"{role}:\n"
            f"  • Игр: {games}\n"
            f"  • Побед: {wins} (винрейт {winrate}%)\n"
            f"  • Средний балл: {avg_points}"
        )

        # Допы показываем для всех ролей
        lines.append(f"  • Допы (суммарно): {total_bonus:.1f}")

        # ЛХ — только для красных ролей (мирный/шериф/не задана)
        if role in ("Мирный", "Шериф", "Не задана"):
            lines.append(f"  • ЛХ (суммарно): {total_lh:.1f}")

        lines.append("")  # пустая строка между ролями

    return "\n".join(lines).strip()


# =========================================================
# 2. ИСТОРИЯ ИГР (ПО ВСЕМ / ПО ИГРОКУ)
# =========================================================

async def build_all_games_history_text(limit: int = 5) -> str:
    """
    Строит текст для раздела «Все игры» — последние N игр с полным протоколом.

    Берём данные из game_history (get_last_games).
    """
    games = await database.get_last_games(limit=limit)
    if not games:
        return "📜 История игр пока пуста."

    lines: List[str] = []
    lines.append("📜 Последние игры:\n")

    for g in games:
        gid = g["id"]
        date_str = g["game_date"] or "-"
        winner = g["winner_label"] or "Итог не указан"
        protocol_text = g["protocol_text"] or ""

        lines.append(f"Игра #{gid} — {date_str} — {winner}")
        lines.append(protocol_text)
        lines.append("")  # пустая строка между играми

    return "\n".join(lines).strip()


async def build_user_games_history_text(user_id: int, limit: int = 5) -> str:
    """
    Строит текст «Игры этого игрока» — только те игры, где он участвовал.

    Берём данные из game_slots_history / game_history (get_user_games).
    """
    games = await database.get_user_games(user_id, limit=limit)
    if not games:
        return "📜 У тебя пока нет игр в истории (по данным протоколов)."

    lines: List[str] = []
    lines.append("📜 Твои игры:\n")

    for g in games:
        gid = g["id"]
        date_str = g["game_date"] or "-"
        winner = g["winner_label"] or "Итог не указан"
        protocol_text = g["protocol_text"] or ""

        lines.append(f"Игра #{gid} — {date_str} — {winner}")
        lines.append(protocol_text)
        lines.append("")

    return "\n".join(lines).strip()