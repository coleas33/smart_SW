"""`hole.position_stack`: the worst case over a declared model (feature 010 T034).

`contracts/alignment.md` section 4 is normative, and research R2.7 the reason for its shape:
the stack is computed over the richest model whose contributors all have a tolerance - size
and position, or size only with each missing position named as an excluded effect - and is
unresolved, naming what is missing and where it looked, when a size has none. Nothing is
assumed. These tests drive it with a fake lookup, because no source is read until US8; the
real `NoSources` is the last test, the one every review runs today.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from swreview.checks.joint_alignment import (
    CHECK_STACK,
    check_nominal_alignment,
    check_position_stack,
    run_joint_checks,
)
from swreview.checks.joints import build_joint_map
from swreview.checks.tolerances import (
    SOURCE_ORDER,
    NoSources,
    ResolvedTolerance,
    SourceKind,
    ToleranceSubject,
    UnresolvedTolerance,
)
from swreview.ir.models import Dimension, Quantity, SourceRef, Tolerance
from tests.support.mechanical import Face
from tests.support.packages import persist_ref
from tests.unit.test_joint_alignment import Z, at, dowel_joint, only_joint, parts, screw_joint

SOURCE = SourceRef(document_id="doc:0002", persist_ref=persist_ref("mdm:0001"))


def bilateral(nominal: float, upper: float, lower: float) -> Dimension:
    return Dimension(
        nominal=Quantity(value=nominal, unit="mm"),
        tolerance=Tolerance(
            kind="bilateral",
            upper=Quantity(value=upper, unit="mm"),
            lower=Quantity(value=lower, unit="mm"),
            source=SOURCE,
        ),
        source=SOURCE,
        text_as_read=f"{nominal} +{upper}/{lower}",
    )


def zone(value: float) -> Dimension:
    return Dimension(
        nominal=Quantity(value=value, unit="mm"),
        tolerance=Tolerance(kind="basic", upper=None, lower=None, source=SOURCE),
        source=SOURCE,
        text_as_read=f"position {value}",
    )


@dataclass
class FakeLookup:
    """Resolves by subject kind; records every subject it was asked about."""

    hole: Dimension | None = None
    pin: Dimension | None = None
    position: Dimension | None = None
    conflict: str | None = None
    asked: list[ToleranceSubject] = field(default_factory=list)

    def resolve(self, subject: ToleranceSubject) -> ResolvedTolerance | UnresolvedTolerance:
        self.asked.append(subject)
        dimension = {"hole_size": self.hole, "pin_size": self.pin, "hole_position": self.position}[
            subject.kind
        ]
        if dimension is None:
            return UnresolvedTolerance(
                subject=subject,
                searched=tuple((source, "nothing binds it here") for source in SOURCE_ORDER),
            )
        source: SourceKind = "annotation" if subject.kind == "hole_position" else "model_dimension"
        return ResolvedTolerance(
            subject=subject,
            source_kind=source,
            cited=f"doc:0002 {subject.kind} of {subject.instance_id or 'the pin'}",
            dimension=dimension,
            conflict=self.conflict,
        )

    def holds_any_source(self) -> bool:
        return True


def resolved_everything() -> FakeLookup:
    """Holes 3.1 +0.02/0, the pin 3.0 +0/-0.01, every position a 0.02 mm zone.

    Two holes: c_min = 2 x (3.1 - 3.0) / 2 = 0.1, c_max = 2 x (3.12 - 2.99) / 2 = 0.13, and the
    two half-zones sum to z = 0.02.
    """
    return FakeLookup(
        hole=bilateral(3.1, 0.02, 0.0), pin=bilateral(3.0, 0.0, -0.01), position=zone(0.02)
    )


def stack_at(offset: float, lookup: FakeLookup):
    joint, package = only_joint(dowel_joint(3.1, 3.1, offset))
    return check_position_stack(joint, package, lookup)


# --- the three verdicts at their boundaries -------------------------------------------------


@pytest.mark.parametrize(
    ("offset", "status"),
    [
        (0.0, "checked_within_scope"),
        (0.08, "checked_within_scope"),  # e + z = 0.1 = c_min
        (0.081, "suspected"),
        (0.1, "suspected"),
        (0.15, "suspected"),  # e - z = 0.13 = c_max
        (0.151, "demonstrated"),
    ],
)
def test_the_three_verdicts_fall_where_the_worst_case_puts_them(offset: float, status: str) -> None:
    result = stack_at(offset, resolved_everything())

    assert result is not None
    assert result.check == CHECK_STACK
    assert result.status == status
    values = result.calculation.result
    assert values["model"] == "size_and_position"
    assert (values["clearance_min_mm"], values["clearance_max_mm"]) == (0.1, 0.13)
    assert values["position_half_zones_mm"] == 0.02


def test_a_suspected_stack_says_it_passes_at_some_sizes_and_fails_at_others() -> None:
    result = stack_at(0.1, resolved_everything())

    assert "passes at some sizes within tolerance and fails at others" in result.observed
    assert result.severity == "medium"


def test_a_demonstrated_stack_fails_even_at_the_largest_clearance() -> None:
    result = stack_at(0.2, resolved_everything())

    assert result.severity == "high"
    assert "0.2 mm" in result.observed and "0.13 mm" in result.observed


# --- the model ---------------------------------------------------------------------------


def test_a_missing_position_is_size_only_with_the_position_named_as_excluded() -> None:
    lookup = FakeLookup(hole=bilateral(3.1, 0.02, 0.0), pin=bilateral(3.0, 0.0, -0.01))

    result = stack_at(0.05, lookup)

    values = result.calculation.result
    assert values["model"] == "size_only"
    assert values["position_half_zones_mm"] == 0.0
    excluded = [effect for effect in result.calculation.excluded_effects if "position of" in effect]
    assert len(excluded) == 2
    assert all("model annotation: nothing binds it here" in effect for effect in excluded)
    assert result.status == "checked_within_scope"


def test_a_missing_size_is_unresolved_naming_it_and_every_source_searched() -> None:
    lookup = FakeLookup(pin=bilateral(3.0, 0.0, -0.01), position=zone(0.02))

    result = stack_at(0.0, lookup)

    assert result.status == "unresolved"
    assert "a tolerance for the size of hol:0001#1" in result.observed
    assert any(
        "drawing callout: nothing binds it here" in limit and "general tolerance" in limit
        for limit in result.coverage_limits
    )
    assert result.calculation is None


def test_a_screw_needs_no_tolerance_on_its_own_size() -> None:
    """The fixed-fastener convention: the thread's nominal is its maximum material size."""
    lookup = FakeLookup(hole=bilateral(3.4, 0.1, 0.0), position=zone(0.1))
    joint, package = only_joint(screw_joint(clearance_bore=3.4))

    result = check_position_stack(joint, package, lookup)

    assert "pin_size" not in {subject.kind for subject in lookup.asked}
    values = result.calculation.result
    assert values["fastener_min_mm"] == values["fastener_max_mm"] == 3.0
    assert values["clearance_min_mm"] == 0.2
    assert result.status == "checked_within_scope"


def test_every_contributor_is_cited_in_the_inputs() -> None:
    result = stack_at(0.0, resolved_everything())

    inputs = result.calculation.inputs
    assert inputs["hol:0001#1_source"] == "model dimension: doc:0002 hole_size of hol:0001#1"
    assert inputs["hol:0001#1_min"] == Quantity(value=3.1, unit="mm")
    assert inputs["hol:0001#1_max"] == Quantity(value=3.12, unit="mm")
    assert inputs["fastener_min"] == Quantity(value=2.99, unit="mm")
    assert inputs["hol:0002#1_position_source"].startswith("model annotation:")
    assert inputs["F_source"].startswith("the fastener size the Hole Wizard hole")


def test_a_conflict_between_sources_becomes_a_coverage_limit() -> None:
    lookup = resolved_everything()
    lookup.conflict = "the drawing says 3.1 +0.02/0 and the model dimension 3.1 +0.03/0"

    result = stack_at(0.0, lookup)

    assert lookup.conflict in result.coverage_limits


def lone_tapped_screw():
    """A screw face in a lone tapped hole: a joint with no clearance hole."""
    builder = parts(2)
    builder.hole(
        "cmp:0001",
        hole_type="tapped",
        size="M3x0.5",
        thread="M3x0.5",
        end_condition="blind",
        instances=at((0.0, 0.0, 0.0), Face(2.5, -8.0, 0.0)),
    )
    builder.cylinder_face(
        "cmp:0002", origin_mm=(0.0, 0.0, 0.0), direction=Z, diameter_mm=3.0, lo_mm=-6.0, hi_mm=4.0
    )
    return builder


def test_a_joint_with_no_clearance_hole_has_no_stack() -> None:
    joint, package = only_joint(lone_tapped_screw())

    assert check_position_stack(joint, package, resolved_everything()) is None


def test_joints_with_no_clearance_hole_are_named_once_per_check() -> None:
    package = lone_tapped_screw().build().package

    checks = run_joint_checks(package, build_joint_map(package), resolved_everything())

    assert checks.results == ()
    assert [(item.check, item.reason.split(":")[0]) for item in checks.skipped] == [
        ("hole.nominal_alignment", "no clearance hole to line up in jnt"),
        ("hole.position_stack", "no clearance hole to line up in jnt"),
    ]


# --- the callout at maximum material --------------------------------------------------------


def test_the_nominal_callout_adds_the_maximum_material_zone_when_sizes_resolve() -> None:
    joint, package = only_joint(dowel_joint(3.1, 3.1, 0.0))

    result = check_nominal_alignment(joint, package, resolved_everything())

    assert result.calculation.result["callout"].endswith("; ⌀0.2 at maximum material")


def test_the_nominal_callout_is_unchanged_when_a_size_does_not_resolve() -> None:
    joint, package = only_joint(dowel_joint(3.1, 3.1, 0.0))

    result = check_nominal_alignment(joint, package, FakeLookup(position=zone(0.02)))

    assert "maximum material" not in result.calculation.result["callout"]


# --- no source at all: what every review does today -----------------------------------------


def test_with_no_source_the_stack_is_one_skipped_item_for_every_joint_and_no_finding() -> None:
    package = dowel_joint(3.1, 3.0, 0.75).build().package
    joint_map = build_joint_map(package)

    checks = run_joint_checks(package, joint_map, NoSources())

    assert [item.result.check for item in checks.results] == ["hole.nominal_alignment"]
    [skipped] = [item for item in checks.skipped if item.check == CHECK_STACK]
    assert skipped.reason == (
        "no tolerance source is read for this package; searched: drawing callout, model "
        "annotation, model dimension, Hole Wizard class, general tolerance"
    )
    assert skipped.scope.component_ids == ["cmp:0001", "cmp:0002"]


def test_no_sources_answers_every_subject_unresolved_naming_all_five() -> None:
    subject = ToleranceSubject(
        kind="hole_size", nominal_mm=3.1, document_id="doc:0002", instance_id="hol:0001#1"
    )

    answer = NoSources().resolve(subject)

    assert isinstance(answer, UnresolvedTolerance)
    assert [source for source, _ in answer.searched] == list(SOURCE_ORDER)
    assert {why for _, why in answer.searched} == {"no tolerance source is read yet"}
    assert NoSources().holds_any_source() is False


def test_with_a_source_every_joint_gets_both_checks() -> None:
    package = dowel_joint(3.1, 3.0, 0.75).build().package
    joint_map = build_joint_map(package)

    checks = run_joint_checks(package, joint_map, resolved_everything())

    assert [item.result.check for item in checks.results] == [
        "hole.nominal_alignment",
        "hole.position_stack",
    ]
    assert not [item for item in checks.skipped if item.check == CHECK_STACK]
