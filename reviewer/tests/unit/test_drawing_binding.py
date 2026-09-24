"""Which drawing record ties to which tolerance subject, and why none does (feature 011 T032).

`contracts/drawing-source.md` section 3 is normative. A drawing record is evidence about one of
feature 010's `ToleranceSubject`s only through a view usable for the subject's component
(section 1) and one of two exact routes: an **attached face** - one of its `attached_faces`,
scoped to the subject's document, is one of the subject's faces - or a **model dimension** - its
name, before a document suffix however it is spelled, is the name of the one model dimension
feature 010's source 3 binds to the subject. A size subject binds a diameter, a radius or a hole
callout **of the subject's size** (a counterbore's diameter on the same hole instance is not the
bore's); a position subject a geometric tolerance with a position or coaxiality frame. A
dimension whose displayed value is overridden, or whose override flag is unread, binds nothing.

**The binding ships disabled** (research R2.8, FR-024): with `DRAWING_BINDING_VALIDATED` as
shipped nothing binds and the reason names the seat validation. Every other test here sets it,
on or off, and never reads the shipped value.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import pytest

from swreview.checks.tolerances import ToleranceSubject
from swreview.drawings import binding
from swreview.drawings.binding import (
    NOT_VALIDATED,
    DrawingBinding,
    bindings_for,
    search_bindings,
)
from swreview.drawings.evidence import DrawingIndex
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage, GtolFrame
from tests.support.drawings import Attach, DrawingBuilder

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "drawings"

DOWEL = ToleranceSubject(
    kind="hole_size",
    nominal_mm=3.0,
    document_id="doc:0002",
    face_ids=("fac:0001",),
    instance_id="hol:0001#1",
    component_id="cmp:0001",
)
BORE = ToleranceSubject(
    kind="hole_size",
    nominal_mm=4.5,
    document_id="doc:0002",
    face_ids=("fac:0002", "fac:0003"),
    instance_id="hol:0002#1",
    component_id="cmp:0001",
)
DOWEL_POSITION = ToleranceSubject(
    kind="hole_position",
    nominal_mm=3.0,
    document_id="doc:0002",
    face_ids=("fac:0001",),
    instance_id="hol:0001#1",
    component_id="cmp:0001",
)
PIN = ToleranceSubject(
    kind="pin_size", nominal_mm=3.0, document_id="doc:0004", face_ids=("fac:0006",),
    component_id="cmp:0003",
)
POSITION_FRAME = GtolFrame(number=1, symbols_raw=["<GTOL-POSI>"], values_raw=["0.05"])


@pytest.fixture(scope="module")
def plate() -> EvidencePackage:
    return load_package(FIXTURES / "plate-drawing").package


def routes(found: tuple[DrawingBinding, ...]) -> list[tuple[str, str, bool]]:
    return [(item.record_id, item.route, item.via_edge) for item in found]


def tolerances_base() -> EvidencePackage:
    """Feature 010's tolerances assembly with no drawing, the base of every small package."""
    from tests.support.mechanical import load_generator

    generator = FIXTURES.parent / "mechanical" / "generate_fixtures.py"
    return load_generator(generator).build_tolerances_assembly().package  # type: ignore[no-any-return]


def one_drawing(
    add: Any, *, view: dict[str, Any] | None = None, base: EvidencePackage | None = None
) -> EvidencePackage:
    """The base with one drawing of the plate whose one view `add(builder, view)` fills."""
    builder = DrawingBuilder(base or tolerances_base())
    record = builder.drawing(builder.drawing_document("FICT-TULMKALO-3001"))
    shown = builder.view(builder.sheet(record, "Sheet1"), "Drawing View1", references="doc:0002",
                         **(view or {}))
    add(builder, shown)
    return builder.build()


def found_for(package: EvidencePackage, subject: ToleranceSubject) -> tuple[DrawingBinding, ...]:
    return bindings_for(DrawingIndex.for_package(package), package, subject)


# --- 1. the switch, as shipped --------------------------------------------------------------------


def test_the_switch_ships_off() -> None:
    """The one test that reads the shipped value (011 T096): T066's commit, which sets the switch
    once a seat has validated the binding, edits this pin deliberately and nothing else - every
    other test sets the switch itself (`validated`, `not_validated`), which
    `test_binding_switch_flip.py` holds."""
    assert binding.DRAWING_BINDING_VALIDATED is False


@pytest.mark.usefixtures("not_validated")
def test_with_the_switch_off_nothing_binds_and_the_reason_names_the_seat_validation(
    plate: EvidencePackage,
) -> None:
    index = DrawingIndex.for_package(plate)

    for subject in (DOWEL, BORE, DOWEL_POSITION):
        search = search_bindings(index, plate, subject)
        assert search.bindings == ()
        assert search.why == NOT_VALIDATED
        assert bindings_for(index, plate, subject) == ()
    assert NOT_VALIDATED == (
        "drawing callouts are read but not yet validated on a seat against a drawing whose "
        "callouts are known (feature 011 research R2.8)"
    )


def test_a_document_no_drawing_shows_says_so_whatever_the_switch(plate: EvidencePackage) -> None:
    search = search_bindings(DrawingIndex.for_package(plate), plate, PIN)

    assert search.bindings == ()
    assert search.why == "no drawing of doc:0004 was read"


# --- 2. the fixture ------------------------------------------------------------------------------


@pytest.mark.usefixtures("validated")
def test_the_dowel_hole_binds_by_face_and_by_model_dimension(plate: EvidencePackage) -> None:
    search = search_bindings(DrawingIndex.for_package(plate), plate, DOWEL)

    assert routes(search.bindings) == [
        ("ddm:0001", "attached_face", False),
        ("ddm:0002", "model_dimension", False),
    ]
    assert all(item.view.drawing_id == "doc:0006" for item in search.bindings)
    assert all(item.subject == DOWEL for item in search.bindings)
    assert search.excluded == (
        "dimension ddm:0009 is overridden on the drawing",
        "view Drawing View1 of doc:0007 shows configuration 'FICT-VENTA'; the review read "
        "'Default'",
    )


@pytest.mark.usefixtures("validated")
def test_the_bore_binds_its_own_diameter_and_callout_never_the_counterbores(
    plate: EvidencePackage,
) -> None:
    """The Ø8 on the counterbore face is on the same hole instance and is not its size."""
    search = search_bindings(DrawingIndex.for_package(plate), plate, BORE)

    assert routes(search.bindings) == [
        ("ddm:0003", "attached_face", False),
        ("ddm:0006", "attached_face", False),
    ]
    assert search.excluded == ("view Drawing View2 of doc:0007 is out of date with its model",)


@pytest.mark.usefixtures("validated")
def test_the_dowel_position_binds_the_position_tolerance(plate: EvidencePackage) -> None:
    search = search_bindings(DrawingIndex.for_package(plate), plate, DOWEL_POSITION)

    assert routes(search.bindings) == [("dan:0001", "attached_face", False)]
    assert search.bindings[0].record.gtol_frames[0].symbols_raw[0] == "<GTOL-POSI>"


# --- 3. each route and kind, on small packages ---------------------------------------------------


@pytest.mark.usefixtures("validated")
@pytest.mark.parametrize(
    ("fields", "binds"),
    [
        ({"type_raw": 6}, True),  # diameter
        ({"type_raw": 5, "value_mm": 1.5}, True),  # radial: 1.5 is the 3.0 hole's radius
        ({"type_raw": 15}, True),  # diametric linear
        ({"type_raw": 14, "value_mm": 1.5}, True),  # radial linear
        ({"type_raw": 2, "prefix": "", "hole_callout": True}, True),  # a hole callout
        ({"type_raw": 2, "prefix": ""}, False),  # a linear dimension never sizes a hole
        ({"type_raw": 1, "prefix": ""}, False),
    ],
)
def test_a_size_binds_a_diameter_a_radius_or_a_hole_callout_only(
    fields: dict[str, Any], binds: bool
) -> None:
    def add(builder: DrawingBuilder, view: Any) -> None:
        builder.dimension(
            view, "KALOMIR91@FICT-TULMKALO-3001", attached=[Attach("fac:0001")],
            **{"value_mm": 3.0, **fields},
        )

    package = one_drawing(add)

    assert len(found_for(package, DOWEL)) == (1 if binds else 0)


@pytest.mark.usefixtures("validated")
def test_a_dimension_of_another_size_on_one_of_the_subjects_faces_binds_nothing() -> None:
    def add(builder: DrawingBuilder, view: Any) -> None:
        builder.dimension(view, "KALOMIR91@FICT-TULMKALO-3001", value_mm=8.0,
                          attached=[Attach("fac:0003")])

    package = one_drawing(add)
    search = search_bindings(DrawingIndex.for_package(package), package, BORE)

    assert search.bindings == ()
    assert "hol:0002#1" in search.why and "attached" in search.why


@pytest.mark.usefixtures("validated")
def test_an_edge_derived_face_binds_and_says_so() -> None:
    def add(builder: DrawingBuilder, view: Any) -> None:
        builder.dimension(view, "KALOMIR91@FICT-TULMKALO-3001", value_mm=3.0,
                          attached=[Attach("fac:0001", via="edge")])

    [found] = found_for(one_drawing(add), DOWEL)

    assert (found.route, found.via_edge) == ("attached_face", True)


@pytest.mark.usefixtures("validated")
def test_a_face_reached_directly_as_well_as_by_edge_is_not_via_edge() -> None:
    def add(builder: DrawingBuilder, view: Any) -> None:
        builder.dimension(view, "KALOMIR91@FICT-TULMKALO-3001", value_mm=3.0,
                          attached=[Attach("fac:0001", via="edge"), Attach("fac:0001")])

    [found] = found_for(one_drawing(add), DOWEL)

    assert found.via_edge is False


@pytest.mark.usefixtures("validated")
def test_an_attachment_scoped_to_another_document_binds_nothing() -> None:
    from swreview.ir.models import AttachedFace
    from tests.support.packages import persist_ref

    def add(builder: DrawingBuilder, view: Any) -> None:
        builder.dimension(
            view, "KALOMIR91@FICT-TULMKALO-3001", value_mm=3.0,
            attached=[AttachedFace(persist_ref=persist_ref("fac:0001"), scope="doc:0003",
                                   via="face")],
        )

    assert found_for(one_drawing(add), DOWEL) == ()


@pytest.mark.usefixtures("validated")
@pytest.mark.parametrize(
    "name",
    [
        "KALOMIR1@FICT-HOLE-0001@fict-tulmkalo-3001.sldprt",
        "KALOMIR1@FICT-HOLE-0001@FICT-TULMKALO-3001.SLDPRT",
        "KALOMIR1@FICT-HOLE-0001@FICT-TULMKALO-3001",
        "kalomir1@fict-hole-0001@Fict-TulmKalo-3001.SldPrt",
    ],
)
def test_the_model_dimension_route_reads_the_name_before_the_document_suffix(name: str) -> None:
    def add(builder: DrawingBuilder, view: Any) -> None:
        builder.dimension(view, name, value_mm=3.0, tolerance_type_raw=8, fit_hole_class="H7")

    [found] = found_for(one_drawing(add), DOWEL)

    assert found.route == "model_dimension"


@pytest.mark.usefixtures("validated")
def test_a_name_that_is_not_the_model_dimensions_binds_nothing() -> None:
    def add(builder: DrawingBuilder, view: Any) -> None:
        builder.dimension(view, "KALOMIR2@FICT-HOLE-0001@fict-tulmkalo-3001.sldprt",
                          value_mm=3.0)

    package = one_drawing(add)
    search = search_bindings(DrawingIndex.for_package(package), package, DOWEL)

    assert search.bindings == ()
    assert "KALOMIR1@FICT-HOLE-0001" in search.why


@pytest.mark.usefixtures("validated")
def test_an_ambiguous_model_dimension_binds_nothing_by_name() -> None:
    """The bore's two equal 4.5 mm model dimensions leave no one model dimension to name."""
    def add(builder: DrawingBuilder, view: Any) -> None:
        builder.dimension(view, "KALOMIR2@FICT-HOLE-0001@fict-tulmkalo-3001.sldprt",
                          value_mm=4.5)

    package = one_drawing(add)
    search = search_bindings(DrawingIndex.for_package(package), package, BORE)

    assert search.bindings == ()
    assert "2 dimensions of doc:0002 are 4.5 mm" in search.why


@pytest.mark.usefixtures("validated")
@pytest.mark.parametrize(
    ("overridden", "reason"),
    [
        (True, "dimension ddm:0001 is overridden on the drawing"),
        (None, "whether dimension ddm:0001 is overridden on the drawing was not read"),
    ],
)
def test_an_overridden_dimension_or_an_unread_flag_binds_nothing(
    overridden: bool | None, reason: str
) -> None:
    def add(builder: DrawingBuilder, view: Any) -> None:
        builder.dimension(view, "KALOMIR91@FICT-TULMKALO-3001", value_mm=3.0,
                          overridden=overridden, override_mm=3.05,
                          attached=[Attach("fac:0001")])

    package = one_drawing(add)
    search = search_bindings(DrawingIndex.for_package(package), package, DOWEL)

    assert search.bindings == ()
    assert search.excluded == (reason,)
    assert search.why == reason


@pytest.mark.usefixtures("validated")
@pytest.mark.parametrize(
    ("view", "reason"),
    [
        ({"out_of_date": True}, "view Drawing View1 of doc:0006 is out of date with its model"),
        ({"loaded": False}, "view Drawing View1 of doc:0006 shows a model that is not loaded"),
        (
            {"configuration": "FICT-VENTA"},
            "view Drawing View1 of doc:0006 shows configuration 'FICT-VENTA'; the review read "
            "'Default'",
        ),
    ],
)
def test_a_record_in_an_unusable_view_is_excluded_with_section_1s_words(
    view: dict[str, Any], reason: str
) -> None:
    def add(builder: DrawingBuilder, shown: Any) -> None:
        builder.dimension(shown, "KALOMIR91@FICT-TULMKALO-3001", value_mm=3.0,
                          tolerance=("bilateral", 0.01, 0.0), tolerance_type_raw=2,
                          attached=[Attach("fac:0001")])

    package = one_drawing(add, view=view)
    search = search_bindings(DrawingIndex.for_package(package), package, DOWEL)

    assert search.bindings == ()
    assert search.why == reason


@pytest.mark.usefixtures("validated")
def test_a_position_binds_only_a_position_or_coaxiality_frame() -> None:
    flatness = GtolFrame(number=1, symbols_raw=["<GTOL-FLAT>"], values_raw=["0.05"])
    concentric = GtolFrame(number=1, symbols_raw=["<GTOL-CONC>"], values_raw=["0.02"])

    def add(builder: DrawingBuilder, view: Any) -> None:
        builder.annotation(view, type_raw=5, name="GTOL1", gtol_frames=[flatness],
                           attached=[Attach("fac:0001")])
        builder.annotation(view, type_raw=5, name="GTOL2", gtol_frames=[concentric],
                           attached=[Attach("fac:0001")])
        builder.annotation(view, type_raw=2, name="DATUMTAG1", datum_label="A",
                           attached=[Attach("fac:0001")])

    found = found_for(one_drawing(add), DOWEL_POSITION)

    assert [item.record.name for item in found] == ["GTOL2"]


@pytest.mark.usefixtures("validated")
def test_a_position_never_binds_a_dimension_and_a_size_never_a_tolerance_frame() -> None:
    def add(builder: DrawingBuilder, view: Any) -> None:
        builder.dimension(view, "KALOMIR91@FICT-TULMKALO-3001", value_mm=3.0,
                          attached=[Attach("fac:0001")])
        builder.annotation(view, type_raw=5, name="GTOL1", gtol_frames=[POSITION_FRAME],
                           attached=[Attach("fac:0001")])

    package = one_drawing(add)

    assert [item.route for item in found_for(package, DOWEL)] == ["attached_face"]
    assert found_for(package, DOWEL)[0].record_id.startswith("ddm:")
    assert [item.record_id[:3] for item in found_for(package, DOWEL_POSITION)] == ["dan"]


@pytest.mark.usefixtures("validated")
def test_a_part_in_two_configurations_binds_only_for_the_instance_the_view_shows() -> None:
    base = tolerances_base()
    second = base.components[0].model_copy(
        update={"id": "cmp:0009", "referenced_configuration": "FICT-VENTA", "name": "second"}
    )
    base = base.model_copy(update={"components": [*base.components, second]})

    def add(builder: DrawingBuilder, view: Any) -> None:
        builder.dimension(view, "KALOMIR91@FICT-TULMKALO-3001", value_mm=3.0,
                          attached=[Attach("fac:0001")])

    package = one_drawing(add, view={"configuration": "FICT-VENTA"}, base=base)
    other = ToleranceSubject(
        kind="hole_size", nominal_mm=3.0, document_id="doc:0002", face_ids=("fac:0001",),
        instance_id="hol:0001#9", component_id="cmp:0009",
    )

    assert found_for(package, other) != ()
    assert found_for(package, DOWEL) == ()


# --- 4. the order ---------------------------------------------------------------------------------


@pytest.mark.usefixtures("validated")
def test_the_order_is_the_indexs_whatever_the_arrays(plate: EvidencePackage) -> None:
    expected = routes(found_for(plate, DOWEL))
    shuffler = random.Random(7)
    for _ in range(5):
        records = []
        for record in plate.drawing_records:
            sheets = []
            for sheet in record.sheets:
                views = [
                    view.model_copy(
                        update={
                            "display_dimensions": shuffler.sample(
                                view.display_dimensions, len(view.display_dimensions)
                            )
                        }
                    )
                    for view in sheet.views
                ]
                shuffled_views = shuffler.sample(views, len(views))
                sheets.append(sheet.model_copy(update={"views": shuffled_views}))
            records.append(record.model_copy(update={"sheets": sheets}))
        shuffled = plate.model_copy(
            update={"drawing_records": shuffler.sample(records, len(records))}
        )
        assert routes(found_for(shuffled, DOWEL)) == expected
