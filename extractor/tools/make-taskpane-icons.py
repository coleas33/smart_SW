"""Regenerate the Task Pane tab icons from the 512 px source.

SOLIDWORKS' `CreateTaskpaneView3` takes one PNG per size (20, 32, 40, 64, 96, 128) and picks
by display scaling. Every size but the smallest is a plain LANCZOS downscale. At 20 px the
source's strokes come out under a pixel wide and the icon blurs into a haze, so that size is
drawn with the strokes thickened first (a dilated copy of the artwork, in its most common opaque colour, composited underneath
the original, so the eyes keep their whites) and the alpha lifted afterwards.

Run from the repository root with the reviewer environment, which has Pillow:

    uv run --project reviewer python extractor/tools/make-taskpane-icons.py
"""

from pathlib import Path

from PIL import Image, ImageFilter

ICONS = Path(__file__).resolve().parents[1] / "SwReview.AddIn" / "Icons"
SOURCE = ICONS / "taskpane-source-512.png"
SIZES = (20, 32, 40, 64, 96, 128)

# The colour the artwork is painted in. The source is one flat colour (the teal it was
# drawn in) plus alpha, so the icon's colour is a swap here rather than a second source
# file: every pixel with any coverage takes this colour and keeps its alpha. The
# background stays transparent, so the pane's own tab strip shows through it.
COLOUR = (190, 38, 38)  # red, since 2026-09-19

# The smallest size only: how far (in source pixels) each stroke grows on either side, and
# the factor the downscaled alpha is multiplied by.
THICKEN_20_PX = 4
ALPHA_GAIN_20 = 1.4


def thickened(source: Image.Image) -> Image.Image:
    """The artwork over a copy of itself whose alpha was dilated and filled with its colour."""
    alpha = source.getchannel("A").filter(ImageFilter.MaxFilter(2 * THICKEN_20_PX + 1))
    opaque = [(n, c) for n, c in source.getcolors(source.width * source.height) if c[3] == 255]
    colour = max(opaque)[1][:3]
    under = Image.new("RGBA", source.size, colour + (0,))
    under.putalpha(alpha)
    return Image.alpha_composite(under, source)


def recoloured(source: Image.Image) -> Image.Image:
    """The artwork painted in `COLOUR`, alpha untouched."""
    painted = Image.new("RGBA", source.size, COLOUR + (0,))
    painted.putalpha(source.getchannel("A"))
    return painted


def main() -> None:
    source = recoloured(Image.open(SOURCE).convert("RGBA"))
    for size in SIZES:
        artwork = thickened(source) if size == 20 else source
        icon = artwork.resize((size, size), Image.LANCZOS)
        if size == 20:
            icon.putalpha(icon.getchannel("A").point(lambda v: min(255, round(v * ALPHA_GAIN_20))))
        icon.save(ICONS / f"taskpane-{size}.png")
        print(f"wrote taskpane-{size}.png")


if __name__ == "__main__":
    main()
