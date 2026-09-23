"""The ISO 286 table (feature 010 T080, `contracts/tolerances.md` section 5).

A class such as `H7` becomes limits on a nominal only through `checks/iso286.yaml`, entered
from ISO 286-1 Table 1 (IT5 to IT11, sizes up to 120 mm) with the H and h classes, whose
fundamental deviation is zero. A class the table does not carry binds nothing: nothing is
interpolated or extrapolated.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swreview.checks.result import limits_mm
from swreview.checks.tolerances import DEFAULT_ISO286_PATH, Iso286, iso_dimension, load_iso286


@pytest.fixture(scope="module")
def table() -> Iso286:
    return load_iso286()


def test_h7_on_10_mm_is_plus_15_microns_to_zero(table: Iso286) -> None:
    assert table.deviations_mm("H7", 10.0) == (0.0, 0.015, "hole")


def test_h6_shaft_on_10_mm_is_zero_to_minus_9_microns(table: Iso286) -> None:
    assert table.deviations_mm("h6", 10.0) == (-0.009, 0.0, "shaft")


@pytest.mark.parametrize(
    ("nominal", "upper"),
    [(3.0, 0.010), (3.0001, 0.012), (6.0, 0.012), (10.0, 0.015), (10.5, 0.018), (120.0, 0.035)],
)
def test_the_range_boundaries_are_over_and_up_to_and_including(
    table: Iso286, nominal: float, upper: float
) -> None:
    assert table.deviations_mm("H7", nominal) == (0.0, upper, "hole")


@pytest.mark.parametrize(
    ("grade", "values"),
    [
        ("IT5", (4, 5, 6, 8, 9, 11, 13, 15)),
        ("IT7", (10, 12, 15, 18, 21, 25, 30, 35)),
        ("IT11", (60, 75, 90, 110, 130, 160, 190, 220)),
    ],
)
def test_the_grades_are_iso_286_1_table_1(table: Iso286, grade: str, values: tuple) -> None:
    assert table.grades_um[grade] == tuple(float(value) for value in values)


@pytest.mark.parametrize(
    ("designation", "nominal", "why"),
    [
        ("g6", 10.0, "class g6 is not in iso286.yaml"),
        ("H12", 10.0, "grade IT12 of H12 is not in iso286.yaml"),
        ("H4", 10.0, "grade IT4 of H4 is not in iso286.yaml"),
        ("H7", 121.0, "outside the sizes iso286.yaml carries"),
        ("H7", 0.0, "outside the sizes iso286.yaml carries"),
        ("swScrewClearanceNormal", 10.0, "is not an ISO 286 tolerance class"),
        ("", 10.0, "is not an ISO 286 tolerance class"),
    ],
)
def test_a_class_outside_the_table_binds_nothing(
    table: Iso286, designation: str, nominal: float, why: str
) -> None:
    answer = table.deviations_mm(designation, nominal)

    assert isinstance(answer, str) and why in answer


def test_the_dimension_built_cites_where_the_class_was_read(table: Iso286) -> None:
    dimension = iso_dimension("H7", 10.0, "doc:0002", "dimension KALOMIR1: fit class H7", table)

    assert not isinstance(dimension, str)
    limits = limits_mm(dimension)
    assert (limits.min_mm, limits.max_mm) == (10.0, 10.015)
    assert dimension.tolerance.source.annotation == "dimension KALOMIR1: fit class H7"
    assert dimension.text_as_read == "⌀10 H7"


def test_the_table_cites_its_source() -> None:
    table = load_iso286()

    assert DEFAULT_ISO286_PATH.name == "iso286.yaml"
    assert table.source.startswith("ISO 286-1:2010, Table 1")
    assert set(table.classes) == {"H", "h"}


def test_a_grade_row_of_the_wrong_length_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "iso.yaml"
    path.write_text(
        "version: 1\nsource: s\nsize_ranges_mm: [[0, 3], [3, 6]]\n"
        "it_grades_um:\n  IT7: [10]\nclasses:\n  H: {kind: hole, fundamental_deviation_um: 0}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="IT7"):
        load_iso286(path)
