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


def _fmt_pct(value) -> str:
    return f"{float(value or 0):.1f}%"


def _fmt_float(value, digits: int = 2) -> str:
    return f"{float(value or 0):.{digits}f}"


def create_profile_pic(player_nickname: str, stats: Dict) -> str:
    # Размеры
    base_w, base_h = 1200, 900
    scale = 2
    w, h = base_w * scale, base_h * scale

    img = Image.new("RGB", (w, h), (10, 11, 14))
    draw = ImageDraw.Draw(img)

    # Шрифты
    fs = lambda s: _load_font(int(s * scale / 2))
    font_title = fs(52)
    font_subtitle = fs(30)
    font_block = fs(30)
    font_text = fs(24)
    font_big = fs(38)
    font_winrate = fs(28)
    font_role = fs(28)

    padding = int(70 * scale / 2) * 2
    y = int(40 * scale)

    # Заголовок
    title = "ПРОФИЛЬ ИГРОКА"
    draw.text((w / 2, y), title, fill=(236, 240, 241), font=font_title, anchor="ma")
    y += _text_size(draw, title, font_title)[1] + int(6 * scale)

    nick = (player_nickname or "Без ника").strip()
    draw.text((w / 2, y), nick, fill=(189, 195, 199), font=font_subtitle, anchor="ma")
    y += _text_size(draw, nick, font_subtitle)[1] + int(16 * scale)

    card_l, card_r = padding, w - padding
    draw.line([(card_l, y), (card_r, y)], fill=(44, 62, 80), width=int(1 * scale))
    y += int(16 * scale)

    # Общая статистика (левый блок)
    left_x1, left_x2 = card_l, card_l + int((card_r - card_l) * 0.48)
    block_h = int(260 * scale)
    block_y = y

    draw.rounded_rectangle((left_x1, block_y, left_x2, block_y + block_h),
                           radius=int(18 * scale), outline=(45, 48, 57), fill=(26, 28, 34), width=int(1 * scale))

    pad = int(18 * scale)
    x_in = left_x1 + pad
    y_in = block_y + pad

    draw.text((x_in, y_in), "Общая статистика:", fill=(189, 195, 199), font=font_block)
    y_in += _text_size(draw, "Общая статистика:", font_block)[1] + int(12 * scale)

    # Данные
    games = stats.get("games_played", 0)
    wins = stats.get("games_won", 0)
    winrate = stats.get("winrate", 0.0)
    win_points = stats.get("win_points_sum", 0.0)
    avg_pts = stats.get("avg_points", 0.0)
    discipline = stats.get("discipline_minus_sum", 0.0)

    col_gap = int(40 * scale)
    col_w = (left_x2 - left_x1 - 2 * pad - col_gap) // 2
    col1_x, col2_x = x_in, x_in + col_w + col_gap

    # Рисуем статистику в две колонки
    y1, y2 = y_in, y_in
    for label, val in [("Сыграно игр", games), ("Выиграно", wins)]:
        draw.text((col1_x, y1), str(val), fill=(236, 240, 241), font=font_big)
        y1 += _text_size(draw, str(val), font_big)[1] + int(4 * scale)
        draw.text((col1_x, y1), label, fill=(149, 165, 166), font=font_text)
        y1 += _text_size(draw, label, font_text)[1] + int(10 * scale)

    for label, val in [("Винрейт", _fmt_pct(winrate)), ("Средний балл", _fmt_float(avg_pts, 2))]:
        draw.text((col2_x, y2), str(val), fill=(236, 240, 241), font=font_big)
        y2 += _text_size(draw, str(val), font_big)[1] + int(4 * scale)
        draw.text((col2_x, y2), label, fill=(149, 165, 166), font=font_text)
        y2 += _text_size(draw, label, font_text)[1] + int(10 * scale)

    y_in = max(y1, y2) + int(8 * scale)

    # Плашка баллов
    by1 = y_in + int(4 * scale)
    by2 = by1 + int(20 * scale)
    draw.rounded_rectangle((x_in, by1, left_x2 - pad, by2), radius=int(10 * scale),
                           fill=(41, 54, 74), outline=(60, 70, 90), width=int(1 * scale))

    pts_text = f"Баллы за победы: {win_points}"
    draw.text((x_in + int(12 * scale), by1 + int(4 * scale)), pts_text,
              fill=(236, 240, 241), font=font_text)

    # Штрафы
    y_in = by2 + int(6 * scale)
    draw.text((x_in, y_in), f"Дисципл. штрафы: {1 if discipline else 0} | сумма: {_fmt_float(discipline, 1)}",
              fill=(192, 57, 43), font=font_text)

    # Протоколы и мнения (правый блок)
    right_x1 = card_l + int((card_r - card_l) * 0.52)
    right_x2 = card_r

    draw.rounded_rectangle((right_x1, block_y, right_x2, block_y + block_h),
                           radius=int(18 * scale), outline=(45, 48, 57), fill=(26, 28, 34), width=int(1 * scale))

    x_in = right_x1 + pad
    y_in = block_y + pad

    draw.text((x_in, y_in), "Качество протоколов и мнений:", fill=(189, 195, 199), font=font_block)
    y_in += _text_size(draw, "Качество протоколов и мнений:", font_block)[1] + int(10 * scale)

    col_w = (right_x2 - right_x1 - 2 * pad - int(16 * scale)) // 2
    proto_x, mn_x = x_in, x_in + col_w + int(16 * scale)

    draw.text((proto_x, y_in), "Протокол", fill=(236, 240, 241), font=font_text)
    draw.text((mn_x, y_in), "Мнение", fill=(236, 240, 241), font=font_text)
    y_in += _text_size(draw, "Протокол", font_text)[1] + int(6 * scale)

    # Данные ПР/МН
    pr_avg = stats.get("pr_avg", 0.0)
    pr_plus_cnt, pr_plus_sum = stats.get("pr_plus_count", 0), stats.get("pr_plus_sum", 0.0)
    pr_minus_cnt, pr_minus_sum = stats.get("pr_minus_count", 0), stats.get("pr_minus_sum", 0.0)
    mn_avg = stats.get("mn_avg", 0.0)
    mn_plus_cnt, mn_plus_sum = stats.get("mn_plus_count", 0), stats.get("mn_plus_sum", 0.0)
    mn_minus_cnt, mn_minus_sum = stats.get("mn_minus_count", 0), stats.get("mn_minus_sum", 0.0)

    draw.text((proto_x, y_in), f"ср. балл: {_fmt_float(pr_avg, 2)}", fill=(189, 195, 199), font=font_text)
    draw.text((mn_x, y_in), f"ср. балл: {_fmt_float(mn_avg, 2)}", fill=(189, 195, 199), font=font_text)
    y_in += _text_size(draw, "ср. балл: 0.00", font_text)[1] + int(4 * scale)

    draw.text((proto_x, y_in), f"+ ({pr_plus_cnt}) | сумма: {_fmt_float(pr_plus_sum, 2)}",
              fill=(46, 204, 113), font=font_text)
    draw.text((mn_x, y_in), f"+ ({mn_plus_cnt}) | сумма: {_fmt_float(mn_plus_sum, 2)}",
              fill=(46, 204, 113), font=font_text)
    y_in += _text_size(draw, "+ (0) | сумма: 0.00", font_text)[1] + int(4 * scale)

    draw.text((proto_x, y_in), f"- ({pr_minus_cnt}) | сумма: {_fmt_float(pr_minus_sum, 2)}",
              fill=(231, 76, 60), font=font_text)
    draw.text((mn_x, y_in), f"- ({mn_minus_cnt}) | сумма: {_fmt_float(mn_minus_sum, 2)}",
              fill=(231, 76, 60), font=font_text)

    # Разделитель перед ролями
    y = block_y + block_h + int(24 * scale)
    draw.line([(card_l, y), (card_r, y)], fill=(44, 62, 80), width=int(1 * scale))
    y += int(16 * scale)

    # Статистика по ролям
    roles = stats.get("roles", {}) or {}
    draw.text((card_l, y), "Статистика по ролям:", fill=(189, 195, 199), font=font_block)
    y += _text_size(draw, "Статистика по ролям:", font_block)[1] + int(10 * scale)

    col_gap = int(20 * scale)
    col_w = (card_r - card_l - col_gap) // 2
    card_h = int(135 * scale)
    gap_y = int(10 * scale)

    for idx, (role_name, rstats) in enumerate(list(roles.items())[:6]):
        col, row = idx % 2, idx // 2
        x1 = card_l + col * (col_w + col_gap)
        x2 = x1 + col_w
        y1 = y + row * (card_h + gap_y)

        accent, bg_soft = _role_color(role_name)
        is_unknown = "не задана" in role_name.lower()

        draw.rounded_rectangle((x1, y1, x2, y1 + card_h), radius=int(14 * scale),
                               outline=accent if not is_unknown else (80, 90, 110),
                               fill=tuple(max(c, 18) for c in bg_soft), width=int(1 * scale))

        ix, iy = x1 + int(14 * scale), y1 + int(8 * scale)

        # Название роли
        draw.text((ix, iy), role_name, fill=(236, 240, 241) if not is_unknown else (180, 185, 195), font=font_role)
        rn_w, rn_h = _text_size(draw, role_name, font_role)
        dot_r = int(4 * scale)
        draw.ellipse((ix + rn_w + int(10 * scale) - dot_r, iy + rn_h // 2 - dot_r,
                      ix + rn_w + int(10 * scale) + dot_r, iy + rn_h // 2 + dot_r), fill=accent)

        iy += rn_h + int(4 * scale)

        # Винрейт и прогресс-бар
        r_winrate = rstats.get("winrate", 0.0)
        wr_text = _fmt_pct(r_winrate)
        draw.text((x2 - int(18 * scale), iy - int(4 * scale)), wr_text,
                  fill=(236, 240, 241), font=font_winrate, anchor="ra")

        bar_x1, bar_x2 = ix, x2 - int(16 * scale)
        bar_y = iy + _text_size(draw, wr_text, font_winrate)[1] + int(4 * scale)
        bar_h = int(6 * scale)

        draw.rounded_rectangle((bar_x1, bar_y, bar_x2, bar_y + bar_h), radius=int(3 * scale), fill=(35, 45, 55))
        fill_w = bar_x1 + (bar_x2 - bar_x1) * min(max(r_winrate, 0), 100) / 100.0
        draw.rounded_rectangle((bar_x1, bar_y, fill_w, bar_y + bar_h), radius=int(3 * scale), fill=accent)

        iy = bar_y + bar_h + int(6 * scale)

        # Строки статистики
        r_games = rstats.get("games", 0)
        r_wins = rstats.get("wins", 0)
        r_avg = rstats.get("avg_points", 0.0)
        r_bonus = rstats.get("bonus_sum", 0.0)
        r_lh = rstats.get("lh_sum", 0.0)

        draw.text((ix, iy), f"Игр: {r_games}  •  Побед: {r_wins}", fill=(236, 240, 241), font=font_text)
        iy += _text_size(draw, f"Игр: {r_games}  •  Побед: {r_wins}", font_text)[1] + int(2 * scale)

        line2 = f"Средний балл: {_fmt_float(r_avg, 2)}  •  Допы: {_fmt_float(r_bonus, 1)}"
        if r_lh:
            line2 += f"  •  ЛХ: {_fmt_float(r_lh, 1)}"
        draw.text((ix, iy), line2, fill=(189, 195, 199) if not is_unknown else (140, 145, 155), font=font_text)

    # Сохранение
    final = img.resize((int(base_w), int(base_h)), Image.LANCZOS)
    safe_nick = "".join(ch for ch in (player_nickname or "player") if ch.isalnum() or ch in "._-")
    path = os.path.join(TEMP_DIR, f"profile_{safe_nick}.png")
    final.save(path)
    return path