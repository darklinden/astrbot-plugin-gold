"""Pillow-based gold price card renderer.

Matches the Rust bot's SVG layout: dark-blue header, four metal sections
with colored indicators, OHLC data, color-coded change percentages.
"""

import io
import os
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from .main import CachedData, PriceData, OUNCE_TO_GRAM

# ── Layout constants (2x for Retina quality) ──────────────────────────────

SCALE = 2

W = 880 * SCALE             # card width
PX = 36 * SCALE             # horizontal padding
HH = 56 * SCALE             # header height
RH = 36 * SCALE             # section label row height
SG = 20 * SCALE             # section gap
CR = 12 * SCALE             # corner radius
BP = 16 * SCALE             # bottom padding

# Column offsets for the last line (change / prev close / update)
C1 = PX
C2 = PX + 200 * SCALE
C3 = PX + 420 * SCALE

# ── Colors ─────────────────────────────────────────────────────────────────

C_BG = (255, 255, 255)
C_HEADER = (26, 35, 126)
C_HEADER_TEXT = (255, 255, 255)
C_SECTION_BG = (245, 245, 245)
C_GOLD_DOT = (255, 215, 0)
C_SILVER_DOT = (192, 192, 192)
C_PRICE = (34, 34, 34)
C_LABEL = (51, 51, 51)
C_OHLC = (85, 85, 85)
C_SOURCE = (153, 153, 153)
C_RED = (229, 57, 53)
C_GREEN = (67, 160, 71)
C_GRAY = (136, 136, 136)

# ── Fonts ──────────────────────────────────────────────────────────────────

_FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "SourceHanSans-Regular.otf")

def _load_fonts():
    try:
        return {
            "title":  ImageFont.truetype(_FONT_PATH, 22 * SCALE),
            "label":  ImageFont.truetype(_FONT_PATH, 15 * SCALE),
            "price":  ImageFont.truetype(_FONT_PATH, 22 * SCALE),
            "detail": ImageFont.truetype(_FONT_PATH, 14 * SCALE),
            "source": ImageFont.truetype(_FONT_PATH, 12 * SCALE),
        }
    except Exception:
        d = ImageFont.load_default()
        return dict.fromkeys(("title", "label", "price", "detail", "source"), d)

F = _load_fonts()


# ── Helpers ────────────────────────────────────────────────────────────────

def _change_color(pct_str: str):
    trimmed = pct_str.strip().rstrip("%")
    if trimmed == "N/A" or not trimmed:
        return C_GRAY
    try:
        v = float(trimmed)
    except ValueError:
        return C_GRAY
    if v > 0:
        return C_RED
    if v < 0:
        return C_GREEN
    return C_GRAY


def _section_h(data: Optional[PriceData]) -> int:
    """Return the pixel height of one metal section."""
    if data is not None:
        return RH + 38 * SCALE + 30 * SCALE + 30 * SCALE  # 268
    return RH + 36 * SCALE  # 144


def _draw_section(
    draw: ImageDraw.Draw,
    y0: int,
    label: str,
    unit: str,
    dot_color: tuple,
    data: Optional[PriceData],
    converted_cny: Optional[str],
) -> int:
    """Draw one metal section. Returns pixel height consumed."""

    # ── Gray label bar ──
    draw.rectangle([(0, y0), (W, y0 + RH)], fill=C_SECTION_BG)

    # Dot indicator
    dot_cx = PX + 12
    dot_cy = y0 + RH // 2
    r = 12
    draw.ellipse([(dot_cx - r, dot_cy - r),
                  (dot_cx + r, dot_cy + r)], fill=dot_color)

    # Label text
    draw.text((PX + 36, dot_cy), label, fill=C_LABEL, font=F["label"],
              anchor="lm")

    y = y0 + RH

    if data is None:
        draw.text((C1, y + 26 * SCALE // 2), "暂无数据",
                  fill=C_SOURCE, font=F["detail"], anchor="lm")
        return _section_h(None)

    # ── Price ──
    if converted_cny:
        price_text = f"{data.price} {unit} (≈ {converted_cny}元/克)"
    else:
        price_text = f"{data.price} {unit}"

    y_mid = y + 19 * SCALE
    draw.text((C1, y_mid), price_text, fill=C_PRICE, font=F["price"],
              anchor="lm")
    y += 38 * SCALE

    # ── OHLC ──
    ohlc = (f"开盘: {data.open_price}  最高: {data.high_price}  "
            f"最低: {data.low_price}")
    y_mid = y + 15 * SCALE
    draw.text((C1, y_mid), ohlc, fill=C_OHLC, font=F["detail"], anchor="lm")
    y += 30 * SCALE

    # ── Change / Prev close / Update ──
    pct_color = _change_color(data.change_percent)
    y_mid = y + 15 * SCALE
    draw.text((C1, y_mid), f"涨跌: {data.change_percent}",
              fill=pct_color, font=F["detail"], anchor="lm")
    draw.text((C2, y_mid),
              f"昨收: {data.prev_close_price}",
              fill=C_OHLC, font=F["detail"], anchor="lm")
    draw.text((C3, y_mid), data.update,
              fill=C_SOURCE, font=F["detail"], anchor="lm")
    y += 30 * SCALE

    return y - y0


# ── Public API ─────────────────────────────────────────────────────────────

def build_card(data: CachedData, usd_cny_rate: Optional[float]) -> bytes:
    """Render a gold-price card PNG and return the raw bytes."""

    # Pre-calculate USD→CNY conversions
    gold_usd_cny: Optional[str] = None
    silver_usd_cny: Optional[str] = None
    if usd_cny_rate:
        if data.gold_usd and data.gold_usd.price not in (None, "N/A"):
            try:
                gold_usd_cny = f"{float(data.gold_usd.price) * usd_cny_rate / OUNCE_TO_GRAM:.2f}"
            except (ValueError, TypeError):
                pass
        if data.silver_usd and data.silver_usd.price not in (None, "N/A"):
            try:
                silver_usd_cny = f"{float(data.silver_usd.price) * usd_cny_rate / OUNCE_TO_GRAM:.2f}"
            except (ValueError, TypeError):
                pass

    # ── Calculate total height ──
    source1_h = 24 * SCALE
    source2_h = 24 * SCALE
    top_gap = 8 * SCALE
    seg_gap = 4 * SCALE

    total_h = (
        HH + top_gap
        + source1_h
        + _section_h(data.gold_cny) + seg_gap
        + _section_h(data.silver_cny)
        + SG
        + source2_h
        + _section_h(data.gold_usd) + seg_gap
        + _section_h(data.silver_usd)
        + BP
    )

    # ── Create image ──
    img = Image.new("RGBA", (W, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Card background (white rounded rect)
    draw.rounded_rectangle([(0, 0), (W, total_h)], radius=CR, fill=C_BG)

    # Header (rounded top; bottom corners will show white card bg)
    draw.rounded_rectangle([(0, 0), (W, HH)], radius=CR, fill=C_HEADER)
    draw.text((PX, HH // 2), "今日金银价格", fill=C_HEADER_TEXT,
              font=F["title"], anchor="lm")

    y = HH + top_gap  # 128

    # ── Source 1 ──
    draw.text((PX, y + source1_h // 2),
              "数据来源: Jisu API (jisuapi.com)",
              fill=C_SOURCE, font=F["source"], anchor="lm")
    y += source1_h

    # ── Gold CNY ──
    y += _draw_section(draw, y, "黄金 (国内)", "元/克", C_GOLD_DOT,
                       data.gold_cny, None)
    y += seg_gap

    # ── Silver CNY ──
    y += _draw_section(draw, y, "白银 (国内)", "元/克", C_SILVER_DOT,
                       data.silver_cny, None)
    y += SG

    # ── Source 2 ──
    draw.text((PX, y + source2_h // 2),
              "数据来源: GoldAPI (gold-api.com) / CurrencyAPI (currencyapi.net)",
              fill=C_SOURCE, font=F["source"], anchor="lm")
    y += source2_h

    # ── Gold USD ──
    y += _draw_section(draw, y, "黄金 (国际)", "USD/盎司", C_GOLD_DOT,
                       data.gold_usd, gold_usd_cny)
    y += seg_gap

    # ── Silver USD ──
    y += _draw_section(draw, y, "白银 (国际)", "USD/盎司", C_SILVER_DOT,
                       data.silver_usd, silver_usd_cny)

    # Export to PNG bytes
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
