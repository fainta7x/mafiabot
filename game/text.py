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
      - слот, имя, роль;
      - фолы;
      - статус (жив / причина вылета);
      - отметка «ВЫСТАВЛЕН»;
      - количество голосов.
    Если alive_only=True — показываются только живые игроки.
    ДОБАВЛЕНО: в шапке выводится Судья, если judge_name не пуст.
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
        nom_text = " | ВЫСТАВЛЕН" if nominated else ""
        votes_text = f" | Голоса: {votes}" if votes > 0 else ""

        tech_fouls_count = _safe_get_tech_fouls_count(info)
        tech_text = f" | Техфолы: {tech_fouls_count}" if tech_fouls_count > 0 else ""

        lines.append(
            f"{slot}. {name} — {role} | Фолы: {fouls}{tech_text} | "
            f"Статус: {status_text}{nom_text}{votes_text}"
        )

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
    Собирает ТОЛЬКО ТЕЛО протокола игры из slots (HTML).
    ДОБАВЛЕНО: в шапке выводится Судья (берётся из БД), если сохранён.
    """
    lines: list[str] = []

    # --- ШАПКА С СУДЬЁЙ И ИТОГО РЕЗУЛЬТАТОМ ---
    judge_name = await database.get_current_game_judge_name()
    if judge_name:
        lines.append(f"<b>Судья:</b> {judge_name}")
    if winner_label:
        lines.append(f"<b>Результат:</b> {winner_label}")
    if lines:
        lines.append("")  # пустая строка после шапки

    # Вытаскиваем служебный ключ порядка убийств, если он есть
    night_kills_order: list[int] = []
    if "_night_kills_order" in slots:
        nk = slots.get("_night_kills_order") or []
        if isinstance(nk, list):
            night_kills_order = [int(x) for x in nk if isinstance(x, int)]

    # ========== НОВАЯ ФУНКЦИЯ: определение команды по роли ==========
    def get_team_from_role(role: str) -> str | None:
        """Определяет команду по роли, если team не задана"""
        role_lower = role.lower() if role else ""
        if "мирный" in role_lower or "шериф" in role_lower:
            return "Красные"
        elif "мафия" in role_lower or "дон" in role_lower:
            return "Чёрные"
        return None

    # Разделяем слоты по командам (игнорируя служебные ключи)
    red_slots: list[Tuple[int, dict]] = []
    black_slots: list[Tuple[int, dict]] = []
    other_slots: list[Tuple[int, dict]] = []

    for slot_num, info in slots.items():
        if isinstance(slot_num, str) and slot_num.startswith("_"):
            continue
        if not isinstance(slot_num, int):
            continue

        team = info.get("team")

        # Если team не задана - определяем по роли
        if not team:
            team = get_team_from_role(info.get("role", ""))

        if team == "Красные":
            red_slots.append((slot_num, info))
        elif team == "Чёрные":
            black_slots.append((slot_num, info))
        else:
            other_slots.append((slot_num, info))

    red_slots.sort(key=lambda x: x[0])
    black_slots.sort(key=lambda x: x[0])
    other_slots.sort(key=lambda x: x[0])

    # ========== ИСПРАВЛЕННАЯ ФУНКЦИЯ ДЛЯ ГРУППЫ ==========
    def _append_group(title: str, items: list[Tuple[int, dict]]):
        if not items:
            return
        lines.append(f"<b>{title}</b>")
        for slot_num, info in items:
            raw_name = info.get("nickname") or info.get("full_name") or "Без имени"
            name = _trim_name(raw_name)
            role = info.get("role", "Не задана")
            alive = info.get("alive", True)
            status_reason = info.get("status_reason", "Жив")
            kicked = info.get("kicked", False)
            ppk = info.get("ppk", False)
            fouls = info.get("fouls", 0)

            # ИСПРАВЛЕНО: безопасное получение количества техфолов
            tech_fouls_count = _safe_get_tech_fouls_count(info)

            # Формируем статус
            if not alive:
                if kicked:
                    status_icon = "🚫"
                    status_text = f"{status_icon} {status_reason}"
                elif "Заголосован" in status_reason:
                    status_icon = "⚖️"
                    status_text = f"{status_icon} Заголосован"
                elif "Убит" in status_reason:
                    status_icon = "💀"
                    status_text = f"{status_icon} Убит ночью"
                else:
                    status_icon = "💀"
                    status_text = f"{status_icon} {status_reason}"
            else:
                if ppk:
                    status_icon = "⚠️"
                    status_text = f"{status_icon} Удалён (ППК)"
                else:
                    status_icon = "✅"
                    status_text = f"{status_icon} Жив"

            is_pu = bool(info.get("pu_mark"))

            # Формируем префикс с ПУ, фолами, техфолами
            prefix_parts = []
            if is_pu:
                prefix_parts.append("👑 ПУ")
            if fouls > 0:
                prefix_parts.append(f"⚠️ Фолы: {fouls}")
            if tech_fouls_count > 0:
                tech_display = _safe_get_tech_fouls_display(info)
                if tech_display:
                    prefix_parts.append(f"⚠️ Тех: {tech_display}")
                else:
                    prefix_parts.append(f"⚠️ Тех: {tech_fouls_count}")

            prefix = " | ".join(prefix_parts)
            if prefix:
                prefix = f"{prefix} | "

            base_pts = float(info.get("base_points", 0.0) or 0.0)
            bonus_pts = float(info.get("bonus_points", 0.0) or 0.0)
            lh_pts = float(info.get("lh_points", 0.0) or 0.0)
            pr_pts = float(info.get("will_protocol_points", 0.0) or 0.0)
            mn_pts = float(info.get("will_opinion_points", 0.0) or 0.0)
            dc_pts = float(info.get("dc_points", 0.0) or 0.0)

            total_pts = round(
                base_pts + bonus_pts + lh_pts + pr_pts + mn_pts + dc_pts, 1
            )

            will_protocol = (info.get("will_protocol_raw") or "").strip()
            will_opinion = (info.get("will_opinion") or "").strip()

            # Фильтруем мусор из текста (кнопки и т.д.)
            trash_words = ["⏹️ Остановить", "⏹️", "❌ Отмена", "✅ Подтвердить"]
            if will_protocol in trash_words:
                will_protocol = ""
            if will_opinion in trash_words:
                will_opinion = ""

            lines.append(f"{slot_num}. <b>{name}</b> — <i>{role}</i> {status_text}")
            lines.append(
                f"   {prefix}"
                f"Игра: {base_pts} | "
                f"Доп: {bonus_pts} | "
                f"ЛХ: {lh_pts} | "
                f"ПР: {pr_pts} | "
                f"МН: {mn_pts} | "
                f"ДЦ: {dc_pts} | "
                f"Итого: <b>{total_pts}</b>"
            )

            if will_protocol:
                lines.append(f"   Протокол: {will_protocol[:100]}")
            if will_opinion:
                lines.append(f"   Мнение: {will_opinion[:100]}")
        lines.append("")

    _append_group("🔴 ГОРОД (КРАСНЫЕ):", red_slots)
    _append_group("⚫ МАФИЯ (ЧЁРНЫЕ):", black_slots)
    _append_group("❓ БЕЗ КОМАНДЫ:", other_slots)

    # Блок "Убийства" с расшифровкой завещаний
    if night_kills_order:
        while lines and lines[-1] == "":
            lines.pop()

        lines.append("___________________________________________")
        lines.append("<b>💀 Убийства (ночные завещания):</b>")

        for killed_slot in night_kills_order:
            info = slots.get(killed_slot) or {}
            proto_text = (info.get("will_protocol_raw") or "").strip()
            proto_pts = float(info.get("will_protocol_points", 0.0) or 0.0)
            op_text = (info.get("will_opinion") or "").strip()
            op_pts = float(info.get("will_opinion_points", 0.0) or 0.0)

            # Фильтруем мусор
            if proto_text in ["⏹️ Остановить", "⏹️"]:
                proto_text = "нет"
            if op_text in ["⏹️ Остановить", "⏹️"]:
                op_text = "нет"

            lines.append(f"💀 Убийство №{killed_slot}:")
            lines.append(f"   📋 Протокол — {proto_text if proto_text else 'нет'} ({proto_pts:+.1f})")
            lines.append(f"   💬 Мнение — {op_text if op_text else 'нет'} ({op_pts:+.1f})")
            lines.append("")

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