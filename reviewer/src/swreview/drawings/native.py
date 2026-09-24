"""Native drawing sheets as the model's tools and the resolver read them (feature 011).

`contracts/drawing-source.md` section 2 is normative. **One conversion**: `native_dimension`
turns a display dimension the drawing phase recorded into the IR `Dimension` that
`find_dimensions`, `get_drawing_sheet`, `refs.resolve_dimension` and the resolver's drawing
source all read, so a native value cannot be read two ways (FR-025, Principle V).

- `nominal` is the value as recorded - metres or radians, `DrawingDumper`'s system units - and
  no value is a reason, never a zero;
- the tolerance is the one the extractor mapped exactly as feature 010 maps a model dimension's;
  `NONE`, `BLOCK`, `GENERAL`, a class-only fit and an unread tolerance are all "not stated on
  the drawing" (`kind="none"`), which is what `find_dimensions` has always reported for an
  untoleranced PDF dimension;
- the `SourceRef` names the drawing document, the sheet, the view and the `ddm:` id;
- `text_as_read` is **composed** - text parts, the value at its written precision in its written
  unit, the tolerance - and says so, because the rendered string is not read (probe D7).

`written_precision` and `written_unit` say what the drawing writes a dimension to. Each answers
`None` when a read it needs was not made: an unknown precision or unit is unknown, and the
general tolerance binds nothing on it (FR-021, FR-022).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from swreview import units
from swreview.drawings.evidence import id_order
from swreview.ir.models import (
    Angle,
    Dimension,
    DisplayDimensionRecord,
    DrawingRecord,
    DrawingSheet,
    DrawingSheetRecord,
    DrawingView,
    EvidencePackage,
    Quantity,
    SourceRef,
    Tolerance,
)

__all__ = [
    "LENGTH_UNITS",
    "NO_OWN_TOLERANCE_TYPES",
    "TABLE_KINDS",
    "NativeSheet",
    "every_native_sheet",
    "ingested_source",
    "native_dimension",
    "native_matches",
    "native_sheet_count",
    "native_sheets",
    "shadowed_sheets",
    "sheet_payload",
    "sheet_reason",
    "table_kind",
    "written_precision",
    "written_tolerance_precision",
    "written_unit",
    "written_unit_raw",
    "written_unit_reason",
]

LENGTH_UNITS: dict[int, Literal["mm", "in"]] = {0: "mm", 3: "in"}
"""`swLengthUnit_e` members a drawing's decimal places can be counted in: `swMM` 0, `swINCHES` 3.
Every other unit is named by its number and binds nothing (research R2.9)."""

NO_OWN_TOLERANCE_TYPES: frozenset[int] = frozenset({0, 10, 11})
"""`swTolType_e` `NONE` 0, `BLOCK` 10 (the tolerance by decimal places) and `GENERAL` 11 (the
drawing's general tolerance table): a dimension of these types states no limits of its own."""

FIT_CLASSES_SHOWN: frozenset[int] = frozenset({7, 8})
"""`FIT` 7 and `FITWITHTOL` 8 show the fit classes; `FITTOLONLY` 9 shows only the limits."""

NO_UNIT_TYPES: frozenset[int] = frozenset({0, 13})
"""`swDimensionTypeUnknown` and `swScalarDimension`: the dumper records no value for them."""

COMPOSED = "(composed)"


def native_sheet_count(package: EvidencePackage) -> int:
    """How many sheets the drawing phase read, over every drawing record of `package`.

    The census and the opening brief print it **only when it is not zero**, so a package
    that carries no native sheet reports exactly what it reported before feature 011 (FR-037).
    """
    return sum(len(record.sheets) for record in package.drawing_records)


# --- what the drawing writes a dimension to --------------------------------------------------


def _read_precision(value: int | None) -> int | None:
    return value if value is not None and value >= 0 else None


def written_precision(record: DisplayDimensionRecord, drawing: DrawingRecord) -> int | None:
    """The decimals `record` is written to: its own, or its drawing's default when it uses it.

    `swDetailingLinearDimPrecision` is the default probe D4 is expected to confirm; if D4 finds
    `swUnitsLinearDecimalPlaces` governs, T064 changes the one line below. `None` when a read
    it needs is null or negative.
    """
    if record.uses_document_precision is None:
        return None
    if record.uses_document_precision:
        return _read_precision(drawing.dimension_precision_raw)
    return _read_precision(record.precision_raw)


def written_tolerance_precision(
    record: DisplayDimensionRecord, drawing: DrawingRecord
) -> int | None:
    """The decimals `record`'s tolerance is written to, by the same rule as its value's."""
    if record.uses_document_precision is None:
        return None
    if record.uses_document_precision:
        return _read_precision(drawing.tolerance_precision_raw)
    return _read_precision(record.tolerance_precision_raw)


def written_unit_raw(record: DisplayDimensionRecord, drawing: DrawingRecord) -> int | None:
    """The `swLengthUnit_e` number `record` is written in: its own, or its drawing's."""
    if record.uses_document_units is None:
        return None
    return drawing.length_unit_raw if record.uses_document_units else record.units_raw


def written_unit(
    record: DisplayDimensionRecord, drawing: DrawingRecord
) -> Literal["mm", "in"] | None:
    """`mm` or `in`, or `None` for another unit or an unread one (`written_unit_reason`)."""
    raw = written_unit_raw(record, drawing)
    return None if raw is None else LENGTH_UNITS.get(raw)


def written_unit_reason(record: DisplayDimensionRecord, drawing: DrawingRecord) -> str | None:
    """Why `written_unit` is `None`, naming the read that was not made or the unit's number."""
    if record.uses_document_units is None:
        return f"whether dimension {record.id} uses its drawing's unit was not read"
    raw = written_unit_raw(record, drawing)
    if raw is None:
        if record.uses_document_units:
            return f"the unit drawing {drawing.document_id} is dimensioned in was not read"
        return f"the unit dimension {record.id} is written in was not read"
    if raw not in LENGTH_UNITS:
        return (
            f"dimension {record.id} is written in unit {raw} (swLengthUnit_e), which is neither "
            "mm nor in"
        )
    return None


# --- the conversion ----------------------------------------------------------------------------


WrittenUnit = Literal["mm", "in"] | None


def _magnitude(value: Quantity | Angle, unit: WrittenUnit) -> float:
    """An angle in degrees; a length in `unit`, or in mm when the written unit is unknown."""
    if isinstance(value, Angle):
        return units.as_degrees(value)
    return units.convert(value, unit).converted.value if unit is not None else units.as_mm(value)


def _number(value: float, precision: int | None) -> str:
    return f"{value:.{precision}f}" if precision is not None else f"{value:g}"


def _value_text(
    value: Quantity | Angle, record: DisplayDimensionRecord, drawing: DrawingRecord
) -> str:
    """The value as the drawing writes it; a length whose unit is unknown in mm, saying so."""
    if isinstance(value, Angle):
        return f"{_number(_magnitude(value, None), written_precision(record, drawing))}°"
    unit = written_unit(record, drawing)
    if unit is None:
        return f"{_magnitude(value, None):g} mm"
    return _number(_magnitude(value, unit), written_precision(record, drawing))


def _deviation(value: Quantity | Angle, unit: WrittenUnit, precision: int | None) -> str:
    number = _magnitude(value, unit)
    text = _number(number, precision)
    return f"+{text}" if number > 0 else text


def _limit(value: Quantity | Angle, unit: WrittenUnit, precision: int | None) -> str:
    return _number(_magnitude(value, unit), precision)


def _tolerance_text(
    tolerance: Tolerance, record: DisplayDimensionRecord, drawing: DrawingRecord
) -> str:
    unit = written_unit(record, drawing)
    precision = written_tolerance_precision(record, drawing)
    upper, lower = tolerance.upper, tolerance.lower
    if tolerance.kind == "basic":
        return "BASIC"
    if tolerance.kind == "symmetric" and upper is not None:
        return f"±{_limit(upper, unit, precision)}"
    if tolerance.kind == "bilateral" and upper is not None and lower is not None:
        return f"{_deviation(upper, unit, precision)}/{_deviation(lower, unit, precision)}"
    if tolerance.kind == "limits" and upper is not None and lower is not None:
        return f"{_limit(upper, unit, precision)}/{_limit(lower, unit, precision)}"
    return ""


def _fit_text(record: DisplayDimensionRecord) -> str:
    if record.tolerance_type_raw not in FIT_CLASSES_SHOWN:
        return ""
    classes = [name for name in (record.fit_hole_class, record.fit_shaft_class) if name]
    return "/".join(classes)


def _composed(
    record: DisplayDimensionRecord,
    value: Quantity | Angle,
    tolerance: Tolerance,
    drawing: DrawingRecord,
) -> str:
    stated = " ".join(
        part for part in (_fit_text(record), _tolerance_text(tolerance, record, drawing)) if part
    )
    main = (
        f"{record.text_prefix or ''}{_value_text(value, record, drawing)}"
        f"{' ' + stated if stated else ''}{record.text_suffix or ''}"
    )
    lines = [line for line in (record.text_above, main, record.text_below) if line]
    return f"{chr(10).join(lines)} {COMPOSED}"


def native_dimension(
    record: DisplayDimensionRecord,
    view: DrawingView,
    sheet: DrawingSheetRecord,
    drawing: DrawingRecord,
) -> Dimension | str:
    """The IR `Dimension` of one display dimension, or why it has none (section 2)."""
    value = record.value
    if value is None:
        if record.dimension_type_raw in NO_UNIT_TYPES:
            return (
                f"dimension {record.id} reports type {record.dimension_type_raw}, which names no "
                "unit, so no value was recorded (its dimension_unit gap)"
            )
        return f"no value of dimension {record.id} was read"
    source = SourceRef(
        document_id=drawing.document_id,
        sheet=sheet.name,
        view=view.name,
        annotation=record.id,
        persist_ref=record.persist_ref,
    )
    stated = record.tolerance
    if record.tolerance_type_raw in NO_OWN_TOLERANCE_TYPES or stated is None:
        stated = Tolerance(kind="none", upper=None, lower=None, source=source)
    return Dimension(
        nominal=value,
        tolerance=stated,
        source=source,
        text_as_read=_composed(record, value, stated, drawing),
    )


# --- the sheets the tools walk -----------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class NativeSheet:
    """One natively read sheet of one drawing, as the sheet and dimension tools walk it."""

    drawing: DrawingRecord
    sheet: DrawingSheetRecord

    def views(self) -> Sequence[DrawingView]:
        return sorted(self.sheet.views, key=lambda item: id_order(item.id))

    def dimensions(
        self,
    ) -> list[tuple[DrawingView, DisplayDimensionRecord, Dimension | str]]:
        """Every display dimension of the sheet with its conversion, or why it has none, by
        view id then dimension id."""
        return [
            (view, record, native_dimension(record, view, self.sheet, self.drawing))
            for view in self.views()
            for record in sorted(view.display_dimensions, key=lambda item: id_order(item.id))
        ]


def native_sheets(package: EvidencePackage, document_id: str) -> list[NativeSheet]:
    """The natively read sheets of drawing `document_id`, in sheet order; none for a document
    that has no drawing record."""
    return [
        NativeSheet(drawing=record, sheet=sheet)
        for record in package.drawing_records
        if record.document_id == document_id
        for sheet in sorted(record.sheets, key=lambda item: item.index)
    ]


def every_native_sheet(package: EvidencePackage) -> list[NativeSheet]:
    """Every natively read sheet of the package: drawing document id, then sheet index."""
    documents = dict.fromkeys(
        record.document_id
        for record in sorted(package.drawing_records, key=lambda item: id_order(item.document_id))
    )
    return [item for document_id in documents for item in native_sheets(package, document_id)]


def shadowed_sheets(package: EvidencePackage) -> frozenset[tuple[str, str]]:
    """`(document id, sheet name)` of every native sheet, once `DRAWING_BINDING_VALIDATED` is
    set: an ingested sheet of the same document and name is then not read beside it, because
    native evidence wins over a PDF's (Principle IV, `contracts/drawing-source.md` section 2).

    Empty while the switch is false: a native dimension cannot be computed with before the seat
    validates it, so hiding the PDF sheet would leave nothing on that sheet a calculating tool
    could use, and a dimension read from a PDF is taken as today (spec, edge cases; corrected
    2026-09-23 on review). Empty too for a package with no native sheet, whose tools therefore
    answer exactly as before (FR-037).
    """
    # Deferred: `binding` imports the resolver, which imports this module.
    from swreview.drawings import binding

    if not binding.DRAWING_BINDING_VALIDATED:
        return frozenset()
    return frozenset(
        (item.drawing.document_id, item.sheet.name) for item in every_native_sheet(package)
    )


def ingested_source(sheet: DrawingSheet) -> str:
    """What `available_sheets` calls an ingested sheet: its stamp, and `pdf_ingest` for a sheet
    written before the stamp existed, which the drawing checks read the same way."""
    return sheet.source or "pdf_ingest"


def sheet_reason(package: EvidencePackage, sheet: DrawingSheetRecord) -> str | None:
    """Why part of a native sheet is missing: the first gap the dump recorded against it (a
    sheet whose views could not be enumerated, say), or `None`."""
    return next((gap.reason for gap in package.gaps if gap.entity_id == sheet.id), None)


TABLE_KINDS: dict[int, str] = {
    0: "General",
    1: "HoleChart",
    2: "BillOfMaterials",
    5: "TitleBlock",
    9: "GeneralTolerance",
}
"""`swTableAnnotationType_e` members the sheet tool names (research R2.12); every other table
is named by its number, and a revision table (3) is in `revision_tables`, never here."""


def table_kind(table_type_raw: int | None) -> str:
    """What the sheet tool calls a table: its kind, or its number when it has no name here."""
    if table_type_raw is None:
        return "table type not read"
    return TABLE_KINDS.get(table_type_raw, f"table type {table_type_raw}")


def sheet_payload(package: EvidencePackage, item: NativeSheet) -> dict[str, Any]:
    """What `get_drawing_sheet` returns for a native sheet: the sheet record with its views,
    dimensions, annotations, notes and tables - each table's kind named - its drawing and why
    anything is missing. Persistent references are feature 008's view to remove, not this
    payload's."""
    payload = item.sheet.model_dump(mode="json")
    for table, record in zip(payload.get("tables", []), item.sheet.tables, strict=True):
        table["kind"] = table_kind(record.table_type_raw)
    payload["document_id"] = item.drawing.document_id
    payload["reason"] = sheet_reason(package, item.sheet)
    return payload


def native_matches(
    package: EvidencePackage, source: SourceRef
) -> list[tuple[DisplayDimensionRecord, Dimension | str]]:
    """Every native display dimension at `source`'s document, sheet and annotation, with its
    conversion or why it has none: what `refs.resolve_dimension` matches on (section 2)."""
    return [
        (record, converted)
        for item in native_sheets(package, source.document_id)
        if item.sheet.name == source.sheet
        for _, record, converted in item.dimensions()
        if record.id == source.annotation
    ]
