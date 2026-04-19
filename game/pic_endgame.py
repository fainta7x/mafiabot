import os
from typing import Dict, Tuple

from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp")
os.makedirs(TEMP_DIR, exist_ok=True)


def _load_font(size: int):
    for fname in ("Montserrat-SemiBold.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(fname, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _shorten(text: str, max_len: int = 20) -> str:
    text = (text or "").strip()
    return text if len(text) <= max_len else text[:max_len - 1] + "…"


def _role_color(role: str) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
    r = (role or "").lower()
    if "дон" in r:
        main = (142, 68, 173)
    elif "маф" in r:
        main = (26, 26, 26)
    elif "шер" in r or "шериф" in r:
        main = (46, 204, 113)
    elif "кр" in r or "мирн" in r or "город" in r:
        main = (192, 57, 43)
    else:
        main = (52, 152, 219)
    bg = (int(main[0] * 0.20), int(main[1] * 0.20), int(main[2] * 0.20))
    return main, bg


def _text_size(draw, text: str, font) -> Tuple[int, int]:
    try:
        bbox = font.getbbox(text)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        return draw.textsize(text, font=font)


def _draw_badge(draw, x, y, text, font, bg_color, fg_color=(0, 0, 0), pad_x=8, pad_y=4, radius=8):
    w, h = _text_size(draw, text, font)
    x1, y1 = x, y
    x2, y2 = x + w + pad_x * 2, y + h + pad_y * 2
    draw.rounded_rectangle((x1, y1, x2, y2), radius=radius, fill=bg_color, outline=None)
    draw.text((x1 + pad_x, y1 + pad_y), text, fill=fg_color, font=font)
    return x2


def create_endgame_pic_summary(slots: Dict[int, dict], game_date: str, evening_game_number: int,
                                global_game_number: int, winner_label: str | None) -> str:
    # Подготовка данных
    red, black, other = [], [], []
    for num, info in slots.items():
        if isinstance(num, str) and num.startswith("_"):
            continue
        if not isinstance(num, int):
            continue
        team = info.get("team")
        if team == "Красные":
            red.append((num, info))
        elif team == "Чёрные":
            black.append((num, info))
        else:
            other.append((num, info))

    red.sort(key=lambda x: x[0])
    black.sort(key=lambda x: x[0])
    other.sort(key=lambda x: x[0])

    night_kills = [int(x) for x in slots.get("_night_kills_order", []) if isinstance(x, int)]

    # Размеры
    base_w, base_h = 1200, 800
    row_h = 80
    est_h = 260 + len(red + black + other) * row_h + (40 + len(night_kills) * 80 if night_kills else 0) + 80
    base_h = max(base_h, est_h)

    scale = 2
    w, h = base_w * scale, base_h * scale
    img = Image.new("RGB", (w, h), (12, 12, 12))
    draw = ImageDraw.Draw(img)

    padding = int(70 * scale / 2) * 2
    y = int(40 * scale)

    # Шрифты
    fs = lambda s: _load_font(int(s * scale / 2))
    font_title = fs(40)
    font_sub = fs(24)
    font_group = fs(26)
    font_name = fs(30)
    font_role = fs(20)
    font_small = fs(20)
    font_badge = fs(18)
    font_big = fs(32)
    font_slot = fs(36)

    # Определяем победителя
    if winner_label and "город" in winner_label.lower():
        winner_team = "red"
        result = "СТАТУС: ПОБЕДА КРАСНЫХ"
    elif winner_label and "маф" in winner_label.lower():
        winner_team = "black"
        result = "СТАТУС: ПОБЕДА ЧЁРНЫХ"
    else:
        winner_team = "none"
        result = "СТАТУС: БЕЗ ПОДВЕДЕНИЯ РЕЗУЛЬТАТА"

    # Заголовок
    draw.text((w / 2, y), "ПРОТОКОЛ ИГРЫ", fill=(236, 240, 241), font=font_title, anchor="ma")
    y += _text_size(draw, "ПРОТОКОЛ ИГРЫ", font_title)[1] + int(8 * scale)

    # Плашка результата
    res_w, res_h = _text_size(draw, result, font_sub)
    pad_x, pad_y = int(10 * scale), int(4 * scale)
    res_x1 = w / 2 - (res_w + pad_x * 2) / 2
    res_y1 = y
    res_x2 = res_x1 + res_w + pad_x * 2
    res_y2 = res_y1 + res_h + pad_y * 2

    if winner_team == "red":
        fill, outline, text_color = (192, 57, 43), None, (236, 240, 241)
    elif winner_team == "black":
        fill, outline, text_color = (26, 26, 26), (240, 240, 240), (240, 240, 240)
    else:
        fill, outline, text_color = (96, 125, 139), None, (236, 240, 241)

    draw.rounded_rectangle((res_x1, res_y1, res_x2, res_y2), radius=int(10 * scale),
                           outline=outline, fill=fill, width=int(2 * scale) if outline else int(1 * scale))
    draw.text((w / 2, res_y1 + pad_y), result, fill=text_color, font=font_sub, anchor="ma")
    y = res_y2 + int(10 * scale)

    # Информация об игре
    draw.text((padding, y), f"Игра №{evening_game_number} • {game_date}", fill=(189, 195, 199), font=font_sub)
    y += _text_size(draw, f"Игра №{evening_game_number} • {game_date}", font_sub)[1] + int(4 * scale)
    draw.text((padding, y), f"№{global_game_number} по истории", fill=(149, 165, 166), font=font_sub)
    y += _text_size(draw, f"№{global_game_number} по истории", font_sub)[1] + int(10 * scale)

    # Разделитель
    card_l, card_r = padding, w - padding
    draw.line([(card_l, y), (card_r, y)], fill=(44, 62, 80), width=int(1 * scale))
    y += int(12 * scale)

    # Константы для отрисовки
    card_w = int((card_r - card_l) * 0.92)
    card_x1 = card_l + int(((card_r - card_l) - card_w) / 2)
    card_x2 = card_x1 + card_w
    row_gap = int(10 * scale)
    row_h_scaled = int(row_h * scale)

    plus_bg, plus_fg = (46, 125, 50), (236, 240, 241)
    zero_bg, zero_fg = (55, 71, 79), (189, 195, 199)
    minus_bg, minus_fg = (183, 28, 28), (248, 249, 249)
    pu_bg, pu_fg = (255, 193, 7), (33, 33, 33)

    def draw_group(title, group, team_key, y_pos):
        if not group:
            return y_pos

        # Заголовок группы
        suffix = " — ПОБЕДА" if winner_team == team_key else " — ПОРАЖЕНИЕ" if winner_team in ("red", "black") and team_key in ("red", "black") and winner_team != team_key else ""
        draw.text((card_x1, y_pos), title + suffix, fill=(189, 195, 199), font=font_group)
        y_pos += _text_size(draw, title + suffix, font_group)[1] + int(6 * scale)
        draw.line([(card_x1, y_pos), (card_x2, y_pos)], fill=(35, 35, 35), width=int(1 * scale))
        y_pos += int(10 * scale)

        for slot_num, info in group:
            name = _shorten(info.get("nickname") or info.get("full_name") or "Без имени", 22)
            role = info.get("role", "Не задана")
            accent, bg_soft = _role_color(role)

            row_top, row_bottom = y_pos, y_pos + row_h_scaled - row_gap
            draw.rounded_rectangle((card_x1, row_top, card_x2, row_bottom), radius=int(18 * scale),
                                   outline=accent, fill=tuple(max(c, 20) for c in bg_soft), width=int(2 * scale))

            inner_l = card_x1 + int(16 * scale)
            inner_t = row_top + int(10 * scale)

            # Номер слота
            slot_w, slot_h = _text_size(draw, str(slot_num), font_slot)
            badge_w = slot_w + int(16 * scale)
            badge_h = slot_h + int(10 * scale)
            draw.rounded_rectangle((inner_l, inner_t, inner_l + badge_w, inner_t + badge_h),
                                   radius=int(10 * scale), fill=(33, 33, 33))

            slot_team = (info.get("team") or "").lower()
            slot_role = (role or "").lower()
            is_don = "дон" in slot_role
            is_black = "чёрн" in slot_team or "маф" in slot_role
            slot_color = accent if is_don else (240, 240, 240) if is_black else accent

            draw.text((inner_l + badge_w / 2, inner_t + badge_h / 2 - int(1 * scale)),
                      str(slot_num), fill=slot_color, font=font_slot, anchor="mm")

            # Имя и роль
            name_x = inner_l + badge_w + int(18 * scale)
            draw.text((name_x, inner_t), name, fill=(236, 240, 241), font=font_name)
            name_w = _text_size(draw, name, font_name)[0]

            dot_r = int(4 * scale)
            draw.ellipse((name_x + name_w + int(10 * scale) - dot_r, inner_t + int(10 * scale) - dot_r,
                          name_x + name_w + int(10 * scale) + dot_r, inner_t + int(10 * scale) + dot_r),
                         fill=accent if is_don else (240, 240, 240) if is_black else accent)

            draw.text((name_x + name_w + int(20 * scale), inner_t + int(4 * scale)),
                      role.upper(), fill=(189, 195, 199), font=font_role)

            # Итоговый балл
            total = round(sum(float(info.get(k, 0) or 0) for k in
                             ["base_points", "bonus_points", "lh_points", "will_protocol_points", "will_opinion_points"]), 1)
            tw, th = _text_size(draw, str(total), font_big)
            sq_w, sq_h = tw + int(32 * scale), th + int(16 * scale)
            sq_x1, sq_x2 = card_x2 - int(16 * scale) - sq_w, card_x2 - int(16 * scale)
            sq_y1, sq_y2 = row_top + int(14 * scale), row_top + int(14 * scale) + sq_h
            draw.rounded_rectangle((sq_x1, sq_y1, sq_x2, sq_y2), radius=int(16 * scale),
                                   outline=accent, fill=(25, 25, 25), width=int(2 * scale))
            draw.text(((sq_x1 + sq_x2) / 2, (sq_y1 + sq_y2) / 2 - int(1 * scale)),
                      str(total), fill=(236, 240, 241), font=font_big, anchor="mm")

            # Бейджи
            bx = name_x
            by = row_top + int(row_h_scaled * 0.56)

            if info.get("pu_mark"):
                bx = _draw_badge(draw, bx, by, "ПУ", font_badge, pu_bg, pu_fg, pad_x=int(6 * scale), pad_y=int(4 * scale), radius=int(8 * scale)) + int(6 * scale)

            for label, key in [("Игра", "base_points"), ("Доп", "bonus_points"), ("ЛХ", "lh_points"),
                               ("ПР", "will_protocol_points"), ("МН", "will_opinion_points")]:
                val = float(info.get(key, 0) or 0)
                if val > 0:
                    bx = _draw_badge(draw, bx, by, f"{label}: {val}", font_badge, plus_bg, plus_fg, pad_x=int(6 * scale), pad_y=int(4 * scale), radius=int(8 * scale)) + int(6 * scale)
                elif val < 0:
                    bx = _draw_badge(draw, bx, by, f"{label}: {val}", font_badge, minus_bg, minus_fg, pad_x=int(6 * scale), pad_y=int(4 * scale), radius=int(8 * scale)) + int(6 * scale)
                else:
                    bx = _draw_badge(draw, bx, by, f"{label}: {val}", font_badge, zero_bg, zero_fg, pad_x=int(6 * scale), pad_y=int(4 * scale), radius=int(8 * scale)) + int(6 * scale)

            y_pos = row_bottom + row_gap

        return y_pos + int(8 * scale)

    # Порядок отрисовки
    groups = [("ГОРОД (КРАСНЫЕ):", red, "red"), ("МАФИЯ (ЧЁРНЫЕ):", black, "black"), ("БЕЗ КОМАНДЫ:", other, "none")]
    if winner_team == "black":
        groups = [("МАФИЯ (ЧЁРНЫЕ):", black, "black"), ("ГОРОД (КРАСНЫЕ):", red, "red"), ("БЕЗ КОМАНДЫ:", other, "none")]

    for title, group, key in groups:
        y = draw_group(title, group, key, y)

    # Убийства
    if night_kills:
        y += int(10 * scale)
        draw.line([(card_x1, y), (card_x2, y)], fill=(44, 62, 80), width=int(1 * scale))
        y += int(14 * scale)
        draw.text((card_x1, y), "Убийства (ночные завещания):", fill=(189, 195, 199), font=font_group)
        y += _text_size(draw, "Убийства (ночные завещания):", font_group)[1] + int(8 * scale)

        for killed in night_kills:
            info = slots.get(killed, {})
            proto_text = (info.get("will_protocol_raw") or "нет").strip()
            proto_pts = float(info.get("will_protocol_points", 0) or 0)
            op_text = (info.get("will_opinion") or "нет").strip()
            op_pts = float(info.get("will_opinion_points", 0) or 0)

            block_bottom = y + int(80 * scale)
            draw.rounded_rectangle((card_x1, y, card_x2, block_bottom), radius=int(12 * scale),
                                   outline=(35, 35, 35), fill=(20, 20, 20), width=int(1 * scale))

            tx = card_x1 + int(14 * scale)
            ty = y + int(8 * scale)
            draw.text((tx, ty), f"Убийство №{killed}", fill=(236, 240, 241), font=font_small)
            ty += _text_size(draw, f"Убийство №{killed}", font_small)[1] + int(6 * scale)

            # Протокол с очками
            base = f"Протокол — {proto_text}"
            draw.text((tx, ty), base, fill=(189, 195, 199), font=font_small)
            base_w = draw.textlength(base, font=font_small)
            draw.text((tx + base_w, ty), " (", fill=(189, 195, 199), font=font_small)
            pts_color = plus_fg if proto_pts > 0 else minus_fg if proto_pts < 0 else zero_fg
            draw.text((tx + base_w + draw.textlength(" (", font=font_small), ty), f"{proto_pts}", fill=pts_color, font=font_small)
            draw.text((tx + base_w + draw.textlength(" (", font=font_small) + draw.textlength(str(proto_pts), font=font_small), ty), ")", fill=(189, 195, 199), font=font_small)
            ty += _text_size(draw, base, font_small)[1] + int(4 * scale)

            # Мнение с очками
            base2 = f"Мнение — {op_text}"
            draw.text((tx, ty), base2, fill=(189, 195, 199), font=font_small)
            base_w2 = draw.textlength(base2, font=font_small)
            draw.text((tx + base_w2, ty), " (", fill=(189, 195, 199), font=font_small)
            pts_color2 = plus_fg if op_pts > 0 else minus_fg if op_pts < 0 else zero_fg
            draw.text((tx + base_w2 + draw.textlength(" (", font=font_small), ty), f"{op_pts}", fill=pts_color2, font=font_small)
            draw.text((tx + base_w2 + draw.textlength(" (", font=font_small) + draw.textlength(str(op_pts), font=font_small), ty), ")", fill=(189, 195, 199), font=font_small)

            y = block_bottom + int(6 * scale)

    # Сохранение
    final = img.resize((base_w, base_h), Image.LANCZOS)
    path = os.path.join(TEMP_DIR, f"endgame_summary_{game_date.replace('.', '-')}_{global_game_number}.png")
    final.save(path)
    return path