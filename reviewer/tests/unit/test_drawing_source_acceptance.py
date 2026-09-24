"""SC-003 and SC-004 on the plate-drawing fixture, through `check_joints` (feature 011 T038).

The acceptance of User Story 3, test only, over the committed `plate-drawing` package: feature
010's `tolerances` assembly with drawing A (usable, millimetres, default precision 2), drawing B
(one view of another configuration, one out of date) and a candidate beside the block.

With `DRAWING_BINDING_VALIDATED` set, as T066 will set it:

- **SC-003**: the dowel joint's stack takes the plate hole's size from drawing A, cited by
  drawing, sheet, view and `ddm:` id, and no subject is bound from drawing B;
- **SC-004**: the counterbore's bore, whose two equal model dimensions leave feature 010's screw
  stack unresolved, takes the general tolerance's two-decimal band under profile A (version 3,
  millimetres) from the two decimals drawing A writes it to.

With the switch as shipped, both stacks are exactly the ones feature 010 records over its
`tolerances` fixture, but for the one sentence that says why the drawing bound nothing.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from swreview.checks.standards.profile import load_profile
from swreview.checks.standards.traversal import graded_documents
from swreview.checks.tolerances import ToleranceSubject, drawing_answer
from swreview.drawings.binding import NOT_VALIDATED, search_bindings
from swreview.drawings.evidence import DrawingIndex
from swreview.findings import Finding
from swreview.ir.loader import load_package
from swreview.tools.checks_mechanical import check_joints
from swreview.tools.context import ToolContext, build_context, use_context
from swreview.tools.standards_checks import StandardsRun, attach_standards_run

TESTS = Path(__file__).resolve().parents[1]
PLATE_DRAWING = TESTS / "fixtures" / "drawings" / "plate-drawing"
TOLERANCES = TESTS / "fixtures" / "mechanical" / "tolerances"
PROFILE_A = TESTS / "fixtures" / "standards" / "profile-a.yaml"

DOWEL = ToleranceSubject(
    kind="hole_size", nominal_mm=3.0, document_id="doc:0002", face_ids=("fac:0001",),
    instance_id="hol:0001#1", component_id="cmp:0001",
)


def reviewed(directory: Path) -> ToolContext:
    """`check_joints` over the package in `directory`, with a standards run over profile A."""
    context = build_context(load_package(directory))
    profile = load_profile(PROFILE_A)
    attach_standards_run(
        context, StandardsRun(profile=profile, documents=graded_documents(context.ir, profile))
    )
    with use_context(context):
        check_joints()
    return context


def stacks(context: ToolContext) -> dict[str, Finding]:
    return {
        finding.inputs[0]: finding
        for finding in context.require_session().findings
        if finding.check == "hole.position_stack"
    }


# --- SC-003 -------------------------------------------------------------------------------------


@pytest.mark.usefixtures("validated")
def test_the_dowel_stack_takes_the_plate_holes_size_from_drawing_a() -> None:
    inputs = stacks(reviewed(PLATE_DRAWING))["hol:0001#1"].calculation.inputs

    assert inputs["hol:0001#1_source"] == (
        "drawing callout: drawing doc:0006, sheet Sheet1, view Drawing View1, ddm:0001"
    )
    assert (inputs["hol:0001#1_min"].value, inputs["hol:0001#1_max"].value) == (3.0, 3.01)
    # The block's hole and the pin have no drawing: they keep feature 010's model dimensions.
    assert inputs["hol:0003#1_source"] == (
        "model dimension: dimension KALOMIR4@FICT-HOLE-0001 (mdm:0004)"
    )
    assert inputs["fastener_source"] == (
        "model dimension: dimension KALOMIR5@FICT-HOLE-0001 (mdm:0005)"
    )


@pytest.mark.usefixtures("validated")
def test_drawing_bs_views_are_named_unusable_and_bind_nothing() -> None:
    package = load_package(PLATE_DRAWING).package
    index = DrawingIndex.for_package(package)
    unusable = {view.view.name: view.why for view in index.views if view.drawing_id == "doc:0007"}

    search = search_bindings(index, package, DOWEL)

    assert unusable == {
        "Drawing View1": (
            "view Drawing View1 of doc:0007 shows configuration 'FICT-VENTA'; the review read "
            "'Default'"
        ),
        "Drawing View2": "view Drawing View2 of doc:0007 is out of date with its model",
    }
    assert all(item.view.drawing_id == "doc:0006" for item in search.bindings)
    assert unusable["Drawing View1"] in search.excluded


@pytest.mark.usefixtures("validated")
def test_no_subject_of_the_plate_is_bound_from_drawing_b() -> None:
    context = reviewed(PLATE_DRAWING)

    sources = [
        value
        for finding in context.require_session().findings
        if finding.calculation is not None
        for key, value in finding.calculation.inputs.items()
        if key.endswith("_source") and isinstance(value, str)
    ]

    assert sources and not any("doc:0007" in source for source in sources)


# --- SC-004 -------------------------------------------------------------------------------------


@pytest.mark.usefixtures("validated")
def test_the_bore_takes_the_two_decimal_band_under_profile_a() -> None:
    stack = stacks(reviewed(PLATE_DRAWING))["hol:0002#1"]
    inputs = stack.calculation.inputs

    assert stack.status != "unresolved"
    assert inputs["hol:0002#1_source"].startswith(
        "general tolerance: general_tolerance of the standards profile sha256 "
    )
    assert inputs["hol:0002#1_source"].endswith("the 2-decimal band")
    assert (inputs["hol:0002#1_min"].value, inputs["hol:0002#1_max"].value) == (4.35, 4.65)


@pytest.mark.usefixtures("validated")
def test_the_bore_reads_its_precision_from_the_dimension_and_the_callout_that_agree() -> None:
    package = load_package(PLATE_DRAWING).package
    bore = ToleranceSubject(
        kind="hole_size", nominal_mm=4.5, document_id="doc:0002",
        face_ids=("fac:0002", "fac:0003"), instance_id="hol:0002#1", component_id="cmp:0001",
    )

    answer = drawing_answer(package, bore)

    assert (answer.decimal_places, answer.unit, answer.record_id) == (2, "mm", "ddm:0003")
    assert answer.why is not None and answer.why.startswith("ddm:0003 and ddm:0006 state")


# --- the switch as shipped ------------------------------------------------------------------------

_DRAWING_CLAUSE = re.compile(r"drawing callout: [^;]*;")


def _without_drawing_clause(value: Any) -> Any:
    if isinstance(value, str):
        return _DRAWING_CLAUSE.sub("drawing callout: -;", value)
    if isinstance(value, dict):
        return {key: _without_drawing_clause(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_without_drawing_clause(item) for item in value]
    return value


def _as_feature_010(finding: Finding) -> dict[str, Any]:
    """What a stack finding says, its id and the drawing source's one sentence left out."""
    return _without_drawing_clause(
        {
            "status": finding.status,
            "severity": finding.severity,
            "observed": finding.observed,
            "inputs_of": finding.inputs,
            "calculation": (
                None if finding.calculation is None else finding.calculation.model_dump()
            ),
            "coverage_limits": list(finding.coverage_limits),
        }
    )


@pytest.mark.usefixtures("not_validated")
def test_with_the_switch_off_both_stacks_are_feature_010s() -> None:
    drawn, bare = stacks(reviewed(PLATE_DRAWING)), stacks(reviewed(TOLERANCES))

    assert sorted(drawn) == sorted(bare) == ["hol:0001#1", "hol:0002#1"]
    for instance in drawn:
        assert _as_feature_010(drawn[instance]) == _as_feature_010(bare[instance])
    screw = drawn["hol:0002#1"].coverage_limits[1]
    assert f"drawing callout: {NOT_VALIDATED};" in screw
    assert "drawing callout: no drawing of doc:0002 was read;" in (
        bare["hol:0002#1"].coverage_limits[1]
    )
