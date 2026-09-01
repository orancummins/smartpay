"""Replace the placeholder cardholder name on the vendored card art.

Citi's product shots are embossed with "LINDA WALKER", their marketing placeholder.
On a dashboard about Alex Morgan that reads as a bug, so this rewrites the name to
match the demo persona.

The name is bright text on a darker card, so it is found by luminance inside a
region of interest rather than by hardcoded pixel boxes, then removed by diffusing
the surrounding colour inward -- which suits these backgrounds because they are
smooth gradients and soft textures rather than hard detail.

Originals are kept in ``_original/`` so the edit is reversible and auditable.
Run:  python scripts/restyle_card_art.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402

CARDS = config.ROOT / "app" / "static" / "cards"
ORIGINALS = CARDS / "_original"

NEW_NAME = "ALEX MORGAN"

#: (filename, region of interest as fractions of w/h, luminance threshold, layout)
#: The ROI keeps the search away from logos and the Mastercard mark, which are also
#: bright; only the embossed name lives inside these boxes.
#:
#: Thresholds are per-card and measured, not guessed. These cards are silver, so a
#: single global threshold masks half the background: on the Strata the name sits
#: above ~210 while the card body reads ~90-165, and the AAdvantage art is brighter
#: again. Measure the luminance percentiles inside the ROI before changing one.
#: ``solid`` clears the whole name box instead of tracing each glyph. The
#: AAdvantage art is a topographic line texture, so a glyph-shaped mask leaves both
#: a readable ghost of "LINDA" between the new letters and a patchwork of smoothed
#: and untouched texture. Clearing the box outright is uniform, and at the size the
#: card is displayed the lost texture is invisible.
TARGETS = [
    ("citi_strata_premier.webp", (0.02, 0.78, 0.55, 0.98), 210, "one-line", False),
    ("citi_double_cash.webp", (0.02, 0.78, 0.55, 0.98), 185, "one-line", False),
    ("citi_aa_platinum_select.webp", (0.345, 0.42, 0.60, 0.68), 198, "two-line", True),
]

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
]


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def find_text_mask(img: Image.Image, roi: tuple, threshold: int) -> Image.Image:
    """Mask the bright pixels inside the region of interest."""
    w, h = img.size
    x0, y0, x1, y1 = int(roi[0] * w), int(roi[1] * h), int(roi[2] * w), int(roi[3] * h)
    grey = img.convert("L")
    mask = Image.new("L", img.size, 0)
    px, mp = grey.load(), mask.load()
    for y in range(y0, y1):
        for x in range(x0, x1):
            if px[x, y] >= threshold:
                mp[x, y] = 255
    # Grow the mask so anti-aliased edges of the glyphs are covered too. This is not
    # cosmetic: at a tighter radius the faint outline of "LINDA" stayed legible
    # underneath the replacement on the AAdvantage art.
    return mask.filter(ImageFilter.MaxFilter(7))


def solidify(mask: Image.Image, pad: int = 5, feather: int = 7) -> Image.Image:
    """Turn a glyph mask into a soft-edged rectangle covering all of it."""
    box = mask.getbbox()
    if box is None:
        return mask
    x0, y0, x1, y1 = box
    solid = Image.new("L", mask.size, 0)
    ImageDraw.Draw(solid).rectangle(
        (x0 - pad, y0 - pad, x1 + pad, y1 + pad), fill=255
    )
    # Feathered so the cleared area fades into the surrounding texture rather than
    # ending on a visible straight edge.
    return solid.filter(ImageFilter.GaussianBlur(feather))


def inpaint(img: Image.Image, mask: Image.Image, passes: int = 14) -> Image.Image:
    """Diffuse surrounding colour into the masked area.

    Repeated blur-and-restore: each pass pulls unmasked colour one step further in,
    so a smooth gradient closes over seamlessly. Cheap, and right for these
    backgrounds -- there is no hard detail under the name to reconstruct.
    """
    out = img.convert("RGB")
    for _ in range(passes):
        blurred = out.filter(ImageFilter.GaussianBlur(2))
        out = Image.composite(blurred, out, mask)
    return out


def draw_name(img: Image.Image, mask: Image.Image, layout: str) -> Image.Image:
    """Print the persona's name where the placeholder was, matching its scale."""
    box = mask.getbbox()
    if box is None:
        return img
    x0, y0, x1, y1 = box
    draw = ImageDraw.Draw(img)

    if layout == "two-line":
        first, last = NEW_NAME.split(" ", 1)
        size = max(int((y1 - y0) * 0.42), 10)
        font = load_font(size)
        for i, line in enumerate((first, last)):
            tw = draw.textbbox((0, 0), line, font=font)[2]
            draw.text(
                (x0 + ((x1 - x0) - tw) / 2, y0 + i * size * 1.28),
                line, font=font, fill=(255, 255, 255),
            )
    else:
        size = max(int((y1 - y0) * 0.86), 9)
        font = load_font(size)
        draw.text((x0, y0), NEW_NAME, font=font, fill=(232, 232, 232))
    return img


def main() -> None:
    ORIGINALS.mkdir(exist_ok=True)
    for name, roi, threshold, layout, solid in TARGETS:
        path = CARDS / name
        backup = ORIGINALS / name
        if not backup.exists():
            shutil.copy2(path, backup)

        img = Image.open(backup).convert("RGB")
        mask = find_text_mask(img, roi, threshold)
        if mask.getbbox() is None:
            print(f"  {name}: no placeholder text found in the region — skipped")
            continue


        text_box = mask.getbbox()
        cleaned = inpaint(img, solidify(mask) if solid else mask, passes=22 if solid else 14)
        final = draw_name(cleaned, mask, layout)
        final.save(path, quality=92, lossless=False)
        print(f"  {name}: name replaced with {NEW_NAME!r} (mask {mask.getbbox()})")


if __name__ == "__main__":
    main()
