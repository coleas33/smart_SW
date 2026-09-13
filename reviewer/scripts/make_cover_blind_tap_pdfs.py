"""Generate the two drawing PDFs of the `cover-blind-tap` benchmark package (T044).

The package is the day-one benchmark for User Story 1: exported files only, no
SOLIDWORKS seat. Two conditions are seeded on purpose and must survive any change to
this script (see `benchmarks/packages/cover-blind-tap/notes.md`):

- the housing sheet calls out `4X M6x1.0 - 6H` with a depth of 14 and nothing else. The
  usable thread depth is not stated anywhere on the drawing, so the fastener
  bottoming check has to stay `unresolved` and ask for it. A check that clears the M6 x
  20 screws by reading 14 as usable thread has broken constitution Principle I;
- page 2 of the cover sheet is flattened - rasterised, with no text layer - as a PDF
  export from SOLIDWORKS sometimes is. It must come back as `parse_status: "no_text"`
  with a `Gap`, never as an empty sheet.

The drawing symbols (`\u21a7` depth, `\u2334` counterbore) are outside Latin-1, so the
base-14 PDF fonts cannot encode them and PyMuPDF would write a text layer that does not
say what the sheet says. Segoe UI Symbol carries them and ships with Windows, which the
workstation this pilot targets runs.

Usage, from `reviewer/`:

    uv run python scripts/make_cover_blind_tap_pdfs.py

then build the package from the manifest, the BOM and these PDFs:

    uv run python -c "from pathlib import Path; \\
        from swreview.ingest.package_builder import build_package; \\
        p = Path('../benchmarks/packages/cover-blind-tap'); \\
        build_package(p, p / 'manifest.json', p / 'bom.csv')"
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

REPO_ROOT = Path(__file__).resolve().parents[2]
DRAWINGS = REPO_ROOT / "benchmarks" / "packages" / "cover-blind-tap" / "drawings"
SYMBOL_FONT = Path("C:/Windows/Fonts/seguisym.ttf")

DEPTH = "\u21a7"
COUNTERBORE = "\u2334"
DIAMETER = "\u00d8"
PLUS_MINUS = "\u00b1"

Item = tuple[float, float, str, float]

HOUSING: list[Item] = [
    # Title block, bottom right.
    (360.0, 760.0, "HOUSING", 12.0),
    (360.0, 778.0, "DWG DRW-2001  REV C", 9.0),
    (360.0, 792.0, "UNITS: MILLIMETERS", 9.0),
    (360.0, 806.0, "SCALE 1:1", 9.0),
    # General notes, bottom left.
    (60.0, 700.0, "NOTES:", 9.0),
    (60.0, 716.0, f"UNLESS OTHERWISE SPECIFIED TOLERANCES {PLUS_MINUS}0.1", 9.0),
    (60.0, 732.0, "MATERIAL: 6061-T6", 9.0),
    (60.0, 748.0, "FINISH: CLEAR ANODIZE", 9.0),
    # Dimensions. The thread callout states a depth of 14 and no usable thread depth.
    (120.0, 300.0, f"4X M6x1.0 - 6H {DEPTH} 14", 10.0),
    (120.0, 360.0, f"{DIAMETER}40 H7", 10.0),
    (330.0, 420.0, f"60 {PLUS_MINUS}0.05", 10.0),
]

COVER_SHEET_1: list[Item] = [
    (360.0, 760.0, "COVER", 12.0),
    (360.0, 778.0, "DWG DRW-2002  REV B", 9.0),
    (360.0, 792.0, "UNITS: MILLIMETERS", 9.0),
    (360.0, 806.0, "SCALE 1:1", 9.0),
    (60.0, 700.0, "NOTES:", 9.0),
    (60.0, 716.0, f"UNLESS OTHERWISE SPECIFIED TOLERANCES {PLUS_MINUS}0.1", 9.0),
    (60.0, 732.0, "MATERIAL: 6061-T6", 9.0),
    (120.0, 300.0, f"{DIAMETER}40 g6", 10.0),
    (120.0, 360.0, f"8.0 {PLUS_MINUS}0.1", 10.0),
    (120.0, 420.0, f"4X {COUNTERBORE} {DIAMETER}11 {DEPTH} 6.5", 10.0),
]

COVER_SHEET_2: list[Item] = [
    (240.0, 120.0, "SECTION A-A", 12.0),
    (120.0, 300.0, f"{COUNTERBORE} {DIAMETER}11 {DEPTH} 6.5", 10.0),
    (120.0, 360.0, f"8.0 {PLUS_MINUS}0.1", 10.0),
    (360.0, 792.0, "UNITS: MILLIMETERS", 9.0),
]


def save(document: pymupdf.Document, target: Path) -> None:
    """Subset the embedded symbol font and compress; these files are kept in the repo."""
    document.subset_fonts()
    document.save(target, garbage=4, deflate=True, clean=True)
    document.close()


def write_items(page: pymupdf.Page, items: list[Item], font: str) -> None:
    """Place each `(x, y, text, size)` item on `page` with the symbol font."""
    for x, y, text, size in items:
        page.insert_text((x, y), text, fontsize=size, fontname="F0", fontfile=font)


def make_housing(target: Path, font: str) -> None:
    """One sheet with a text layer: the drill-depth-only thread callout lives here."""
    document = pymupdf.open()
    write_items(document.new_page(), HOUSING, font)
    save(document, target)


def make_cover(target: Path, font: str) -> None:
    """Sheet 1 keeps its text layer; sheet 2 is rasterised into an image-only page."""
    document = pymupdf.open()
    write_items(document.new_page(), COVER_SHEET_1, font)

    source = pymupdf.open()
    source_page = source.new_page()
    write_items(source_page, COVER_SHEET_2, font)
    pixmap = source_page.get_pixmap(dpi=100)
    flattened = document.new_page(
        width=source_page.rect.width, height=source_page.rect.height
    )
    flattened.insert_image(flattened.rect, pixmap=pixmap)
    source.close()

    save(document, target)


def main() -> None:
    if not SYMBOL_FONT.is_file():
        raise SystemExit(
            f"{SYMBOL_FONT} is required: the depth and counterbore symbols are outside "
            "Latin-1 and the base-14 PDF fonts cannot encode them"
        )
    font = str(SYMBOL_FONT)
    DRAWINGS.mkdir(parents=True, exist_ok=True)
    make_housing(DRAWINGS / "housing.pdf", font)
    make_cover(DRAWINGS / "cover.pdf", font)
    print(f"wrote {DRAWINGS / 'housing.pdf'}")
    print(f"wrote {DRAWINGS / 'cover.pdf'} (sheet 2 flattened, no text layer)")


if __name__ == "__main__":
    main()
