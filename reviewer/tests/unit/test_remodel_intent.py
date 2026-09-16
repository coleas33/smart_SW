"""Unit tests for the intent half of the plan: descriptions and equations (T020).

FR-030, `data-model.md` sections 1.8 and 1.9 and `research.md` R6 give the whole
specification, and it is three claims:

- **absence is not emptiness.** A description read as `None` is *unreadable* and one read as
  `""` is *absent*, and the gap list never conflates them. The difference is operational,
  not pedantic: an unreadable description has no recoverable inverse, so it is refused as a
  change target up front (section 1.8), while an absent one inverts to `""`;
- **the equation inventory says which equations exist, which are globals, and which are
  broken**, and it says `unresolved` wherever the package does not let it say either. A row
  whose `GlobalVariable(i)` or `Value(i)` could not be read is never counted as healthy, and
  a reference the package cannot resolve because the IR carries no dimensions is unresolved
  rather than broken;
- **a global proposal is admissible only where feature data justifies it.** The IR carries
  `equations[]` and **no sketch dimensions** (FR-030, owner decision OQ-2), so the justifying
  parameters are the feature-data fields - a hole diameter, a shell thickness, a fillet
  radius - and a hard-coded sketch value can never appear as a proposal, because there is
  nothing in the package to read it from.
"""

from __future__ import annotations

from swreview.checks.rms_types import load_table
from swreview.ir.models import EvidencePackage, Feature
from swreview.remodel.intent import (
    ADMISSIBLE_PARAMETERS,
    DescriptionGap,
    description_gaps,
    equation_inventory,
    global_candidates,
    is_admissible_parameter,
)
from tests.support.features import equation, feature, fillet_feature, folder, sketch_feature
from tests.support.remodel import remodel_package, variable_radius_fillet_features

TABLE = load_table()


def ids_by_name(package: EvidencePackage) -> dict[str, str]:
    return {row.name: row.id for row in package.features}


def gaps_by_name(package: EvidencePackage) -> dict[str, DescriptionGap]:
    rows = {row.id: row.name for row in package.features}
    return {rows[gap.feature_id]: gap for gap in description_gaps(package.features, TABLE)}


# --- descriptions -----------------------------------------------------------------


def described_package() -> EvidencePackage:
    return remodel_package(
        [
            feature("Boss-Extrude1", "Extrusion", description="the mounting boss"),
            feature("Cut-Extrude1", "Cut", description=""),
            feature("Hole1", "HoleWzd", description=None),
            feature("Chamfer1", "Chamfer", description="   "),
        ]
    )


def test_an_unreadable_description_and_an_absent_one_are_never_conflated() -> None:
    gaps = gaps_by_name(described_package())

    assert gaps["Hole1"].kind == "unreadable"
    assert gaps["Cut-Extrude1"].kind == "absent"
    assert gaps["Hole1"].kind != gaps["Cut-Extrude1"].kind


def test_a_feature_that_already_carries_a_description_is_not_a_gap() -> None:
    gaps = gaps_by_name(described_package())

    assert "Boss-Extrude1" not in gaps


def test_a_blank_description_that_was_read_is_absent_and_not_unreadable() -> None:
    gaps = gaps_by_name(described_package())

    assert gaps["Chamfer1"].kind == "absent"


def test_an_unreadable_description_is_refused_as_a_change_target_up_front() -> None:
    """data-model.md section 1.8: `before` of `null` has no recoverable inverse."""
    gaps = gaps_by_name(described_package())

    assert gaps["Hole1"].proposable is False
    assert gaps["Cut-Extrude1"].proposable is True
    assert "inverse" in gaps["Hole1"].reason


def test_the_gap_list_covers_content_features_only() -> None:
    package = remodel_package(
        [
            folder("3-Core", feature("Boss-Extrude1", "Extrusion", description="")),
            feature("Front Plane", "RefPlane", description=""),
        ]
    )

    assert list(gaps_by_name(package)) == ["Boss-Extrude1"]


def test_the_gap_list_is_in_tree_order_and_carries_the_feature_id() -> None:
    package = described_package()
    ids = ids_by_name(package)

    gaps = description_gaps(package.features, TABLE)

    assert [gap.feature_id for gap in gaps] == [
        ids["Cut-Extrude1"],
        ids["Hole1"],
        ids["Chamfer1"],
    ]
    assert [gap.name for gap in gaps] == ["Cut-Extrude1", "Hole1", "Chamfer1"]


# --- the equation inventory -------------------------------------------------------


def equation_package() -> EvidencePackage:
    return remodel_package(
        [sketch_feature("Sketch1"), feature("Boss-Extrude1", "Extrusion")],
        equations=[
            equation('"width" = 120', is_global=True, value=120.0),
            equation('"height" = "width" * 2', is_global=True, value=240.0),
            equation('"depth" = "missing" + 1', is_global=True, value=None),
            equation('"D1@Sketch1" = "width" / 2', value=60.0),
            equation('"D2@Sketch1" = "gone" + 1', value=None),
            equation('"slack" = 3', is_global=None, value=3.0),
        ],
    )


def inventory():
    return equation_inventory(equation_package().equations)


def test_the_inventory_reports_which_equations_exist() -> None:
    assert [row.index for row in inventory().rows] == [0, 1, 2, 3, 4, 5]


def test_the_inventory_reports_which_equations_are_globals() -> None:
    result = inventory()

    assert [row.lhs for row in result.globals] == ["width", "height", "depth"]
    assert result.declared_globals == frozenset({"width", "height", "depth"})


def test_a_dimension_driving_equation_is_not_a_global() -> None:
    result = inventory()

    assert [row.lhs for row in result.dimension_driven] == ["D1@Sketch1", "D2@Sketch1"]
    assert not set(result.declared_globals) & {"D1@Sketch1", "D2@Sketch1"}


def test_the_inventory_reports_which_equations_are_broken_and_what_they_miss() -> None:
    broken = {row.index: row for row in inventory().broken}

    assert set(broken) == {2, 4}
    assert broken[2].missing == ("missing",)
    assert broken[4].missing == ("gone",)
    assert "missing" in broken[2].reason


def test_an_unreadable_global_flag_is_unresolved_and_never_counted_as_healthy() -> None:
    result = inventory()
    unresolved = {row.index: row for row in result.unresolved}

    assert 5 in unresolved
    assert "GlobalVariable" in unresolved[5].reason
    assert 5 not in {row.index for row in result.globals}
    assert 5 not in {row.index for row in result.broken}


def test_a_reference_to_a_row_whose_global_flag_is_unreadable_is_unresolved() -> None:
    """It may or may not be a declared global, so it is neither broken nor healthy."""
    package = remodel_package(
        [feature("Boss-Extrude1", "Extrusion")],
        equations=[
            equation('"maybe" = 3', is_global=None, value=3.0),
            equation('"width" = "maybe" * 2', is_global=True, value=6.0),
        ],
    )

    result = equation_inventory(package.equations)

    assert {row.index for row in result.broken} == set()
    assert {row.index for row in result.unresolved} == {0, 1}
    assert "maybe" in next(row for row in result.unresolved if row.index == 1).reason


def test_an_unreadable_value_is_unresolved_rather_than_broken() -> None:
    package = remodel_package(
        [feature("Boss-Extrude1", "Extrusion")],
        equations=[equation('"width" = 120', is_global=True, value=None)],
    )

    result = equation_inventory(package.equations)

    assert [row.index for row in result.unresolved] == [0]
    assert result.broken == ()
    assert "value" in result.unresolved[0].reason


def test_broken_and_unresolved_are_disjoint_so_a_row_is_counted_once() -> None:
    result = inventory()

    assert not {row.index for row in result.broken} & {row.index for row in result.unresolved}


def test_an_empty_equation_manager_is_an_answer_and_not_a_gap() -> None:
    result = equation_inventory(())

    assert result.rows == ()
    assert result.globals == ()
    assert result.broken == ()
    assert result.unresolved == ()
    assert result.declared_globals == frozenset()


# --- what justifies a global ------------------------------------------------------


def test_the_admissible_parameters_are_the_feature_data_fields_the_ir_carries() -> None:
    assert ADMISSIBLE_PARAMETERS == ("hole_diameter", "shell_thickness", "default_radius")
    assert all(is_admissible_parameter(name) for name in ADMISSIBLE_PARAMETERS)


def test_a_sketch_dimension_is_never_an_admissible_parameter() -> None:
    for name in ("D1@Sketch1", "sketch_dimension", "dimension", "extrude_depth", ""):
        assert is_admissible_parameter(name) is False


def test_a_fillet_radius_the_package_carries_is_a_candidate_with_its_value_in_metres() -> None:
    package = remodel_package(variable_radius_fillet_features())
    ids = ids_by_name(package)

    candidates = global_candidates(package.features, TABLE)

    assert [candidate.feature_id for candidate in candidates] == [ids["Fillet1"]]
    assert candidates[0].parameter == "default_radius"
    assert candidates[0].value_m == 0.005
    assert candidates[0].name == "Fillet1"


def test_an_unreadable_radius_yields_no_candidate_and_no_default() -> None:
    package = remodel_package([fillet_feature("Fillet-Variable1", radius_m=None)])

    assert global_candidates(package.features, TABLE) == ()


def test_no_candidate_is_ever_read_from_a_sketch() -> None:
    package = remodel_package([sketch_feature("Sketch1"), feature("Cut-Extrude1", "Cut")])

    assert global_candidates(package.features, TABLE) == ()


def test_every_candidate_names_an_admissible_parameter() -> None:
    package = remodel_package(variable_radius_fillet_features())

    for candidate in global_candidates(package.features, TABLE):
        assert is_admissible_parameter(candidate.parameter)


def test_the_ir_carries_no_dimension_for_a_proposal_to_name() -> None:
    """The structural reason a hard-coded sketch value can never be proposed (FR-030)."""
    assert not [name for name in Feature.model_fields if "dimension" in name]
    assert not [name for name in EvidencePackage.model_fields if "dimension" in name]
    assert "equations" in EvidencePackage.model_fields
