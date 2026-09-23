"""The fastener-name parser (feature 010 T038, `contracts/fasteners.md` sections 1 and 2).

Sixty-eight screws in the recorded big assembly were never recognised as fasteners, because
the only reader of a name was the extractor's, and it was reached for Toolbox parts only
(research R2.11). `checks/fastener_names.py` reads a kind, a head, a size, a pitch and a
length from a file name, a Description property or a configuration name.

Two rules outrank the rest. **An unreadable part of a readable name is a null field, never a
guess**, and a text that names no size is `None` - a bracket with tapped holes is not a
screw. And **the Python parser answers every row of the shared vector table** that the C#
parser answers too, so the two cannot drift (research R2.11).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from swreview.checks.fastener_names import (
    DEFAULT_NAMES_PATH,
    FastenerNames,
    ParsedName,
    load_fastener_names,
    parse_fastener_name,
    read_fastener_names,
)

REPO = Path(__file__).resolve().parents[3]
VECTORS_PATH = REPO / "specs" / "010-mechanical-checks" / "contracts" / "fastener-name-vectors.json"
VECTORS: list[dict[str, Any]] = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))


def designation(parsed: ParsedName) -> str:
    """The designation as the vector table spells it: upper case, no whitespace."""
    return "".join(parsed.designation.split()).upper()


# --- the shared vector table ----------------------------------------------------------------


@pytest.mark.parametrize(
    "row", VECTORS, ids=[f"{row['source']}:{row['text'] or '<blank>'}" for row in VECTORS]
)
def test_every_row_of_the_shared_vector_table(row: dict[str, Any]) -> None:
    """Every row, including those the C# parser never receives (`csharp: false`)."""
    parsed = parse_fastener_name(row["text"], row["source"])
    expected = row["expected"]

    if expected is None:
        assert parsed is None, f"{row['text']!r} names no size, so it is not a fastener name"
        return
    assert parsed is not None
    assert parsed.source == row["source"]
    assert parsed.text == row["text"]
    assert parsed.kind == expected["kind"]
    assert parsed.head_type == expected["head_type"]
    assert designation(parsed) == expected["thread"]
    if expected["length_mm"] is None:
        assert parsed.length_mm is None
    else:
        assert parsed.length_mm == pytest.approx(expected["length_mm"], abs=1e-9)


def test_the_vector_table_covers_every_source_and_both_answers() -> None:
    """A floor, not a count: a table that lost a source or its negative rows would leave the
    parametrized test green while testing half the grammar."""
    for source in ("file_name", "description", "configuration"):
        assert any(row["source"] == source and row["expected"] for row in VECTORS)
        assert any(row["source"] == source and row["expected"] is None for row in VECTORS)


# --- the forms one at a time ------------------------------------------------------------------


def test_the_vendor_file_name_reads_head_code_size_pitch_and_length() -> None:
    parsed = parse_fastener_name("SHC_M4-0.7X12_FICT-0001.SLDPRT", "file_name")

    assert parsed is not None
    assert (parsed.kind, parsed.head_code, parsed.head_type) == ("screw", "SHC", "socket head cap")
    assert parsed.drive == "hex_socket"
    assert parsed.designation == "M4x0.7"
    assert parsed.length_mm == 12.0
    assert parsed.thread.recognized
    assert parsed.thread.nominal_diameter is not None
    assert parsed.thread.nominal_diameter.value == 4.0
    assert parsed.thread.pitch_mm == 0.7


def test_only_a_solidworks_extension_is_dropped() -> None:
    """A vendor name has a dot inside its pitch, so "everything after the last dot" would
    cut the size in half."""
    for text in ("SHC_M4-0.7X12_FICT-0001.sldprt", "SHC_M4-0.7X12_FICT-0001.SLDASM"):
        parsed = parse_fastener_name(text, "file_name")
        assert parsed is not None and parsed.length_mm == 12.0


@pytest.mark.parametrize("code", ["FHT", "BHT"])
def test_flat_and_button_head_torx_carry_the_torx_drive(code: str) -> None:
    """Owner answer 2026-09-23 (research R5): FHT is flat head Torx, BHT button head Torx."""
    parsed = parse_fastener_name(f"{code}_M3-0.5X8_FICT-0002", "file_name")

    assert parsed is not None
    assert parsed.kind == "screw"
    assert parsed.drive == "torx"
    assert parsed.head_type == {"FHT": "flat head", "BHT": "button head"}[code]


def test_an_unknown_head_code_reads_the_size_and_leaves_kind_head_and_drive_null() -> None:
    parsed = parse_fastener_name("QZX_M6-1.0X20_FICT-0006", "file_name")

    assert parsed is not None
    assert (parsed.kind, parsed.head_code, parsed.head_type, parsed.drive) == (
        None,
        None,
        None,
        None,
    )
    assert (parsed.designation, parsed.length_mm) == ("M6x1.0", 20.0)


def test_the_vendor_description_reads_the_kind_word_and_names_no_head() -> None:
    parsed = parse_fastener_name("SCREW, SOC M4-0.7 X 12 MM, FICTIONAL", "description")

    assert parsed is not None
    assert (parsed.kind, parsed.head_type, parsed.drive) == ("screw", None, None)
    assert (parsed.designation, parsed.length_mm) == ("M4x0.7", 12.0)


def test_a_head_named_in_words_carries_no_drive() -> None:
    """The vocabulary names a head; only a head code names a drive, so the words leave the
    drive unknown rather than borrowing one."""
    parsed = parse_fastener_name("M6x1.0 x 20 - socket head cap screw", "configuration")

    assert parsed is not None
    assert (parsed.kind, parsed.head_type, parsed.drive) == ("screw", "socket head cap", None)


@pytest.mark.parametrize(
    ("text", "designation_text", "length"),
    [
        ("M6x1.0 x 20 - 20N", "M6x1.0", 20.0),
        ("M6 x 20", "M6", 20.0),
        ("M10x35", "M10", 35.0),
        ("M6x1.0", "M6x1.0", None),
        ("M8", "M8", None),
        ("M4-0.7", "M4x0.7", None),
        ("M4-0.7 x 12", "M4x0.7", 12.0),
        ("m6 × 1.0 × 20", "M6x1.0", 20.0),
    ],
)
def test_the_toolbox_forms(text: str, designation_text: str, length: float | None) -> None:
    """A decimal after the size is a pitch and a bare integer a length; a hyphen pitch is a
    pitch; a spaced-hyphen suffix is ignored; `×` reads as `x`."""
    parsed = parse_fastener_name(text, "configuration")

    assert parsed is not None
    assert parsed.designation == designation_text
    assert parsed.length_mm == length


@pytest.mark.parametrize(
    ("text", "designation_text", "length_mm", "pitch_mm"),
    [
        ("1/4-20 x 1-1/2", "1/4-20", 38.1, 25.4 / 20),
        ("#10-32 x 0.75", "#10-32", 19.05, 25.4 / 32),
        ("0.190-32 x 0.5", "0.190-32", 12.7, 25.4 / 32),
        ("3/8-16", "3/8-16", None, 25.4 / 16),
    ],
)
def test_the_unified_inch_forms_read_the_length_in_inches(
    text: str, designation_text: str, length_mm: float | None, pitch_mm: float
) -> None:
    parsed = parse_fastener_name(text, "configuration")

    assert parsed is not None
    assert parsed.designation == designation_text
    assert parsed.thread.series == "unified"
    assert parsed.thread.pitch_mm == pytest.approx(pitch_mm, abs=1e-6)
    if length_mm is None:
        assert parsed.length_mm is None
    else:
        assert parsed.length_mm == pytest.approx(length_mm, abs=1e-9)


@pytest.mark.parametrize(
    "text",
    ["", "   ", "Default", "garbage", "PLATE_BASE_FICT-0007", "BRACKET_M5_TAPPED_FICT-0008",
     "Socket Head Cap Screw_am", "hex screw"],
)
def test_a_text_that_names_no_size_is_none(text: str) -> None:
    for source in ("file_name", "description", "configuration"):
        assert parse_fastener_name(text, source) is None  # type: ignore[arg-type]


def test_a_none_text_is_none() -> None:
    assert parse_fastener_name(None, "description") is None


def test_an_unknown_source_is_refused() -> None:
    with pytest.raises(ValueError, match="source"):
        parse_fastener_name("M6", "part_number")  # type: ignore[arg-type]


def test_the_x_inside_a_word_never_splits_a_name() -> None:
    """`hex` has an `x` in it; only an `x` between numbers separates size from length, and
    the words after a spaced hyphen still name the head and the kind."""
    parsed = parse_fastener_name("M6x1.0 x 20 - hex head bolt", "configuration")

    assert parsed is not None
    assert (parsed.designation, parsed.length_mm, parsed.kind, parsed.head_type) == (
        "M6x1.0",
        20.0,
        "bolt",
        "hex head",
    )


def test_an_unreadable_length_is_null_not_a_guess() -> None:
    """`20 socket...` is not a number, so the length is unknown; the size still reads."""
    parsed = parse_fastener_name("M6 x 20 socket head cap screw", "configuration")

    assert parsed is not None
    assert (parsed.designation, parsed.length_mm) == ("M6", None)


# --- the order and the cross-check (FR-011) -----------------------------------------------


def test_the_file_name_is_read_first_and_the_others_cross_check() -> None:
    reading = read_fastener_names(
        "SHC_M4-0.7X12_FICT-0001.SLDPRT", "SCREW, SOC M4-0.7 X 12 MM, FICTIONAL", "Default"
    )

    assert reading.name is not None
    assert reading.name.source == "file_name"
    assert [other.source for other in reading.others] == ["description"]
    assert reading.conflicts == ()


def test_the_description_stands_in_when_the_file_name_names_no_size() -> None:
    reading = read_fastener_names("FICT-KALO-0001.SLDPRT", "SCREW, BTN M5-0.8 X 10 MM", "M5x10")

    assert reading.name is not None
    assert reading.name.source == "description"
    assert [other.source for other in reading.others] == ["configuration"]


def test_the_configuration_is_read_last() -> None:
    reading = read_fastener_names("FICT-KALO-0001.SLDPRT", "FICT SCREW KALO", "M6x1.0 x 20")

    assert reading.name is not None
    assert reading.name.source == "configuration"
    assert reading.others == ()


def test_sources_that_disagree_on_the_size_are_named_and_never_reconciled() -> None:
    reading = read_fastener_names(
        "SHC_M4-0.7X12_FICT-0001.SLDPRT", "SCREW, SOC M5-0.8 X 12 MM, FICTIONAL", "M4 x 16"
    )

    assert reading.name is not None and reading.name.designation == "M4x0.7"
    assert reading.conflicts == (
        "the description reads M5x0.8 where the file name reads M4x0.7",
        "the configuration name reads a length of 16.0 mm where the file name reads 12.0 mm",
    )


def test_a_source_silent_on_a_field_is_not_a_conflict() -> None:
    """A configuration name with no pitch or no length does not disagree with a file name
    that states them; only two stated values that differ are a conflict."""
    reading = read_fastener_names("SHC_M4-0.7X12_FICT-0001.SLDPRT", None, "M4")

    assert reading.conflicts == ()


def test_nothing_parses_to_no_name() -> None:
    reading = read_fastener_names("PLATE_BASE_FICT-0007.SLDPRT", "PLATE, BASE", "Default")

    assert reading.name is None and reading.others == () and reading.conflicts == ()


# --- the data file --------------------------------------------------------------------------


def test_the_shipped_table_loads_with_its_three_head_codes() -> None:
    names = load_fastener_names()

    assert DEFAULT_NAMES_PATH.name == "fastener_names.yaml"
    assert isinstance(names, FastenerNames)
    assert names.version == 1
    assert sorted(names.head_codes) == ["BHT", "FHT", "SHC"]
    assert names.head_codes["SHC"].drive == "hex_socket"
    assert names.kinds == ("screw", "bolt", "nut", "washer", "pin")
    assert names.heads[0] == "socket countersunk head"


def test_the_heads_are_longest_first() -> None:
    """So `socket head cap` is found before a shorter phrase inside it could be."""
    heads = load_fastener_names().heads
    for index, head in enumerate(heads):
        assert not any(head in later for later in heads[index + 1 :] if later != head), head


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "names.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_a_head_code_of_an_unknown_kind_is_refused(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "version: 1\nhead_codes:\n  ZZZ: {kind: rivet, head_type: dome, drive: null}\n"
        "kinds: [screw]\nheads: [dome]\n",
    )

    with pytest.raises(ValueError, match="ZZZ"):
        load_fastener_names(path)


def test_a_head_code_missing_its_drive_key_is_refused(tmp_path: Path) -> None:
    """A null drive is a statement ("not known"); a missing key is an omission."""
    path = _write(
        tmp_path,
        "version: 1\nhead_codes:\n  ZZZ: {kind: screw, head_type: dome}\n"
        "kinds: [screw]\nheads: [dome]\n",
    )

    with pytest.raises(ValueError, match="drive"):
        load_fastener_names(path)


def test_a_table_missing_a_section_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, "version: 1\nhead_codes: {}\nkinds: [screw]\n")

    with pytest.raises(ValueError, match="heads"):
        load_fastener_names(path)
