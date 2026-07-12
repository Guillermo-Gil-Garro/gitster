"""Regenerates the card front backgrounds (assets/deck/backgrounds/front/gNN.png).

Deterministic, dependency-light (Pillow only). Backgrounds can be vivid because
the renderer draws a translucent plate behind the card text; still, extreme
darkness is avoided so the outer ring never swallows the owner-color frame.
"""

from __future__ import annotations

import colorsys
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SIZE = 1024
OUT_DIR = Path(__file__).resolve().parents[1] / "assets" / "deck" / "backgrounds" / "front"

# (hue_a, hue_b, pattern) — hues in degrees. Luminosity is clamped in _tone().
DESIGNS = [
    (200, 260, "diagonal"),   # g01 cyan→violet
    (330, 20, "rings"),       # g02 pink→orange
    (45, 90, "dots"),         # g03 amber→lime
    (160, 200, "waves"),      # g04 teal→azure
    (270, 320, "diagonal"),   # g05 purple→magenta
    (10, 45, "rays"),         # g06 red→amber
    (90, 150, "dots"),        # g07 green range
    (210, 180, "waves"),      # g08 blue→teal
    (300, 220, "rings"),      # g09 magenta→blue
    (30, 330, "diagonal"),    # g10 orange→pink
    (120, 60, "rays"),        # g11 green→yellow
    (240, 190, "dots"),       # g12 indigo→cyan
]


def _tone(hue_degrees: float, saturation: float, lightness: float) -> tuple[int, int, int]:
    lightness = min(max(lightness, 0.34), 0.82)
    red, green, blue = colorsys.hls_to_rgb((hue_degrees % 360) / 360.0, lightness, saturation)
    return int(red * 255), int(green * 255), int(blue * 255)


def _gradient(hue_a: float, hue_b: float) -> Image.Image:
    image = Image.new("RGB", (SIZE, SIZE))
    for y in range(SIZE):
        t = y / (SIZE - 1)
        hue = hue_a + (hue_b - hue_a) * t
        color = _tone(hue, 0.62, 0.46 + 0.22 * math.sin(math.pi * t))
        for_line = Image.new("RGB", (SIZE, 1), color)
        image.paste(for_line, (0, y))
    return image.rotate(35, expand=False, resample=Image.BICUBIC, fillcolor=_tone(hue_a, 0.6, 0.5))


def _overlay(image: Image.Image, pattern: str, hue: float, rng: random.Random) -> Image.Image:
    layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    light = _tone(hue, 0.35, 0.78) + (60,)
    dark = _tone(hue, 0.55, 0.36) + (48,)

    if pattern == "dots":
        step = 74
        for row, y in enumerate(range(-step, SIZE + step, step)):
            offset = (step // 2) if row % 2 else 0
            for x in range(-step, SIZE + step, step):
                radius = rng.randint(9, 22)
                draw.ellipse(
                    (x + offset - radius, y - radius, x + offset + radius, y + radius),
                    fill=light if (row + x) % 3 else dark,
                )
    elif pattern == "rings":
        cx, cy = rng.randint(200, 824), rng.randint(200, 824)
        for radius in range(60, 1000, 78):
            draw.ellipse(
                (cx - radius, cy - radius, cx + radius, cy + radius),
                outline=light if (radius // 78) % 2 else dark,
                width=14,
            )
    elif pattern == "waves":
        for band in range(-6, 20):
            points = [
                (x, band * 70 + 46 * math.sin((x / SIZE) * 2 * math.pi * 2.2 + band))
                for x in range(0, SIZE + 16, 16)
            ]
            draw.line(points, fill=light if band % 2 else dark, width=12)
    elif pattern == "rays":
        cx, cy = SIZE // 2, SIZE + 180
        for step_index in range(26):
            angle = math.pi * (0.06 + 0.033 * step_index)
            x2 = cx + 1700 * math.cos(angle)
            y2 = cy - 1700 * math.sin(angle)
            draw.line((cx, cy, x2, y2), fill=light if step_index % 2 else dark, width=22)
    elif pattern == "diagonal":
        for band_index, offset in enumerate(range(-SIZE, SIZE * 2, 96)):
            draw.line((offset, 0, offset + SIZE, SIZE), fill=light if band_index % 2 else dark, width=26)

    layer = layer.filter(ImageFilter.GaussianBlur(1.2))
    return Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for index, (hue_a, hue_b, pattern) in enumerate(DESIGNS, start=1):
        rng = random.Random(1000 + index)
        image = _gradient(hue_a, hue_b)
        image = _overlay(image, pattern, (hue_a + hue_b) / 2, rng)
        out_path = OUT_DIR / f"g{index:02d}.png"
        image.save(out_path, optimize=True)
        print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
