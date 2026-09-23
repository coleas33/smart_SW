"""Which drawing views show which document, and which a check may use (feature 011 T022).

`contracts/drawing-source.md` section 1 is normative. `DrawingIndex.for_package` walks the
drawing records in document-id order, sheets by index, views by id, and yields one
`ViewEvidence` per view that shows a document of the package. A view is usable for a component
only when the drawing is not in detailing mode, the view's model is loaded, the view is not out
of date and it shows the configuration the review read for that component - and otherwise it
carries the **first** failing reason, a null read failing with its own words, because an
unread flag is never a pass (constitution Principle I).
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import pytest

from swreview.drawings.evidence import DrawingIndex, ViewEvidence, id_order
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from tests.support.drawings import DrawingBuilder
from tests.support.mechanical import PackageBuilder

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "drawings"


def fixture(name: str) -> EvidencePackage:
    return load_package(FIXTURES / name).package


def projection(view: ViewEvidence) -> tuple[Any, ...]:
    return (
        view.drawing_id,
        view.sheet.id,
        view.view.id,
        view.document_id,
        view.configuration,
        view.usable,
        view.why,
    )


# --- small packages ----------------------------------------------------------------------------


def part_package(*configurations: str) -> tuple[PackageBuilder, str, list[str]]:
    """An assembly holding one part instanced once per configuration given."""
    base = PackageBuilder(design_stem="FICT-TULMVEN-9000", schema_version="1.6.0")
    part = base.document(
        "FICT-TULMKALO-9001", "part", configurations=tuple(dict.fromkeys(configurations))
    )
    components = [base.component(part, configuration=name) for name in configurations]
    return base, part, components


def one_view(
    *,
    drawing: dict[str, Any] | None = None,
    view: dict[str, Any] | None = None,
    configurations: tuple[str, ...] = ("Default",),
) -> tuple[EvidencePackage, DrawingIndex]:
    base, part, _ = part_package(*configurations)
    builder = DrawingBuilder(base.build().package)
    record = builder.drawing(builder.drawing_document("FICT-TULMKALO-9001"), **(drawing or {}))
    sheet = builder.sheet(record, "Sheet1")
    builder.view(sheet, "Drawing View1", references=part, **(view or {}))
    package = builder.build()
    return package, DrawingIndex.for_package(package)


# --- 1. the fixtures ---------------------------------------------------------------------------


def test_the_plate_is_shown_by_one_usable_view_and_two_unusable_ones() -> None:
    package = fixture("plate-drawing")
    index = DrawingIndex.for_package(package)
    plate = "doc:0002"

    views = index.views_of(plate)

    assert [(view.drawing_id, view.view.name) for view in views] == [
        ("doc:0006", "Drawing View1"),
        ("doc:0007", "Drawing View1"),
        ("doc:0007", "Drawing View2"),
    ]
    assert [view.usable for view in views] == [True, False, False]
    assert views[0].why is None
    assert views[1].why == (
        "view Drawing View1 of doc:0007 shows configuration 'FICT-VENTA'; the review read "
        "'Default'"
    )
    assert views[2].why == "view Drawing View2 of doc:0007 is out of date with its model"
    assert index.drawings_of(plate) == ("doc:0006", "doc:0007")


def test_a_view_that_shows_no_document_is_not_evidence_about_one() -> None:
    """The sheet-format pseudo-view references nothing, so it shows no document."""
    index = DrawingIndex.for_package(fixture("plate-drawing"))

    assert all(view.view.name != "Sheet Format1" for view in index.views)
    assert {view.document_id for view in index.views} == {"doc:0002"}


def test_the_candidate_is_indexed_by_its_document() -> None:
    index = DrawingIndex.for_package(fixture("plate-drawing"))

    [candidate] = index.candidates
    assert candidate.document_id == "doc:0003"
    assert index.candidate_of("doc:0003") == candidate
    assert index.candidate_of("doc:0002") is None


def test_one_part_shown_by_three_drawings_and_a_view_of_an_outside_document() -> None:
    package = fixture("assembly-drawings")
    index = DrawingIndex.for_package(package)
    kalo = next(
        item.document_id for item in package.documents if item.file_name.startswith("FICT-OKTAKALO")
    )
    root = package.design.root_assembly_document_id

    assert len(index.drawings_of(kalo)) == 3
    assert list(index.drawings_of(kalo)) == sorted(index.drawings_of(kalo), key=id_order)
    assert len(index.views_of(root)) == 1
    outside = [
        view
        for record in package.drawing_records
        for sheet in record.sheets
        for view in sheet.views
        if view.referenced_document_id is None and view.referenced_model_path
    ]
    assert outside
    assert all(item.view.id != outside[0].id for item in index.views)
    assert index.candidates == ()


def test_the_root_drawing_is_the_design_root_when_it_is_a_drawing() -> None:
    root = fixture("drawing-root")

    assert DrawingIndex.for_package(root).root_drawing_id == root.design.root_assembly_document_id
    assert DrawingIndex.for_package(fixture("plate-drawing")).root_drawing_id is None


def test_a_package_with_no_drawing_gives_an_empty_index() -> None:
    base, part, _ = part_package("Default")
    index = DrawingIndex.for_package(base.build().package)

    assert index.views == ()
    assert index.views_of(part) == ()
    assert index.drawings_of(part) == ()
    assert index.candidates == ()
    assert index.root_drawing_id is None


# --- 2. each condition on its own (section 1's table) -----------------------------------------


@pytest.mark.parametrize(
    ("drawing", "view", "reason"),
    [
        (
            {"is_detailing_mode": True},
            {},
            "drawing doc:0003 is in detailing mode, so its views load no model",
        ),
        (
            {"is_detailing_mode": None},
            {},
            "whether drawing doc:0003 is in detailing mode was not read",
        ),
        (
            {},
            {"loaded": False},
            "view Drawing View1 of doc:0003 shows a model that is not loaded",
        ),
        (
            {},
            {"loaded": None},
            "whether view Drawing View1 of doc:0003 has its model loaded was not read",
        ),
        (
            {},
            {"out_of_date": True},
            "view Drawing View1 of doc:0003 is out of date with its model",
        ),
        (
            {},
            {"out_of_date": None},
            "whether view Drawing View1 is up to date was not read",
        ),
        (
            {},
            {"configuration": "FICT-VENTA"},
            "view Drawing View1 of doc:0003 shows configuration 'FICT-VENTA'; the review read "
            "'Default'",
        ),
        (
            {},
            {"configuration": None},
            "the configuration view Drawing View1 shows was not read",
        ),
    ],
)
def test_each_condition_failing_on_its_own_names_its_reason(
    drawing: dict[str, Any], view: dict[str, Any], reason: str
) -> None:
    package, index = one_view(drawing=drawing, view=view)
    [evidence] = index.views
    component = package.components[0].id

    assert evidence.usable is False
    assert evidence.why == reason
    assert index.why_not_for(evidence, component) == reason


def test_every_condition_holding_is_usable() -> None:
    package, index = one_view()
    [evidence] = index.views

    assert evidence.usable is True and evidence.why is None
    assert index.why_not_for(evidence, package.components[0].id) is None


def test_the_first_failing_condition_is_the_one_named() -> None:
    """Detailing mode before the load, the load before the date, the date before the
    configuration: section 1's order."""
    _, index = one_view(
        drawing={"is_detailing_mode": True},
        view={"loaded": False, "out_of_date": True, "configuration": "FICT-VENTA"},
    )
    assert index.views[0].why == (
        "drawing doc:0003 is in detailing mode, so its views load no model"
    )

    _, index = one_view(view={"loaded": False, "out_of_date": True, "configuration": None})
    assert index.views[0].why == "view Drawing View1 of doc:0003 shows a model that is not loaded"

    _, index = one_view(view={"out_of_date": None, "configuration": "FICT-VENTA"})
    assert index.views[0].why == "whether view Drawing View1 is up to date was not read"


def test_an_unnamed_view_is_named_by_its_id() -> None:
    package, _ = one_view(view={"out_of_date": True})
    views = package.drawing_records[0].sheets[0].views
    views[0] = views[0].model_copy(update={"name": None})

    [evidence] = DrawingIndex.for_package(package).views

    assert evidence.why == f"view {views[0].id} of doc:0003 is out of date with its model"


# --- 3. a part used in two configurations -----------------------------------------------------


def test_a_view_is_usable_for_the_instances_of_the_configuration_it_shows_only() -> None:
    base, part, (first, second) = part_package("Default", "FICT-VENTA")
    builder = DrawingBuilder(base.build().package)
    record = builder.drawing(builder.drawing_document("FICT-TULMKALO-9001"))
    builder.view(builder.sheet(record, "Sheet1"), "Drawing View1", references=part,
                 configuration="FICT-VENTA")
    index = DrawingIndex.for_package(builder.build())
    [evidence] = index.views

    assert evidence.usable is True, "it shows a configuration the review read"
    assert index.why_not_for(evidence, second) is None
    assert index.why_not_for(evidence, first) == (
        "view Drawing View1 of doc:0003 shows configuration 'FICT-VENTA'; the review read "
        "'Default'"
    )


def test_a_view_of_a_configuration_no_instance_uses_names_every_one_the_review_read() -> None:
    base, part, _ = part_package("Default", "FICT-VENTA")
    builder = DrawingBuilder(base.build().package)
    record = builder.drawing(builder.drawing_document("FICT-TULMKALO-9001"))
    builder.view(builder.sheet(record, "Sheet1"), "Drawing View1", references=part,
                 configuration="FICT-OTHER")
    [evidence] = DrawingIndex.for_package(builder.build()).views

    assert evidence.usable is False
    assert evidence.why == (
        "view Drawing View1 of doc:0003 shows configuration 'FICT-OTHER'; the review read "
        "'Default' and 'FICT-VENTA'"
    )


def test_a_document_with_no_instance_is_compared_with_its_own_configuration() -> None:
    """The root of a part review has no component row: the document's own configuration is
    what the review read for it."""
    base, _, _ = part_package("Default")
    package = base.build().package
    root = package.design.root_assembly_document_id
    builder = DrawingBuilder(package)
    record = builder.drawing(builder.drawing_document("FICT-TULMVEN-9000"))
    builder.view(builder.sheet(record, "Sheet1"), "Drawing View1", references=root)
    index = DrawingIndex.for_package(builder.build())
    [evidence] = index.views

    assert evidence.usable is True
    assert index.why_not_for(evidence, None) is None


def test_a_document_whose_configuration_the_review_did_not_record_is_unusable() -> None:
    base, _, _ = part_package("Default")
    package = base.build().package
    root = package.design.root_assembly_document_id
    package.documents[0] = package.documents[0].model_copy(update={"active_configuration": ""})
    builder = DrawingBuilder(package)
    record = builder.drawing(builder.drawing_document("FICT-TULMVEN-9000"))
    builder.view(builder.sheet(record, "Sheet1"), "Drawing View1", references=root)
    [evidence] = DrawingIndex.for_package(builder.build()).views

    assert evidence.usable is False
    assert evidence.why == f"the configuration the review read for {root} is not recorded"


def test_an_unknown_component_is_compared_with_the_document() -> None:
    package, index = one_view()
    [evidence] = index.views

    assert index.why_not_for(evidence, "cmp:9999") is None
    assert index.why_not_for(evidence, None) is None
    assert package


# --- 4. the order is the package's ids, never the arrays' ----------------------------------------


@pytest.mark.parametrize("name", ["plate-drawing", "assembly-drawings", "drawing-root"])
def test_shuffled_arrays_give_the_same_index(name: str) -> None:
    package = fixture(name)
    expected = [projection(view) for view in DrawingIndex.for_package(package).views]
    shuffler = random.Random(11)
    for _ in range(5):
        records = [
            record.model_copy(
                update={
                    "sheets": shuffler.sample(
                        [
                            sheet.model_copy(
                                update={"views": shuffler.sample(sheet.views, len(sheet.views))}
                            )
                            for sheet in record.sheets
                        ],
                        len(record.sheets),
                    )
                }
            )
            for record in package.drawing_records
        ]
        shuffled = package.model_copy(
            update={
                "drawing_records": shuffler.sample(records, len(records)),
                "documents": shuffler.sample(package.documents, len(package.documents)),
                "components": shuffler.sample(package.components, len(package.components)),
                "drawing_candidates": shuffler.sample(
                    package.drawing_candidates, len(package.drawing_candidates)
                ),
            }
        )
        index = DrawingIndex.for_package(shuffled)
        assert [projection(view) for view in index.views] == expected


def test_id_order_reads_the_number_not_the_spelling() -> None:
    ids = ["doc:10", "doc:2", "doc:0001", "dvw:0003", "doc:x"]

    assert sorted(ids, key=id_order) == ["doc:0001", "doc:2", "doc:10", "doc:x", "dvw:0003"]
