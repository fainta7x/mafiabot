# game/pic_endgame.py

import os
from typing import Dict, Tuple

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
        main = (142, 68, 173)   # фиолетовый
    elif "маф" in r:
        main = (26, 26, 26)     # глубокий графитовый для мафии
    elif "шер" in r or "шериф" in r:
        main = (46, 204, 113)   # мягкий зелёный
    elif "кр" in r or "мирн" in r or "город" in r:
        main = (192, 57, 43)    # винный красный
    else:
        main = (52, 152, 219)   # синий

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


def create_endgame_pic_summary(
    slots: Dict[int, dict],
    game_date: str,
    evening_game_number: int,
    global_game_number: int,
    winner_label: str | None,
) -> str:
    """
    Современный общий протокол игры:
      - тёмная тема, цветные рамки по ролям;
      - один выразительный номер слева;
      - soft-square итоговый балл справа;
      - аккуратные бейджи очков;
      - блок убийств с цветной подсветкой +/-.
    """
    # --- Подготовка данных по командам ---
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

    # --- Подготовка данных по убийствам ---
    night_kills_order: list[int] = []
    nk = slots.get("_night_kills_order")
    if isinstance(nk, list):
        night_kills_order = [int(x) for x in nk if isinstance(x, int)]

    # Базовый логический размер (до масштабирования)
    base_width = 1200
    base_height = 800

    # Оценка высоты
    def count_group_items(group: list[Tuple[int, dict]]) -> int:
        return len(group)

    total_items = count_group_items(red_slots) + count_group_items(black_slots) + count_group_items(other_slots)
    row_height = 80  # увеличенный для воздуха
    kills_block_height = 0
    if night_kills_order:
        kills_block_height = 40 + len(night_kills_order) * 80

    est_height = 260 + total_items * row_height + kills_block_height + 80
    base_height = max(base_height, est_height)

    # --- Рисуем в 2x для антиалиасинга ---
    scale = 2
    width = base_width * scale
    height = base_height * scale

    img = Image.new("RGB", (width, height), color=(12, 12, 12))
    draw = ImageDraw.Draw(img)

    padding_x = int(70 * scale / 2) * 2
    y = int(40 * scale)

    # Шрифты под масштаб
    font_title = _load_font(int(40 * scale / 2))
    font_subtitle = _load_font(int(24 * scale / 2))
    font_group = _load_font(int(26 * scale / 2))
    font_name = _load_font(int(30 * scale / 2))   # ник крупнее
    font_role = _load_font(int(20 * scale / 2))
    font_small = _load_font(int(20 * scale / 2))
    font_badge = _load_font(int(18 * scale / 2))
    font_total_big = _load_font(int(32 * scale / 2))  # итог крупный

    # Итог и цвет победителя
    if winner_label and "город" in winner_label.lower():
        winner_team = "red"
        result_text = "СТАТУС: ПОБЕДА КРАСНЫХ"
    elif winner_label and "маф" in winner_label.lower():
        winner_team = "black"
        result_text = "СТАТУС: ПОБЕДА ЧЁРНЫХ"
    else:
        winner_team = "none"
        result_text = "СТАТУС: БЕЗ ПОДВЕДЕНИЯ РЕЗУЛЬТАТА"

    top_accent_red = (192, 57, 43)
    # для мафии сделаем реально тёмный почти чёрный фон, как у слотов
    top_accent_black_fill = (26, 26, 26)
    top_accent_neutral = (96, 125, 139)

    if winner_team == "red":
        top_fill = top_accent_red
        top_outline = None
        top_text_color = (236, 240, 241)
    elif winner_team == "black":
        # тёмный фон как у мафии, белая рамка и белый текст
        top_fill = top_accent_black_fill
        top_outline = (240, 240, 240)
        top_text_color = (240, 240, 240)
    else:
        top_fill = top_accent_neutral
        top_outline = None
        top_text_color = (236, 240, 241)

    # Заголовок — центрируем по ширине
    title = "ПРОТОКОЛ ИГРЫ"
    title_w, title_h = _text_size(draw, title, font_title)
    title_x = width / 2
    draw.text((title_x, y), title, fill=(236, 240, 241), font=font_title, anchor="ma")
    y += title_h + int(8 * scale)

    # Плашка ИТОГ — тоже центрируем под заголовком
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
        outline=top_outline,
        fill=top_fill,
        width=int(2 * scale) if top_outline else int(1 * scale),
    )
    draw.text(
        (width / 2, res_y1 + res_pad_y),
        result_text,
        fill=top_text_color,
        font=font_subtitle,
        anchor="ma",
    )

    y = res_y2 + int(10 * scale)

    # Подзаголовок с датой и номерами (выравниваем по левому padding_x)
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

    # Общая ширина карточек (~90% ширины)
    card_width = int((card_right - card_left) * 0.92)
    card_x1 = card_left + int(((card_right - card_left) - card_width) / 2)
    card_x2 = card_x1 + card_width

    def draw_group(title: str, group: list[Tuple[int, dict]], y_pos: int, team_key: str) -> int:
        if not group:
            return y_pos

        # Заголовок с ПОБЕДОЙ/ПОРАЖЕНИЕМ
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

        # Разделительная линия
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

            accent, bg_soft = _role_color(role)

            row_top = y_pos
            row_bottom = y_pos + row_height_scaled - row_gap

            # Фон + рамка карточки
            base_bg = (
                max(bg_soft[0], 20),
                max(bg_soft[1], 20),
                max(bg_soft[2], 20),
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

            # Номер слота — один badge, крупнее ника
            slot_text = str(slot_num)
            font_slot = _load_font(int(36 * scale / 2))
            slot_w, slot_h = _text_size(draw, slot_text, font_slot)
            slot_badge_w = slot_w + int(16 * scale)
            slot_badge_h = slot_h + int(10 * scale)

            slot_x1 = inner_left
            slot_y1 = inner_top
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

            # Цвет номера:
            # - для дона — фиолетовый (accent)
            # - для обычной мафии/чёрных — белый
            # - для остальных — accent
            slot_team = (info.get("team") or "").lower()
            slot_role = (role or "").lower()
            is_black_team = "чёрн" in slot_team or "маф" in slot_role
            is_don = "дон" in slot_role

            if is_don:
                slot_color = accent
            elif is_black_team:
                slot_color = (240, 240, 240)
            else:
                slot_color = accent

            draw.text(
                ((slot_x1 + slot_x2) / 2, (slot_y1 + slot_y2) / 2 - int(1 * scale)),
                slot_text,
                fill=slot_color,
                font=font_slot,
                anchor="mm",
            )

            # Ник — начинается сразу после бейджа слота, небольшой отступ
            x_name_start = slot_x2 + int(18 * scale)

            # Ник (жирный, главный)
            draw.text(
                (x_name_start, inner_top),
                name,
                fill=(236, 240, 241),
                font=font_name,
            )
            name_w, _ = _text_size(draw, name, font_name)

            # Кружок между ником и ролью
            dot_x = x_name_start + name_w + int(10 * scale)
            dot_y = inner_top + int(10 * scale)
            dot_r = int(4 * scale)

            # Цвет точки:
            # - для дона — фиолетовый (accent)
            # - для обычной мафии — белый
            # - для остальных — accent
            if is_don:
                dot_color = accent
            elif is_black_team:
                dot_color = (240, 240, 240)
            else:
                dot_color = accent

            draw.ellipse(
                (dot_x - dot_r, dot_y - dot_r, dot_x + dot_r, dot_y + dot_r),
                fill=dot_color,
                outline=None,
            )

            # Роль (капс, меньше, немного правее и ниже)
            role_x = dot_x + int(10 * scale)
            role_y = inner_top + int(4 * scale)
            draw.text(
                (role_x, role_y),
                role_caps,
                fill=(189, 195, 199),
                font=font_role,
            )

            # Правый soft square: итоговый балл
            base_pts = float(info.get("base_points", 0.0) or 0.0)
            bonus_pts = float(info.get("bonus_points", 0.0) or 0.0)
            lh_pts = float(info.get("lh_points", 0.0) or 0.0)
            pr_pts = float(info.get("will_protocol_points", 0.0) or 0.0)
            mn_pts = float(info.get("will_opinion_points", 0.0) or 0.0)
            total_pts = round(base_pts + bonus_pts + lh_pts + pr_pts + mn_pts, 1)
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
            _draw_rounded_rect(
                draw,
                sq_x1,
                sq_y1,
                sq_x2,
                sq_y2,
                radius=int(16 * scale),
                outline=accent,
                fill=sq_fill,
                width=int(2 * scale),
            )

            # Центрирование итога строго по центру soft-square
            cx = (sq_x1 + sq_x2) / 2
            cy = (sq_y1 + sq_y2) / 2
            draw.text(
                (cx, cy - int(1 * scale)),  # лёгкий подъём на 1px в масштабе
                total_text,
                fill=(236, 240, 241),
                font=font_total_big,
                anchor="mm",
            )

            # Нижняя строка: ПУ + очки бейджами
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
                txt = f"{label}: {value}"
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

            y_pos = row_bottom + row_gap

        y_pos += int(8 * scale)
        return y_pos

    # --- Победившая команда всегда сверху ---
    groups_order: list[Tuple[str, list[Tuple[int, dict]], str]] = [
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

    # Блок "Убийства (ночные завещания)"
    if night_kills_order:
        y += int(10 * scale)
        draw.line(
            [(card_x1, y), (card_x2, y)],
            fill=(44, 62, 80),
            width=int(1 * scale),
        )
        y += int(14 * scale)

        draw.text(
            (card_x1, y),
            "Убийства (ночные завещания):",
            fill=(189, 195, 199),
            font=font_group,
        )
        _, kh = _text_size(draw, "Убийства (ночные завещания):", font_group)
        y += kh + int(8 * scale)

        for killed_slot in night_kills_order:
            info = slots.get(killed_slot) or {}
            proto_text = (info.get("will_protocol_raw") or "нет").strip()
            proto_pts = float(info.get("will_protocol_points", 0.0) or 0.0)
            op_text = (info.get("will_opinion") or "нет").strip()
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

            kill_title = f"Убийство №{killed_slot}"
            draw.text(
                (x_text, y_text),
                kill_title,
                fill=(236, 240, 241),
                font=font_small,
            )
            _, t_h = _text_size(draw, kill_title, font_small)
            y_text += t_h + int(6 * scale)

            # Протокол — разрезанная строка с цветным +/- в скобках
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

            delta_proto_txt = f"{proto_pts}"
            delta_color_proto = plus_fg if proto_pts > 0 else minus_fg if proto_pts < 0 else zero_fg
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

            # Мнение — аналогично
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

            delta_op_txt = f"{op_pts}"
            delta_color_op = plus_fg if op_pts > 0 else minus_fg if op_pts < 0 else zero_fg
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

    # --- Даунскейл для сглаживания ---
    final_img = img.resize((base_width, base_height), resample=Image.LANCZOS)

    filename = f"endgame_summary_{game_date.replace('.', '-')}_{global_game_number}.png"
    path = os.path.join(TEMP_DIR, filename)
    final_img.save(path)

    return path