from typing import Dict, Optional, List

import database

# =========================================================
# STATS_UTILS — ЛИЧНАЯ И ИГРОВАЯ СТАТИСТИКА
# =========================================================


# =========================================================
# 1. ЛИЧНАЯ СТАТИСТИКА ИГРОКА
# =========================================================

async def build_user_stats_data(user_id: int) -> dict:
    """
    Собирает данные для картинки профиля из БД.
    """
    # Профиль
    user_profile = await database.get_user_profile(user_id)
    if user_profile:
        full_name, nickname, debt, last_visit = user_profile
    else:
        full_name = None
        nickname = None

    # Игровые счётчики
    counters = await database.get_user_game_counters(user_id)
    if not counters or counters["games_played"] == 0:
        # Нет игр — возвращаем пустую статистику
        return {
            "nickname": nickname or full_name or f"Player {user_id}",
            "games_played": 0,
            "games_won": 0,
            "winrate": 0.0,
            "win_points_sum": 0,
            "avg_points": 0.0,
            "pr_avg": 0.0,
            "pr_minus_count": 0,
            "pr_minus_sum": 0.0,
            "pr_plus_count": 0,
            "pr_plus_sum": 0.0,
            "mn_avg": 0.0,
            "mn_minus_count": 0,
            "mn_minus_sum": 0.0,
            "mn_plus_count": 0,
            "mn_plus_sum": 0.0,
            "discipline_minus_sum": 0.0,
            "roles": {},
            # новые поля, чтобы не ломать картинку даже при нуле игр
            "pu_count": 0,
            "avg_lh": 0.0,
            "removed_count": 0,
            "techfouls_total": 0,
            "ppk_guilty_count": 0,
        }

    games_played = counters["games_played"]
    games_won = counters["games_won"]
    points = counters["points"]

    winrate = round(games_won / games_played * 100, 1) if games_played > 0 else 0.0
    avg_points = round(points / games_played, 2) if games_played > 0 else 0.0

    # Статистика по ролям
    roles_stats = await database.get_user_roles_stats(user_id)

    # Агрегация ПР/МН и дисциплинарных минусов
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

    # Дополнительные агрегаты по игроку (ПУ, ЛХ, удаления, техфолы, ППК)
    extra = await database.get_user_extra_stats(user_id)
    pu_count = extra.get("pu_count", 0)
    avg_lh = extra.get("avg_lh", 0.0)
    removed_count = extra.get("removed_count", 0)
    techfouls_total = extra.get("techfouls_total", 0)
    ppk_guilty_count = extra.get("ppk_guilty_count", 0)

    # Формат для ролей (картинка профиля)
    roles_for_pic = {}
    for r in roles_stats:
        role = r["role"]
        roles_for_pic[role] = {
            "games": r["games"],
            "wins": r["wins"],
            "winrate": r["winrate"],
            "avg_points": r["avg_points"],
            "bonus_sum": r.get("total_bonus", 0.0),
            "lh_sum": r.get("total_lh", 0.0),
        }

    return {
        "nickname": nickname or full_name or f"Player {user_id}",
        "games_played": games_played,
        "games_won": games_won,
        "winrate": winrate,
        "win_points_sum": points,
        "avg_points": avg_points,
        "pr_avg": pr_avg_all,
        "pr_minus_count": pr_neg_count_allа,
        "pr_minus_sum": pr_neg_sum_all,
        "pr_plus_count": pr_pos_count_all,
        "pr_plus_sum": pr_pos_sum_all,
        "mn_avg": mn_avg_all,
        "mn_minus_count": mn_neg_count_all,
        "mn_minus_sum": mn_neg_sum_all,
        "mn_plus_count": mn_pos_count_all,
        "mn_plus_sum": mn_pos_sum_all,
        "discipline_minus_sum": total_negative_all,
        "roles": roles_for_pic,
        # НОВЫЕ ПОЛЯ ДЛЯ КАРТИНКИ ПРОФИЛЯ
        "pu_count": pu_count,
        "avg_lh": avg_lh,
        "removed_count": removed_count,
        "techfouls_total": techfouls_total,
        "ppk_guilty_count": ppk_guilty_count,
    }


async def build_user_stats_text(user_id: int) -> str:
    """
    Собирает текст личной статистики игрока.
    """
    counters: Optional[Dict[str, int]] = await database.get_user_game_counters(user_id)
    roles_stats = await database.get_user_roles_stats(user_id)

    lines: List[str] = []

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
        lines.append(f"  Минусовой: {pr_neg_count_all} раз (сумма минусов {pr_neg_sum_all:.2f})")
        lines.append(f"  Плюсовой: {pr_pos_count_all} раз (сумма плюсов {pr_pos_sum_all:.2f})")
        lines.append("")
        lines.append(f"• Мнение (МН): ср. балл {mn_avg_all:.2f}")
        lines.append(f"  Минусовой: {mn_neg_count_all} раз (сумма минусов {mn_neg_sum_all:.2f})")
        lines.append(f"  Плюсовой: {mn_pos_count_all} раз (сумма плюсов {mn_pos_sum_all:.2f})")
        lines.append("")
        lines.append(f"• Минуса дисциплинарные (суммарно): {total_negative_all:.1f}")

    if roles_stats:
        lines.append("")
        lines.append(_format_roles_stats(roles_stats))
    else:
        lines.append("")
        lines.append("🎭 Пока нет данных по ролям — ещё не сохранено ни одной завершённой игры в историю слотов.")

    return "\n".join(lines)


def _aggregate_pr_mn_and_negative(roles_stats: List[Dict]) -> tuple:
    """
    Агрегируем ПР/МН и дисциплинарные минуса по всем ролям.
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

        # Дисциплинарные минуса
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
    """
    lines: List[str] = []
    lines.append("🎭 Статистика по ролям:\n")

    for r in roles_stats:
        role = r["role"]
        games = r["games"]
        wins = r["wins"]
        winrate = r["winrate"]
        avg_points = r["avg_points"]
        total_bonus = r.get("total_bonus", 0.0)
        total_lh = r.get("total_lh", 0.0)

        lines.append(
            f"{role}:\n"
            f"  • Игр: {games}\n"
            f"  • Побед: {wins} (винрейт {winrate}%)\n"
            f"  • Средний балл: {avg_points}"
        )
        lines.append(f"  • Допы (суммарно): {total_bonus:.1f}")

        if role in ("Мирный", "Шериф", "Не задана"):
            lines.append(f"  • ЛХ (суммарно): {total_lh:.1f}")

        lines.append("")

    return "\n".join(lines).strip()


# =========================================================
# 2. ИСТОРИЯ ИГР (ПО ВСЕМ / ПО ИГРОКУ)
# =========================================================

async def build_all_games_history_text(limit: int = 5) -> str:
    games = await database.get_last_games(limit=limit)
    if not games:
        return "📜 История игр пока пуста."

    lines: List[str] = ["📜 Последние игры:\n"]
    for g in games:
        gid = g["id"]
        date_str = g["game_date"] or "-"
        winner = g["winner_label"] or "Итог не указан"
        protocol_text = g["protocol_text"] or ""

        lines.append(f"Игра #{gid} — {date_str} — {winner}")
        lines.append(protocol_text)
        lines.append("")

    return "\n".join(lines).strip()


async def build_user_games_history_text(user_id: int, limit: int = 5) -> str:
    games = await database.get_user_games(user_id, limit=limit)
    if not games:
        return "📜 У тебя пока нет игр в истории (по данным протоколов)."

    lines: List[str] = ["📜 Твои игры:\n"]
    for g in games:
        gid = g["id"]
        date_str = g["game_date"] or "-"
        winner = g["winner_label"] or "Итог не указан"
        protocol_text = g["protocol_text"] or ""

        lines.append(f"Игра #{gid} — {date_str} — {winner}")
        lines.append(protocol_text)
        lines.append("")

    return "\n".join(lines).strip()