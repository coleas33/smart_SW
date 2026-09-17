"""Unit tests for the PDF drawing parser (T026).

Every fixture is a PDF built in the test with PyMuPDF, so the cases are exactly the
layouts the parser claims to handle: spans that must be clustered back into one callout,
a stacked bilateral tolerance, title-block units, general notes, and the page that has
no text layer at all - the flattened sheet that must never be mistaken for an empty one
(research R8, constitution Principle I).
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from swreview.ingest.pdf_drawing import parse_drawing_pdf
from swreview.ir.models import Gap

BENCHMARK_DRAWINGS = (
    Path(__file__).resolve().parents[3]
    / "benchmarks"
    / "packages"
    / "cover-blind-tap"
    / "drawings"
)

Item = tuple[float, float, str] | tuple[float, float, str, float]

SYMBOL_FONT = Path("C:/Windows/Fonts/seguisym.ttf")
needs_symbol_font = pytest.mark.skipif(
    not SYMBOL_FONT.exists(),
    reason=f"drawing symbol glyphs need {SYMBOL_FONT}",
)


def build_pdf(path: Path, *pages: list[Item], fontfile: Path | None = None) -> Path:
    """Write a PDF whose pages carry `(x, y, text[, size])` text items."""
    document = pymupdf.open()
    for items in pages:
        page = document.new_page()
        for item in items:
            x, y, text = item[0], item[1], item[2]
            size = item[3] if len(item) > 3 else 10.0
            page.insert_text(
                (x, y),
                text,
                fontsize=size,
                fontname="F0" if fontfile else "helv",
                fontfile=str(fontfile) if fontfile else None,
            )
    document.save(path)
    document.close()
    return path


def flatten(source: Path, target: Path, keep_pages: int = 0) -> Path:
    """Rasterise `source` into an image-only PDF: a drawing exported without a text layer."""
    original = pymupdf.open(source)
    flattened = pymupdf.open()
    for index, page in enumerate(original):
        if index < keep_pages:
            flattened.insert_pdf(original, from_page=index, to_page=index)
            continue
        pixmap = page.get_pixmap(dpi=72)
        new_page = flattened.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(new_page.rect, pixmap=pixmap)
    flattened.save(target)
    flattened.close()
    original.close()
    return target


def title_block(units: str = "MILLIMETERS") -> Item:
    return (60.0, 60.0, f"UNITS: {units}", 9.0)


# --- sheet level ------------------------------------------------------------------


def test_sheet_metadata(tmp_path: Path) -> None:
    path = build_pdf(tmp_path / "d.pdf", [title_block(), (100.0, 200.0, "12.5")])

    sheets = parse_drawing_pdf(path, "DRW-2001")

    assert len(sheets) == 1
    sheet = sheets[0]
    assert sheet.document_id == "DRW-2001"
    assert sheet.page == 1
    assert sheet.parse_status == "text"
    assert sheet.units == "mm"
    assert "pymupdf" in sheet.parser
    assert sheet.views == []


def test_every_sheet_the_ingest_writes_is_stamped_pdf_ingest(tmp_path: Path) -> None:
    """FR-024: a sheet says which path produced it, so the drawing checks can tell.

    All three of the parser's exits are stamped - the sheet it read, the flattened page it
    could not read, and the file it could not open - because a sheet with no source is read
    as PDF-ingested anyway and a consumer must not have to infer that from `parser`.
    """
    text = build_pdf(tmp_path / "text.pdf", [title_block(), (100.0, 200.0, "12.5")])
    flat = flatten(build_pdf(tmp_path / "src.pdf", [title_block()]), tmp_path / "flat.pdf")
    broken = tmp_path / "broken.pdf"
    broken.write_text("this is not a PDF", encoding="utf-8")

    sheets = [
        *parse_drawing_pdf(text, "DRW-2001", gaps=[]),
        *parse_drawing_pdf(flat, "DRW-2002", gaps=[]),
        *parse_drawing_pdf(broken, "DRW-2003", gaps=[]),
    ]

    assert [sheet.parse_status for sheet in sheets] == ["text", "no_text", "failed"]
    assert {sheet.source for sheet in sheets} == {"pdf_ingest"}


def test_the_stamp_is_the_only_source_the_ingest_writes(tmp_path: Path) -> None:
    """`native` is the native dumper's word for its own records and is never written here."""
    path = build_pdf(tmp_path / "d.pdf", [title_block(), (100.0, 200.0, "12.5")], [title_block()])

    assert [sheet.source for sheet in parse_drawing_pdf(path, "D")] == ["pdf_ingest"] * 2


def test_units_from_the_title_block(tmp_path: Path) -> None:
    millimetres = build_pdf(tmp_path / "mm.pdf", [title_block("MILLIMETERS")])
    inches = build_pdf(tmp_path / "in.pdf", [title_block("INCHES")])
    abbreviated = build_pdf(tmp_path / "abbr.pdf", [(60.0, 60.0, "UNITS: MM")])

    assert parse_drawing_pdf(millimetres, "D")[0].units == "mm"
    assert parse_drawing_pdf(inches, "D")[0].units == "in"
    assert parse_drawing_pdf(abbreviated, "D")[0].units == "mm"


def test_units_unknown_when_the_title_block_says_nothing(tmp_path: Path) -> None:
    path = build_pdf(tmp_path / "d.pdf", [(100.0, 200.0, "12.5")])

    assert parse_drawing_pdf(path, "D")[0].units == "unknown"


def test_units_hint_is_used_only_when_the_sheet_states_nothing(tmp_path: Path) -> None:
    silent = build_pdf(tmp_path / "silent.pdf", [(100.0, 200.0, "12.5")])
    stated = build_pdf(tmp_path / "stated.pdf", [title_block("INCHES"), (100.0, 200.0, "1.25")])

    assert parse_drawing_pdf(silent, "D", sheet_units_hint="in")[0].units == "in"
    assert parse_drawing_pdf(stated, "D", sheet_units_hint="mm")[0].units == "in"


def test_scale_from_the_title_block(tmp_path: Path) -> None:
    path = build_pdf(tmp_path / "d.pdf", [title_block(), (200.0, 60.0, "SCALE 1:2", 9.0)])

    assert parse_drawing_pdf(path, "D")[0].scale == "1:2"


def test_every_page_becomes_a_sheet(tmp_path: Path) -> None:
    path = build_pdf(
        tmp_path / "d.pdf",
        [title_block(), (100.0, 200.0, "12.5")],
        [title_block(), (100.0, 200.0, "8.0")],
    )

    sheets = parse_drawing_pdf(path, "DRW-2002")

    assert [sheet.page for sheet in sheets] == [1, 2]
    assert [sheet.dimensions[0].nominal.value for sheet in sheets] == [12.5, 8.0]


# --- clustering -------------------------------------------------------------------


def test_adjacent_spans_cluster_into_one_dimension(tmp_path: Path) -> None:
    """The nominal and its tolerance are separate text objects on the same baseline."""
    path = build_pdf(
        tmp_path / "d.pdf",
        [title_block(), (100.0, 200.0, "\u00d810.00"), (145.0, 200.0, "\u00b10.02")],
    )

    sheet = parse_drawing_pdf(path, "DRW-2001")[0]

    assert len(sheet.dimensions) == 1
    dimension = sheet.dimensions[0]
    assert dimension.nominal.value == 10.0
    assert dimension.nominal.unit == "mm"
    assert dimension.tolerance.kind == "symmetric"
    assert dimension.tolerance.upper.value == pytest.approx(0.02)
    assert dimension.text_as_read == "\u00d810.00 \u00b10.02"


def test_clustered_dimension_carries_its_page_and_bbox(tmp_path: Path) -> None:
    path = build_pdf(
        tmp_path / "d.pdf",
        [title_block(), (100.0, 200.0, "\u00d810.00"), (145.0, 200.0, "\u00b10.02")],
    )

    source = parse_drawing_pdf(path, "DRW-2001")[0].dimensions[0].source

    assert source.document_id == "DRW-2001"
    assert source.page == 1
    assert source.sheet == "Sheet1"
    assert source.bbox is not None
    x0, _y0, x1, _y1 = source.bbox
    assert x0 == pytest.approx(100.0, abs=1.0)
    assert x1 > 165.0


def test_stacked_bilateral_tolerance_clusters(tmp_path: Path) -> None:
    """SOLIDWORKS stacks the two deviations above and below the nominal's baseline."""
    path = build_pdf(
        tmp_path / "d.pdf",
        [
            title_block(),
            (100.0, 240.0, "10"),
            (120.0, 236.0, "+0.05", 8.0),
            (120.0, 246.0, "-0.00", 8.0),
        ],
    )

    sheet = parse_drawing_pdf(path, "D")[0]

    assert len(sheet.dimensions) == 1
    dimension = sheet.dimensions[0]
    assert dimension.nominal.value == 10.0
    assert dimension.tolerance.kind == "bilateral"
    assert dimension.tolerance.upper.value == pytest.approx(0.05)
    assert dimension.tolerance.lower.value == pytest.approx(0.0)
    assert dimension.text_as_read == "10 +0.05 -0.00"


def test_dimensions_far_apart_stay_separate(tmp_path: Path) -> None:
    path = build_pdf(
        tmp_path / "d.pdf",
        [title_block(), (100.0, 200.0, "12.5"), (400.0, 200.0, "60"), (100.0, 400.0, "8.0")],
    )

    sheet = parse_drawing_pdf(path, "D")[0]

    assert sorted(d.nominal.value for d in sheet.dimensions) == [8.0, 12.5, 60.0]


@needs_symbol_font
def test_thread_callout_with_drawing_symbols(tmp_path: Path) -> None:
    path = build_pdf(
        tmp_path / "d.pdf",
        [title_block(), (100.0, 300.0, "4X M6x1.0 - 6H \u21a7 14")],
        fontfile=SYMBOL_FONT,
    )

    sheet = parse_drawing_pdf(path, "DRW-2001")[0]

    assert [d.nominal.value for d in sheet.dimensions] == [14.0]
    assert sheet.dimensions[0].text_as_read == "4X M6x1.0 - 6H \u21a7 14"
    assert sheet.dimensions[0].tolerance.kind == "none"


@needs_symbol_font
def test_counterbore_callout_gives_diameter_and_depth(tmp_path: Path) -> None:
    path = build_pdf(
        tmp_path / "d.pdf",
        [title_block(), (100.0, 300.0, "4X \u2334 \u00d811 \u21a7 6.5")],
        fontfile=SYMBOL_FONT,
    )

    sheet = parse_drawing_pdf(path, "DRW-2002")[0]

    assert [d.nominal.value for d in sheet.dimensions] == [11.0, 6.5]


# --- annotation ids ---------------------------------------------------------------


def test_every_dimension_gets_a_stable_annotation_id(tmp_path: Path) -> None:
    """`document_id:sheet:annotation` is how a check addresses a parsed dimension."""
    path = build_pdf(
        tmp_path / "d.pdf",
        [title_block(), (100.0, 200.0, "12.5"), (400.0, 200.0, "60"), (100.0, 400.0, "8.0")],
    )

    sheet = parse_drawing_pdf(path, "DRW-2001")[0]

    assert [d.source.annotation for d in sheet.dimensions] == ["dim-1-1", "dim-1-2", "dim-1-3"]
    assert [d.nominal.value for d in sheet.dimensions] == [12.5, 60.0, 8.0]


def test_annotation_ids_number_per_page(tmp_path: Path) -> None:
    path = build_pdf(
        tmp_path / "d.pdf",
        [title_block(), (100.0, 200.0, "12.5")],
        [title_block(), (100.0, 200.0, "8.0")],
    )

    sheets = parse_drawing_pdf(path, "DRW-2002")

    assert [d.source.annotation for sheet in sheets for d in sheet.dimensions] == [
        "dim-1-1",
        "dim-2-1",
    ]


@needs_symbol_font
def test_one_callout_that_parses_into_two_dimensions_gets_two_ids(tmp_path: Path) -> None:
    """A counterbore callout is one cluster and two dimensions; each needs its own id."""
    path = build_pdf(
        tmp_path / "d.pdf",
        [title_block(), (100.0, 300.0, "4X ⌴ Ø11 ↧ 6.5")],
        fontfile=SYMBOL_FONT,
    )

    sheet = parse_drawing_pdf(path, "D")[0]

    assert len(sheet.dimensions) == 2
    assert [d.source.annotation for d in sheet.dimensions] == ["dim-1-1", "dim-1-2"]


def test_annotation_ids_are_stable_across_reparses(tmp_path: Path) -> None:
    path = build_pdf(
        tmp_path / "d.pdf",
        [title_block(), (100.0, 200.0, "12.5"), (400.0, 200.0, "60")],
    )

    first = parse_drawing_pdf(path, "D")[0]
    second = parse_drawing_pdf(path, "D")[0]

    assert [d.source.annotation for d in first.dimensions] == [
        d.source.annotation for d in second.dimensions
    ]


def test_every_general_note_gets_an_annotation_id(tmp_path: Path) -> None:
    path = build_pdf(
        tmp_path / "d.pdf",
        [
            title_block(),
            (60.0, 400.0, "NOTES:", 9.0),
            (60.0, 420.0, "MATERIAL: 6061-T6", 9.0),
        ],
    )

    sheet = parse_drawing_pdf(path, "D")[0]

    assert [note.source.annotation for note in sheet.general_notes] == ["note-1-1", "note-1-2"]


# --- notes ------------------------------------------------------------------------


def test_general_notes_are_detected_with_their_kind(tmp_path: Path) -> None:
    path = build_pdf(
        tmp_path / "d.pdf",
        [
            title_block(),
            (60.0, 400.0, "NOTES:", 9.0),
            (60.0, 420.0, "UNLESS OTHERWISE SPECIFIED TOLERANCES \u00b10.1", 9.0),
            (60.0, 440.0, "MATERIAL: 6061-T6", 9.0),
            (60.0, 460.0, "FINISH: CLEAR ANODIZE", 9.0),
        ],
    )

    sheet = parse_drawing_pdf(path, "D")[0]

    assert [(note.kind, note.text) for note in sheet.general_notes] == [
        ("other", "NOTES:"),
        ("general_tolerance", "UNLESS OTHERWISE SPECIFIED TOLERANCES \u00b10.1"),
        ("material", "MATERIAL: 6061-T6"),
        ("finish", "FINISH: CLEAR ANODIZE"),
    ]
    assert sheet.general_notes[0].source.page == 1
    assert sheet.general_notes[0].source.document_id == "D"


def test_a_tolerances_heading_is_a_general_tolerance_note(tmp_path: Path) -> None:
    path = build_pdf(
        tmp_path / "d.pdf", [title_block(), (60.0, 400.0, "TOLERANCES: ±0.5", 9.0)]
    )

    sheet = parse_drawing_pdf(path, "D")[0]

    assert [note.kind for note in sheet.general_notes] == ["general_tolerance"]


def test_notes_are_not_read_as_dimensions(tmp_path: Path) -> None:
    path = build_pdf(
        tmp_path / "d.pdf",
        [
            title_block(),
            (60.0, 400.0, "MATERIAL: 6061-T6", 9.0),
            (60.0, 420.0, "FINISH: CLEAR ANODIZE", 9.0),
            (100.0, 200.0, "12.5"),
        ],
    )

    sheet = parse_drawing_pdf(path, "D")[0]

    assert [d.text_as_read for d in sheet.dimensions] == ["12.5"]


# --- gaps -------------------------------------------------------------------------


def test_a_page_with_no_text_layer_is_no_text_and_a_gap(tmp_path: Path) -> None:
    source = build_pdf(tmp_path / "src.pdf", [title_block(), (100.0, 200.0, "12.5")])
    flat = flatten(source, tmp_path / "flat.pdf")
    gaps: list[Gap] = []

    sheets = parse_drawing_pdf(flat, "DRW-2002", gaps=gaps)

    assert len(sheets) == 1
    assert sheets[0].parse_status == "no_text"
    assert sheets[0].dimensions == []
    assert sheets[0].general_notes == []
    assert sheets[0].units == "unknown"
    assert len(gaps) == 1
    assert gaps[0].kind == "no_text"
    assert gaps[0].entity_kind == "drawing_sheet"
    assert gaps[0].entity_id == "DRW-2002:1"
    assert "text layer" in gaps[0].reason


def test_only_the_flattened_page_of_a_mixed_document_is_a_gap(tmp_path: Path) -> None:
    """The cover drawing: page 1 has a text layer, page 2 was flattened on export."""
    source = build_pdf(
        tmp_path / "src.pdf",
        [title_block(), (100.0, 200.0, "8.0 \u00b10.1")],
        [title_block(), (100.0, 200.0, "\u00d840 H7")],
    )
    mixed = flatten(source, tmp_path / "mixed.pdf", keep_pages=1)
    gaps: list[Gap] = []

    sheets = parse_drawing_pdf(mixed, "DRW-2002", gaps=gaps)

    assert [sheet.parse_status for sheet in sheets] == ["text", "no_text"]
    assert [gap.entity_id for gap in gaps] == ["DRW-2002:2"]


def test_a_file_that_cannot_be_opened_is_failed_and_a_gap(tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_text("this is not a PDF", encoding="utf-8")
    gaps: list[Gap] = []

    sheets = parse_drawing_pdf(broken, "DRW-2001", gaps=gaps)

    assert len(sheets) == 1
    assert sheets[0].parse_status == "failed"
    assert sheets[0].page == 1
    assert sheets[0].units == "unknown"
    assert len(gaps) == 1
    assert gaps[0].kind == "tool_error"
    assert gaps[0].entity_kind == "drawing_sheet"
    assert gaps[0].error


def test_a_missing_file_is_failed_and_a_gap(tmp_path: Path) -> None:
    gaps: list[Gap] = []

    sheets = parse_drawing_pdf(tmp_path / "absent.pdf", "DRW-2001", gaps=gaps)

    assert sheets[0].parse_status == "failed"
    assert gaps[0].kind == "tool_error"


def test_dimensions_on_a_sheet_with_unknown_units_become_a_gap(tmp_path: Path) -> None:
    """A number with no unit is not evidence; it is a gap naming the sheet."""
    path = build_pdf(
        tmp_path / "d.pdf", [(100.0, 200.0, "Ø10.00"), (145.0, 200.0, "±0.02")]
    )
    gaps: list[Gap] = []

    sheet = parse_drawing_pdf(path, "DRW-2001", gaps=gaps)[0]

    assert sheet.units == "unknown"
    assert sheet.dimensions == []
    assert [(gap.kind, gap.entity_kind, gap.entity_id) for gap in gaps] == [
        ("not_extracted", "dimension", "DRW-2001:1")
    ]
    assert "unit" in gaps[0].reason


def test_no_gaps_are_reported_for_a_clean_sheet(tmp_path: Path) -> None:
    path = build_pdf(tmp_path / "d.pdf", [title_block(), (100.0, 200.0, "12.5")])
    gaps: list[Gap] = []

    parse_drawing_pdf(path, "D", gaps=gaps)

    assert gaps == []


def test_gaps_argument_is_optional(tmp_path: Path) -> None:
    source = build_pdf(tmp_path / "src.pdf", [title_block(), (100.0, 200.0, "12.5")])
    flat = flatten(source, tmp_path / "flat.pdf")

    assert parse_drawing_pdf(flat, "D")[0].parse_status == "no_text"


# --- the committed benchmark drawings ---------------------------------------------


@pytest.mark.skipif(
    not BENCHMARK_DRAWINGS.is_dir(),
    reason="run reviewer/scripts/make_cover_blind_tap_pdfs.py first",
)
class TestCoverBlindTapDrawings:
    """The seeded conditions of the day-one benchmark, read back off the real PDFs."""

    def test_housing_states_a_depth_of_14_and_no_usable_thread_depth(self) -> None:
        sheets = parse_drawing_pdf(BENCHMARK_DRAWINGS / "housing.pdf", "DRW-2001")

        assert [sheet.parse_status for sheet in sheets] == ["text"]
        assert sheets[0].units == "mm"
        callouts = {d.text_as_read: d for d in sheets[0].dimensions}
        thread = callouts["4X M6x1.0 - 6H ↧ 14"]
        assert thread.nominal.value == 14.0
        assert thread.tolerance.kind == "none"
        assert not any("THREAD" in text.upper() for text in callouts)

    def test_housing_dimensions_are_addressable_by_annotation(self) -> None:
        sheet = parse_drawing_pdf(BENCHMARK_DRAWINGS / "housing.pdf", "DRW-2001")[0]

        assert [d.source.annotation for d in sheet.dimensions] == [
            "dim-1-1",
            "dim-1-2",
            "dim-1-3",
        ]
        assert {d.source.annotation: d.text_as_read for d in sheet.dimensions}[
            "dim-1-1"
        ] == "4X M6x1.0 - 6H ↧ 14"

    def test_housing_carries_its_general_notes(self) -> None:
        notes = parse_drawing_pdf(BENCHMARK_DRAWINGS / "housing.pdf", "DRW-2001")[0]
        kinds = {note.kind for note in notes.general_notes}

        assert {"general_tolerance", "material", "finish"} <= kinds

    def test_cover_sheet_two_has_no_text_layer(self) -> None:
        gaps: list[Gap] = []

        sheets = parse_drawing_pdf(BENCHMARK_DRAWINGS / "cover.pdf", "DRW-2002", gaps=gaps)

        assert [sheet.parse_status for sheet in sheets] == ["text", "no_text"]
        assert [(gap.kind, gap.entity_id) for gap in gaps] == [("no_text", "DRW-2002:2")]

    def test_cover_sheet_one_states_the_counterbore_and_thickness(self) -> None:
        sheet = parse_drawing_pdf(BENCHMARK_DRAWINGS / "cover.pdf", "DRW-2002")[0]
        values = {d.text_as_read: d.nominal.value for d in sheet.dimensions}

        assert values["8.0 ±0.1"] == 8.0
        assert sorted(
            d.nominal.value
            for d in sheet.dimensions
            if d.text_as_read == "4X ⌴ Ø11 ↧ 6.5"
        ) == [6.5, 11.0]
