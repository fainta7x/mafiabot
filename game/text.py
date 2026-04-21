from typing import Dict, List, Tuple


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
      "1 2 3"      -> [1, 2, 3]
      "1,2, 3"     -> [1, 2, 3]
      "1 1 2"      -> [1, 2]
      "a 3 b 4"    -> [3, 4]
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


# =========================================================
# 2. ТЕКСТОВЫЕ ПРЕДСТАВЛЕНИЯ
# =========================================================

def build_slots_text(slots: Dict[int, dict]) -> str:
    """
    Черновик новой игры:
      - показывает список слотов и имена игроков;
      - даёт подсказку, как переименовать или добавить слот.
    """
    sorted_slots = dict(sorted(slots.items(), key=lambda x: x[0]))

    lines = ["🎲 Черновик новой игры.\n", "Текущие слоты игроков:\n"]
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


def build_game_state(slots: Dict[int, dict], alive_only: bool = False) -> str:
    """
    Отображение текущего состояния игры:
      - слот, имя, роль;
      - фолы;
      - статус (жив / причина вылета);
      - отметка «ВЫСТАВЛЕН»;
      - количество голосов.
    Если alive_only=True — показываются только живые игроки.
    """
    sorted_slots = dict(sorted(slots.items(), key=lambda x: x[0]))

    lines: List[str] = ["📋 Текущее состояние игры:\n"]
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

        tech_fouls_count = len(info.get("technical_fouls", []))
        tech_text = f" | Техфолы: {tech_fouls_count}" if tech_fouls_count > 0 else ""

        lines.append(
            f"{slot}. {name} — {role} | Фолы: {fouls}{tech_text} | Статус: {status_text}{nom_text}{votes_text}"
        )

    if alive_only:
        # Переписываем заголовок, если показываем только живых
        lines[0] = "📋 ЖИВЫЕ игроки на данный момент:\n"

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


def build_protocol_text(
        slots: Dict[int, dict],
        updated: bool = False,
        winner_label: str | None = None,
) -> str:
    """
    Собирает ТОЛЬКО ТЕЛО протокола игры из slots (HTML).
    """
    lines: list[str] = []

    # Вытаскиваем служебный ключ порядка убийств, если он есть
    night_kills_order: list[int] = []
    if "_night_kills_order" in slots:
        nk = slots.get("_night_kills_order") or []
        if isinstance(nk, list):
            night_kills_order = [int(x) for x in nk if isinstance(x, int)]

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
            pu_mark = "👑 ПУ" if is_pu else ""

            base_pts = float(info.get("base_points", 0.0) or 0.0)
            bonus_pts = float(info.get("bonus_points", 0.0) or 0.0)
            lh_pts = float(info.get("lh_points", 0.0) or 0.0)
            pr_pts = float(info.get("will_protocol_points", 0.0) or 0.0)
            mn_pts = float(info.get("will_opinion_points", 0.0) or 0.0)
            dc_pts = float(info.get("dc_points", 0.0) or 0.0)

            total_pts = round(base_pts + bonus_pts + lh_pts + pr_pts + mn_pts + dc_pts, 1)

            will_protocol = (info.get("will_protocol_raw") or "").strip()
            will_opinion = (info.get("will_opinion") or "").strip()

            lines.append(f"{slot_num}. <b>{name}</b> — <i>{role}</i> {status_text}")
            lines.append(
                "   "
                f"{pu_mark} | "
                f"Игра: {base_pts} | "
                f"Доп: {bonus_pts} | "
                f"ЛХ: {lh_pts} | "
                f"ПР: {pr_pts} | "
                f"МН: {mn_pts} | "
                f"ДЦ: {dc_pts} | "
                f"Итого: <b>{total_pts}</b>"
            )

            if will_protocol:
                lines.append(f"   Протокол: {will_protocol}")
            if will_opinion:
                lines.append(f"   Мнение: {will_opinion}")
        lines.append("")

    _append_group("Красные:", red_slots)
    _append_group("Чёрные:", black_slots)
    _append_group("Без команды:", other_slots)

    # Блок "Убийства" с расшифровкой завещаний
    if night_kills_order:
        while lines and lines[-1] == "":
            lines.pop()

        lines.append("___________________________________________")
        lines.append("<b>Убийства (ночные завещания):</b>")

        for killed_slot in night_kills_order:
            info = slots.get(killed_slot) or {}
            proto_text = (info.get("will_protocol_raw") or "нет").strip()
            proto_pts = float(info.get("will_protocol_points", 0.0) or 0.0)
            op_text = (info.get("will_opinion") or "нет").strip()
            op_pts = float(info.get("will_opinion_points", 0.0) or 0.0)

            lines.append(f"Убийство №{killed_slot}:")
            lines.append(f"Протокол — {proto_text} ({proto_pts})")
            lines.append(f"Мнение — {op_text} ({op_pts})")
            lines.append("")

    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)