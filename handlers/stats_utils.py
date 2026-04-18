from typing import Dict, Optional, List
import database


async def build_user_stats_text(user_id: int) -> str:
    """
    Собирает текст личной статистики игрока:
    - общая по играм (users.games_played/games_won/points)
    - агрегированные ПР/МН и дисциплинарные минуса по всем играм
    - по ролям (из game_slots_history)
    """
    counters: Optional[Dict[str, int]] = await database.get_user_game_counters(user_id)
    roles_stats = await database.get_user_roles_stats(user_id)

    lines: List[str] = []

    # === Общая статистика по играм ===
    if not counters or counters["games_played"] == 0:
        lines.append("📊 У тебя пока нет сыгранных игр в общей статистике (users).")
        return "\n".join(lines)

    gp = counters["games_played"]
    gw = counters["games_won"]
    pts = counters["points"]

    winrate = round(gw / gp * 100, 1) if gp > 0 else 0.0
    avg_points = round(pts / gp, 2) if gp > 0 else 0.0

    lines.append("📊 Твоя статистика по играм:\n")
    lines.append(f"• Сыграно игр: {gp}")
    lines.append(f"• Выиграно: {gw}")
    lines.append(f"• Винрейт: {winrate}%")
    lines.append("")
    lines.append(f"• Баллов за победы (суммарно): {pts}")
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
        lines.append(f"• Минуса дисциплинарные: {total_negative_all:.1f}")

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
    Возвращаем кортеж:
    (
        pr_avg_all,
        pr_neg_count_all, pr_neg_sum_all,
        pr_pos_count_all, pr_pos_sum_all,
        mn_avg_all,
        mn_neg_count_all, mn_neg_sum_all,
        mn_pos_count_all, mn_pos_sum_all,
        total_negative_all,
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

        # Переводим средний ПР по роли в сумму: avg * игр
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

        # Допы показываем для всех ролей, без плюса перед числом
        lines.append(f"  • Допы (суммарно): {total_bonus:.1f}")

        # ЛХ — только для красных ролей (мирный/шериф/не задана)
        if role in ("Мирный", "Шериф", "Не задана"):
            lines.append(f"  • ЛХ (суммарно): {total_lh:.1f}")

        lines.append("")  # пустая строка между ролями

    return "\n".join(lines).strip()


# ===== История игр (все / игры пользователя) =====

async def build_all_games_history_text(limit: int = 5) -> str:
    """
    Текст для раздела 'Все игры' — последние N игр с полным протоколом.
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
    Текст для раздела 'Игры этого игрока' — только те игры, где он участвовал.
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