from typing import Dict


def _format_player_name(full_name: str | None, nickname: str | None) -> str:
    if nickname and nickname not in ("", "Не установлен"):
        return nickname
    if full_name and full_name not in ("", "Неизвестный"):
        return full_name
    return "Без имени"


def _trim_name(name: str | None, max_len: int = 18) -> str:
    """
    Обрезает слишком длинные ники, чтобы строки протокола не разваливались.
    """
    if not name:
        return "Без имени"
    name = name.strip()
    if len(name) <= max_len:
        return name
    return name[: max_len - 1] + "…"


def build_slots_text(slots: Dict[int, dict]) -> str:
    sorted_slots = dict(sorted(slots.items(), key=lambda x: x[0]))

    lines = ["🎲 Черновик новой игры.\n", "Текущие слоты игроков:\n"]
    for slot, info in sorted_slots.items():
        name_part = _format_player_name(info["full_name"], info["nickname"])
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
    sorted_slots = dict(sorted(slots.items(), key=lambda x: x[0]))

    lines = ["🎭 Роли и команды по слотам:\n"]
    for slot, info in sorted_slots.items():
        name = _format_player_name(info.get("full_name"), info.get("nickname"))
        role = info.get("role", "Не задана")
        team = info.get("team", "—")
        lines.append(f"{slot}. {name} — {role} ({team})")

    return "\n".join(lines)


def build_game_state(slots: Dict[int, dict], alive_only: bool = False) -> str:
    sorted_slots = dict(sorted(slots.items(), key=lambda x: x[0]))

    lines = ["📋 Текущее состояние игры:\n"]
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

        lines.append(
            f"{slot}. {name} — {role} | Фолы: {fouls} | Статус: {status_text}{nom_text}{votes_text}"
        )

    if alive_only:
        lines.insert(0, "📋 ЖИВЫЕ игроки на данный момент:\n")

    return "\n".join(lines)


def build_votes_summary(slots: Dict[int, dict]) -> str:
    sorted_slots = dict(sorted(slots.items(), key=lambda x: x[0]))
    lines = ["🗳 Результаты голосования (только выставленные):\n"]
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
    Собирает ТОЛЬКО ТЕЛО протокола игры из slots.

    ВАЖНО:
    - Здесь НЕ добавляем строку "📑 Протокол игры ...".
      Шапку рисуем в handlers/profile.py при показе истории.
    - Используем HTML-разметку: <b>, <i>.
    - Длинные ники подрезаем.
    """
    lines: list[str] = []

    # Разделяем слоты по командам
    red_slots: list[tuple[int, dict]] = []
    black_slots: list[tuple[int, dict]] = []
    other_slots: list[tuple[int, dict]] = []

    for slot_num, info in slots.items():
        team = info.get("team")
        if team == "Красные":
            red_slots.append((slot_num, info))
        elif team == "Чёрные":
            black_slots.append((slot_num, info))
        else:
            other_slots.append((slot_num, info))

    # Сортируем внутри команд по номеру слота
    red_slots.sort(key=lambda x: x[0])
    black_slots.sort(key=lambda x: x[0])
    other_slots.sort(key=lambda x: x[0])

    def _append_group(title: str, items: list[tuple[int, dict]]):
        if not items:
            return
        lines.append(f"<b>{title}</b>")
        for slot_num, info in items:
            raw_name = info.get("nickname") or info.get("full_name") or "Без имени"
            name = _trim_name(raw_name)

            role = info.get("role", "Не задана")

            is_pu = bool(info.get("pu_mark"))
            pu_mark = "ПУ" if is_pu else "—"

            base_pts = info.get("base_points", 0.0) or 0.0
            bonus_pts = info.get("bonus_points", 0.0) or 0.0
            lh_pts = info.get("lh_points", 0.0) or 0.0
            total_pts = round(base_pts + bonus_pts + lh_pts, 1)

            lines.append(
                f"{slot_num}. <b>{name}</b> — <i>{role}</i>"
            )
            lines.append(
                f"   {pu_mark} | Игра: {base_pts} | Доп: {bonus_pts} | ЛХ: {lh_pts} | Итого: <b>{total_pts}</b>"
            )
        lines.append("")

    _append_group("Красные:", red_slots)
    _append_group("Чёрные:", black_slots)
    _append_group("Без команды:", other_slots)

    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)


def _parse_slots_list(text: str) -> list[int]:
    cleaned = text.replace(",", " ")
    parts = cleaned.split()
    result: list[int] = []
    for p in parts:
        if not p.strip():
            continue
        try:
            num = int(p)
        except ValueError:
            continue
        if num not in result:
            result.append(num)
    return result