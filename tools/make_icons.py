"""Draws the OptoStim logo and writes assets/icon_512.png, icon_256.png, OptoStim.ico, OptoStim.icns.

    pip install pillow numpy
    python tools/make_icons.py

Style: rounded navy tile (#101d3d at the top to #060b1a at the bottom) with one
bright symbol, here a glowing laser pulse train.
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "assets"
TOP, BOTTOM = (0x10, 0x1D, 0x3D), (0x06, 0x0B, 0x1A)
GLOW, BODY, CORE = (108, 76, 255), (140, 120, 255), (232, 226, 255)


def render(size: int = 1024) -> Image.Image:
    ss = 2                                   # supersampling inside this function
    n = size * ss
    # vertical gradient tile
    ramp = np.linspace(0.0, 1.0, n)[:, None, None]
    grad = (np.array(TOP) * (1 - ramp) + np.array(BOTTOM) * ramp).astype(np.uint8)
    grad = np.repeat(grad, n, axis=1)
    tile = Image.fromarray(grad, "RGB").convert("RGBA")
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, n - 1, n - 1), radius=int(n * 0.225), fill=255)
    tile.putalpha(mask)

    # faint inner edge so the tile reads on dark backgrounds
    edge = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    ImageDraw.Draw(edge).rounded_rectangle((n * 0.004,) * 2 + (n * 0.996,) * 2, radius=int(n * 0.222),
                                           outline=(255, 255, 255, 26), width=max(2, int(n * 0.004)))
    tile = Image.alpha_composite(tile, edge)

    # pulse-train polyline: low, 3 pulses, low
    lo, hi = 0.64, 0.36
    x, pw, gap, lead = 0.105, 0.15, 0.11, 0.06
    pts = [(x, lo), (x + lead, lo)]
    x += lead
    for i in range(3):
        pts += [(x, lo), (x, hi), (x + pw, hi), (x + pw, lo)]
        x += pw + (gap if i < 2 else 0)
    pts += [(x + lead, lo)]
    pts = [(px * n, py * n) for px, py in pts]

    def stroke(width: float, colour, blur: float = 0.0, alpha: float = 1.0) -> Image.Image:
        layer = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        w = int(width * n)
        d.line(pts, fill=colour + (255,), width=w, joint="curve")
        r = w / 2
        for px, py in (pts[0], pts[-1]):
            d.ellipse((px - r, py - r, px + r, py + r), fill=colour + (255,))
        if blur:
            layer = layer.filter(ImageFilter.GaussianBlur(blur * n))
        if alpha < 1.0:
            layer.putalpha(layer.getchannel("A").point(lambda v: int(v * alpha)))
        return layer

    glow = Image.alpha_composite(stroke(0.075, GLOW, blur=0.035, alpha=0.9),
                                 stroke(0.05, GLOW, blur=0.012, alpha=0.8))
    art = Image.alpha_composite(glow, stroke(0.036, BODY))
    art = Image.alpha_composite(art, stroke(0.014, CORE))
    # keep the glow inside the tile
    art.putalpha(ImageChops.multiply(art.getchannel("A"), mask))
    tile = Image.alpha_composite(tile, art)
    return tile.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    big = render(1024)
    big512 = big.resize((512, 512), Image.Resampling.LANCZOS)
    big512.save(OUT / "icon_512.png", optimize=True)
    big.resize((256, 256), Image.Resampling.LANCZOS).save(OUT / "icon_256.png", optimize=True)
    big512.save(OUT / "OptoStim.ico",
                sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    big.save(OUT / "OptoStim.icns")
    print("wrote", ", ".join(sorted(p.name for p in OUT.iterdir())))


if __name__ == "__main__":
    main()
