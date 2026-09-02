"""Generate placeholder card art for the First Hawaiian Priority Destinations
World Elite Mastercard added to Alex's demo wallet.

We cannot vendor the issuer's real card image here, so this renders a clean,
brand-styled placeholder at the same 306x192 footprint as the other card art,
embossed with the demo persona name. Provenance is recorded in
app/static/cards/SOURCES.md. Re-run to regenerate:

    python scripts/make_first_hawaiian_art.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "cards" / "first_hawaiian_priority_destinations.webp"
W, H = 306, 192
PERSONA = "ALEX MORGAN"


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = (
        ["arialbd.ttf", "Arialbd.ttf", "DejaVuSans-Bold.ttf"]
        if bold
        else ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf"]
    )
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _gradient(top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    base = Image.new("RGB", (W, H), top)
    draw = ImageDraw.Draw(base)
    for y in range(H):
        t = y / (H - 1)
        draw.line(
            [(0, y), (W, y)],
            fill=tuple(int(top[c] + (bottom[c] - top[c]) * t) for c in range(3)),
        )
    return base


def main() -> None:
    # First Hawaiian Bank teal/green brand direction.
    img = _gradient((15, 76, 74), (8, 38, 42))
    draw = ImageDraw.Draw(img, "RGBA")

    # Subtle wave motif so it does not read as a flat rectangle.
    for i in range(-1, 5):
        y = 70 + i * 26
        draw.arc([(-60, y), (W + 60, y + 130)], 200, 340, fill=(255, 255, 255, 18), width=10)

    draw.text((18, 16), "First Hawaiian", font=_font(19, bold=True), fill=(255, 255, 255))
    draw.text((18, 40), "Priority Destinations", font=_font(12), fill=(196, 230, 224))

    # EMV chip.
    draw.rounded_rectangle([(20, 74), (52, 100)], radius=5, fill=(214, 197, 138))
    draw.rounded_rectangle([(20, 74), (52, 100)], radius=5, outline=(150, 132, 84), width=1)

    draw.text((18, 120), "•••• •••• •••• 4028", font=_font(15, bold=True), fill=(238, 244, 242))
    draw.text((18, 150), PERSONA, font=_font(12, bold=True), fill=(214, 232, 228))
    draw.text((150, 150), "WORLD ELITE", font=_font(9, bold=True), fill=(206, 224, 220))

    # Mastercard interlocking circles.
    cx, cy, r = 250, 150, 15
    draw.ellipse([(cx - r - 9, cy - r), (cx - 9 + r, cy + r)], fill=(235, 90, 60, 235))
    draw.ellipse([(cx + 9 - r, cy - r), (cx + 9 + r, cy + r)], fill=(245, 166, 35, 210))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, "WEBP", quality=90)
    print(f"Wrote {OUT} ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main()
