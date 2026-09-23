"""The finding subject key (008 T007, research R2.8, data-model section 4).

The replay compares the findings a recorded review produced with the findings the current
code produces, and a finding id cannot be the join: checks first renumbers every step and every
finding. The key is what a finding is *about* - its check, its components, where on a drawing,
the entity ids among its inputs, its configuration - and nothing that a re-run would renumber.
It is unique on every recorded session (99 of 99 on the big one), where check and components
alone are not: two `hole.coaxiality` findings share both components and differ only by the hole
ids in their inputs.
"""

from __future__ import annotations

import pytest

from swreview.findings import ENTITY_ID, Finding, build_finding, finding_subject_key
from swreview.ir.models import SourceRef
from tests.support.packages import build_package, persist_ref

PACKAGE = build_package()


def finding(**overrides: object) -> Finding:
    base = build_finding(
        finding_id="F-001",
        check="hole.coaxiality",
        title="Holes hol:0004 and hol:0010 are not coaxial",
        status="unresolved",
        severity="medium",
        package=PACKAGE,
        configuration="Default",
        observed="observed",
        requirement="required",
        recommended_action="look again",
        component_ids=["cmp:0001", "cmp:0002"],
        inputs=["hol:0004", "hol:0010"],
        coverage_limits=["the offset needs both axes"],
        numeric=False,
    )
    return base.model_copy(update=overrides)


def sheet(document_id: str = "doc:1", **fields: object) -> SourceRef:
    return SourceRef(document_id=document_id, **fields)


def test_the_key_ignores_the_id_the_step_ids_and_the_capture_ids() -> None:
    first = finding()
    renumbered = finding(id="F-093", tool_result_ids=[4, 12], capture_ids=["cap:0003"])

    assert finding_subject_key(first) == finding_subject_key(renumbered)


def test_component_order_does_not_matter() -> None:
    forward = finding(component_ids=["cmp:0001", "cmp:0002"])
    backward = finding(component_ids=["cmp:0002", "cmp:0001"])

    assert finding_subject_key(forward) == finding_subject_key(backward)


def test_two_hole_pairs_on_the_same_components_are_two_subjects() -> None:
    first = finding(inputs=["hol:0004", "hol:0010"])
    second = finding(inputs=["hol:0017", "hol:0027"])

    assert finding_subject_key(first) != finding_subject_key(second)


def test_the_order_of_entity_ids_in_the_inputs_does_not_matter() -> None:
    assert finding_subject_key(finding(inputs=["hol:0010", "hol:0004"])) == finding_subject_key(
        finding(inputs=["hol:0004", "hol:0010"])
    )


def test_a_drawing_locations_persist_ref_does_not_change_the_key() -> None:
    one = finding(drawing_locations=[sheet(sheet="Sheet1", persist_ref=persist_ref("a"))])
    other = finding(drawing_locations=[sheet(sheet="Sheet1", persist_ref=persist_ref("b"))])

    assert finding_subject_key(one) == finding_subject_key(other)


@pytest.mark.parametrize(
    "changed",
    [
        {"sheet": "Sheet2"},
        {"view": "Drawing View3"},
        {"annotation": "D12"},
        {"page": 2},
        {"document_id": "doc:2"},
    ],
)
def test_a_drawing_locations_sheet_view_annotation_page_or_document_does(
    changed: dict[str, object],
) -> None:
    fields: dict[str, object] = {"sheet": "Sheet1", "view": "Drawing View1", "annotation": "D1"}
    base = finding(drawing_locations=[sheet(**fields, page=1)])
    document_id = str(changed.pop("document_id", "doc:1"))
    moved = finding(drawing_locations=[sheet(document_id, **{**fields, "page": 1, **changed})])

    assert finding_subject_key(base) != finding_subject_key(moved)


def test_drawing_locations_with_missing_locators_sort_without_error() -> None:
    mixed = finding(
        drawing_locations=[sheet(page=3), sheet(sheet="Sheet1"), sheet(annotation="D1")]
    )
    shuffled = finding(
        drawing_locations=[sheet(annotation="D1"), sheet(page=3), sheet(sheet="Sheet1")]
    )

    assert finding_subject_key(mixed) == finding_subject_key(shuffled)


def test_the_configuration_matters() -> None:
    assert finding_subject_key(finding(configuration="Default")) != finding_subject_key(
        finding(configuration="Assembled")
    )


def test_the_check_matters() -> None:
    assert finding_subject_key(finding(check="hole.coaxiality")) != finding_subject_key(
        finding(check="hole.spacing")
    )


def test_prose_inputs_do_not_count_and_entity_ids_do() -> None:
    plain = finding(inputs=["hol:0004"])
    with_prose = finding(inputs=["hol:0004", "int:0001 cmp:0015+cmp:0026 Default computed"])
    with_another_id = finding(inputs=["hol:0004", "hol:0005"])

    assert finding_subject_key(plain) == finding_subject_key(with_prose)
    assert finding_subject_key(plain) != finding_subject_key(with_another_id)


def test_the_key_is_hashable_so_findings_compare_as_multisets() -> None:
    from collections import Counter

    counts = Counter(finding_subject_key(item) for item in (finding(), finding(id="F-002")))

    assert list(counts.values()) == [2]


@pytest.mark.parametrize("text", ["cmp:0001", "feat:12345", "hole:0007", "int:0113"])
def test_entity_id_matches_the_ir_shape(text: str) -> None:
    assert ENTITY_ID.match(text)


@pytest.mark.parametrize(
    "text", ["cmp:12", "CMP:0001", "YWJj", "cmp:0001 extra", "components:0001", "c:0001", ""]
)
def test_entity_id_refuses_anything_else(text: str) -> None:
    assert not ENTITY_ID.match(text)
