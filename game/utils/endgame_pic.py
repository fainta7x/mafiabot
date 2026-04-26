import os
from typing import Dict, Tuple, List, Any

from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp")
os.makedirs(TEMP_DIR, exist_ok=True)


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """
    Пытаемся загрузить что-то приличное.
    Можно положить свой .ttf рядом (Montserrat / JetBrains Mono) и заменить имя.
    """
    for fname in ("Montserrat-SemiBold.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(fname, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _shorten(text: str, max_len: int = 20) -> str:
    text = text or ""
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _role_color(role: str) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
    """
    Цвет акцента по роли: (основной цвет, мягкий фон).
    """
    r = (role or "").lower()

    if "дон" in r:
        main = (142, 68, 173)  # фиолетовый
    elif "маф" in r:
        main = (26, 26, 26)  # глубокий графитовый для мафии
    elif "шер" in r or "шериф" in r:
        main = (46, 204, 113)  # мягкий зелёный
    elif "кр" in r or "мирн" in r or "город" in r:
        main = (192, 57, 43)  # винный красный
    else:
        main = (52, 152, 219)  # синий

    bg = (
        int(main[0] * 0.20),
        int(main[1] * 0.20),
        int(main[2] * 0.20),
    )
    return main, bg


def _draw_rounded_rect(
        draw: ImageDraw.ImageDraw,
        x1,
        y1,
        x2,
        y2,
        radius,
        outline=None,
        fill=None,
        width: int = 1,
):
    draw.rounded_rectangle((x1, y1, x2, y2), radius=radius, outline=outline, width=width, fill=fill)


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> Tuple[int, int]:
    """
    Кросс-версионный расчёт размера текста.
    """
    try:
        bbox = font.getbbox(text)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        return draw.textsize(text, font=font)


def _draw_badge(
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        text: str,
        font: ImageFont.ImageFont,
        bg_color: Tuple[int, int, int],
        fg_color: Tuple[int, int, int] = (0, 0, 0),
        padding_x: int = 8,
        padding_y: int = 4,
        radius: int = 8,
) -> int:
    """
    Маленький скруглённый бейдж с текстом.
    Возвращает новый x (правый край).
    """
    w, h = _text_size(draw, text, font)
    x1 = x
    y1 = y
    x2 = x + w + padding_x * 2
    y2 = y + h + padding_y * 2

    draw.rounded_rectangle(
        (x1, y1, x2, y2),
        radius=radius,
        fill=bg_color,
        outline=None,
        width=1,
    )
    draw.text(
        (x1 + padding_x, y1 + padding_y),
        text,
        fill=fg_color,
        font=font,
    )
    return x2


def _lerp_color(c1: Tuple[int, int, int], c2: Tuple[int, int, int], t: float) -> Tuple[int, int, int]:
    """
    Линейная интерполяция между цветами c1 -> c2.
    t=0 -> c1, t=1 -> c2.
    """
    t = max(0.0, min(1.0, t))
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def _get_elo_display(info: dict) -> Tuple[str, Tuple[int, int, int], str]:
    """
    Возвращает текст изменения Эло, цвет и итоговое Эло.
    """
    elo_change = info.get("elo_change")
    new_elo = info.get("new_elo")

    if (elo_change is None or elo_change == 0) and not new_elo:
        return "", None, ""

    if elo_change and elo_change != 0:
        if elo_change > 0:
            change_text = f"+{elo_change}"
            change_color = (46, 204, 113)
        else:
            change_text = f"{elo_change}"
            change_color = (231, 76, 60)
    else:
        change_text = ""
        change_color = None

    if new_elo:
        total_elo = f"{new_elo}"
    else:
        total_elo = ""

    return change_text, change_color, total_elo


def create_endgame_pic_summary(
        slots: Dict[Any, dict],
        game_date: str,
        evening_game_number: int,
        global_game_number: int,
        winner_label: str | None,
        judge_name: str | None = None,  # <-- НОВЫЙ ПАРАМЕТР
) -> str:
    """
    Современный общий протокол игры.
    """
    # ========== ФИЛЬТРУЕМ СЛОТЫ ==========
    clean_slots = {}
    night_kills_order = []

    for key, value in slots.items():
        if isinstance(key, int) and 1 <= key <= 10:
            clean_slots[key] = value
        elif key == "_night_kills_order" and isinstance(value, list):
            night_kills_order = value
        elif isinstance(key, str) and key.isdigit():
            num = int(key)
            if 1 <= num <= 10:
                clean_slots[num] = value

    slots = clean_slots

    if not night_kills_order:
        for slot_num, info in slots.items():
            if isinstance(slot_num, int):
                alive = info.get("alive", True)
                kicked = info.get("kicked", False)
                status_reason = info.get("status_reason", "")
                if not alive or kicked or "убит" in status_reason.lower() or "заголосован" in status_reason.lower():
                    night_kills_order.append(slot_num)
        night_kills_order.sort()

    print(f"[PIC_DEBUG] Всего слотов получено: {len(slots)}")

    # --- Подготовка данных по командам ---
    red_slots: List[Tuple[int, dict]] = []
    black_slots: List[Tuple[int, dict]] = []
    other_slots: List[Tuple[int, dict]] = []

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

    # Базовый логический размер
    base_width = 1200
    base_height = 800

    def count_group_items(group: List[Tuple[int, dict]]) -> int:
        return len(group)

    total_items = (
            count_group_items(red_slots)
            + count_group_items(black_slots)
            + count_group_items(other_slots)
    )
    row_height = 80
    kills_block_height = 0
    if night_kills_order:
        kills_block_height = 40 + len(night_kills_order) * 80

    est_height = 300 + total_items * row_height + kills_block_height + 80
    base_height = max(base_height, est_height)

    # --- Рисуем в 2x ---
    scale = 2
    width = base_width * scale
    height = base_height * scale

    img = Image.new("RGB", (width, height), color=(12, 12, 12))
    draw = ImageDraw.Draw(img)

    padding_x = int(70 * scale / 2) * 2
    y = int(40 * scale)

    # Шрифты
    font_title = _load_font(int(40 * scale / 2))
    font_subtitle = _load_font(int(24 * scale / 2))
    font_group = _load_font(int(26 * scale / 2))
    font_name = _load_font(int(27 * scale / 2))
    font_role = _load_font(int(18 * scale / 2))
    font_small = _load_font(int(18 * scale / 2))
    font_status = _load_font(int(18 * scale / 2))
    font_badge = _load_font(int(18 * scale / 2))
    font_total_big = _load_font(int(32 * scale / 2))
    font_elo = _load_font(int(19 * scale / 2))
    font_slot = _load_font(int(28 * scale / 2))

    # --- Итог и цвет победителя ---
    wl = (winner_label or "").lower()

    if "город" in wl:
        winner_team = "red"
        result_text = "СТАТУС: ПОБЕДА КРАСНЫХ"
    elif "маф" in wl:
        winner_team = "black"
        result_text = "СТАТУС: ПОБЕДА ЧЁРНЫХ"
    elif "ппк" in wl and "красн" in wl:
        winner_team = "red"
        result_text = f"СТАТУС: {winner_label}"
    elif "ппк" in wl and "чёрн" in wl:
        winner_team = "black"
        result_text = f"СТАТУС: {winner_label}"
    else:
        winner_team = "none"
        result_text = "СТАТУС: БЕЗ ПОДВЕДЕНИЯ РЕЗУЛЬТАТА"

    top_accent_red = (192, 57, 43)
    top_accent_black = (52, 73, 94)
    top_accent_neutral = (96, 125, 139)

    if winner_team == "red":
        top_accent = top_accent_red
    elif winner_team == "black":
        top_accent = top_accent_black
    else:
        top_accent = top_accent_neutral

    # Заголовок
    title = "ПРОТОКОЛ ИГРЫ"
    title_w, title_h = _text_size(draw, title, font_title)
    title_x = width / 2
    draw.text((title_x, y), title, fill=(236, 240, 241), font=font_title, anchor="ma")
    y += title_h + int(8 * scale)

    # Плашка ИТОГ
    result_w, result_h = _text_size(draw, result_text, font_subtitle)
    res_pad_x = int(10 * scale)
    res_pad_y = int(4 * scale)
    res_x1 = width / 2 - (result_w + res_pad_x * 2) / 2
    res_y1 = y
    res_x2 = res_x1 + result_w + res_pad_x * 2
    res_y2 = res_y1 + result_h + res_pad_y * 2

    _draw_rounded_rect(
        draw,
        res_x1,
        res_y1,
        res_x2,
        res_y2,
        radius=int(10 * scale),
        outline=None,
        fill=(top_accent[0], top_accent[1], top_accent[2]),
        width=int(1 * scale),
    )
    draw.text(
        (width / 2, res_y1 + res_pad_y),
        result_text,
        fill=(236, 240, 241),
        font=font_subtitle,
        anchor="ma",
    )

    y = res_y2 + int(10 * scale)

    # ========== БЛОК СУДЬИ ==========
    if judge_name:
        judge_text = f"Судья: {judge_name}"
        judge_w, judge_h = _text_size(draw, judge_text, font_subtitle)
        draw.text(
            (padding_x, y),
            judge_text,
            fill=(255, 255, 255),
            font=font_subtitle,
        )
        y += judge_h + int(8 * scale)
    # ================================

    # Подзаголовок с датой и номерами
    header_line_1 = f"Игра №{evening_game_number} • {game_date}"
    header_line_2 = f"№{global_game_number} по истории"

    draw.text(
        (padding_x, y),
        header_line_1,
        fill=(189, 195, 199),
        font=font_subtitle,
    )
    _, h1 = _text_size(draw, header_line_1, font_subtitle)
    y += h1 + int(4 * scale)

    draw.text(
        (padding_x, y),
        header_line_2,
        fill=(149, 165, 166),
        font=font_subtitle,
    )
    _, h2 = _text_size(draw, header_line_2, font_subtitle)
    y += h2 + int(10 * scale)

    # Разделитель
    card_left = padding_x
    card_right = width - padding_x
    draw.line(
        [(card_left, y), (card_right, y)],
        fill=(44, 62, 80),
        width=int(1 * scale),
    )
    y += int(12 * scale)

    # Цвета бейджей
    plus_bg = (46, 125, 50)
    plus_fg = (236, 240, 241)
    zero_bg = (55, 71, 79)
    zero_fg = (189, 195, 199)
    minus_bg = (183, 28, 28)
    minus_fg = (248, 249, 249)
    pu_bg = (255, 193, 7)
    pu_fg = (33, 33, 33)

    row_gap = int(10 * scale)
    row_height_scaled = int(row_height * scale)

    # Общая ширина карточек
    card_width = int((card_right - card_left) * 0.90)
    card_x1 = card_left + int(((card_right - card_left) - card_width) / 2)
    card_x2 = card_x1 + card_width

    def draw_group(title: str, group: List[Tuple[int, dict]], y_pos: int, team_key: str) -> int:
        if not group:
            return y_pos

        def get_status_label(slot_info: dict) -> tuple[str, Tuple[int, int, int]]:
            alive = slot_info.get("alive", True)
            reason = (slot_info.get("status_reason") or "").strip()

            green_live = (46, 204, 113)
            red_dead = (244, 67, 54)
            grey_passive = (158, 158, 158)
            grey_neutral = (189, 195, 199)

            r_low = reason.lower()

            if alive:
                if not reason or "жив" in r_low:
                    return "Жив", green_live
                return reason, green_live

            if "ппк" in r_low:
                return "Удалён (ППК)", red_dead
            if "ведущ" in r_low:
                return "Удалён ведущим", red_dead
            if "4 фола" in r_low:
                return "Удалён (4 фола)", red_dead
            if "2 техфол" in r_low:
                return "Удалён (2 техфола)", red_dead
            if "заголос" in r_low:
                return "Заголосован", grey_passive
            if "убит" in r_low:
                return reason or "Убит", grey_passive
            if "фол" in r_low or "тех" in r_low:
                return reason, red_dead
            return reason or "Мёртв", grey_neutral

        # Заголовок группы
        suffix = ""
        if winner_team == team_key:
            suffix = " — ПОБЕДА"
        elif winner_team in ("red", "black") and team_key in ("red", "black") and winner_team != team_key:
            suffix = " — ПОРАЖЕНИЕ"

        title_text = title + suffix

        draw.text(
            (card_x1, y_pos),
            title_text,
            fill=(189, 195, 199),
            font=font_group,
        )
        _, gh = _text_size(draw, title_text, font_group)
        y_pos += gh + int(6 * scale)

        draw.line(
            [(card_x1, y_pos), (card_x2, y_pos)],
            fill=(35, 35, 35),
            width=int(1 * scale),
        )
        y_pos += int(10 * scale)

        for slot_num, info in group:
            raw_name = info.get("nickname") or info.get("full_name") or "Без имени"
            name = _shorten(raw_name, max_len=22)
            role = info.get("role", "Не задана")
            role_caps = (role or "").upper()
            alive = info.get("alive", True)

            elo_change_text, elo_change_color, elo_total = _get_elo_display(info)

            accent, bg_soft = _role_color(role)

            if not alive:
                bg_soft = _lerp_color(bg_soft, (12, 12, 12), 0.85)
                accent = _lerp_color(accent, (60, 60, 60), 0.85)

            row_top = y_pos
            row_bottom = y_pos + row_height_scaled - row_gap

            base_bg = (
                max(bg_soft[0], 15),
                max(bg_soft[1], 15),
                max(bg_soft[2], 15),
            )
            outline_color = accent

            _draw_rounded_rect(
                draw,
                card_x1,
                row_top,
                card_x2,
                row_bottom,
                radius=int(18 * scale),
                outline=outline_color,
                fill=base_bg,
                width=int(2 * scale),
            )

            inner_left = card_x1 + int(16 * scale)
            inner_right = card_x2 - int(16 * scale)
            inner_top = row_top + int(10 * scale)

            # Номер слота
            slot_text = str(slot_num)
            slot_w, slot_h = _text_size(draw, slot_text, font_slot)
            slot_badge_w = slot_w + int(14 * scale)
            slot_badge_h = slot_h + int(8 * scale)

            slot_x1 = inner_left
            slot_y1 = inner_top + int(4 * scale)
            slot_x2 = slot_x1 + slot_badge_w
            slot_y2 = slot_y1 + slot_badge_h

            _draw_rounded_rect(
                draw,
                slot_x1,
                slot_y1,
                slot_x2,
                slot_y2,
                radius=int(10 * scale),
                outline=None,
                fill=(33, 33, 33),
                width=0,
            )

            slot_team = (info.get("team") or "").lower()
            slot_role = (role or "").lower()
            is_black_team = "чёрн" in slot_team or "маф" in slot_role
            is_don = "дон" in slot_role

            if is_don:
                num_color = accent if alive else _lerp_color(accent, (140, 140, 140), 0.8)
            elif is_black_team:
                num_color = (240, 240, 240) if alive else (140, 140, 140)
            else:
                num_color = accent if alive else _lerp_color(accent, (140, 140, 140), 0.8)

            draw.text(
                ((slot_x1 + slot_x2) / 2, (slot_y1 + slot_y2) / 2 - int(1 * scale)),
                slot_text,
                fill=num_color,
                font=font_slot,
                anchor="mm",
            )

            x_name_start = slot_x2 + int(18 * scale)

            name_color_alive = (236, 240, 241)
            name_color_dead = (130, 130, 130)
            name_color = name_color_alive if alive else name_color_dead

            base_y = inner_top + int(4 * scale)

            draw.text(
                (x_name_start, base_y),
                name,
                fill=name_color,
                font=font_name,
            )
            name_w, _ = _text_size(draw, name, font_name)

            current_x = x_name_start + name_w + int(6 * scale)

            if elo_change_text:
                draw.text(
                    (current_x, base_y),
                    f"({elo_change_text})",
                    fill=elo_change_color,
                    font=font_elo,
                )
                current_x += _text_size(draw, f"({elo_change_text})", font_elo)[0] + int(4 * scale)

            if elo_total:
                draw.text(
                    (current_x, base_y),
                    f"→{elo_total}",
                    fill=(255, 193, 7),
                    font=font_elo,
                )
                current_x += _text_size(draw, f"→{elo_total}", font_elo)[0] + int(8 * scale)

            dot_x = current_x + int(4 * scale)
            dot_y = base_y + int(4 * scale)
            dot_r = int(4 * scale)

            if is_don:
                dot_color = accent if alive else _lerp_color(accent, (120, 120, 120), 0.85)
            elif is_black_team:
                dot_color = (240, 240, 240) if alive else (135, 135, 135)
            else:
                dot_color = accent if alive else _lerp_color(accent, (120, 120, 120), 0.85)

            draw.ellipse(
                (dot_x - dot_r, dot_y - dot_r, dot_x + dot_r, dot_y + dot_r),
                fill=dot_color,
                outline=None,
            )

            role_x = dot_x + int(10 * scale)
            role_y = base_y
            role_color = (189, 195, 199) if alive else (120, 120, 120)
            draw.text(
                (role_x, role_y),
                role_caps,
                fill=role_color,
                font=font_role,
            )

            status_label, status_color = get_status_label(info)
            status_label_short = _shorten(status_label, max_len=26)

            status_x = role_x + _text_size(draw, role_caps, font_role)[0] + int(12 * scale)
            status_y = base_y

            if not alive:
                status_color = _lerp_color(status_color, (130, 130, 130), 0.7)

            draw.text(
                (status_x, status_y),
                status_label_short,
                fill=status_color,
                font=font_status,
            )

            # Очки
            base_pts = float(info.get("base_points", 0.0) or 0.0)
            bonus_pts = float(info.get("bonus_points", 0.0) or 0.0)
            lh_pts = float(info.get("lh_points", 0.0) or 0.0)
            pr_pts = float(info.get("will_protocol_points", 0.0) or 0.0)
            mn_pts = float(info.get("will_opinion_points", 0.0) or 0.0)
            dc_pts = float(info.get("dc_points", 0.0) or 0.0)

            total_pts = round(base_pts + bonus_pts + lh_pts + pr_pts + mn_pts + dc_pts, 1)
            total_text = str(total_pts)

            tw, th = _text_size(draw, total_text, font_total_big)
            sq_pad_x = int(16 * scale)
            sq_pad_y = int(8 * scale)
            sq_w = tw + sq_pad_x * 2
            sq_h = th + sq_pad_y * 2

            sq_x2 = inner_right
            sq_x1 = sq_x2 - sq_w
            sq_y1 = row_top + int(14 * scale)
            sq_y2 = sq_y1 + sq_h

            sq_fill = (
                int(255 * 0.10),
                int(255 * 0.10),
                int(255 * 0.10),
            )
            sq_outline = accent

            _draw_rounded_rect(
                draw,
                sq_x1,
                sq_y1,
                sq_x2,
                sq_y2,
                radius=int(16 * scale),
                outline=sq_outline,
                fill=sq_fill,
                width=int(2 * scale),
            )

            cx = (sq_x1 + sq_x2) / 2
            cy = (sq_y1 + sq_y2) / 2
            total_color = (236, 240, 241)
            draw.text(
                (cx, cy - int(1 * scale)),
                total_text,
                fill=total_color,
                font=font_total_big,
                anchor="mm",
            )

            # Бейджи
            badges_y = row_top + int(row_height_scaled * 0.56)
            badges_x = x_name_start

            is_pu = bool(info.get("pu_mark"))
            if is_pu:
                badges_x = _draw_badge(
                    draw,
                    badges_x,
                    badges_y,
                    "ПУ",
                    font_badge,
                    bg_color=pu_bg,
                    fg_color=pu_fg,
                    padding_x=int(6 * scale),
                    padding_y=int(4 * scale),
                    radius=int(8 * scale),
                ) + int(6 * scale)

            def add_points_badge(label: str, value: float) -> int:
                nonlocal badges_x
                txt = f"{label}: {value:+.1f}"
                if value > 0:
                    badges_x = _draw_badge(
                        draw,
                        badges_x,
                        badges_y,
                        txt,
                        font_badge,
                        bg_color=plus_bg,
                        fg_color=plus_fg,
                        padding_x=int(6 * scale),
                        padding_y=int(4 * scale),
                        radius=int(8 * scale),
                    ) + int(6 * scale)
                elif value < 0:
                    badges_x = _draw_badge(
                        draw,
                        badges_x,
                        badges_y,
                        txt,
                        font_badge,
                        bg_color=minus_bg,
                        fg_color=minus_fg,
                        padding_x=int(6 * scale),
                        padding_y=int(4 * scale),
                        radius=int(8 * scale),
                    ) + int(6 * scale)
                else:
                    badges_x = _draw_badge(
                        draw,
                        badges_x,
                        badges_y,
                        txt,
                        font_badge,
                        bg_color=zero_bg,
                        fg_color=zero_fg,
                        padding_x=int(6 * scale),
                        padding_y=int(4 * scale),
                        radius=int(8 * scale),
                    ) + int(6 * scale)
                return badges_x

            add_points_badge("Игра", base_pts)
            add_points_badge("Доп", bonus_pts)
            add_points_badge("ЛХ", lh_pts)
            add_points_badge("ПР", pr_pts)
            add_points_badge("МН", mn_pts)
            if abs(dc_pts) > 0.0:
                add_points_badge("ДЦ", dc_pts)

            fouls = int(info.get("fouls", 0) or 0)
            if fouls > 0:
                fouls_bg = minus_bg if fouls >= 4 else zero_bg
                fouls_fg = minus_fg if fouls >= 4 else zero_fg
                badges_x = _draw_badge(
                    draw,
                    badges_x,
                    badges_y,
                    f"Фолы: {fouls}",
                    font_badge,
                    bg_color=fouls_bg,
                    fg_color=fouls_fg,
                    padding_x=int(6 * scale),
                    padding_y=int(4 * scale),
                    radius=int(8 * scale),
                ) + int(6 * scale)

            technical_fouls = info.get("technical_fouls") or []
            if technical_fouls:
                small_count = sum(1 for t in technical_fouls if t == "small")
                big_count = sum(1 for t in technical_fouls if t == "big")
                parts = []
                if small_count:
                    parts.append(f"{small_count}S")
                if big_count:
                    parts.append(f"{big_count}B")
                tech_text = "Тех: " + "/".join(parts)
                badges_x = _draw_badge(
                    draw,
                    badges_x,
                    badges_y,
                    tech_text,
                    font_badge,
                    bg_color=minus_bg,
                    fg_color=minus_fg,
                    padding_x=int(6 * scale),
                    padding_y=int(4 * scale),
                    radius=int(8 * scale),
                ) + int(6 * scale)

            y_pos = row_bottom + row_gap

        y_pos += int(8 * scale)
        return y_pos

    # Порядок групп
    groups_order: List[Tuple[str, List[Tuple[int, dict]], str]] = [
        ("ГОРОД (КРАСНЫЕ):", red_slots, "red"),
        ("МАФИЯ (ЧЁРНЫЕ):", black_slots, "black"),
        ("БЕЗ КОМАНДЫ:", other_slots, "none"),
    ]

    if winner_team == "red":
        groups_order = [
            ("ГОРОД (КРАСНЫЕ):", red_slots, "red"),
            ("МАФИЯ (ЧЁРНЫЕ):", black_slots, "black"),
            ("БЕЗ КОМАНДЫ:", other_slots, "none"),
        ]
    elif winner_team == "black":
        groups_order = [
            ("МАФИЯ (ЧЁРНЫЕ):", black_slots, "black"),
            ("ГОРОД (КРАСНЫЕ):", red_slots, "red"),
            ("БЕЗ КОМАНДЫ:", other_slots, "none"),
        ]

    for title, group, key in groups_order:
        y = draw_group(title, group, y, team_key=key)

    # Блок убийств
    if night_kills_order:
        y += int(10 * scale)
        draw.line(
            [(card_x1, y), (card_x2, y)],
            fill=(44, 62, 80),
            width=int(1 * scale),
        )
        y += int(14 * scale)

        kills_title = "Убийства (ночные завещания):"
        draw.text(
            (card_x1, y),
            kills_title,
            fill=(189, 195, 199),
            font=font_group,
        )
        _, kh = _text_size(draw, kills_title, font_group)
        y += kh + int(8 * scale)

        for killed_slot in night_kills_order:
            info = slots.get(killed_slot) or {}
            proto_text = (info.get("will_protocol_raw") or "").strip()
            if not proto_text:
                proto_text = "нет"
            proto_pts = float(info.get("will_protocol_points", 0.0) or 0.0)
            op_text = (info.get("will_opinion") or "").strip()
            if not op_text:
                op_text = "нет"
            op_pts = float(info.get("will_opinion_points", 0.0) or 0.0)

            block_top = y
            block_bottom = y + int(80 * scale)

            _draw_rounded_rect(
                draw,
                card_x1,
                block_top,
                card_x2,
                block_bottom,
                radius=int(12 * scale),
                outline=(35, 35, 35),
                fill=(20, 20, 20),
                width=int(1 * scale),
            )

            x_text = card_x1 + int(14 * scale)
            y_text = block_top + int(8 * scale)

            kill_title = f"Убийство слота {killed_slot}"
            draw.text(
                (x_text, y_text),
                kill_title,
                fill=(236, 240, 241),
                font=font_small,
            )
            _, t_h = _text_size(draw, kill_title, font_small)
            y_text += t_h + int(6 * scale)

            base_text_proto = f"Протокол — {proto_text}"
            draw.text(
                (x_text, y_text),
                base_text_proto,
                fill=(189, 195, 199),
                font=font_small,
            )
            base_w_proto = draw.textlength(base_text_proto, font=font_small)

            paren_open = " ("
            paren_open_w = draw.textlength(paren_open, font=font_small)
            draw.text(
                (x_text + base_w_proto, y_text),
                paren_open,
                fill=(189, 195, 199),
                font=font_small,
            )

            delta_proto_txt = f"{proto_pts:+.1f}"
            delta_color_proto = (
                plus_fg if proto_pts > 0 else minus_fg if proto_pts < 0 else zero_fg
            )
            draw.text(
                (x_text + base_w_proto + paren_open_w, y_text),
                delta_proto_txt,
                fill=delta_color_proto,
                font=font_small,
            )
            delta_w = draw.textlength(delta_proto_txt, font=font_small)

            draw.text(
                (x_text + base_w_proto + paren_open_w + delta_w, y_text),
                ")",
                fill=(189, 195, 199),
                font=font_small,
            )

            _, t_h2 = _text_size(draw, base_text_proto, font=font_small)
            y_text += t_h2 + int(4 * scale)

            base_text_op = f"Мнение — {op_text}"
            draw.text(
                (x_text, y_text),
                base_text_op,
                fill=(189, 195, 199),
                font=font_small,
            )
            base_w_op = draw.textlength(base_text_op, font=font_small)

            paren_open_w2 = draw.textlength(paren_open, font=font_small)
            draw.text(
                (x_text + base_w_op, y_text),
                paren_open,
                fill=(189, 195, 199),
                font=font_small,
            )

            delta_op_txt = f"{op_pts:+.1f}"
            delta_color_op = (
                plus_fg if op_pts > 0 else minus_fg if op_pts < 0 else zero_fg
            )
            draw.text(
                (x_text + base_w_op + paren_open_w2, y_text),
                delta_op_txt,
                fill=delta_color_op,
                font=font_small,
            )
            delta_w2 = draw.textlength(delta_op_txt, font=font_small)

            draw.text(
                (x_text + base_w_op + paren_open_w2 + delta_w2, y_text),
                ")",
                fill=(189, 195, 199),
                font=font_small,
            )

            y = block_bottom + int(6 * scale)

    # Сохраняем
    final_img = img.resize((base_width, base_height), resample=Image.LANCZOS)

    filename = f"endgame_summary_{game_date.replace('.', '-')}_{global_game_number}.png"
    path = os.path.join(TEMP_DIR, filename)
    final_img.save(path)

    return path