"""Genera icon.ico (multi-resolution) per il launcher MarketAI."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent / "icon.ico"


def make_icon(size: int) -> Image.Image:
    """Disegna un'icona quadrata size×size con tema 'analisi finanziaria'."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Sfondo: gradiente blu scuro → blu acceso (rounded square)
    radius = int(size * 0.20)
    bg_top = (15, 23, 42)       # slate-900
    bg_bot = (29, 78, 216)      # blue-700
    for y in range(size):
        t = y / max(size - 1, 1)
        r = int(bg_top[0] + (bg_bot[0] - bg_top[0]) * t)
        g = int(bg_top[1] + (bg_bot[1] - bg_top[1]) * t)
        b = int(bg_top[2] + (bg_bot[2] - bg_top[2]) * t)
        d.line([(0, y), (size, y)], fill=(r, g, b, 255))

    # Maschera angoli arrotondati
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, 0, size, size), radius=radius, fill=255)
    img.putalpha(mask)

    # Candele (chart) — 3 candele bull/bear/bull
    pad = int(size * 0.18)
    chart_w = size - 2 * pad
    chart_h = int(size * 0.55)
    chart_top = int(size * 0.22)

    candle_w = int(chart_w / 5)
    gap = int((chart_w - 3 * candle_w) / 2)

    # Candela 1 (bullish — verde)
    x1 = pad
    body1 = (x1, chart_top + int(chart_h * 0.35),
             x1 + candle_w, chart_top + int(chart_h * 0.85))
    wick1 = (x1 + candle_w // 2, chart_top + int(chart_h * 0.10),
             x1 + candle_w // 2, chart_top + int(chart_h * 0.95))
    d.line(wick1, fill=(34, 197, 94, 255), width=max(1, size // 64))
    d.rectangle(body1, fill=(34, 197, 94, 255))

    # Candela 2 (bearish — rossa)
    x2 = x1 + candle_w + gap
    body2 = (x2, chart_top + int(chart_h * 0.20),
             x2 + candle_w, chart_top + int(chart_h * 0.65))
    wick2 = (x2 + candle_w // 2, chart_top + int(chart_h * 0.05),
             x2 + candle_w // 2, chart_top + int(chart_h * 0.80))
    d.line(wick2, fill=(239, 68, 68, 255), width=max(1, size // 64))
    d.rectangle(body2, fill=(239, 68, 68, 255))

    # Candela 3 (bullish forte — verde)
    x3 = x2 + candle_w + gap
    body3 = (x3, chart_top + int(chart_h * 0.10),
             x3 + candle_w, chart_top + int(chart_h * 0.50))
    wick3 = (x3 + candle_w // 2, chart_top + int(chart_h * 0.02),
             x3 + candle_w // 2, chart_top + int(chart_h * 0.65))
    d.line(wick3, fill=(34, 197, 94, 255), width=max(1, size // 64))
    d.rectangle(body3, fill=(34, 197, 94, 255))

    # Linea trend dorata sopra le candele
    trend = [
        (x1 + candle_w // 2, chart_top + int(chart_h * 0.35)),
        (x2 + candle_w // 2, chart_top + int(chart_h * 0.20)),
        (x3 + candle_w // 2, chart_top + int(chart_h * 0.10)),
    ]
    d.line(trend, fill=(250, 204, 21, 255), width=max(2, size // 32))
    for px, py in trend:
        r = max(2, size // 32)
        d.ellipse((px - r, py - r, px + r, py + r), fill=(250, 204, 21, 255))

    # Etichetta "AI" in basso
    try:
        font_size = max(8, int(size * 0.16))
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size)
    except OSError:
        font = ImageFont.load_default()
    text = "AI"
    bbox = d.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (size - tw) // 2 - bbox[0]
    ty = size - th - int(size * 0.10) - bbox[1]
    d.text((tx, ty), text, fill=(255, 255, 255, 255), font=font)

    return img


def main() -> None:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [make_icon(s) for s in sizes]
    # Salva come ICO multi-risoluzione
    images[-1].save(
        OUT,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[:-1],
    )
    print(f"OK: {OUT}  ({OUT.stat().st_size} bytes)")
    # Salva anche un PNG 256 per anteprima
    images[-1].save(OUT.with_suffix(".png"), format="PNG")


if __name__ == "__main__":
    main()
