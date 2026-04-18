# stats_utils.py
from typing import Dict, Optional, List
import database


async def build_user_stats_text(user_id: int) -> str:
    """
    Собирает текст личной статистики игрока:
    - общая по играм (users.games_played/games_won/points)
    - по ролям (из game_slots_history)
    """
    counters: Optional[Dict[str, int]] = await database.get_user_game_counters(user_id)

    lines: List[str] = []

    # === Общая статистика по играм ===
    if not counters or counters["games_played"] == 0:
        lines.append("📊 У тебя пока нет сыгранных игр в общей статистике (users).")
    else:
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

    # === Статистика по ролям ===
    roles_stats = await database.get_user_roles_stats(user_id)

    if roles_stats:
        if lines:
            lines.append("")  # пустая строка между блоками
        lines.append(_format_roles_stats(roles_stats))
    else:
        if lines:
            lines.append("")
        lines.append(
            "🎭 Пока нет данных по ролям — ещё не сохранено ни одной завершённой игры в историю слотов."
        )

    return "\n".join(lines)


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
        total_negative = r["total_negative"]

        lines.append(
            f"{role}:\n"
            f"  • Игр: {games}\n"
            f"  • Побед: {wins} (винрейт {winrate}%)\n"
            f"  • Средний балл: {avg_points}"
        )

        # Допы показываем для всех ролей
        lines.append(f"  • Допы (суммарно): {total_bonus:+.1f}")

        # ЛХ — только для красных ролей (мирный/шериф/не задана)
        if role in ("Мирный", "Шериф", "Не задана"):
            lines.append(f"  • ЛХ (суммарно): {total_lh:+.1f}")

        # Минусы — просто суммарные отрицательные очки
        lines.append(f"  • Минуса: {total_negative:.1f}\n")

    return "\n".join(lines)


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