from typing import Dict, List, Tuple

import database  # нужен для получения имени судьи в протоколе


# =========================================================
# UTILS — ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ ОТОБРАЖЕНИЯ ИГРЫ
#
# ОГЛАВЛЕНИЕ:
# 1. ОБЩИЕ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ ИМЁН И СПИСКОВ СЛОТОВ
#    - _format_player_name
#    - _trim_name
#    - _parse_slots_list
#
# 2. ТЕКСТОВЫЕ ПРЕДСТАВЛЕНИЯ:
#    - build_slots_text      — черновик новой игры (слоты и ники)
#    - build_roles_summary   — роли и команды по слотам
#    - build_game_state      — текущее состояние игры
#    - build_votes_summary   — результаты голосования
#    - build_protocol_text   — тело протокола игры (HTML)
# =========================================================


# =========================================================
# 1. ОБЩИЕ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =========================================================

def _format_player_name(full_name: str | None, nickname: str | None) -> str:
    """
    Выбираем "правильное" имя игрока для отображения:
      - если есть ник и он не пустой/«Не установлен» -> берём ник;
      - иначе, если есть full_name и он не пустой/«Неизвестный» -> берём его;
      - иначе -> "Без имени".
    """
    if nickname and nickname not in ("", "Не установлен"):
        return nickname
    if full_name and full_name not in ("", "Неизвестный"):
        return full_name
    return "Без имени"


def _trim_name(name: str | None, max_len: int = 18) -> str:
    """
    Обрезает слишком длинные ники, чтобы строки протокола не разваливались.
    Если имени нет — возвращает "Без имени".
    """
    if not name:
        return "Без имени"
    name = name.strip()
    if len(name) <= max_len:
        return name
    return name[: max_len - 1] + "…"


def _parse_slots_list(text: str) -> list[int]:
    """
    Парсит строку с номерами слотов в список int без повторов.

    Примеры:
      "1 2 3"     -> [1, 2, 3]
      "1,2, 3"    -> [1, 2, 3]
      "1 1 2"     -> [1, 2]
      "a 3 b 4"   -> [3, 4]
    """
    cleaned = text.replace(",", " ")
    parts = cleaned.split()
    result: list[int] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        try:
            num = int(p)
        except ValueError:
            continue
        if num not in result:
            result.append(num)
    return result


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ БЕЗОПАСНОЙ РАБОТЫ ==========
def _safe_get_tech_fouls_count(info: dict) -> int:
    """
    Безопасно получает количество техфолов.
    technical_fouls может быть:
      - списком (старый формат) -> возвращаем len()
      - числом (новый формат) -> возвращаем число
      - None -> возвращаем 0
    """
    tf = info.get("technical_fouls")
    if tf is None:
        return 0
    if isinstance(tf, list):
        return len(tf)
    if isinstance(tf, int):
        return tf
    return 0


def _safe_get_tech_fouls_display(info: dict) -> str:
    """
    Возвращает строковое представление техфолов для отображения.
    """
    tf = info.get("technical_fouls")
    if tf is None:
        return ""
    if isinstance(tf, list):
        small_count = sum(1 for t in tf if t == "small")
        big_count = sum(1 for t in tf if t == "big")
        parts = []
        if small_count:
            parts.append(f"{small_count}S")
        if big_count:
            parts.append(f"{big_count}B")
        return " / ".join(parts) if parts else ""
    if isinstance(tf, int):
        return str(tf) if tf > 0 else ""
    return ""


def _get_elo_display(info: dict) -> str:
    """
    Возвращает строку с изменением Эло для отображения в протоколе.
    Формат: (+13) или (-17) с использованием tg-spoiler для цвета.
    """
    elo_change = info.get("elo_change")
    if elo_change is None:
        return ""

    if elo_change > 0:
        return f" <tg-spoiler>(+{elo_change})</tg-spoiler>"
    elif elo_change < 0:
        return f" <tg-spoiler>({elo_change})</tg-spoiler>"
    else:
        return " <tg-spoiler>(0)</tg-spoiler>"


# =========================================================


# =========================================================
# 2. ТЕКСТОВЫЕ ПРЕДСТАВЛЕНИЯ
# =========================================================

def build_slots_text(
        slots: Dict[int, dict],
        judge_name: str | None = None,
) -> str:
    """
    Черновик новой игры:
      - показывает список слотов и имена игроков;
      - даёт подсказку, как переименовать или добавить слот;
      - ДОБАВЛЕНО: выводит Судью, если передан judge_name.
    """
    sorted_slots = dict(sorted(slots.items(), key=lambda x: x[0]))

    lines: list[str] = []

    # Шапка с Судьёй
    if judge_name:
        lines.append(f"🎲 Черновик новой игры.\nСудья: <b>{judge_name}</b>\n")
    else:
        lines.append("🎲 Черновик новой игры.\n")

    lines.append("Текущие слоты игроков:\n")
    for slot, info in sorted_slots.items():
        name_part = _format_player_name(info.get("full_name"), info.get("nickname"))
        lines.append(f"{slot}. {name_part}")

    lines.append(
        "\nЧтобы поменять или задать ник в слоте, напиши в чат:\n"
        "номер_слота пробел новый_ник\n"
        "Например: 3 Волк\n\n"
        "Можно добавлять новые слоты до 10 игрока.\n"
        "Когда всё будет готово — нажми «Ок» или отправь текстом «Ок»."
    )
    return "\n".join(lines)


def build_roles_summary(slots: Dict[int, dict]) -> str:
    """
    Краткая сводка ролей и команд по слотам.
    """
    sorted_slots = dict(sorted(slots.items(), key=lambda x: x[0]))

    lines = ["🎭 Роли и команды по слотам:\n"]
    for slot, info in sorted_slots.items():
        name = _format_player_name(info.get("full_name"), info.get("nickname"))
        role = info.get("role", "Не задана")
        team = info.get("team", "—")
        lines.append(f"{slot}. {name} — {role} ({team})")

    return "\n".join(lines)


def build_game_state(
        slots: Dict[int, dict],
        alive_only: bool = False,
        judge_name: str | None = None,
) -> str:
    """
    Отображение текущего состояния игры:
      - слот, имя, роль (СКАРЫТА ПОД СПОЙЛЕРОМ);
      - фолы;
      - статус (жив / причина вылета);
      - отметка «ВЫСТАВЛЕН»;
      - количество голосов.
    Если alive_only=True — показываются только живые игроки.
    """
    sorted_slots = dict(sorted(slots.items(), key=lambda x: x[0]))

    if alive_only:
        header = "📋 ЖИВЫЕ игроки на данный момент:\n"
    else:
        header = "📋 Текущее состояние игры:\n"

    if judge_name:
        header = header.rstrip() + f"\nСудья: <b>{judge_name}</b>\n"

    lines: List[str] = [header]
    for slot, info in sorted_slots.items():
        if alive_only and not info.get("alive", True):
            continue

        name = _format_player_name(info.get("full_name"), info.get("nickname"))
        role = info.get("role", "Не задана")
        fouls = info.get("fouls", 0)
        alive = info.get("alive", True)
        status_reason = info.get("status_reason") or ("Жив" if alive else "Не в игре")
        nominated = info.get("nominated", False)
        votes = info.get("votes", 0)

        status_text = "Жив" if alive else status_reason
        nom_text = " | ВЫСТ" if nominated else ""
        votes_text = f" | Голоса: {votes}" if votes > 0 else ""

        tech_fouls_count = _safe_get_tech_fouls_count(info)
        tech_text = f" | Тех: {tech_fouls_count}" if tech_fouls_count > 0 else ""

        # Выравниваем колонки для идеальной сетки
        slot_pad = f"{slot:2}"
        name_pad = name[:12].ljust(12)
        role_pad = role.ljust(9) # "Не задана" = 9 символов, остальные меньше

        # Собираем строку через HTML-теги:
        # <code> для ровного шрифта и <tg-spoiler> для скрытия роли
        left_part = f"<code>{slot_pad}. {name_pad} — </code>"
        role_part = f"<tg-spoiler><code>{role_pad}</code></tg-spoiler>"
        right_part = f"<code> | Ф: {fouls}{tech_text} | {status_text}{nom_text}{votes_text}</code>"

        lines.append(left_part + role_part + right_part)

    return "\n".join(lines)


def build_votes_summary(slots: Dict[int, dict]) -> str:
    """
    Краткая сводка результатов голосования:
      - только выставленные игроки;
      - их роли, голоса и статус.
    """
    sorted_slots = dict(sorted(slots.items(), key=lambda x: x[0]))
    lines: List[str] = ["🗳 Результаты голосования (только выставленные):\n"]

    for slot, info in sorted_slots.items():
        if not info.get("nominated"):
            continue

        name = _format_player_name(info.get("full_name"), info.get("nickname"))
        role = info.get("role", "Не задана")
        votes = info.get("votes", 0)
        alive = info.get("alive", True)
        status_reason = info.get("status_reason") or ("Жив" if alive else "Не в игре")
        status_text = "Жив" if alive else status_reason

        lines.append(
            f"{slot}. {name} — {role} | Голоса: {votes} | Статус: {status_text}"
        )

    if len(lines) == 1:
        lines.append("Нет выставленных игроков.")
    return "\n".join(lines)


async def build_protocol_text(
        slots: Dict[int, dict],
        updated: bool = False,
        winner_label: str | None = None,
) -> str:
    """
    Тело протокола: Супер-компактная и идеально ровная таблица в одну строку.
    """
    lines: list[str] = []

    night_kills_order: list[int] = []
    if "_night_kills_order" in slots:
        nk = slots.get("_night_kills_order") or []
        if isinstance(nk, list):
            night_kills_order = [int(x) for x in nk if isinstance(x, int)]

    def get_team_from_role(role: str) -> str | None:
        role_lower = role.lower() if role else ""
        if "мирный" in role_lower or "шериф" in role_lower:
            return "Красные"
        elif "мафия" in role_lower or "дон" in role_lower:
            return "Чёрные"
        return None

    red_slots, black_slots, other_slots = [], [], []
    for slot_num, info in slots.items():
        if isinstance(slot_num, str) and slot_num.startswith("_"): continue
        if not isinstance(slot_num, int): continue

        team = info.get("team") or get_team_from_role(info.get("role", ""))
        if team == "Красные":
            red_slots.append((slot_num, info))
        elif team == "Чёрные":
            black_slots.append((slot_num, info))
        else:
            other_slots.append((slot_num, info))

    red_slots.sort(key=lambda x: x[0])
    black_slots.sort(key=lambda x: x[0])
    other_slots.sort(key=lambda x: x[0])

    def _append_group(title: str, items: list[Tuple[int, dict]]):
        if not items: return

        lines.append(f"<b>{title}</b>")
        # Идеально подогнанная по пикселям шапка
        lines.append("<code> №  Игрок     Эло     | И | Д | Л | П | М | Ц | Σ </code>")

        for slot_num, info in items:
            raw_name = info.get("nickname") or info.get("full_name") or "Без имени"
            name = _trim_name(raw_name, max_len=8).ljust(8)  # Ограничиваем имя до 8 символов

            # --- ЭЛО (всегда 5 символов) ---
            elo_change = info.get("elo_change")
            if elo_change is None:
                elo_str = "     "
            elif elo_change > 0:
                elo_str = f"(+{elo_change})"
            elif elo_change < 0:
                elo_str = f"({elo_change})"
            else:
                elo_str = "(0)"
            elo_pad = elo_str.center(5)

            # --- РОЛЬ (только пометки для Шерифа и Дона) ---
            r = info.get("role", "").lower()
            role_mark = "Ш" if "шер" in r else "Д" if "дон" in r else " "

            # --- СТАТУС ---
            alive = info.get("alive", True)
            status_reason = info.get("status_reason", "Жив")
            s_icon = "✅" if alive else (
                "⚖️" if "Заголосован" in status_reason else "💀" if "Убит" in status_reason else "🚫")

            # --- ЖЕСТКОЕ ФОРМАТИРОВАНИЕ ЧИСЕЛ (всегда 3 символа) ---
            def fv(val):
                v = float(val or 0.0)
                if v == 0: return "  0"
                if v == 1: return "  1"
                if v == -1: return " -1"
                s = f"{v:.1f}"
                if s.startswith("0."): return f" .{s[2]}"  # ".2" (3 символа)
                if s.startswith("-0."): return f"-.{s[3]}"  # "-.2" (3 символа)
                return f"{s:>3}"  # На всякий случай

            b = fv(info.get('base_points'))
            bo = fv(info.get('bonus_points'))
            lh = fv(info.get('lh_points'))
            pr = fv(info.get('will_protocol_points'))
            mn = fv(info.get('will_opinion_points'))
            dc = fv(info.get('dc_points'))

            tot_val = sum([float(info.get(k) or 0) for k in
                           ['base_points', 'bonus_points', 'lh_points', 'will_protocol_points', 'will_opinion_points',
                            'dc_points']])
            tot = f"{tot_val:>4.1f}" if tot_val < 0 else f" {tot_val:>3.1f}"

            # Сборка строки в единый моноблок
            res = f"<code>{slot_num:2}. {name} </code><tg-spoiler><code>{elo_pad}</code></tg-spoiler><code>{role_mark}{s_icon}|{b}|{bo}|{lh}|{pr}|{mn}|{dc}|{tot}</code>"
            lines.append(res)

            # Завещания выносим отдельно, чтобы не растягивать экран
            wp = (info.get("will_protocol_raw") or "").strip()
            wo = (info.get("will_opinion") or "").strip()
            if wp and wp not in ["⏹️", "❌"]: lines.append(f"   <i>└ ПР: {wp[:40]}</i>")
            if wo and wo not in ["⏹️", "❌"]: lines.append(f"   <i>└ МН: {wo[:40]}</i>")

        lines.append("")

    _append_group("🔴 ГОРОД (КРАСНЫЕ):", red_slots)
    _append_group("⚫ МАФИЯ (ЧЁРНЫЕ):", black_slots)
    _append_group("❓ БЕЗ КОМАНДЫ:", other_slots)

    if night_kills_order:
        lines.append("<b>💀 Ночные убийства:</b>")
        for nk_slot in night_kills_order:
            info = slots.get(nk_slot, {})
            p_pts = float(info.get("will_protocol_points", 0.0) or 0.0)
            o_pts = float(info.get("will_opinion_points", 0.0) or 0.0)
            lines.append(f"<code>Слот {nk_slot:2} | ПР: {p_pts:>+4.1f} | МН: {o_pts:>+4.1f}</code>")

    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)


# Экспортируем всё что нужно
__all__ = [
    'build_slots_text',
    'build_roles_summary',
    'build_game_state',
    'build_votes_summary',
    'build_protocol_text',
]