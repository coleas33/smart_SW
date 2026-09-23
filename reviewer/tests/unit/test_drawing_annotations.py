"""A drawing's position tolerance, and every callout and table the sheet tool shows (T041).

`contracts/drawing-source.md` section 4 item 3 and FR-027 to FR-031 are normative. A position or
coaxiality frame on a drawing annotation bound to a hole (the binding of section 3, behind the
same switch) is that hole's position tolerance for the stack-up, read through feature 010's
frame reading generalised to a list of frames. A zone value written without a unit is read in
the drawing's recorded length unit and **cited so** (owner, 2026-09-23, research R5 Q6); with
that unit unread, or not a unit the review knows, it binds nothing and says why. The sheet tool
returns the typed annotations and every table with its kind named; notes are verbatim.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from swreview.checks.result import round_length
from swreview.checks.tolerances import (
    ResolvedTolerance,
    ResolverLookup,
    ToleranceSubject,
    drawing_answer,
    frame_zone,
    resolve_tolerance,
)
from swreview.drawings import binding
from swreview.drawings.native import TABLE_KINDS, table_kind
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage, GtolFrame
from swreview.tools.context import context_for, use_context
from swreview.tools.query import get_drawing_sheet
from tests.support.drawings import Attach, DrawingBuilder
from tests.support.mechanical import load_generator

TESTS = Path(__file__).resolve().parents[1]
PLATE_DRAWING = TESTS / "fixtures" / "drawings" / "plate-drawing"
MECHANICAL = TESTS / "fixtures" / "mechanical" / "generate_fixtures.py"

POSITION = ToleranceSubject(
    kind="hole_position", nominal_mm=3.0, document_id="doc:0002", face_ids=("fac:0001",),
    instance_id="hol:0001#1", component_id="cmp:0001",
)


@pytest.fixture
def validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(binding, "DRAWING_BINDING_VALIDATED", True)


@pytest.fixture(scope="module")
def plate() -> EvidencePackage:
    return load_package(PLATE_DRAWING).package


def frame(symbol: str, value: str, number: int = 1) -> GtolFrame:
    return GtolFrame(number=number, symbols_raw=[symbol], values_raw=[value])


def with_gtol(*frames: GtolFrame, drawing: dict[str, Any] | None = None) -> EvidencePackage:
    """The tolerances assembly with one drawing whose GTol on the dowel face has `frames`."""
    builder = DrawingBuilder(load_generator(MECHANICAL).build_tolerances_assembly().package)
    record = builder.drawing(builder.drawing_document("FICT-TULMKALO-3001"), **(drawing or {}))
    view = builder.view(builder.sheet(record, "Sheet1"), "Drawing View1", references="doc:0002")
    builder.annotation(view, type_raw=5, name="GTOL1", gtol_frames=list(frames),
                       attached=[Attach("fac:0001")])
    return builder.build()


def without_model_sources(package: EvidencePackage) -> EvidencePackage:
    holes = [hole.model_copy(update={"wizard": None}) for hole in package.holes]
    return package.model_copy(
        update={"model_dimensions": [], "model_annotations": [], "holes": holes}
    )


# --- 1. the frame reading, generalised ----------------------------------------------------------


def test_the_zone_is_read_from_a_list_of_frames() -> None:
    frames = [frame("<GTOL-FLAT>", "0.01"), frame("<GTOL-POSI>", "0.05mm", 2)]

    assert frame_zone(frames) == (0.05, "mm", 2)
    assert frame_zone([frame("<GTOL-POSI>", "0.05")]) == (0.05, None, 1)
    assert frame_zone([frame("<GTOL-CONC>", "0.002in")]) == (0.002, "in", 1)
    assert frame_zone([frame("<GTOL-FLAT>", "0.01")]) is None
    assert frame_zone([frame("<GTOL-POSI>", "")]) is None
    assert frame_zone([]) is None


# --- 2. the position rule (section 4 item 3) ------------------------------------------------------


@pytest.mark.usefixtures("validated")
def test_the_dowel_position_binds_from_the_drawing_read_in_its_unit(
    plate: EvidencePackage,
) -> None:
    answer = drawing_answer(plate, POSITION)
    resolved = resolve_tolerance(plate, None, POSITION)

    assert answer.dimension is not None
    assert answer.cited == (
        "drawing doc:0006, sheet Sheet1, view Drawing View1, dan:0001 (frame 1), read in the "
        "drawing's unit, mm"
    )
    assert answer.record_id == "dan:0001"
    assert isinstance(resolved, ResolvedTolerance)
    assert resolved.source_kind == "drawing"
    assert round_length(resolved.dimension.nominal.value) == 0.05
    assert resolved.dimension.nominal.unit == "mm"
    assert resolved.dimension.source.annotation == "dan:0001"


@pytest.mark.usefixtures("validated")
def test_a_zone_that_states_its_unit_is_read_in_that_unit_and_not_cited_as_the_drawings() -> None:
    package = with_gtol(frame("<GTOL-POSI>", "0.002in"))

    answer = drawing_answer(package, POSITION)

    assert answer.dimension is not None and answer.dimension.nominal.unit == "in"
    assert answer.cited == "drawing doc:0006, sheet Sheet1, view Drawing View1, dan:0001 (frame 1)"


@pytest.mark.usefixtures("validated")
def test_an_inch_drawings_unitless_zone_is_read_in_inches() -> None:
    package = with_gtol(frame("<GTOL-POSI>", "0.002"), drawing={"length_unit_raw": 3})

    answer = drawing_answer(package, POSITION)

    assert answer.dimension is not None and answer.dimension.nominal.unit == "in"
    assert answer.cited is not None and answer.cited.endswith("read in the drawing's unit, in")


@pytest.mark.usefixtures("validated")
def test_with_the_drawings_unit_unread_a_unitless_zone_binds_nothing_naming_why() -> None:
    package = with_gtol(frame("<GTOL-POSI>", "0.05"), drawing={"length_unit_raw": None})

    answer = drawing_answer(package, POSITION)

    assert answer.dimension is None
    assert answer.why == (
        "dan:0001 states a position zone of 0.05 with no unit, and the unit drawing doc:0006 is "
        "dimensioned in was not read"
    )


@pytest.mark.usefixtures("validated")
def test_a_drawing_in_another_unit_binds_a_unitless_zone_nothing() -> None:
    package = with_gtol(frame("<GTOL-POSI>", "0.05"), drawing={"length_unit_raw": 1})

    answer = drawing_answer(package, POSITION)

    assert answer.dimension is None
    assert answer.why == (
        "dan:0001 states a position zone of 0.05 with no unit, and drawing doc:0006 is "
        "dimensioned in unit 1 (swLengthUnit_e), which is neither mm nor in"
    )


@pytest.mark.usefixtures("validated")
def test_a_frame_with_no_readable_zone_binds_nothing_naming_why() -> None:
    package = with_gtol(frame("<GTOL-POSI>", "per note"))

    answer = drawing_answer(package, POSITION)

    assert answer.dimension is None
    assert answer.why == "dan:0001 states no position zone the review can read"


@pytest.mark.usefixtures("validated")
def test_two_drawings_with_different_zones_are_the_drawing_sources_conflict() -> None:
    builder = DrawingBuilder(load_generator(MECHANICAL).build_tolerances_assembly().package)
    for stem, value in (("FICT-TULMKALO-3001", "0.05"), ("FICT-TULMKALO-3001-B", "0.08")):
        record = builder.drawing(builder.drawing_document(stem))
        view = builder.view(builder.sheet(record, "Sheet1"), "Drawing View1",
                            references="doc:0002")
        builder.annotation(view, type_raw=5, name="GTOL1",
                           gtol_frames=[frame("<GTOL-POSI>", value)],
                           attached=[Attach("fac:0001")])

    answer = drawing_answer(builder.build(), POSITION)

    assert answer.conflict is not None
    assert answer.conflict.endswith("give the position of hol:0001#1 different tolerances; "
                                    "drawing doc:0006, sheet Sheet1, view Drawing View1, "
                                    "dan:0001 (frame 1), read in the drawing's unit, mm is used")


def test_with_the_switch_off_the_position_is_feature_010s(plate: EvidencePackage) -> None:
    answer = resolve_tolerance(plate, None, POSITION)

    assert not isinstance(answer, ResolvedTolerance)
    assert dict(answer.searched)["drawing"].startswith("drawing callouts are read but not yet")


def test_a_bindable_drawing_zone_is_a_source_only_while_the_switch_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unitless = without_model_sources(with_gtol(frame("<GTOL-POSI>", "0.05")))
    unread = without_model_sources(
        with_gtol(frame("<GTOL-POSI>", "0.05"), drawing={"length_unit_raw": None})
    )

    assert ResolverLookup(unitless).holds_any_source() is False
    monkeypatch.setattr(binding, "DRAWING_BINDING_VALIDATED", True)
    assert ResolverLookup(unitless).holds_any_source() is True
    assert ResolverLookup(unread).holds_any_source() is False


# --- 3. the sheet tool shows every callout and table ------------------------------------------


def test_the_table_kinds_are_named_and_the_rest_are_numbered() -> None:
    assert TABLE_KINDS == {
        0: "General",
        1: "HoleChart",
        2: "BillOfMaterials",
        5: "TitleBlock",
        9: "GeneralTolerance",
    }
    assert table_kind(6) == "table type 6"
    assert table_kind(None) == "table type not read"


def test_the_sheet_tool_returns_the_typed_annotations_and_the_named_tables(
    plate: EvidencePackage,
) -> None:
    with use_context(context_for(plate)):
        sheet = get_drawing_sheet("doc:0006")

    assert [(table["kind"], table["title"]) for table in sheet["tables"]] == [
        ("TitleBlock", "TITLE BLOCK"),
        ("GeneralTolerance", "GENERAL TOLERANCE"),
        ("HoleChart", "HOLE TABLE"),
    ]
    assert sheet["tables"][2]["rows"][0]["cells"] == ["TAG", "X LOC", "Y LOC", "SIZE"]
    views = {view["name"]: view for view in sheet["views"]}
    annotations = {item["name"]: item for item in views["Drawing View1"]["annotations"]}
    assert annotations["GTOL1"]["gtol_frames"][0]["symbols_raw"][0] == "<GTOL-POSI>"
    assert annotations["DATUMTAG1"]["datum_label"] == "A"
    assert annotations["SFSYMBOL1"]["surface_finish_texts_raw"] == ["1.6", ""]
    assert annotations["SFSYMBOL1"]["attached_faces"][0]["scope"] == "doc:0002"


def test_notes_are_verbatim(plate: EvidencePackage) -> None:
    with use_context(context_for(plate)):
        sheet = get_drawing_sheet("doc:0006")

    views = {view["name"]: view for view in sheet["views"]}
    assert [note["text"] for note in views["Sheet Format1"]["notes"]] == [
        "FICTIONAL NOTE 1",
        "GENERAL TOLERANCE FICTIONAL: .X 0.4 .XX 0.15 .XXX 0.04",
        "BREAK SHARP EDGES FICTIONAL",
    ]


def test_a_bill_of_materials_names_its_kind_and_keeps_its_rows() -> None:
    package = load_package(TESTS / "fixtures" / "drawings" / "assembly-drawings").package
    drawing = next(
        item.document_id
        for item in package.documents
        if item.file_name == "FICT-OKTAVEN-5000.SLDDRW"
    )

    with use_context(context_for(package)):
        sheet = get_drawing_sheet(drawing)

    [bom] = sheet["tables"]
    assert bom["kind"] == "BillOfMaterials"
    assert len(bom["bom_rows"]) == 4
