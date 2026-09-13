"""Unit tests for the worst-case axial stack check (T078).

The stack is the check most likely to be handed an incomplete drawing, so these tests
pin what it does with a dimension that carries no tolerance (refuses, naming it), with a
tolerance that came from a general note (uses it, citing where it came from), and with a
target gap it can miss (`demonstrated`). Malformed calls - no dimensions, a sign per
dimension missing - are programming errors and raise (constitution Principles I and V).
"""

from __future__ import annotations

import pytest

from swreview.checks.stack import check_axial_stack
from swreview.ir.models import Angle, Dimension, Quantity, SourceRef, Tolerance

SHEET = "Sheet1"
DEPTH_SOURCE = SourceRef(document_id="doc:3", sheet=SHEET, annotation="DIM-DEPTH")
PLATE_A_SOURCE = SourceRef(document_id="doc:3", sheet=SHEET, annotation="DIM-PLATE-A")
PLATE_B_SOURCE = SourceRef(document_id="doc:3", sheet=SHEET, annotation="DIM-PLATE-B")
GAP_SOURCE = SourceRef(document_id="doc:3", sheet=SHEET, annotation="DIM-GAP")
NOTE_SOURCE = SourceRef(document_id="doc:3", sheet=SHEET, annotation="NOTE-1")


def mm(value: float) -> Quantity:
    return Quantity(value=value, unit="mm")


def inch(value: float) -> Quantity:
    return Quantity(value=value, unit="in")


def tol(
    kind: str,
    *,
    upper: Quantity | Angle | None = None,
    lower: Quantity | Angle | None = None,
    source: SourceRef,
) -> Tolerance:
    return Tolerance(kind=kind, upper=upper, lower=lower, source=source)


def dimension(
    nominal: Quantity | Angle,
    tolerance: Tolerance,
    *,
    source: SourceRef,
    text: str,
) -> Dimension:
    return Dimension(nominal=nominal, tolerance=tolerance, source=source, text_as_read=text)


# Housing depth 30 +/-0.2 less two plates: 12 +/-0.1 (general note) and 12 +0.05/-0.15.
# Nominal gap 6.000, worst case 5.650 to 6.450.
DEPTH = dimension(
    mm(30.0),
    tol("symmetric", upper=mm(0.2), source=DEPTH_SOURCE),
    source=DEPTH_SOURCE,
    text="30 +/-0.2",
)
PLATE_A = dimension(
    mm(12.0),
    tol("symmetric", upper=mm(0.1), source=NOTE_SOURCE),
    source=PLATE_A_SOURCE,
    text="12",
)
PLATE_B = dimension(
    mm(12.0),
    tol("bilateral", upper=mm(0.05), lower=mm(-0.15), source=PLATE_B_SOURCE),
    source=PLATE_B_SOURCE,
    text="12 +0.05/-0.15",
)
STACK = [DEPTH, PLATE_A, PLATE_B]
SIGNS = [1, -1, -1]


def target(lower: float, upper: float) -> Dimension:
    return dimension(
        mm((lower + upper) / 2),
        tol("limits", upper=mm(upper), lower=mm(lower), source=GAP_SOURCE),
        source=GAP_SOURCE,
        text=f"gap {lower}/{upper}",
    )


def test_worst_case_stack_applies_the_signs() -> None:
    result = check_axial_stack(STACK, SIGNS, None)

    assert result.check == "stack.worst_case"
    assert result.calculation is not None
    values = result.calculation.result
    assert values["nominal_mm"] == pytest.approx(6.0)
    assert values["min_mm"] == pytest.approx(5.65)
    assert values["max_mm"] == pytest.approx(6.45)
    assert values["tolerance_plus_mm"] == pytest.approx(0.45)
    assert values["tolerance_minus_mm"] == pytest.approx(0.35)


def test_a_stack_without_a_target_is_checked_within_scope() -> None:
    result = check_axial_stack(STACK, SIGNS, None)

    assert result.status == "checked_within_scope"
    assert result.severity == "info"
    assert result.inputs == STACK


def test_an_untoleranced_dimension_is_unresolved_naming_the_index_and_text() -> None:
    untoleranced = dimension(
        mm(12.0),
        tol("none", source=PLATE_A_SOURCE),
        source=PLATE_A_SOURCE,
        text="12 as drawn",
    )

    result = check_axial_stack([DEPTH, untoleranced, PLATE_B], SIGNS, None)

    assert result.status == "unresolved"
    assert result.calculation is None
    assert "dimension 1" in result.observed
    assert "12 as drawn" in result.observed
    assert result.coverage_limits


def test_a_basic_dimension_in_the_stack_is_unresolved() -> None:
    basic = dimension(
        mm(12.0),
        tol("basic", source=PLATE_B_SOURCE),
        source=PLATE_B_SOURCE,
        text="12 basic",
    )

    result = check_axial_stack([DEPTH, PLATE_A, basic], SIGNS, None)

    assert result.status == "unresolved"
    assert "dimension 2" in result.observed


def test_a_general_note_tolerance_is_used_and_cited() -> None:
    result = check_axial_stack(STACK, SIGNS, None)

    assert result.calculation is not None
    assumptions = " ".join(result.calculation.assumptions)
    assert "NOTE-1" in assumptions
    assert "12" in assumptions
    # The +/-0.1 from the note is what widens the stack to 5.65/6.45.
    assert result.calculation.result["min_mm"] == pytest.approx(5.65)


def test_a_stack_that_can_miss_the_target_is_demonstrated() -> None:
    result = check_axial_stack(STACK, SIGNS, target(5.80, 6.50))

    assert result.status == "demonstrated"
    assert result.severity == "high"
    assert result.calculation is not None
    assert result.calculation.result["violates_target"] is True
    assert result.calculation.result["target_min_mm"] == pytest.approx(5.80)
    assert result.calculation.result["target_max_mm"] == pytest.approx(6.50)
    assert "5.8" in result.requirement


def test_a_stack_inside_the_target_is_checked_within_scope() -> None:
    result = check_axial_stack(STACK, SIGNS, target(5.50, 6.50))

    assert result.status == "checked_within_scope"
    assert result.calculation is not None
    assert result.calculation.result["violates_target"] is False


def test_a_stack_above_the_target_maximum_is_demonstrated() -> None:
    result = check_axial_stack(STACK, SIGNS, target(5.00, 6.40))

    assert result.status == "demonstrated"
    assert result.calculation is not None
    assert result.calculation.result["violates_target"] is True


def test_an_untoleranced_target_is_unresolved_naming_the_target() -> None:
    untoleranced_target = dimension(
        mm(6.0),
        tol("none", source=GAP_SOURCE),
        source=GAP_SOURCE,
        text="gap 6",
    )

    result = check_axial_stack(STACK, SIGNS, untoleranced_target)

    assert result.status == "unresolved"
    assert "target" in result.observed
    assert "gap 6" in result.observed


def test_an_empty_stack_raises() -> None:
    with pytest.raises(ValueError, match="at least one dimension"):
        check_axial_stack([], [], None)


def test_a_sign_count_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="sign"):
        check_axial_stack(STACK, [1, -1], None)


def test_a_sign_that_is_not_plus_or_minus_one_raises() -> None:
    with pytest.raises(ValueError, match="sign"):
        check_axial_stack(STACK, [1, -1, 0], None)


def test_mixed_units_are_converted_with_source_and_converted_recorded() -> None:
    # 1.000 +/-0.005 in = 25.4 +/-0.127 mm, less 12 +/-0.1 mm: 13.4 -0.227/+0.227.
    imperial = dimension(
        inch(1.0),
        tol("symmetric", upper=inch(0.005), source=DEPTH_SOURCE),
        source=DEPTH_SOURCE,
        text="1.000 +/-0.005 in",
    )
    metric = dimension(
        mm(12.0),
        tol("symmetric", upper=mm(0.1), source=PLATE_A_SOURCE),
        source=PLATE_A_SOURCE,
        text="12 +/-0.1",
    )

    result = check_axial_stack([imperial, metric], [1, -1], None)

    assert result.calculation is not None
    inputs = result.calculation.inputs
    assert inputs["dim_0_min_source"] == Quantity(value=0.995, unit="in")
    assert inputs["dim_0_min_mm"] == Quantity(value=25.273, unit="mm")
    assert inputs["dim_0_max_source"] == Quantity(value=1.005, unit="in")
    assert inputs["dim_0_max_mm"] == Quantity(value=25.527, unit="mm")
    assert inputs["dim_1_min_mm"] == Quantity(value=11.9, unit="mm")
    assert inputs["dim_0_sign"] == "+1"
    assert inputs["dim_1_sign"] == "-1"
    assert result.calculation.result["nominal_mm"] == pytest.approx(13.4)
    assert result.calculation.result["min_mm"] == pytest.approx(13.173)
    assert result.calculation.result["max_mm"] == pytest.approx(13.627)
    assert result.calculation.units_out == "mm"


def test_an_angular_dimension_raises_before_any_arithmetic() -> None:
    angular = dimension(
        Angle(value=30.0, unit="deg"),
        tol("symmetric", upper=Angle(value=0.5, unit="deg"), source=PLATE_A_SOURCE),
        source=PLATE_A_SOURCE,
        text="30 +/-0.5 deg",
    )

    with pytest.raises(TypeError, match="angle"):
        check_axial_stack([DEPTH, angular], [1, -1], None)


def test_an_angular_target_raises() -> None:
    angular = dimension(
        Angle(value=6.0, unit="deg"),
        tol("symmetric", upper=Angle(value=0.5, unit="deg"), source=GAP_SOURCE),
        source=GAP_SOURCE,
        text="6 +/-0.5 deg",
    )

    with pytest.raises(TypeError, match="angle"):
        check_axial_stack(STACK, SIGNS, angular)


def test_the_calculation_names_the_model_function_and_excluded_effects() -> None:
    result = check_axial_stack(STACK, SIGNS, None)

    assert result.calculation is not None
    calculation = result.calculation
    assert calculation.model == "stack.worst_case"
    assert calculation.function == "swreview.checks.stack.check_axial_stack"
    assert calculation.function_version == "1"
    joined = " ".join(calculation.excluded_effects).lower()
    for effect in ("position", "form", "temperature", "deformation", "statistical"):
        assert effect in joined
    assert any("worst case" in assumption for assumption in calculation.assumptions)
    assert result.coverage_limits
