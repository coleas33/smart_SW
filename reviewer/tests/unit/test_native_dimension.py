"""One conversion of a native display dimension to the IR `Dimension` (feature 011 T030).

`contracts/drawing-source.md` section 2 is normative. `native_dimension` is the one place a
display dimension the drawing phase recorded becomes the `Dimension` the tools and the
resolver read: the value as recorded, the tolerance the extractor mapped (or "not stated on the
drawing" for `NONE`, `BLOCK`, `GENERAL`, a class-only fit or an unread one), a `SourceRef`
naming the drawing, sheet, view and `ddm:` id, and a `text_as_read` **composed** from the text
parts at the written precision and labelled so, because the rendered string is not read (probe
D7). `written_precision` and `written_unit` say what the drawing writes a dimension to, and
say nothing when a read they need was not made.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from swreview.drawings.native import (
    native_dimension,
    native_sheet_count,
    native_sheets,
    written_precision,
    written_unit,
    written_unit_reason,
)
from swreview.ir.loader import load_package
from swreview.ir.models import (
    Angle,
    Dimension,
    DisplayDimensionRecord,
    DrawingRecord,
    DrawingSheetRecord,
    DrawingView,
    EvidencePackage,
    Quantity,
    SourceRef,
    Tolerance,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "drawings"


@pytest.fixture(scope="module")
def plate() -> EvidencePackage:
    return load_package(FIXTURES / "plate-drawing").package


def located(package: EvidencePackage, name: str) -> tuple[
    DisplayDimensionRecord, DrawingView, DrawingSheetRecord, DrawingRecord
]:
    """The display dimension whose name starts `name`, with its view, sheet and drawing."""
    for record in package.drawing_records:
        for sheet in record.sheets:
            for view in sheet.views:
                for dimension in view.display_dimensions:
                    if (dimension.name or "").startswith(name):
                        return dimension, view, sheet, record
    raise AssertionError(f"no dimension {name}")


def converted(package: EvidencePackage, name: str) -> Dimension | str:
    return native_dimension(*located(package, name))


# --- a small hand-built drawing ------------------------------------------------------------------

SHEET = DrawingSheetRecord(id="dsh:0001", name="Sheet1", index=0, was_active=True)
VIEW = DrawingView(id="dvw:0001", sheet_id="dsh:0001", name="Drawing View1")


def drawing(**fields: Any) -> DrawingRecord:
    base: dict[str, Any] = {
        "document_id": "doc:0009",
        "length_unit_raw": 0,
        "dimension_precision_raw": 2,
        "tolerance_precision_raw": 3,
    }
    return DrawingRecord(**{**base, **fields})


def record(**fields: Any) -> DisplayDimensionRecord:
    base: dict[str, Any] = {
        "id": "ddm:0001",
        "view_id": "dvw:0001",
        "name": "KALOMIR1@FICT-TULMKALO-9001",
        "dimension_type_raw": 6,
        "is_overridden": False,
        "value": Quantity(value=0.0125, unit="m"),
        "text_prefix": "<MOD-DIAM>",
        "text_suffix": "",
        "text_above": "",
        "text_below": "",
        "precision_raw": 2,
        "tolerance_precision_raw": 3,
        "uses_document_precision": False,
        "units_raw": 0,
        "uses_document_units": False,
        "tolerance_type_raw": 0,
    }
    return DisplayDimensionRecord(**{**base, **fields})


def where() -> SourceRef:
    return SourceRef(document_id="doc:0009", sheet="Sheet1", view="Drawing View1",
                     annotation="ddm:0001")


def tolerance(kind: str, upper: float | None, lower: float | None) -> Tolerance:
    return Tolerance(
        kind=kind,  # type: ignore[arg-type]
        upper=None if upper is None else Quantity(value=upper / 1000.0, unit="m"),
        lower=None if lower is None else Quantity(value=lower / 1000.0, unit="m"),
        source=where(),
    )


def convert(dimension: DisplayDimensionRecord, owner: DrawingRecord | None = None) -> Dimension:
    result = native_dimension(dimension, VIEW, SHEET, owner or drawing())
    assert isinstance(result, Dimension), result
    return result


# --- 1. the value, the unit and the source -----------------------------------------------------


def test_a_toleranced_length_converts_with_its_limits_and_its_place(plate: EvidencePackage) -> None:
    dimension, view, sheet, owner = located(plate, "KALOMIR11")

    result = native_dimension(dimension, view, sheet, owner)

    assert isinstance(result, Dimension)
    assert result.nominal == Quantity(value=0.003, unit="m")
    assert result.tolerance == dimension.tolerance
    assert result.source == SourceRef(
        document_id="doc:0006",
        sheet="Sheet1",
        view="Drawing View1",
        annotation=dimension.id,
        persist_ref=dimension.persist_ref,
    )
    assert result.text_as_read == "<MOD-DIAM>3.00 +0.010/0.000 (composed)"


def test_an_angle_converts_in_degrees() -> None:
    angle = record(
        dimension_type_raw=3,
        value=Angle(value=0.7853981633974483, unit="rad"),
        text_prefix="",
        units_raw=None,
        uses_document_units=None,
        precision_raw=1,
    )

    result = convert(angle)

    assert result.nominal == Angle(value=0.7853981633974483, unit="rad")
    assert result.text_as_read == "45.0° (composed)"


def test_a_dimension_with_no_unit_is_a_reason_naming_its_gap(plate: EvidencePackage) -> None:
    result = converted(plate, "KALOMIR18")

    assert isinstance(result, str)
    assert "type 13" in result and "names no unit" in result
    assert "dimension_unit" in result


def test_a_dimension_whose_value_was_not_read_is_a_reason() -> None:
    result = native_dimension(record(value=None), VIEW, SHEET, drawing())

    assert result == "no value of dimension ddm:0001 was read"


def test_the_value_is_the_models_even_when_the_drawing_overrides_it(plate: EvidencePackage) -> None:
    """The override is what the sheet shows; `value` is the model's. Showing it is not binding
    it: the binding refuses an overridden dimension (section 3)."""
    result = converted(plate, "KALOMIR19")

    assert isinstance(result, Dimension)
    assert result.nominal == Quantity(value=0.003, unit="m")


def test_an_unnamed_view_leaves_the_view_locator_out() -> None:
    unnamed = VIEW.model_copy(update={"name": None})

    result = native_dimension(record(), unnamed, SHEET, drawing())

    assert isinstance(result, Dimension)
    assert result.source.view is None
    assert result.source.sheet == "Sheet1" and result.source.annotation == "ddm:0001"


# --- 2. the tolerance ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("KALOMIR13", "none"),  # NONE (0)
        ("KALOMIR14", "none"),  # BLOCK (10)
        ("KALOMIR15", "none"),  # GENERAL (11)
        ("KALOMIR1@", "none"),  # a class-only fit (8), no IR kind
        ("KALOMIR11", "bilateral"),
    ],
)
def test_each_tolerance_type_maps_to_what_the_drawing_states(
    plate: EvidencePackage, name: str, kind: str
) -> None:
    result = converted(plate, name)

    assert isinstance(result, Dimension)
    assert result.tolerance.kind == kind


def test_an_unread_tolerance_is_not_stated_never_a_guess() -> None:
    result = convert(record(tolerance=None, tolerance_type_raw=None))

    assert result.tolerance.kind == "none"
    assert result.tolerance.upper is None and result.tolerance.lower is None
    assert result.tolerance.source == result.source


def test_block_and_general_state_no_limits_of_their_own() -> None:
    for raw in (10, 11):
        result = convert(record(tolerance=None, tolerance_type_raw=raw))
        assert (result.tolerance.kind, result.tolerance.upper) == ("none", None)


@pytest.mark.parametrize(
    ("given", "raw", "text"),
    [
        (("symmetric", 0.05, None), 4, "<MOD-DIAM>12.50 ±0.050 (composed)"),
        (("bilateral", 0.02, -0.01), 2, "<MOD-DIAM>12.50 +0.020/-0.010 (composed)"),
        (("basic", None, None), 1, "<MOD-DIAM>12.50 BASIC (composed)"),
        (("limits", 12.52, 12.49), 3, "<MOD-DIAM>12.50 12.520/12.490 (composed)"),
    ],
)
def test_the_composed_text_states_the_tolerance(
    given: tuple[str, float | None, float | None], raw: int, text: str
) -> None:
    result = convert(record(tolerance=tolerance(*given), tolerance_type_raw=raw))

    assert result.text_as_read == text


def test_a_fit_names_its_classes() -> None:
    hole_only = convert(record(tolerance=None, tolerance_type_raw=7, fit_hole_class="H7"))
    both = convert(
        record(tolerance=None, tolerance_type_raw=7, fit_hole_class="H7", fit_shaft_class="g6")
    )
    with_limits = convert(
        record(
            tolerance=tolerance("bilateral", 0.018, 0.0),
            tolerance_type_raw=8,
            fit_hole_class="H7",
        )
    )

    assert hole_only.text_as_read == "<MOD-DIAM>12.50 H7 (composed)"
    assert both.text_as_read == "<MOD-DIAM>12.50 H7/g6 (composed)"
    assert with_limits.text_as_read == "<MOD-DIAM>12.50 H7 +0.018/0.000 (composed)"
    assert with_limits.tolerance.kind == "bilateral"


def test_the_text_above_and_below_go_on_their_own_lines() -> None:
    result = convert(record(text_above="2X", text_below="THRU", text_suffix=" TYP"))

    assert result.text_as_read == "2X\n<MOD-DIAM>12.50 TYP\nTHRU (composed)"


def test_an_unread_text_part_is_left_out() -> None:
    result = convert(record(text_prefix=None, text_suffix=None, text_above=None, text_below=None))

    assert result.text_as_read == "12.50 (composed)"


def test_the_value_is_written_in_the_drawings_unit() -> None:
    inches = convert(record(units_raw=3, value=Quantity(value=0.0254, unit="m"), precision_raw=3))

    assert inches.text_as_read == "<MOD-DIAM>1.000 (composed)"


def test_an_unknown_written_unit_or_precision_shows_the_value_in_mm_and_says_so() -> None:
    other_unit = convert(record(units_raw=1))
    no_precision = convert(record(precision_raw=None))

    assert other_unit.text_as_read == "<MOD-DIAM>12.5 mm (composed)"
    assert no_precision.text_as_read == "<MOD-DIAM>12.5 (composed)"


# --- 3. the written precision -------------------------------------------------------------------


def test_the_written_precision_is_the_dimensions_own() -> None:
    assert written_precision(record(precision_raw=3), drawing()) == 3


def test_the_written_precision_is_the_drawings_default_when_the_dimension_uses_it(
    plate: EvidencePackage,
) -> None:
    dimension, _, _, owner = located(plate, "KALOMIR13")

    assert dimension.uses_document_precision is True
    assert written_precision(dimension, owner) == owner.dimension_precision_raw == 2
    assert written_precision(
        record(uses_document_precision=True, precision_raw=4), drawing(dimension_precision_raw=1)
    ) == 1


@pytest.mark.parametrize(
    ("dimension", "owner"),
    [
        ({"uses_document_precision": None}, {}),
        ({"precision_raw": None}, {}),
        ({"precision_raw": -1}, {}),
        ({"uses_document_precision": True}, {"dimension_precision_raw": None}),
        ({"uses_document_precision": True}, {"dimension_precision_raw": -1}),
    ],
)
def test_an_unread_precision_is_unknown(dimension: dict[str, Any], owner: dict[str, Any]) -> None:
    assert written_precision(record(**dimension), drawing(**owner)) is None


# --- 4. the written unit ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dimension", "owner", "unit"),
    [
        ({"units_raw": 0}, {}, "mm"),
        ({"units_raw": 3}, {}, "in"),
        ({"uses_document_units": True, "units_raw": 3}, {"length_unit_raw": 0}, "mm"),
        ({"uses_document_units": True, "units_raw": 0}, {"length_unit_raw": 3}, "in"),
    ],
)
def test_the_written_unit_is_the_dimensions_or_the_drawings(
    dimension: dict[str, Any], owner: dict[str, Any], unit: str
) -> None:
    assert written_unit(record(**dimension), drawing(**owner)) == unit
    assert written_unit_reason(record(**dimension), drawing(**owner)) is None


def test_another_unit_is_no_unit_and_the_reason_keeps_its_number() -> None:
    dimension, owner = record(units_raw=1), drawing()

    assert written_unit(dimension, owner) is None
    assert written_unit_reason(dimension, owner) == (
        "dimension ddm:0001 is written in unit 1 (swLengthUnit_e), which is neither mm nor in"
    )


@pytest.mark.parametrize(
    ("dimension", "owner", "reason"),
    [
        ({"units_raw": None}, {}, "the unit dimension ddm:0001 is written in was not read"),
        ({"uses_document_units": None}, {},
         "whether dimension ddm:0001 uses its drawing's unit was not read"),
        ({"uses_document_units": True}, {"length_unit_raw": None},
         "the unit drawing doc:0009 is dimensioned in was not read"),
    ],
)
def test_an_unread_unit_is_unknown_and_says_which_read(
    dimension: dict[str, Any], owner: dict[str, Any], reason: str
) -> None:
    assert written_unit(record(**dimension), drawing(**owner)) is None
    assert written_unit_reason(record(**dimension), drawing(**owner)) == reason


# --- 5. the sheets the tools walk ---------------------------------------------------------------


def test_native_sheets_are_a_drawings_own_in_sheet_order(plate: EvidencePackage) -> None:
    sheets = native_sheets(plate, "doc:0006")

    assert [(item.drawing.document_id, item.sheet.name) for item in sheets] == [
        ("doc:0006", "Sheet1")
    ]
    assert native_sheets(plate, "doc:0002") == []
    assert native_sheets(plate, "doc:9999") == []


def test_a_native_sheet_lists_every_dimension_converted_or_its_reason(
    plate: EvidencePackage,
) -> None:
    [sheet] = native_sheets(plate, "doc:0006")

    rows = sheet.dimensions()

    names = [record.name for _, record, _ in rows]
    assert len(names) == 9
    reasons = [result for _, _, result in rows if isinstance(result, str)]
    assert len(reasons) == 1 and "names no unit" in reasons[0]
    assert all(view.name == "Drawing View1" for view, _, _ in rows)


def test_native_sheets_come_in_index_order_whatever_the_array_order() -> None:
    root = load_package(FIXTURES / "drawing-root").package
    record_ = root.drawing_records[0]
    reversed_record = record_.model_copy(update={"sheets": list(reversed(record_.sheets))})
    shuffled = root.model_copy(update={"drawing_records": [reversed_record]})

    names = [item.sheet.name for item in native_sheets(shuffled, record_.document_id)]

    assert names == ["Sheet1", "Sheet2", "Sheet3"]
    assert native_sheet_count(shuffled) == 3
