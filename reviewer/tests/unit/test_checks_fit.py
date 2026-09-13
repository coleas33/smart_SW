"""Unit tests for the size-only fit check (T077).

`check_fit` is the first arithmetic in the reviewer that can clear a design, so these
tests pin every tolerance convention it reads, both worst conditions it computes, and
the two ways it must refuse: a missing tolerance is `unresolved` naming the side, and an
angular dimension is a `TypeError` raised before any arithmetic (constitution
Principles I and II, FR-022).
"""

from __future__ import annotations

import pytest

from swreview.checks.fit import check_fit
from swreview.ir.models import Angle, Dimension, Quantity, SourceRef, Tolerance

BORE_SOURCE = SourceRef(document_id="doc:3", sheet="Sheet1", annotation="DIM-BORE")
SHAFT_SOURCE = SourceRef(document_id="doc:3", sheet="Sheet1", annotation="DIM-SHAFT")


def mm(value: float) -> Quantity:
    return Quantity(value=value, unit="mm")


def inch(value: float) -> Quantity:
    return Quantity(value=value, unit="in")


def bore(
    tolerance: Tolerance,
    nominal: Quantity | Angle | None = None,
    text: str = "B40",
) -> Dimension:
    return Dimension(
        nominal=mm(40.0) if nominal is None else nominal,
        tolerance=tolerance,
        source=BORE_SOURCE,
        text_as_read=text,
    )


def shaft(
    tolerance: Tolerance,
    nominal: Quantity | Angle | None = None,
    text: str = "S40",
) -> Dimension:
    return Dimension(
        nominal=mm(40.0) if nominal is None else nominal,
        tolerance=tolerance,
        source=SHAFT_SOURCE,
        text_as_read=text,
    )


def tol(
    kind: str,
    *,
    upper: Quantity | Angle | None = None,
    lower: Quantity | Angle | None = None,
    source: SourceRef = BORE_SOURCE,
) -> Tolerance:
    return Tolerance(kind=kind, upper=upper, lower=lower, source=source)


# 40 H7 = 40.000/40.025, 40 g6 = 39.975/39.991: clearance 0.009 to 0.050.
H7_BORE = tol("limits", upper=mm(40.025), lower=mm(40.000), source=BORE_SOURCE)
G6_SHAFT = tol("limits", upper=mm(39.991), lower=mm(39.975), source=SHAFT_SOURCE)


def results(bore_dim: Dimension, shaft_dim: Dimension) -> dict[str, object]:
    result = check_fit(bore_dim, shaft_dim)
    assert result.calculation is not None
    return dict(result.calculation.result)


def test_limit_dimensions_give_min_and_max_clearance() -> None:
    values = results(bore(H7_BORE), shaft(G6_SHAFT))

    assert values["min_clearance_mm"] == pytest.approx(0.009)
    assert values["max_clearance_mm"] == pytest.approx(0.050)
    assert values["fit_class"] == "clearance"


def test_a_clearance_fit_is_checked_within_scope() -> None:
    result = check_fit(bore(H7_BORE), shaft(G6_SHAFT))

    assert result.check == "fit.size_only"
    assert result.status == "checked_within_scope"
    assert result.severity == "info"
    assert result.inputs == [bore(H7_BORE), shaft(G6_SHAFT)]


def test_symmetric_tolerances_are_read_as_half_widths() -> None:
    # bore 40 +/-0.025 = 39.975/40.025, shaft 39.95 +/-0.01 = 39.940/39.960.
    values = results(
        bore(tol("symmetric", upper=mm(0.025))),
        shaft(tol("symmetric", upper=mm(0.010), source=SHAFT_SOURCE), nominal=mm(39.95)),
    )

    assert values["min_clearance_mm"] == pytest.approx(0.015)
    assert values["max_clearance_mm"] == pytest.approx(0.085)
    assert values["fit_class"] == "clearance"


def test_bilateral_lower_is_a_signed_deviation() -> None:
    # bore 40 +0.03/-0.01 = 39.99/40.03, shaft 40 -0.02/-0.05 = 39.95/39.98.
    values = results(
        bore(tol("bilateral", upper=mm(0.03), lower=mm(-0.01))),
        shaft(tol("bilateral", upper=mm(-0.02), lower=mm(-0.05), source=SHAFT_SOURCE)),
    )

    assert values["min_clearance_mm"] == pytest.approx(0.010)
    assert values["max_clearance_mm"] == pytest.approx(0.080)


def test_bilateral_with_a_positive_lower_deviation_is_taken_as_written() -> None:
    # shaft 40 +0.05/+0.02 = 40.02/40.05 against bore 40.000/40.015: interference.
    values = results(
        bore(tol("limits", upper=mm(40.015), lower=mm(40.000))),
        shaft(tol("bilateral", upper=mm(0.05), lower=mm(0.02), source=SHAFT_SOURCE)),
    )

    assert values["min_clearance_mm"] == pytest.approx(-0.050)
    assert values["max_clearance_mm"] == pytest.approx(-0.005)
    assert values["fit_class"] == "interference"


def test_an_interference_fit_is_suspected_not_demonstrated() -> None:
    result = check_fit(
        bore(tol("limits", upper=mm(40.010), lower=mm(40.000))),
        shaft(tol("limits", upper=mm(40.040), lower=mm(40.030), source=SHAFT_SOURCE)),
    )

    assert result.status == "suspected"
    assert result.severity == "high"
    assert result.calculation is not None
    assert result.calculation.result["fit_class"] == "interference"


def test_a_transition_fit_is_suspected() -> None:
    # bore 40.000/40.025 against shaft 39.995/40.015: -0.015 to +0.030.
    result = check_fit(
        bore(H7_BORE),
        shaft(tol("limits", upper=mm(40.015), lower=mm(39.995), source=SHAFT_SOURCE)),
    )

    assert result.status == "suspected"
    assert result.calculation is not None
    assert result.calculation.result["fit_class"] == "transition"
    assert result.calculation.result["min_clearance_mm"] == pytest.approx(-0.015)
    assert result.calculation.result["max_clearance_mm"] == pytest.approx(0.030)


def test_zero_minimum_clearance_is_a_clearance_fit() -> None:
    values = results(
        bore(tol("limits", upper=mm(40.025), lower=mm(40.000))),
        shaft(tol("limits", upper=mm(40.000), lower=mm(39.980), source=SHAFT_SOURCE)),
    )

    assert values["min_clearance_mm"] == pytest.approx(0.0)
    assert values["fit_class"] == "clearance"


def test_tolerance_kind_none_on_the_bore_is_unresolved_naming_the_bore() -> None:
    result = check_fit(bore(tol("none"), text="B40 untoleranced"), shaft(G6_SHAFT))

    assert result.status == "unresolved"
    assert result.calculation is None
    assert "bore" in result.observed
    assert "B40 untoleranced" in result.observed
    assert result.coverage_limits
    assert any("bore" in limit for limit in result.coverage_limits)


def test_tolerance_kind_none_on_the_shaft_is_unresolved_naming_the_shaft() -> None:
    result = check_fit(bore(H7_BORE), shaft(tol("none", source=SHAFT_SOURCE)))

    assert result.status == "unresolved"
    assert "shaft" in result.observed
    assert "bore" not in result.observed


def test_a_basic_dimension_is_unresolved() -> None:
    result = check_fit(bore(tol("basic")), shaft(G6_SHAFT))

    assert result.status == "unresolved"
    assert "basic" in result.observed


def test_a_symmetric_tolerance_without_an_upper_value_is_unresolved() -> None:
    result = check_fit(bore(tol("symmetric")), shaft(G6_SHAFT))

    assert result.status == "unresolved"
    assert "bore" in result.observed


def test_a_bilateral_tolerance_without_a_lower_deviation_is_unresolved() -> None:
    result = check_fit(bore(tol("bilateral", upper=mm(0.03))), shaft(G6_SHAFT))

    assert result.status == "unresolved"
    assert "lower" in result.observed


def test_a_limit_dimension_without_an_upper_limit_is_unresolved() -> None:
    result = check_fit(
        bore(H7_BORE),
        shaft(tol("limits", lower=mm(39.975), source=SHAFT_SOURCE)),
    )

    assert result.status == "unresolved"
    assert "shaft" in result.observed


def test_mixed_units_report_both_the_source_and_the_converted_value() -> None:
    # bore 1.5010/1.5000 in = 38.1254/38.1000 mm, shaft 38 +/-0.01 mm.
    result = check_fit(
        bore(
            tol("limits", upper=inch(1.5010), lower=inch(1.5000)),
            nominal=inch(1.5),
            text="1.500 in",
        ),
        shaft(tol("symmetric", upper=mm(0.01), source=SHAFT_SOURCE), nominal=mm(38.0)),
    )

    assert result.calculation is not None
    inputs = result.calculation.inputs
    assert inputs["bore_max_source"] == Quantity(value=1.501, unit="in")
    assert inputs["bore_max_mm"] == Quantity(value=38.1254, unit="mm")
    assert inputs["bore_min_source"] == Quantity(value=1.5, unit="in")
    assert inputs["bore_min_mm"] == Quantity(value=38.1, unit="mm")
    assert inputs["shaft_max_source"] == Quantity(value=38.01, unit="mm")
    assert inputs["shaft_max_mm"] == Quantity(value=38.01, unit="mm")
    assert result.calculation.result["min_clearance_mm"] == pytest.approx(0.09)
    assert result.calculation.result["max_clearance_mm"] == pytest.approx(0.1354)
    assert result.calculation.units_out == "mm"


def test_an_angular_bore_raises_before_any_arithmetic() -> None:
    angular = bore(
        tol("symmetric", upper=Angle(value=0.5, unit="deg")),
        nominal=Angle(value=45.0, unit="deg"),
        text="45 +/-0.5 deg",
    )

    with pytest.raises(TypeError, match="angle"):
        check_fit(angular, shaft(G6_SHAFT))


def test_an_angular_shaft_raises_even_when_the_bore_is_unresolved() -> None:
    angular = shaft(
        tol("symmetric", upper=Angle(value=0.5, unit="deg"), source=SHAFT_SOURCE),
        nominal=Angle(value=45.0, unit="deg"),
    )

    with pytest.raises(TypeError, match="angle"):
        check_fit(bore(tol("none")), angular)


def test_an_angular_tolerance_on_a_length_nominal_raises() -> None:
    with pytest.raises(TypeError, match="angle"):
        check_fit(
            bore(tol("symmetric", upper=Angle(value=0.1, unit="deg"))),
            shaft(G6_SHAFT),
        )


def test_the_calculation_names_the_model_function_and_excluded_effects() -> None:
    result = check_fit(bore(H7_BORE), shaft(G6_SHAFT))

    assert result.calculation is not None
    calculation = result.calculation
    assert calculation.model == "fit.size_only"
    assert calculation.function == "swreview.checks.fit.check_fit"
    assert calculation.function_version == "1"
    joined = " ".join(calculation.excluded_effects).lower()
    for effect in ("position", "form", "coating", "temperature", "deformation"):
        assert effect in joined
    assert result.coverage_limits


def test_an_inverted_limit_dimension_raises() -> None:
    with pytest.raises(ValueError, match="lower limit"):
        check_fit(bore(tol("limits", upper=mm(40.000), lower=mm(40.025))), shaft(G6_SHAFT))
