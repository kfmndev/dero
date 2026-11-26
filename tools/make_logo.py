# /// script
# requires-python = ">=3.13"
# dependencies = ["fonttools>=4.55", "brotli>=1.1"]
# ///
"""Regenerate the README logos (assets/logo-light.svg, assets/logo-dark.svg).

Draws "dero." in Hubot Sans ExtraBold (the font of the app header) as vector outlines, so the logo looks the same on
GitHub without the font installed. The dependencies are declared above, so uv fetches them:  uv run tools/make_logo.py
"""

from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / "dero" / "static" / "fonts" / "hubot-sans.woff2"
WEIGHT = 800  # the weight of the header's h1
SIZE = 100  # 1 em = 100 units
PAD = 4  # space around the ink, on every side
# extra room below: 0.5rem (8 px) when the README shows the logo 68 px high (93 units, 60 px of them the logo)
BOTTOM = 11

THEMES = {  # name -> (text colour, dot colour): the app's text and accent tokens in light and dark
    "light": ("#15171c", "#05f"),
    "dark": ("#eceef2", "#05f"),
}


def build() -> dict[str, str]:
    """The SVG text of the logo for each theme."""
    font = instantiateVariableFont(TTFont(FONT), {"wght": WEIGHT})
    glyphs, cmap, hmtx = font.getGlyphSet(), font.getBestCmap(), font["hmtx"]
    scale = SIZE / font["head"].unitsPerEm
    bounds = BoundsPen(glyphs)

    def draw(text: str, x: float) -> tuple[str, float]:
        """The outline of the text starting at x, and where it ends."""
        paths = []

        for ch in text:
            name = cmap[ord(ch)]
            pen = SVGPathPen(glyphs, ntos=lambda v: f"{v:.1f}".rstrip("0").rstrip("."))
            # font units are y-up; flip to SVG's y-down, with the baseline at y = 0
            flip = (scale, 0, 0, -scale, x, 0)
            glyphs[name].draw(TransformPen(pen, flip))
            glyphs[name].draw(TransformPen(bounds, flip))
            paths.append(pen.getCommands())
            x += hmtx[name][0] * scale

        return " ".join(paths), x

    word, x = draw("dero", 0)
    dot, _ = draw(".", x)
    left, top, right, bottom = bounds.bounds  # the ink, so the logo has no spare room above, below or at the sides
    left, top, width, height = left - PAD, top - PAD, right - left + 2 * PAD, bottom - top + 2 * PAD + BOTTOM
    out = {}

    for theme, (text, accent) in THEMES.items():
        out[theme] = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{left:.1f} {top:.1f} {width:.1f} {height:.1f}" '
            f'width="{width * 1.6:.0f}" height="{height * 1.6:.0f}" role="img" aria-label="dero">\n'
            f'  <path fill="{text}" d="{word}"/>\n'
            f'  <path fill="{accent}" d="{dot}"/>\n</svg>\n'
        )

    return out


if __name__ == "__main__":
    for theme, svg in build().items():
        (ROOT / "assets" / f"logo-{theme}.svg").write_text(svg)
        print("wrote", f"assets/logo-{theme}.svg")
