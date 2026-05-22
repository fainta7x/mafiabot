import os
import time
from typing import Dict, Tuple

from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp")
os.makedirs(TEMP_DIR, exist_ok=True)


def _cleanup_old_profile_files(nickname: str, keep: int = 5):
    """Удаляет старые файлы профиля для конкретного ника, оставляя только keep последних."""
    safe_nick = "".join(ch for ch in (nickname or "player") if ch.isalnum() or ch in "._-")
    try:
        files = [
            os.path.join(TEMP_DIR, f)
            for f in os.listdir(TEMP_DIR)
            if f.startswith(f"profile_{safe_nick}") and f.endswith(".png")
        ]
        files.sort(key=os.path.getmtime)
        for f in files[:-keep]:
            os.remove(f)
            print(f"[PROFILE_IMG] Removed old file: {f}")
    except Exception as e:
        print(f"[PROFILE_IMG] Cleanup error: {e}")


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
    # Увеличиваем базовую высоту, чтобы влезло Эло
    base_w, base_h = 1200, 1050
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
    font_role = fs(28)
    font_elo = fs(44)  # шрифт для Эло
    font_elo_label = fs(28)  # шрифт для надписи "ELO РЕЙТИНГ"

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

    # ========== НОВЫЙ БЛОК: ELO РЕЙТИНГ ==========
    elo = stats.get("elo", 1500)

    # Рисуем плашку Эло в верхней части
    elo_box_h = int(60 * scale)
    elo_box_y = y
    draw.rounded_rectangle(
        (card_l, elo_box_y, card_r, elo_box_y + elo_box_h),
        radius=int(12 * scale),
        outline=(255, 193, 7),
        fill=(30, 30, 40),
        width=int(2 * scale),
    )

    # Определяем цвет для Эло в зависимости от значения
    if elo >= 1700:
        elo_color = (255, 215, 0)  # золотой
    elif elo >= 1550:
        elo_color = (192, 192, 192)  # серебряный
    elif elo >= 1400:
        elo_color = (205, 127, 50)  # бронзовый
    else:
        elo_color = (150, 150, 150)  # серый

    # Рисуем надпись "ELO РЕЙТИНГ" и значение
    draw.text(
        (card_l + int(20 * scale), elo_box_y + int(18 * scale)),
        "ELO РЕЙТИНГ",
        fill=elo_color,
        font=font_elo_label,
    )
    draw.text(
        (card_r - int(20 * scale), elo_box_y + int(12 * scale)),
        str(elo),
        fill=elo_color,
        font=font_elo,
        anchor="ra",
    )

    y = elo_box_y + elo_box_h + int(16 * scale)
    # ========== КОНЕЦ БЛОКА ЭЛО ==========

    # Общая статистика (левый блок)
    left_x1, left_x2 = card_l, card_l + int((card_r - card_l) * 0.48)
    block_h = int(320 * scale)
    block_y = y

    draw.rounded_rectangle(
        (left_x1, block_y, left_x2, block_y + block_h),
        radius=int(18 * scale),
        outline=(45, 48, 57),
        fill=(26, 28, 34),
        width=int(1 * scale),
    )

    pad = int(18 * scale)
    x_in = left_x1 + pad
    y_in = block_y + pad

    draw.text((x_in, y_in), "Общая статистика:", fill=(189, 195, 199), font=font_block)
    y_in += _text_size(draw, "Общая статистика:", font_block)[1] + int(12 * scale)

    # Базовые данные
    games = stats.get("games_played", 0)
    wins = stats.get("games_won", 0)
    winrate = stats.get("winrate", 0.0)
    win_points = stats.get("win_points_sum", 0.0)
    avg_pts = stats.get("avg_points", 0.0)
    discipline = stats.get("discipline_minus_sum", 0.0)

    col_gap = int(40 * scale)
    col_w = (left_x2 - left_x1 - 2 * pad - col_gap) // 2
    col1_x, col2_x = x_in, x_in + col_w + col_gap

    # Статистика в две колонки
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
    draw.rounded_rectangle(
        (x_in, by1, left_x2 - pad, by2),
        radius=int(10 * scale),
        fill=(41, 54, 74),
        outline=(60, 70, 90),
        width=int(1 * scale),
    )

    pts_text = f"Баллы за победы: {win_points}"
    draw.text(
        (x_in + int(12 * scale), by1 + int(4 * scale)),
        pts_text,
        fill=(236, 240, 241),
        font=font_text,
    )

    # Штрафы
    y_in = by2 + int(6 * scale)
    draw.text(
        (x_in, y_in),
        f"Дисципл. штрафы: {1 if discipline else 0} | сумма: {_fmt_float(discipline, 1)}",
        fill=(192, 57, 43),
        font=font_text,
    )
    y_in += _text_size(draw, "Дисципл. штрафы: x | сумма: 0.0", font=font_text)[1] + int(6 * scale)

    # Доп. статистика игрока
    pu_count = int(stats.get("pu_count", 0) or 0)
    avg_lh = float(stats.get("avg_lh", 0.0) or 0.0)
    removed_count = int(stats.get("removed_count", 0) or 0)
    techfouls_total = int(stats.get("techfouls_total", 0) or 0)
    ppk_guilty_count = int(stats.get("ppk_guilty_count", 0) or 0)

    draw.text(
        (x_in, y_in),
        "Доп. статистика:",
        fill=(189, 195, 199),
        font=font_text,
    )
    y_in += _text_size(draw, "Доп. статистика:", font=font_text)[1] + int(4 * scale)

    extra_lines = [
        f"ПУ: {pu_count}",
        f"Среднее ЛХ: {_fmt_float(avg_lh, 2)}",
        f"Удалён (всего): {removed_count}",
        f"Техфолы (шт.): {techfouls_total}",
        f"Виновник ППК: {ppk_guilty_count}",
    ]
    for line in extra_lines:
        draw.text((x_in, y_in), line, fill=(189, 195, 199), font=font_text)
        y_in += _text_size(draw, line, font=font_text)[1] + int(2 * scale)

    # Протоколы и мнения (правый блок)
    right_x1 = card_l + int((card_r - card_l) * 0.52)
    right_x2 = card_r

    draw.rounded_rectangle(
        (right_x1, block_y, right_x2, block_y + block_h),
        radius=int(18 * scale),
        outline=(45, 48, 57),
        fill=(26, 28, 34),
        width=int(1 * scale),
    )

    x_in = right_x1 + pad
    y_in = block_y + pad

    draw.text(
        (x_in, y_in),
        "Качество протоколов и мнений:",
        fill=(189, 195, 199),
        font=font_block,
    )
    y_in += _text_size(draw, "Качество протоколов и мнений:", font_block)[1] + int(10 * scale)

    col_w = (right_x2 - right_x1 - 2 * pad - int(16 * scale)) // 2
    proto_x, mn_x = x_in, x_in + col_w + int(16 * scale)

    draw.text((proto_x, y_in), "Протокол", fill=(236, 240, 241), font=font_text)
    draw.text((mn_x, y_in), "Мнение", fill=(236, 240, 241), font=font_text)
    y_in += _text_size(draw, "Протокол", font=font_text)[1] + int(6 * scale)

    # Данные ПР/МН
    pr_avg = stats.get("pr_avg", 0.0)
    pr_plus_cnt, pr_plus_sum = stats.get("pr_plus_count", 0), stats.get("pr_plus_sum", 0.0)
    pr_minus_cnt, pr_minus_sum = stats.get("pr_minus_count", 0), stats.get("pr_minus_sum", 0.0)
    mn_avg = stats.get("mn_avg", 0.0)
    mn_plus_cnt, mn_plus_sum = stats.get("mn_plus_count", 0), stats.get("mn_plus_sum", 0.0)
    mn_minus_cnt, mn_minus_sum = stats.get("mn_minus_count", 0), stats.get("mn_minus_sum", 0.0)

    draw.text(
        (proto_x, y_in),
        f"ср. балл: {_fmt_float(pr_avg, 2)}",
        fill=(189, 195, 199),
        font=font_text,
    )
    draw.text(
        (mn_x, y_in),
        f"ср. балл: {_fmt_float(mn_avg, 2)}",
        fill=(189, 195, 199),
        font=font_text,
    )
    y_in += _text_size(draw, "ср. балл: 0.00", font=font_text)[1] + int(4 * scale)

    draw.text(
        (proto_x, y_in),
        f"+ ({pr_plus_cnt}) | сумма: {_fmt_float(pr_plus_sum, 2)}",
        fill=(46, 204, 113),
        font=font_text,
    )
    draw.text(
        (mn_x, y_in),
        f"+ ({mn_plus_cnt}) | сумма: {_fmt_float(mn_plus_sum, 2)}",
        fill=(46, 204, 113),
        font=font_text,
    )
    y_in += _text_size(draw, "+ (0) | сумма: 0.00", font=font_text)[1] + int(4 * scale)

    draw.text(
        (proto_x, y_in),
        f"- ({pr_minus_cnt}) | сумма: {_fmt_float(pr_minus_sum, 2)}",
        fill=(231, 76, 60),
        font=font_text,
    )
    draw.text(
        (mn_x, y_in),
        f"- ({mn_minus_cnt}) | сумма: {_fmt_float(mn_minus_sum, 2)}",
        fill=(231, 76, 60),
        font=font_text,
    )

    # Разделитель перед ролями
    y = block_y + block_h + int(24 * scale)
    draw.line([(card_l, y), (card_r, y)], fill=(44, 62, 80), width=int(1 * scale))
    y += int(16 * scale)

    # Статистика по ролям
    roles_all = stats.get("roles", {}) or {}
    # Убираем полностью "Не задана"
    roles = {k: v for k, v in roles_all.items() if k != "Не задана"}
    draw.text((card_l, y), "Статистика по ролям:", fill=(189, 195, 199), font=font_block)
    y += _text_size(draw, "Статистика по ролям:", font_block)[1] + int(10 * scale)

    col_gap = int(20 * scale)
    col_w = (card_r - card_l - col_gap) // 2
    card_h = int(120 * scale)  # фиксированная, но умеренная высота
    gap_y = int(12 * scale)

    # Не больше 4 ролей, чтобы всё гарантированно влезло (2×2)
    for idx, (role_name, rstats) in enumerate(list(roles.items())[:4]):
        col, row = idx % 2, idx // 2
        x1 = card_l + col * (col_w + col_gap)
        x2 = x1 + col_w
        y1 = y + row * (card_h + gap_y)
        y2 = y1 + card_h

        accent, bg_soft = _role_color(role_name)

        draw.rounded_rectangle(
            (x1, y1, x2, y2),
            radius=int(14 * scale),
            outline=accent,
            fill=(24, 27, 33),
            width=int(2 * scale),
        )

        inner_pad = int(14 * scale)
        rx = x1 + inner_pad
        ry = y1 + inner_pad

        # Заголовок роли (всегда белым, чтобы не потерялся на фоне)
        draw.text(
            (rx, ry),
            role_name,
            fill=(236, 240, 241),
            font=font_role,
        )
        ry += _text_size(draw, role_name, font=font_role)[1] + int(4 * scale)

        games_r = rstats.get("games", 0)
        wins_r = rstats.get("wins", 0)
        wr_r = rstats.get("winrate", 0.0)
        avg_r = rstats.get("avg_points", 0.0)
        bonus_sum = rstats.get("bonus_sum", 0.0)
        lh_sum = rstats.get("lh_sum", 0.0)

        lines_role = [
            f"Игр: {games_r} | Побед: {wins_r} ({_fmt_pct(wr_r)})",
            f"Средний балл: {_fmt_float(avg_r, 2)}",
            f"Допы (суммарно): {_fmt_float(bonus_sum, 1)}",
        ]
        # ЛХ только для Мирных/Шерифа
        if role_name in ("Мирный", "Шериф"):
            lines_role.append(f"ЛХ (суммарно): {_fmt_float(lh_sum, 1)}")

        for line in lines_role:
            draw.text((rx, ry), line, fill=(189, 195, 199), font=font_text)
            ry += _text_size(draw, line, font=font_text)[1] + int(2 * scale)

    # Сохраняем файл
    safe_nick = "".join(ch for ch in (player_nickname or "player") if ch.isalnum() or ch in "._-")
    ts = int(time.time())
    filename = f"profile_{safe_nick}_{ts}.png"
    out_path = os.path.join(TEMP_DIR, filename)
    img.save(out_path, "PNG", optimize=True)

    _cleanup_old_profile_files(player_nickname, keep=5)

    return out_path