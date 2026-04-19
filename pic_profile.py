import os
from typing import Dict, Tuple

from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp")
os.makedirs(TEMP_DIR, exist_ok=True)


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """
    Унифицированная загрузка шрифта.
    Положи Montserrat-SemiBold.ttf рядом с файлом для красивого вида.
    """
    for fname in ("Montserrat-SemiBold.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(fname, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _role_color(role: str) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
    """
    Цвет акцента по роли: (основной цвет, мягкий фон).
    Совместимо с pic_endgame.py.
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
        main = (52, 152, 219)   # синий / базовый

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


def _fmt_pct(value: float | int | None) -> str:
    if value is None:
        return "0.0%"
    return f"{float(value):.1f}%"


def _fmt_float(value: float | int | None, digits: int = 2) -> str:
    if value is None:
        return f"0.{ '0' * digits }"
    fmt = f"{{:.{digits}f}}"
    return fmt.format(float(value))


def create_profile_pic(
    player_nickname: str,
    stats: Dict,
) -> str:
    """
    Рендер карточки профиля игрока.
    Упор на сетку, читаемость и акценты на цифрах.
    """
    # --- Базовые размеры ---
    base_width = 1200
    base_height = 900

    scale = 2
    width = base_width * scale
    height = base_height * scale

    img = Image.new("RGB", (width, height), color=(10, 11, 14))
    draw = ImageDraw.Draw(img)

    padding_x = int(70 * scale / 2) * 2
    y = int(40 * scale)

    # --- Шрифты ---
    font_title = _load_font(int(52 * scale / 2))
    font_subtitle = _load_font(int(30 * scale / 2))
    font_block_title = _load_font(int(30 * scale / 2))
    font_text = _load_font(int(24 * scale / 2))
    font_big_number = _load_font(int(38 * scale / 2))
    font_badge = _load_font(int(22 * scale / 2))
    font_winrate_big = _load_font(int(28 * scale / 2))   # чуть меньше
    font_role_title = _load_font(int(28 * scale / 2))    # для названий ролей

    # Цвета фонов карточек
    card_fill = (26, 28, 34)      # #1A1C22
    card_outline = (45, 48, 57)   # #2D3039

    # --- Заголовок: ПРОФИЛЬ ИГРОКА ---
    title = "ПРОФИЛЬ ИГРОКА"
    title_x = width / 2
    _, title_h = _text_size(draw, title, font_title)
    draw.text(
        (title_x, y),
        title,
        fill=(236, 240, 241),
        font=font_title,
        anchor="ma",
    )
    y += title_h + int(6 * scale)

    # Ник игрока
    nick_text = (player_nickname or "Без ника").strip()
    _, nick_h = _text_size(draw, nick_text, font_subtitle)
    draw.text(
        (title_x, y),
        nick_text,
        fill=(189, 195, 199),
        font=font_subtitle,
        anchor="ma",
    )
    y += nick_h + int(16 * scale)

    # Разделитель
    card_left = padding_x
    card_right = width - padding_x
    draw.line(
        [(card_left, y), (card_right, y)],
        fill=(44, 62, 80),
        width=int(1 * scale),
    )
    y += int(16 * scale)

    # --- Блок 1: Общая статистика (слева) ---
    left_col_x1 = card_left
    left_col_x2 = card_left + int((card_right - card_left) * 0.48)

    block_height = int(260 * scale)
    block1_top = y
    block1_bottom = block1_top + block_height

    _draw_rounded_rect(
        draw,
        left_col_x1,
        block1_top,
        left_col_x2,
        block1_bottom,
        radius=int(18 * scale),
        outline=card_outline,
        fill=card_fill,
        width=int(1 * scale),
    )

    inner_pad = int(18 * scale)
    x_inner = left_col_x1 + inner_pad
    y_inner = block1_top + inner_pad

    draw.text(
        (x_inner, y_inner),
        "Общая статистика:",
        fill=(189, 195, 199),
        font=font_block_title,
    )
    _, bh = _text_size(draw, "Общая статистика:", font_block_title)
    y_inner += bh + int(12 * scale)

    games_played = stats.get("games_played", 0)
    games_won = stats.get("games_won", 0)
    winrate = stats.get("winrate", 0.0)
    win_points_sum = stats.get("win_points_sum", 0.0)
    avg_points = stats.get("avg_points", 0.0)
    discipline_minus_sum = stats.get("discipline_minus_sum", 0.0)

    col_gap = int(40 * scale)
    col_width = (left_col_x2 - left_col_x1 - 2 * inner_pad - col_gap) // 2
    col1_x = x_inner
    col2_x = x_inner + col_width + col_gap

    def draw_big_stat(x: int, y_pos: int, label: str, value_text: str) -> int:
        draw.text(
            (x, y_pos),
            value_text,
            fill=(236, 240, 241),
            font=font_big_number,
        )
        _, val_h = _text_size(draw, value_text, font_big_number)
        y_label = y_pos + val_h + int(4 * scale)
        draw.text(
            (x, y_label),
            label,
            fill=(149, 165, 166),
            font=font_text,
        )
        _, lab_h = _text_size(draw, label, font_text)
        return y_label + lab_h + int(10 * scale)

    y_inner_col1 = y_inner
    y_inner_col2 = y_inner

    y_inner_col1 = draw_big_stat(col1_x, y_inner_col1, "Сыграно игр", str(games_played))
    y_inner_col1 = draw_big_stat(col1_x, y_inner_col1, "Выиграно", str(games_won))

    y_inner_col2 = draw_big_stat(col2_x, y_inner_col2, "Винрейт", _fmt_pct(winrate))
    y_inner_col2 = draw_big_stat(col2_x, y_inner_col2, "Средний балл за игру", _fmt_float(avg_points, 2))

    y_inner = max(y_inner_col1, y_inner_col2) + int(8 * scale)

    # --- Плашка "Баллы за победы" ---
    badge_y1 = y_inner + int(4 * scale)
    badge_y2 = badge_y1 + int(40 * scale / 2)
    badge_x1 = x_inner
    badge_x2 = left_col_x2 - inner_pad

    _draw_rounded_rect(
        draw,
        badge_x1,
        badge_y1,
        badge_x2,
        badge_y2,
        radius=int(10 * scale),
        fill=(41, 54, 74),
        outline=(60, 70, 90),
        width=int(1 * scale),
    )

    # Чистый текст без спецсимволов
    win_points_str = f"Баллы за победы: {win_points_sum}".strip()
    label_w, label_h = _text_size(draw, win_points_str, font_text)
    label_x = badge_x1 + int(12 * scale)
    label_y = badge_y1 + (badge_y2 - badge_y1 - label_h) // 2

    draw.text(
        (label_x, label_y),
        win_points_str,
        fill=(236, 240, 241),
        font=font_text,
    )

    # Дисциплинарные штрафы под плашкой
    y_inner = badge_y2 + int(6 * scale)
    disc_text = f"Дисципл. штрафы: {0 if discipline_minus_sum == 0 else 1} | сумма: {_fmt_float(discipline_minus_sum, 1)}"
    # Здесь count захардкожен как пример (0/1). В боевой версии подставь реальное количество.
    draw.text(
        (x_inner, y_inner),
        disc_text,
        fill=(192, 57, 43),  # тускло-красный
        font=font_text,
    )

    # --- Блок 2: Протоколы и мнения (справа) ---
    right_col_x1 = card_left + int((card_right - card_left) * 0.52)
    right_col_x2 = card_right

    block2_top = y
    block2_bottom = block2_top + block_height

    _draw_rounded_rect(
        draw,
        right_col_x1,
        block2_top,
        right_col_x2,
        block2_bottom,
        radius=int(18 * scale),
        outline=card_outline,
        fill=card_fill,
        width=int(1 * scale),
    )

    x2_inner = right_col_x1 + inner_pad
    y2_inner = block2_top + inner_pad

    draw.text(
        (x2_inner, y2_inner),
        "Качество протоколов и мнений:",
        fill=(189, 195, 199),
        font=font_block_title,
    )
    _, bh2 = _text_size(draw, "Качество протоколов и мнений:", font_block_title)
    y2_inner += bh2 + int(10 * scale)

    pr_avg = stats.get("pr_avg", 0.0)
    pr_minus_count = stats.get("pr_minus_count", 0)
    pr_minus_sum = stats.get("pr_minus_sum", 0.0)
    pr_plus_count = stats.get("pr_plus_count", 0)
    pr_plus_sum = stats.get("pr_plus_sum", 0.0)

    mn_avg = stats.get("mn_avg", 0.0)
    mn_minus_count = stats.get("mn_minus_count", 0)
    mn_minus_sum = stats.get("mn_minus_sum", 0.0)
    mn_plus_count = stats.get("mn_plus_count", 0)
    mn_plus_sum = stats.get("mn_plus_sum", 0.0)

    # Две колонки: Протокол / Мнение
    col_width_pm = int((right_col_x2 - right_col_x1 - 2 * inner_pad - int(16 * scale)) / 2)
    proto_x = x2_inner
    mn_x = x2_inner + col_width_pm + int(16 * scale)

    draw.text(
        (proto_x, y2_inner),
        "Протокол",
        fill=(236, 240, 241),
        font=font_text,
    )
    draw.text(
        (mn_x, y2_inner),
        "Мнение",
        fill=(236, 240, 241),
        font=font_text,
    )
    _, hdr_h = _text_size(draw, "Протокол", font_text)
    row_y = y2_inner + hdr_h + int(6 * scale)

    # ср. балл
    draw.text(
        (proto_x, row_y),
        f"ср. балл: {_fmt_float(pr_avg, 2)}",
        fill=(189, 195, 199),
        font=font_text,
    )
    draw.text(
        (mn_x, row_y),
        f"ср. балл: {_fmt_float(mn_avg, 2)}",
        fill=(189, 195, 199),
        font=font_text,
    )
    _, row_h = _text_size(draw, "ср. балл: 0.00", font_text)
    row_y += row_h + int(4 * scale)

    # плюсы
    plus_color = (46, 204, 113)
    pr_plus_text = f"+ ({pr_plus_count}) | сумма: {_fmt_float(pr_plus_sum, 2)}"
    mn_plus_text = f"+ ({mn_plus_count}) | сумма: {_fmt_float(mn_plus_sum, 2)}"

    draw.text(
        (proto_x, row_y),
        pr_plus_text,
        fill=plus_color,
        font=font_text,
    )
    draw.text(
        (mn_x, row_y),
        mn_plus_text,
        fill=plus_color,
        font=font_text,
    )
    _, row_h2 = _text_size(draw, "+ (0) | сумма: 0.00", font_text)
    row_y += row_h2 + int(4 * scale)

    # минусы
    minus_color = (231, 76, 60)
    pr_minus_text = f"- ({pr_minus_count}) | сумма: {_fmt_float(pr_minus_sum, 2)}"
    mn_minus_text = f"- ({mn_minus_count}) | сумма: {_fmt_float(mn_minus_sum, 2)}"

    draw.text(
        (proto_x, row_y),
        pr_minus_text,
        fill=minus_color,
        font=font_text,
    )
    draw.text(
        (mn_x, row_y),
        mn_minus_text,
        fill=minus_color,
        font=font_text,
    )

    # --- Между верхними блоками и ролями ---
    y = max(block1_bottom, block2_bottom) + int(24 * scale)

    draw.line(
        [(card_left, y), (card_right, y)],
        fill=(44, 62, 80),
        width=int(1 * scale),
    )
    y += int(16 * scale)

    # --- Блок 3: Статистика по ролям ---
    roles = stats.get("roles", {}) or {}

    draw.text(
        (card_left, y),
        "Статистика по ролям:",
        fill=(189, 195, 199),
        font=font_block_title,
    )
    _, roles_title_h = _text_size(draw, "Статистика по ролям:", font_block_title)
    y += roles_title_h + int(10 * scale)

    col_gap_x = int(20 * scale)
    col_width_roles = int((card_right - card_left - col_gap_x) / 2)
    role_card_height = int(135 * scale)
    role_gap_y = int(10 * scale)

    role_items = list(roles.items())

    for idx, (role_name, rstats) in enumerate(role_items):
        col = idx % 2
        row = idx // 2

        x1 = card_left + col * (col_width_roles + col_gap_x)
        x2 = x1 + col_width_roles
        y1 = y + row * (role_card_height + role_gap_y)
        y2 = y1 + role_card_height

        accent, bg_soft = _role_color(role_name)

        bg_card = (
            max(bg_soft[0], 18),
            max(bg_soft[1], 18),
            max(bg_soft[2], 18),
        )

        is_unknown = "не задана" in role_name.lower()

        border_color = accent if not is_unknown else (80, 90, 110)
        text_main_color = (236, 240, 241) if not is_unknown else (180, 185, 195)
        text_secondary_color = (189, 195, 199) if not is_unknown else (140, 145, 155)

        _draw_rounded_rect(
            draw,
            x1,
            y1,
            x2,
            y2,
            radius=int(14 * scale),
            outline=border_color,
            fill=bg_card,
            width=int(1 * scale),
        )

        inner_rx = x1 + int(14 * scale)
        inner_ry = y1 + int(8 * scale)

        # Название роли (крупнее) + кружочек
        draw.text(
            (inner_rx, inner_ry),
            role_name,
            fill=text_main_color,
            font=font_role_title,
        )
        rn_w, rn_h = _text_size(draw, role_name, font_role_title)

        dot_r = int(4 * scale)
        dot_x = inner_rx + rn_w + int(10 * scale)
        dot_y = inner_ry + rn_h // 2
        draw.ellipse(
            (dot_x - dot_r, dot_y - dot_r, dot_x + dot_r, dot_y + dot_r),
            fill=accent,
            outline=None,
        )

        inner_ry += rn_h + int(4 * scale)

        r_games = rstats.get("games", 0)
        r_wins = rstats.get("wins", 0)
        r_winrate = rstats.get("winrate", 0.0)
        r_avg = rstats.get("avg_points", 0.0)
        r_bonus = rstats.get("bonus_sum", 0.0)
        r_lh = rstats.get("lh_sum", 0.0)

        # Винрейт — правый акцент, чуть выше прогресс-бара
        winrate_text = _fmt_pct(r_winrate)
        wr_w, wr_h = _text_size(draw, winrate_text, font_winrate_big)
        right_padding = int(18 * scale)
        winrate_x = x2 - right_padding
        # принудительно приподнимаем над шкалой (смещение вверх)
        winrate_y = inner_ry - int(4 * scale)

        draw.text(
            (winrate_x, winrate_y),
            winrate_text,
            fill=text_main_color,
            font=font_winrate_big,
            anchor="ra",
        )

        # Прогресс-бар строго под числом
        bar_margin_x = int(16 * scale)
        bar_x1 = inner_rx
        bar_x2 = x2 - bar_margin_x
        bar_y1 = winrate_y + wr_h + int(4 * scale)
        bar_y2 = bar_y1 + int(6 * scale)

        # фон бара
        draw.rounded_rectangle(
            (bar_x1, bar_y1, bar_x2, bar_y2),
            radius=int(3 * scale),
            fill=(35, 45, 55),
            outline=None,
        )

        pct = max(0.0, min(float(r_winrate), 100.0))
        fill_x2 = bar_x1 + (bar_x2 - bar_x1) * pct / 100.0

        # псевдо-градиент: нижний слой чуть светлее, верхний — accent
        mid_color = (
            min(accent[0] + 20, 255),
            min(accent[1] + 20, 255),
            min(accent[2] + 20, 255),
        )
        draw.rounded_rectangle(
            (bar_x1, bar_y1, fill_x2, bar_y2),
            radius=int(3 * scale),
            fill=mid_color,
            outline=None,
        )
        draw.rounded_rectangle(
            (bar_x1, bar_y1, fill_x2, bar_y2),
            radius=int(3 * scale),
            fill=accent,
            outline=None,
        )

        inner_ry = bar_y2 + int(6 * scale)

        line1 = f"Игр: {r_games}  •  Побед: {r_wins}"
        line2 = f"Средний балл: {_fmt_float(r_avg, 2)}  •  Допы: {_fmt_float(r_bonus, 1)}"
        if r_lh:
            line2 += f"  •  ЛХ: {_fmt_float(r_lh, 1)}"

        draw.text(
            (inner_rx, inner_ry),
            line1,
            fill=text_main_color,
            font=font_text,
        )
        _, l1_h = _text_size(draw, line1, font_text)
        inner_ry += l1_h + int(2 * scale)

        draw.text(
            (inner_rx, inner_ry),
            line2,
            fill=text_secondary_color,
            font=font_text,
        )

    # --- Даунскейл ---
    final_img = img.resize((base_width, base_height), resample=Image.LANCZOS)

    safe_nick = "".join(ch for ch in (player_nickname or "player") if ch.isalnum() or ch in "._-")
    filename = f"profile_{safe_nick}.png"
    path = os.path.join(TEMP_DIR, filename)
    final_img.save(path)

    print("[PROFILE_IMG] Saved profile image to:", path)

    return path