"""The ingested-sheet builder (feature 014 T110; `generator.md` 6 and 11; GN-7; FR-027).

`check_fit`, `check_axial_stack` and a toleranced `check_hole_alignment` read a dimension only
through `tools/refs.resolve_dimension`, which matches PDF-ingested sheets and refuses a native
drawing dimension while the binding is unvalidated, so the case generator's fits, stacks and
drawn tolerances need a builder of ingested sheets (research §8.14). This module pins
`SheetBuilder` in `tests/support/drawings.py`:

1. a dimension it writes resolves to itself, with its tolerance in each `Limits` form, and the
   fit check reads a builder bore and shaft as it reads `test_tools_checks_fit.py`'s sheet;
2. annotations are the parser's `dim-<page>-<n>`, and an unreadable sheet is the ingest's
   `no_text` sheet with its gap;
3. `build()` only appends, and the drawing document and its manifest entry come from the one
   writer `DrawingBuilder.drawing_document` also calls, whose own output stays byte for byte
   (`test_support_drawings.py`'s regeneration test, unchanged);
4. each misuse is a `ValueError` naming the argument, and writes nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

import pytest

from swreview.ir.models import (
    Document,
    EvidencePackage,
    Gap,
    ManifestEntry,
    Note,
    Quantity,
    SourceRef,
)
from swreview.tools import checks_fit
from swreview.tools.context import context_for, use_context
from swreview.tools.refs import resolve_dimension
from tests.support import drawings
from tests.support.drawings import DrawingBuilder, Limits, SheetBuilder
from tests.support.mechanical import FICTIONAL_ROOT
from tests.support.packages import build_package

STEM = "FICT-KALO-0001"
FIRST_DRAWING = "doc:0003"
"""`build_package` holds two documents, so the first drawing a builder adds is the third."""


def mm(value: float) -> Quantity:
    return Quantity(value=value, unit="mm")


def bore_and_shaft() -> tuple[EvidencePackage, SourceRef, SourceRef]:
    """`test_tools_checks_fit.py`'s 40 H7 bore over a 40 g6 shaft, drawn by the builder."""
    builder = SheetBuilder(build_package())
    drawing = builder.drawing(STEM)
    builder.sheet(drawing, page=1)
    bore = builder.dimension(
        drawing, "Sheet1", 40.0, limits=("bilateral", 0.025, 0.0), text="40 +0.025/0"
    )
    shaft = builder.dimension(
        drawing, "Sheet1", 40.0, limits=("bilateral", -0.009, -0.025), text="40 -0.009/-0.025"
    )
    return builder.build(), bore, shaft


# --- 1. a dimension, its tolerance, and the fit check -------------------------------------


def test_a_dimension_resolves_through_resolve_dimension_to_the_one_written() -> None:
    package, bore, shaft = bore_and_shaft()

    [sheet] = package.drawings
    written_bore, written_shaft = sheet.dimensions
    assert bore == SourceRef(document_id=FIRST_DRAWING, sheet="Sheet1", annotation="dim-1-1")
    assert shaft == SourceRef(document_id=FIRST_DRAWING, sheet="Sheet1", annotation="dim-1-2")
    assert resolve_dimension(package, bore) is written_bore
    assert resolve_dimension(package, shaft) is written_shaft
    # The JSON form a model sends resolves to the same dimension.
    assert resolve_dimension(package, bore.model_dump(exclude_none=True)) is written_bore
    # Nominal in mm, the text as given, the dimension and its tolerance at the returned triple.
    assert written_bore.nominal == mm(40.0)
    assert written_bore.text_as_read == "40 +0.025/0"
    assert written_bore.source == bore
    assert written_bore.tolerance.source == bore


@pytest.mark.parametrize(
    ("limits", "kind", "upper", "lower"),
    [
        (("bilateral", 0.025, 0.0), "bilateral", mm(0.025), mm(0.0)),
        (("bilateral", -0.009, -0.025), "bilateral", mm(-0.009), mm(-0.025)),
        # An upper equal to its lower is not below it, so it is written.
        (("bilateral", 0.02, 0.02), "bilateral", mm(0.02), mm(0.02)),
        # The parser's shape: a symmetric half-width as signed deviations either side.
        (("symmetric", 0.05), "symmetric", mm(0.05), mm(-0.05)),
        (None, "none", None, None),
    ],
)
def test_each_limits_form_maps_to_its_tolerance_kind_and_values(
    limits: Limits, kind: str, upper: Quantity | None, lower: Quantity | None
) -> None:
    builder = SheetBuilder(build_package())
    drawing = builder.drawing(STEM)
    builder.sheet(drawing, page=1)
    ref = builder.dimension(drawing, "Sheet1", 12.0, limits=limits, text="12")

    tolerance = resolve_dimension(builder.build(), ref).tolerance
    assert tolerance.kind == kind
    assert tolerance.upper == upper
    assert tolerance.lower == lower
    assert tolerance.source == ref


def test_check_fit_over_a_builder_bore_and_shaft_writes_the_pinned_clearance_finding() -> None:
    """The finding `test_tools_checks_fit.py` pins for its hand-built sheet."""
    package, bore, shaft = bore_and_shaft()

    with use_context(context_for(package)) as context:
        result = checks_fit.check_fit(bore, shaft)

    assert result["status"] == "recorded"
    finding = result["finding"]
    assert finding["check"] == "fit.size_only"
    assert finding["status"] == "checked_within_scope"
    assert finding["calculation"]["result"]["fit_class"] == "clearance"
    assert finding["calculation"]["result"]["min_clearance_mm"] == 0.009
    assert finding["calculation"]["result"]["max_clearance_mm"] == 0.05
    assert [location["annotation"] for location in finding["drawing_locations"]] == [
        "dim-1-1",
        "dim-1-2",
    ]
    assert [entry["document_id"] for entry in finding["provenance"]] == [FIRST_DRAWING]
    assert [item.id for item in context.session.findings] == [finding["id"]]


# --- 2. annotations, readable sheets and unreadable ones ----------------------------------


def test_annotations_read_dim_page_n_in_call_order_on_each_sheet() -> None:
    builder = SheetBuilder(build_package())
    first = builder.drawing(STEM)
    second = builder.drawing("FICT-KALO-0002")
    builder.sheet(first, page=1)
    builder.sheet(first, "Sheet2", page=2)
    builder.sheet(second, page=1)

    refs = [
        builder.dimension(first, "Sheet1", 10.0, limits=None, text="10"),
        builder.dimension(first, "Sheet2", 20.0, limits=None, text="20"),
        builder.dimension(first, "Sheet1", 30.0, limits=None, text="30"),
        builder.dimension(second, "Sheet1", 40.0, limits=None, text="40"),
    ]

    assert [(ref.document_id, ref.sheet, ref.annotation) for ref in refs] == [
        (first, "Sheet1", "dim-1-1"),
        (first, "Sheet2", "dim-2-1"),
        (first, "Sheet1", "dim-1-2"),
        (second, "Sheet1", "dim-1-1"),
    ]
    package = builder.build()
    assert [
        (sheet.document_id, sheet.sheet_name, [item.source.annotation for item in sheet.dimensions])
        for sheet in package.drawings
    ] == [
        (first, "Sheet1", ["dim-1-1", "dim-1-2"]),
        (first, "Sheet2", ["dim-2-1"]),
        (second, "Sheet1", ["dim-1-1"]),
    ]
    assert [item.text_as_read for item in package.drawings[0].dimensions] == ["10", "30"]


def test_a_readable_sheet_is_an_ingested_mm_sheet_at_1_1_carrying_its_notes() -> None:
    builder = SheetBuilder(build_package())
    drawing = builder.drawing(STEM)
    builder.sheet(
        drawing,
        "Sheet2",
        page=2,
        notes=(
            ("UNLESS OTHERWISE SPECIFIED TOLERANCES +/-0.1", "general_tolerance"),
            ("MATERIAL: 6061-T6", "material"),
        ),
    )

    package = builder.build()

    [sheet] = package.drawings
    assert sheet.document_id == drawing
    assert sheet.sheet_name == "Sheet2"
    assert sheet.page == 2
    assert sheet.units == "mm"
    assert sheet.scale == "1:1"
    assert sheet.parse_status == "text"
    assert sheet.source == "pdf_ingest"
    assert sheet.dimensions == [] and sheet.views == []
    # The parser's note ids, `note-<page>-<n>` in the order given.
    assert sheet.general_notes == [
        Note(
            text="UNLESS OTHERWISE SPECIFIED TOLERANCES +/-0.1",
            source=SourceRef(document_id=drawing, sheet="Sheet2", annotation="note-2-1"),
            kind="general_tolerance",
        ),
        Note(
            text="MATERIAL: 6061-T6",
            source=SourceRef(document_id=drawing, sheet="Sheet2", annotation="note-2-2"),
            kind="material",
        ),
    ]
    assert package.gaps == build_package().gaps
    assert EvidencePackage.model_validate_json(package.model_dump_json()) == package


def test_an_unreadable_sheet_writes_no_text_no_dimension_and_the_ingest_s_gap() -> None:
    """The shape `ingest/pdf_drawing.py` writes for a page with no text layer: nothing on it
    was read, so it states no unit and no scale either."""
    base = build_package()
    builder = SheetBuilder(base)
    drawing = builder.drawing(STEM)
    builder.sheet(drawing, page=1)
    builder.sheet(drawing, "Sheet2", page=2, readable=False)

    package = builder.build()

    readable, unreadable = package.drawings
    assert readable.parse_status == "text"
    assert unreadable.sheet_name == "Sheet2"
    assert unreadable.page == 2
    assert unreadable.parse_status == "no_text"
    assert unreadable.dimensions == [] and unreadable.general_notes == []
    assert unreadable.units == "unknown"
    assert unreadable.scale is None
    assert unreadable.source == "pdf_ingest"
    assert package.gaps == [
        *base.gaps,
        Gap(
            kind="no_text",
            entity_kind="drawing_sheet",
            entity_id=f"{drawing}:2",
            reason=(
                f"page 2 of {drawing} has no text layer; it was exported flattened and "
                "nothing on it could be read"
            ),
            error=None,
        ),
    ]


# --- 3. build() appends, through the one drawing-document writer --------------------------


def test_drawing_writes_the_next_document_at_the_fictional_vault_with_a_pdf_entry() -> None:
    base = build_package()
    builder = SheetBuilder(base)

    drawing = builder.drawing(STEM, properties={"Description": "FICTIONAL"})
    package = builder.build()

    path = f"{FICTIONAL_ROOT}Vault\\{STEM}.SLDDRW"
    assert drawing == FIRST_DRAWING
    assert package.documents[-1] == Document(
        document_id=FIRST_DRAWING,
        kind="drawing",
        file_name=f"{STEM}.SLDDRW",
        path=path,
        configurations=["Default"],
        active_configuration="Default",
        custom_properties={"Description": "FICTIONAL"},
        config_properties={},
        material=None,
        mass=None,
    )
    assert package.manifest.entries[-1] == ManifestEntry(
        document_id=FIRST_DRAWING,
        vault_path=path,
        vault_version=1,
        revision=None,
        configuration="Default",
        local_modified=False,
        export_method="pdf",
    )
    assert package.design.drawing_document_ids == [FIRST_DRAWING]
    assert builder.drawing("FICT-KALO-0002") == "doc:0004"


def test_build_changes_no_base_row_and_appends_documents_entries_sheets_and_gaps() -> None:
    """The base already holds a drawing, its sheets and a gap (an earlier builder's), so what
    the second builder writes is seen to be appended after them."""
    earlier = SheetBuilder(build_package())
    earlier_drawing = earlier.drawing(STEM)
    earlier.sheet(earlier_drawing, page=1)
    earlier.dimension(earlier_drawing, "Sheet1", 8.0, limits=("symmetric", 0.1), text="8 +/-0.1")
    earlier.sheet(earlier_drawing, "Sheet2", page=2, readable=False)
    base = earlier.build()
    snapshot = base.model_dump_json()

    builder = SheetBuilder(base)
    drawing = builder.drawing("FICT-KALO-0002")
    builder.sheet(drawing, page=1)
    builder.sheet(drawing, "Sheet2", page=2, readable=False)
    builder.dimension(drawing, "Sheet1", 6.0, limits=None, text="6")
    package = builder.build()

    assert base.model_dump_json() == snapshot, "the base package was changed in place"
    count = len(base.documents)
    assert package.documents[:count] == base.documents
    assert [item.document_id for item in package.documents[count:]] == [drawing]
    assert package.manifest.entries[:count] == base.manifest.entries
    assert [item.document_id for item in package.manifest.entries[count:]] == [drawing]
    assert package.manifest.discrepancies == base.manifest.discrepancies
    assert package.design.drawing_document_ids == [earlier_drawing, drawing]
    assert package.design.model_copy(
        update={"drawing_document_ids": base.design.drawing_document_ids}
    ) == base.design
    assert package.drawings[: len(base.drawings)] == base.drawings
    assert [
        (item.document_id, item.sheet_name) for item in package.drawings[len(base.drawings) :]
    ] == [
        (drawing, "Sheet1"),
        (drawing, "Sheet2"),
    ]
    assert package.gaps[: len(base.gaps)] == base.gaps
    assert [item.entity_id for item in package.gaps[len(base.gaps) :]] == [f"{drawing}:2"]
    appended = {"documents", "manifest", "design", "drawings", "gaps"}
    for field in sorted(set(EvidencePackage.model_fields) - appended):
        assert getattr(package, field) == getattr(base, field), field


def test_a_built_package_does_not_change_when_the_builder_goes_on() -> None:
    builder = SheetBuilder(build_package())
    drawing = builder.drawing(STEM)
    builder.sheet(drawing, page=1)
    built = builder.build()
    snapshot = built.model_dump_json()

    builder.dimension(drawing, "Sheet1", 6.0, limits=None, text="6")
    builder.sheet(builder.drawing("FICT-KALO-0002"), page=1, readable=False)

    assert built.model_dump_json() == snapshot
    assert builder.build() != built


def test_both_builders_write_their_drawing_document_through_the_one_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One function writes a drawing document and its manifest entry, so the two builders
    cannot disagree about what a drawing document is: they differ only in the configuration
    and the export method they pass it."""
    original = drawings.write_drawing_document
    calls: list[tuple[str, str, str]] = []

    def spy(
        documents: list[Document],
        entries: list[ManifestEntry],
        stem: str,
        *,
        properties: Mapping[str, str] | None,
        configuration: str,
        export_method: Literal["native", "pdf"],
    ) -> str:
        calls.append((stem, configuration, export_method))
        return original(
            documents,
            entries,
            stem,
            properties=properties,
            configuration=configuration,
            export_method=export_method,
        )

    monkeypatch.setattr(drawings, "write_drawing_document", spy)
    sheets = SheetBuilder(build_package())
    natives = DrawingBuilder(build_package())

    ingested_id = sheets.drawing(STEM)
    native_id = natives.drawing_document(STEM)

    assert calls == [(STEM, "Default", "pdf"), (STEM, "", "native")]
    assert ingested_id == native_id == FIRST_DRAWING
    ingested, native = sheets.build(), natives.build()
    assert ingested.documents[-1].model_copy(
        update={"configurations": [], "active_configuration": ""}
    ) == native.documents[-1]
    assert ingested.manifest.entries[-1].model_copy(
        update={"configuration": "", "export_method": "native"}
    ) == native.manifest.entries[-1]


# --- 4. refusals ---------------------------------------------------------------------------


def builder_with_two_sheets() -> tuple[SheetBuilder, str]:
    """A drawing with a readable `Sheet1` and an unreadable `Sheet2`."""
    builder = SheetBuilder(build_package())
    drawing = builder.drawing(STEM)
    builder.sheet(drawing, page=1)
    builder.sheet(drawing, "Sheet2", page=2, readable=False)
    return builder, drawing


def test_an_unknown_drawing_id_is_refused_naming_it() -> None:
    builder, _ = builder_with_two_sheets()
    before = builder.build()

    # A document of the base that is not a drawing this builder wrote, and no document at all.
    with pytest.raises(ValueError, match=r"drawing_id 'doc:2'"):
        builder.sheet("doc:2", page=1)
    with pytest.raises(ValueError, match=r"drawing_id 'doc:0099'"):
        builder.sheet("doc:0099", page=1)
    with pytest.raises(ValueError, match=r"drawing_id 'doc:0099'"):
        builder.dimension("doc:0099", "Sheet1", 6.0, limits=None, text="6")

    assert builder.build() == before


def test_a_sheet_named_twice_on_one_drawing_is_refused_naming_it() -> None:
    builder, drawing = builder_with_two_sheets()
    before = builder.build()

    with pytest.raises(ValueError, match=r"name 'Sheet1'"):
        builder.sheet(drawing, page=3)
    with pytest.raises(ValueError, match=r"name 'Sheet2'"):
        builder.sheet(drawing, "Sheet2", page=3)
    assert builder.build() == before

    # The same name on another drawing is another sheet.
    other = builder.drawing("FICT-KALO-0002")
    builder.sheet(other, page=1)
    assert [(item.document_id, item.sheet_name) for item in builder.build().drawings] == [
        (drawing, "Sheet1"),
        (drawing, "Sheet2"),
        (other, "Sheet1"),
    ]


def test_a_dimension_on_a_missing_sheet_is_refused_naming_it() -> None:
    builder, drawing = builder_with_two_sheets()
    before = builder.build()

    with pytest.raises(ValueError, match=r"sheet 'Sheet3'"):
        builder.dimension(drawing, "Sheet3", 6.0, limits=None, text="6")

    assert builder.build() == before


def test_a_dimension_on_an_unreadable_sheet_is_refused_naming_it() -> None:
    builder, drawing = builder_with_two_sheets()
    before = builder.build()

    with pytest.raises(ValueError, match=r"sheet 'Sheet2'.*unreadable"):
        builder.dimension(drawing, "Sheet2", 6.0, limits=None, text="6")

    assert builder.build() == before


def test_notes_on_an_unreadable_sheet_are_refused_naming_them() -> None:
    """A page with no text layer has no notes either; writing them would be a sheet the
    ingest can never produce, and dropping them would lose what the caller asked for."""
    builder, drawing = builder_with_two_sheets()
    before = builder.build()

    with pytest.raises(ValueError, match=r"notes"):
        builder.sheet(drawing, "Sheet3", page=3, readable=False, notes=(("NOTES:", "other"),))

    assert builder.build() == before


@pytest.mark.parametrize(
    "limits",
    [
        ("bilateral", 0.0, 0.025),
        ("bilateral", -0.025, -0.009),
        ("symmetric", 0.0),
        ("symmetric", -0.05),
    ],
)
def test_limits_out_of_order_or_not_above_zero_are_refused_naming_them(limits: Limits) -> None:
    builder, drawing = builder_with_two_sheets()
    before = builder.build()

    with pytest.raises(ValueError, match=r"limits"):
        builder.dimension(drawing, "Sheet1", 6.0, limits=limits, text="6")

    assert builder.build() == before
