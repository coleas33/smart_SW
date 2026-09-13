"""Unit tests for the drawing dimension grammar (T025).

Every case here is a string a SOLIDWORKS drawing actually puts on a sheet. The grammar
has one job beyond reading the number: never invent one. A fit class it cannot expand,
a thread with no depth, a sheet with no stated units - all stay unknown, and
`text_as_read` keeps the callout verbatim for the engineer to check (constitution
Principles I and II).
"""

from __future__ import annotations

import pytest

from swreview.ingest.dimension_grammar import (
    looks_like_dimension,
    normalize_text,
    parse_callout,
    parse_dimension_text,
    parse_dimensions,
    parse_thread_callout,
)
from swreview.ir.models import Angle, Quantity, SourceRef

SOURCE = SourceRef(document_id="DRW-2001", sheet="Sheet1", page=1, bbox=[10.0, 20.0, 60.0, 30.0])


def parse(text: str, units: str = "mm"):
    """Parse `text` against `SOURCE`; the common shape of every case below."""
    return parse_dimension_text(text, units, SOURCE)


# --- diameters and symmetric tolerances -------------------------------------------


def test_diameter_with_symmetric_tolerance() -> None:
    dimension = parse("Ø10.00 ±0.02")

    assert dimension is not None
    assert dimension.nominal == Quantity(value=10.0, unit="mm")
    assert dimension.tolerance.kind == "symmetric"
    assert dimension.tolerance.upper == Quantity(value=0.02, unit="mm")
    assert dimension.tolerance.lower == Quantity(value=-0.02, unit="mm")
    assert dimension.text_as_read == "Ø10.00 ±0.02"
    assert dimension.source == SOURCE
    assert dimension.tolerance.source == SOURCE


def test_diameter_sign_variant_is_read_the_same_way() -> None:
    """U+2300 DIAMETER SIGN and U+00D8 LATIN CAPITAL O WITH STROKE both appear in PDFs."""
    dimension = parse("⌀10 H7")

    assert dimension is not None
    assert dimension.nominal == Quantity(value=10.0, unit="mm")
    assert dimension.text_as_read == "⌀10 H7"


def test_a_fit_class_is_not_expanded_into_a_tolerance() -> None:
    """H7 has a tolerance in a table this build does not carry; guessing it is forbidden."""
    dimension = parse("⌀10 H7")

    assert dimension is not None
    assert dimension.tolerance.kind == "none"
    assert dimension.tolerance.upper is None
    assert dimension.tolerance.lower is None
    assert parse_callout("⌀10 H7").fit_class == "H7"


def test_a_shaft_fit_class_is_kept_as_read() -> None:
    callout = parse_callout("Ø40 g6")

    assert callout is not None
    assert callout.fit_class == "g6"
    assert parse("Ø40 g6").tolerance.kind == "none"


# --- limits and bilateral ---------------------------------------------------------


def test_limit_dimension_gives_the_mean_as_nominal() -> None:
    dimension = parse("10.02/10.00")

    assert dimension is not None
    assert dimension.nominal.unit == "mm"
    assert dimension.nominal.value == pytest.approx(10.01)
    assert dimension.tolerance.kind == "limits"
    assert dimension.tolerance.upper == Quantity(value=10.02, unit="mm")
    assert dimension.tolerance.lower == Quantity(value=10.00, unit="mm")


def test_bilateral_tolerance_with_a_slash() -> None:
    dimension = parse("10 +0.05/-0.00")

    assert dimension is not None
    assert dimension.nominal == Quantity(value=10.0, unit="mm")
    assert dimension.tolerance.kind == "bilateral"
    assert dimension.tolerance.upper == Quantity(value=0.05, unit="mm")
    assert dimension.tolerance.lower.value == pytest.approx(0.0)


def test_bilateral_tolerance_stacked_on_two_lines() -> None:
    """PyMuPDF hands the parser the two tolerance spans joined by a space."""
    dimension = parse("10 +0.05 -0.00")

    assert dimension is not None
    assert dimension.tolerance.kind == "bilateral"
    assert dimension.tolerance.upper == Quantity(value=0.05, unit="mm")
    assert dimension.tolerance.lower.value == pytest.approx(0.0)


def test_a_one_sided_tolerance_leaves_the_other_side_unknown() -> None:
    dimension = parse("10 +0.05")

    assert dimension is not None
    assert dimension.tolerance.kind == "bilateral"
    assert dimension.tolerance.upper == Quantity(value=0.05, unit="mm")
    assert dimension.tolerance.lower is None


def test_basic_dimension() -> None:
    dimension = parse("20 BSC")

    assert dimension is not None
    assert dimension.tolerance.kind == "basic"
    assert dimension.tolerance.upper is None
    assert dimension.tolerance.lower is None


# --- threads ----------------------------------------------------------------------


def test_thread_callout_yields_the_depth_as_the_dimension() -> None:
    text = "M6x1.0 - 6H ↧ 12"

    dimension = parse(text)

    assert dimension is not None
    assert dimension.nominal == Quantity(value=12.0, unit="mm")
    assert dimension.tolerance.kind == "none"
    assert dimension.text_as_read == text


def test_parse_thread_callout_reports_designation_class_and_depth() -> None:
    thread = parse_thread_callout("M6x1.0 - 6H ↧ 12")

    assert thread is not None
    assert thread.designation == "M6x1.0"
    assert thread.thread_class == "6H"
    assert thread.depth == pytest.approx(12.0)


def test_parse_thread_callout_with_spaces_around_the_pitch() -> None:
    thread = parse_thread_callout("4X M6 x 1.0 - 6H ↧ 14")

    assert thread is not None
    assert thread.designation == "M6x1.0"
    assert thread.thread_class == "6H"
    assert thread.depth == pytest.approx(14.0)
    assert parse_callout("4X M6 x 1.0 - 6H ↧ 14").count == 4


def test_a_thread_with_no_depth_states_no_depth() -> None:
    """The housing drawing's seeded defect: a thread callout with no usable depth."""
    thread = parse_thread_callout("M6x1.0 - 6H")

    assert thread is not None
    assert thread.designation == "M6x1.0"
    assert thread.depth is None
    assert parse("M6x1.0 - 6H") is None


def test_parse_thread_callout_returns_none_for_a_plain_dimension() -> None:
    assert parse_thread_callout("Ø10.00 ±0.02") is None


# --- angles -----------------------------------------------------------------------


def test_angular_dimension_is_an_angle_not_a_length() -> None:
    dimension = parse("45° ±0°30'")

    assert dimension is not None
    assert isinstance(dimension.nominal, Angle)
    assert not isinstance(dimension.nominal, Quantity)
    assert dimension.nominal == Angle(value=45.0, unit="deg")
    assert dimension.tolerance.kind == "symmetric"
    assert isinstance(dimension.tolerance.upper, Angle)
    assert dimension.tolerance.upper.value == pytest.approx(0.5)
    assert dimension.tolerance.lower.value == pytest.approx(-0.5)


def test_angular_dimension_survives_unknown_sheet_units() -> None:
    """Degrees are stated by the callout itself, not by the title block."""
    dimension = parse("30.5°", units="unknown")

    assert dimension is not None
    assert dimension.nominal == Angle(value=30.5, unit="deg")


def test_a_bare_tolerance_on_an_angle_is_read_as_degrees() -> None:
    dimension = parse("45° ±0.5")

    assert dimension is not None
    assert dimension.tolerance.upper == Angle(value=0.5, unit="deg")


def test_an_angular_tolerance_on_a_length_is_not_applied() -> None:
    """A degrees-and-minutes tolerance on a linear nominal is not understood; not guessed."""
    dimension = parse("10 ±0°30'")

    assert dimension is not None
    assert isinstance(dimension.nominal, Quantity)
    assert dimension.tolerance.kind == "none"


# --- inch sheets ------------------------------------------------------------------


def test_leading_decimal_point_on_an_inch_sheet() -> None:
    dimension = parse(".3937 ±.0005", units="in")

    assert dimension is not None
    assert dimension.nominal == Quantity(value=0.3937, unit="in")
    assert dimension.tolerance.upper == Quantity(value=0.0005, unit="in")
    assert dimension.tolerance.lower == Quantity(value=-0.0005, unit="in")


def test_length_with_unknown_sheet_units_is_not_given_a_unit() -> None:
    """No title block, no unit: the callout is a gap, never a millimetre by default."""
    assert parse("Ø10.00 ±0.02", units="unknown") is None
    assert looks_like_dimension("Ø10.00 ±0.02")


# --- counts, modifiers, symbols ---------------------------------------------------


def test_count_prefix_and_through_modifier() -> None:
    callout = parse_callout("2X Ø6.6 THRU")

    assert callout is not None
    assert callout.count == 2
    assert callout.feature == "diameter"
    assert callout.nominal == pytest.approx(6.6)
    assert "THRU" in callout.modifiers

    dimension = parse("2X Ø6.6 THRU")
    assert dimension.nominal == Quantity(value=6.6, unit="mm")
    assert dimension.tolerance.kind == "none"
    assert dimension.text_as_read == "2X Ø6.6 THRU"


def test_radius() -> None:
    callout = parse_callout("R5")

    assert callout is not None
    assert callout.feature == "radius"
    assert parse("R5").nominal == Quantity(value=5.0, unit="mm")


def test_bare_number_is_a_dimension_with_no_tolerance() -> None:
    dimension = parse("12.5")

    assert dimension is not None
    assert dimension.nominal == Quantity(value=12.5, unit="mm")
    assert dimension.tolerance.kind == "none"
    assert dimension.text_as_read == "12.5"


def test_counterbore_yields_both_the_diameter_and_the_depth() -> None:
    text = "4X ⌴ Ø11 ↧ 6.5"
    callout = parse_callout(text)

    assert callout is not None
    assert callout.count == 4
    assert callout.feature == "counterbore"
    assert callout.nominal == pytest.approx(11.0)
    assert callout.depth == pytest.approx(6.5)

    dimensions = parse_dimensions(text, "mm", SOURCE)
    assert [d.nominal.value for d in dimensions] == [pytest.approx(11.0), pytest.approx(6.5)]
    assert {d.text_as_read for d in dimensions} == {text}


def test_countersink_symbol() -> None:
    callout = parse_callout("⌵ Ø12")

    assert callout is not None
    assert callout.feature == "countersink"
    assert callout.nominal == pytest.approx(12.0)


def test_parse_dimensions_returns_one_dimension_when_there_is_no_depth() -> None:
    assert len(parse_dimensions("Ø10.00 ±0.02", "mm", SOURCE)) == 1


def test_parse_dimensions_is_empty_for_unknown_text() -> None:
    assert parse_dimensions("SECTION A-A", "mm", SOURCE) == []


# --- ascii fallbacks and normalisation --------------------------------------------


def test_ascii_fallbacks_match_the_unicode_forms() -> None:
    assert parse("DIA 10.00 +/-0.02") == parse("Ø10.00 ±0.02").model_copy(
        update={"text_as_read": "DIA 10.00 +/-0.02"}
    )


def test_ascii_degree_fallback() -> None:
    dimension = parse("45 DEG +/-0.5")

    assert dimension is not None
    assert dimension.nominal == Angle(value=45.0, unit="deg")


def test_ascii_depth_fallback() -> None:
    thread = parse_thread_callout("M6x1.0 - 6H DEPTH 12")

    assert thread is not None
    assert thread.depth == pytest.approx(12.0)


def test_normalize_text_collapses_whitespace_and_maps_symbols() -> None:
    assert normalize_text("DIA 10.00\n+/-0.02") == "Ø10.00 ±0.02"


def test_text_as_read_is_preserved_verbatim() -> None:
    text = "  Ø10.00   ±0.02 "

    dimension = parse(text)

    assert dimension is not None
    assert dimension.text_as_read == text


# --- text that is not a dimension -------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "SECTION A-A",
        "DO NOT SCALE DRAWING",
        "NOTES:",
        "SCALE 1:2",
        "SHEET 1 OF 2",
        "1:2",
        "A",
        "6061-T6",
        "UNITS: MILLIMETERS",
        "MATERIAL: 6061-T6",
        "UNLESS OTHERWISE SPECIFIED TOLERANCES ±0.1",
    ],
)
def test_unknown_text_is_not_a_dimension(text: str) -> None:
    assert parse_callout(text) is None
    assert parse(text) is None
    assert not looks_like_dimension(text)
