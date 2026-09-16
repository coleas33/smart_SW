"""Unit tests for the 17 part-scope RMS rule evaluators (T019).

`specs/003-resilient-modeling/contracts/rules.md` is normative: one test class per rule,
covering every row of its line in the part-scope table - the pass, the fail or warn, every
skip condition with the reason the contract words, and every unresolved condition - plus
the cross-cutting rules of the same file ("Class vocabulary", "Content features",
"Suppressed features", "Unresolved part documents").

Three things are asserted everywhere rather than once, because they are the shape of the
contract and not the detail of any one rule:

- **one `RuleResult` per outcome reached.** `by_outcome` refuses a rule that returns two
  results in the same bucket, so a rule cannot quietly emit a fail per feature;
- **subjects.** Asserted by name (the ids are an allocation detail of the builder), which
  is also how "end-tag markers are never subjects" is pinned;
- **observed text.** A finding that does not name the feature it is about is not evidence,
  so every fail and warn asserts the substring an engineer would search for.

`rms.detail.individually_suppressible` is US4: the rows of its outcome table that need a
`suppress-test` run live in `test_rms_suppress_rule.py` (T056), and what is here is the
tree half of it - no Detail group, no run, a run for another document.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from swreview.checks.rms import RULES, evaluable
from swreview.checks.rms.groups import assign_groups
from swreview.checks.rms.part import PartTree, evaluate_part, part_tree
from swreview.checks.rms.results import RuleResult
from swreview.checks.rms_types import load_table
from swreview.ir.models import Gap
from tests.support.features import (
    EquationSpec,
    FeatureSpec,
    InstanceSpec,
    PartSpec,
    SuppressTestRun,
    end_tag,
    equation,
    feature,
    fillet_feature,
    folder,
    rms_package,
    sketch_feature,
    suppress_row,
    suppress_run,
)

TABLE = load_table()
DOCUMENT = "doc:2"
SHAPES = ("nested", "flat")

REFERENCE, CONSTRUCTION, CORE, DETAIL, MODIFY, QUARANTINE = TABLE.groups

PART_RULE_IDS = tuple(rule.id for rule in evaluable() if rule.scope == "part")
EQUATION_RULE_IDS = tuple(rule.id for rule in evaluable() if rule.scope == "equations")


# --- helpers ----------------------------------------------------------------------


def build_tree(
    specs: Sequence[FeatureSpec],
    *,
    shape: str = "nested",
    document_id: str = DOCUMENT,
    instances: Sequence[InstanceSpec] | None = None,
    equations: Sequence[EquationSpec] = (),
    suppress_test: SuppressTestRun | None = None,
    gaps: Sequence[Gap] = (),
) -> PartTree:
    """One part document's rows, group assignment and package, as a rule reads them."""
    package = rms_package(
        parts=[
            PartSpec(
                document_id=document_id,
                name="housing",
                features=specs,
                shape=shape,  # type: ignore[arg-type]
                instances=instances,
                equations=equations,
            )
        ],
        suppress_test=suppress_test,
        gaps=gaps,
    )
    rows = [row for row in package.features if row.document_id == document_id]
    return part_tree(document_id, rows, TABLE, assign_groups(rows, TABLE), package)


def run(rule_id: str, specs: Sequence[FeatureSpec], **kwargs: Any) -> list[RuleResult]:
    """Evaluate one rule through the registry, which also pins that it is bound."""
    rule = RULES[rule_id]
    assert rule.fn is not None, f"{rule_id} has no evaluator"
    return rule.fn(build_tree(specs, **kwargs))


def by_outcome(results: Sequence[RuleResult]) -> dict[str, RuleResult]:
    """The results keyed by outcome, refusing two results in one bucket."""
    keyed: dict[str, RuleResult] = {}
    for result in results:
        assert result.outcome not in keyed, (
            f"{result.rule_id} returned two {result.outcome} results for one document"
        )
        assert result.document_id == DOCUMENT
        keyed[result.outcome] = result
    return keyed


def names(tree: PartTree, result: RuleResult) -> list[str]:
    """The subjects of a result by feature name, in the order the rule named them."""
    return [tree.by_id[subject].name for subject in result.subjects]


def subject_names(rule_id: str, specs: Sequence[FeatureSpec], outcome: str, **kwargs: Any):
    """`(result, subject names)` for the one result of `outcome`; fails when absent."""
    tree = build_tree(specs, **kwargs)
    rule = RULES[rule_id]
    assert rule.fn is not None
    results = rule.fn(tree)
    keyed = by_outcome(results)
    assert outcome in keyed, f"{rule_id} reached {sorted(keyed)}, not {outcome!r}"
    return keyed[outcome], names(tree, keyed[outcome])


# --- rms.folders.present ----------------------------------------------------------


class TestFoldersPresent:
    RULE = "rms.folders.present"

    def test_all_six_groups_pass(self) -> None:
        keyed = by_outcome(run(self.RULE, [folder(name) for name in TABLE.groups]))

        assert list(keyed) == ["pass"]
        assert keyed["pass"].subjects == []

    def test_missing_groups_warn_and_name_them(self) -> None:
        result, _ = subject_names(
            self.RULE, [folder(name) for name in TABLE.groups[:4]], "warn"
        )

        assert result.result is not None
        assert result.result.status == "suspected"
        assert result.result.severity == "low"
        assert MODIFY in result.result.observed
        assert QUARANTINE in result.result.observed
        assert CORE not in result.result.observed
        assert result.result.requirement == RULES[self.RULE].statement

    def test_a_part_with_no_folders_at_all_warns_rather_than_skipping(self) -> None:
        keyed = by_outcome(run(self.RULE, [feature("Boss1", "Extrusion")]))

        assert list(keyed) == ["warn"]
        assert keyed["warn"].result is not None
        for group in TABLE.groups:
            assert group in keyed["warn"].result.observed


# --- rms.folders.ordered ----------------------------------------------------------


class TestFoldersOrdered:
    RULE = "rms.folders.ordered"

    def test_fewer_than_two_groups_skips(self) -> None:
        keyed = by_outcome(run(self.RULE, [folder(CORE, feature("Boss1", "Extrusion"))]))

        assert list(keyed) == ["skip"]
        assert keyed["skip"].reason == "fewer than two groups"

    def test_no_groups_at_all_skips(self) -> None:
        keyed = by_outcome(run(self.RULE, [feature("Boss1", "Extrusion")]))

        assert keyed["skip"].reason == "fewer than two groups"

    def test_groups_in_order_pass_and_name_the_folders(self) -> None:
        result, subjects = subject_names(
            self.RULE, [folder(REFERENCE), folder(CORE), folder(DETAIL)], "pass"
        )

        assert result.outcome == "pass"
        assert subjects == [REFERENCE, CORE, DETAIL]

    def test_groups_out_of_order_fail_naming_both(self) -> None:
        result, subjects = subject_names(self.RULE, [folder(DETAIL), folder(CORE)], "fail")

        assert subjects == [DETAIL, CORE]
        assert result.result is not None
        assert result.result.status == "demonstrated"
        assert result.result.severity == "medium"
        assert f"in tree order: {DETAIL}, {CORE}" in result.result.observed

    def test_a_duplicate_group_folder_fails_naming_both_occurrences(self) -> None:
        result, subjects = subject_names(
            self.RULE,
            [folder(CORE, feature("Boss1", "Extrusion")), folder(CORE)],
            "fail",
        )

        assert subjects == [CORE, CORE]
        assert result.result is not None
        assert f"duplicated group folder(s): {CORE}" in result.result.observed
        assert len({item for item in result.subjects}) == 2


# --- rms.grouping.all_features_in_a_group -----------------------------------------


class TestGroupingAllFeaturesInAGroup:
    RULE = "rms.grouping.all_features_in_a_group"

    @pytest.mark.parametrize("shape", SHAPES)
    def test_every_content_feature_in_a_group_passes(self, shape: str) -> None:
        result, subjects = subject_names(
            self.RULE,
            [folder(CORE, feature("Boss1", "Extrusion"), feature("Cut1", "Cut"))],
            "pass",
            shape=shape,
        )

        assert result.outcome == "pass"
        assert subjects == ["Boss1", "Cut1"]

    def test_a_part_with_no_group_folders_fails_listing_every_content_feature(self) -> None:
        result, subjects = subject_names(
            self.RULE,
            [
                feature("Front Plane", "RefPlane"),
                feature("Sensors", "SensorFolder"),
                feature("Boss1", "Extrusion"),
                feature("Widget1", "Frobnicate"),
            ],
            "fail",
        )

        assert subjects == ["Boss1", "Widget1"]
        assert result.result is not None
        assert "Boss1" in result.result.observed
        assert "Widget1" in result.result.observed
        assert len(result.result.inputs) == 2
        assert " Boss1 [Extrusion] persist_ref=" in result.result.inputs[0]
        assert result.result.inputs[0].endswith(f"scope={DOCUMENT}")

    def test_content_after_an_end_tag_stays_in_the_group(self) -> None:
        keyed = by_outcome(
            run(
                self.RULE,
                [
                    folder(CORE, feature("Boss1", "Extrusion")),
                    end_tag(CORE),
                    feature("Cut1", "Cut"),
                ],
            )
        )

        assert list(keyed) == ["pass"]

    def test_a_part_with_no_content_features_passes_vacuously(self) -> None:
        keyed = by_outcome(run(self.RULE, [feature("Front Plane", "RefPlane")]))

        assert list(keyed) == ["pass"]
        assert keyed["pass"].subjects == []


# --- rms.groups.no_solids_in_ref_or_construction ----------------------------------


class TestNoSolidsInRefOrConstruction:
    RULE = "rms.groups.no_solids_in_ref_or_construction"

    def test_neither_group_present_skips(self) -> None:
        keyed = by_outcome(run(self.RULE, [folder(CORE, feature("Boss1", "Extrusion"))]))

        assert list(keyed) == ["skip"]
        assert keyed["skip"].reason == "no Reference or Construction group"

    def test_reference_geometry_only_passes(self) -> None:
        result, subjects = subject_names(
            self.RULE,
            [
                folder(REFERENCE, feature("Axis1", "RefAxis")),
                folder(CONSTRUCTION, feature("Surface1", "SurfaceExtrude")),
            ],
            "pass",
        )

        assert result.outcome == "pass"
        assert subjects == ["Axis1", "Surface1"]

    def test_material_in_either_group_fails(self) -> None:
        result, subjects = subject_names(
            self.RULE,
            [
                folder(REFERENCE, feature("Boss1", "Extrusion")),
                folder(CONSTRUCTION, feature("Hole1", "HoleWzd"), feature("Axis1", "RefAxis")),
                folder(CORE, feature("Boss2", "Extrusion")),
            ],
            "fail",
        )

        assert subjects == ["Boss1", "Hole1"]
        assert result.result is not None
        assert "Boss1 [Extrusion]" in result.result.observed
        assert "Hole1 [HoleWzd]" in result.result.observed
        assert "Boss2" not in result.result.observed

    def test_an_ambiguous_feature_counts_as_material(self) -> None:
        _, subjects = subject_names(
            self.RULE, [folder(REFERENCE, feature("Ice1", "ICE"))], "fail"
        )

        assert subjects == ["Ice1"]

    def test_an_unknown_class_is_unresolved_and_the_rest_still_pass(self) -> None:
        tree = build_tree(
            [
                folder(
                    CONSTRUCTION,
                    feature("Widget1", "Frobnicate"),
                    feature("Axis1", "RefAxis"),
                )
            ]
        )
        keyed = by_outcome(RULES[self.RULE].fn(tree))

        assert sorted(keyed) == ["pass", "unresolved"]
        assert names(tree, keyed["unresolved"]) == ["Widget1"]
        assert keyed["unresolved"].reason is not None
        assert "Frobnicate" in keyed["unresolved"].reason
        assert names(tree, keyed["pass"]) == ["Axis1"]


# --- rms.core.shell_last ----------------------------------------------------------


class TestShellLast:
    RULE = "rms.core.shell_last"

    def test_no_core_group_skips(self) -> None:
        keyed = by_outcome(run(self.RULE, [folder(DETAIL, feature("Shell1", "Shell"))]))

        assert keyed["skip"].reason == "no Core group"

    def test_no_shell_skips(self) -> None:
        keyed = by_outcome(run(self.RULE, [folder(CORE, feature("Boss1", "Extrusion"))]))

        assert keyed["skip"].reason == "no shell in Core"

    def test_a_trailing_shell_passes(self) -> None:
        result, subjects = subject_names(
            self.RULE,
            [folder(CORE, feature("Boss1", "Extrusion"), feature("Shell1", "Shell"))],
            "pass",
        )

        assert result.outcome == "pass"
        assert subjects == ["Shell1"]

    def test_features_after_the_shell_fail(self) -> None:
        result, subjects = subject_names(
            self.RULE,
            [
                folder(
                    CORE,
                    feature("Shell1", "Shell"),
                    feature("Boss1", "Extrusion"),
                    feature("Cut1", "Cut"),
                )
            ],
            "fail",
        )

        assert subjects == ["Shell1", "Boss1", "Cut1"]
        assert result.result is not None
        assert "Shell1" in result.result.observed
        assert "Boss1, Cut1" in result.result.observed

    def test_the_last_shell_is_the_one_that_has_to_trail(self) -> None:
        keyed = by_outcome(
            run(
                self.RULE,
                [
                    folder(
                        CORE,
                        feature("Shell1", "Shell"),
                        feature("Boss1", "Extrusion"),
                        feature("Shell2", "Shell"),
                    )
                ],
            )
        )

        assert list(keyed) == ["pass"]

    def test_a_feature_in_a_later_group_is_not_after_the_shell(self) -> None:
        keyed = by_outcome(
            run(
                self.RULE,
                [
                    folder(CORE, feature("Shell1", "Shell")),
                    folder(DETAIL, feature("Hole1", "HoleWzd")),
                ],
            )
        )

        assert list(keyed) == ["pass"]


# --- rms.detail.holes_last --------------------------------------------------------


class TestHolesLast:
    RULE = "rms.detail.holes_last"

    def test_no_detail_group_skips(self) -> None:
        keyed = by_outcome(run(self.RULE, [folder(CORE, feature("Hole1", "HoleWzd"))]))

        assert keyed["skip"].reason == "no Detail group"

    def test_no_hole_skips(self) -> None:
        keyed = by_outcome(run(self.RULE, [folder(DETAIL, feature("Boss1", "Extrusion"))]))

        assert keyed["skip"].reason == "no hole in Detail"

    def test_trailing_holes_pass(self) -> None:
        result, subjects = subject_names(
            self.RULE,
            [
                folder(
                    DETAIL,
                    feature("Boss1", "Extrusion"),
                    feature("Hole1", "HoleWzd"),
                    feature("Hole2", "SimpleHole"),
                )
            ],
            "pass",
        )

        assert result.outcome == "pass"
        assert subjects == ["Hole1", "Hole2"]

    def test_a_feature_after_a_hole_warns(self) -> None:
        result, subjects = subject_names(
            self.RULE,
            [
                folder(
                    DETAIL,
                    feature("Hole1", "HoleWzd"),
                    feature("Boss1", "Extrusion"),
                    feature("Hole2", "SimpleHole"),
                )
            ],
            "warn",
        )

        assert subjects == ["Hole1", "Boss1", "Hole2"]
        assert result.result is not None
        assert result.result.status == "suspected"
        assert result.result.severity == "low"
        assert "Boss1" in result.result.observed
        assert "Hole1" in result.result.observed

    def test_sketches_are_ignored(self) -> None:
        keyed = by_outcome(
            run(
                self.RULE,
                [
                    folder(
                        DETAIL,
                        feature("Hole1", "HoleWzd"),
                        sketch_feature("Sketch1", consumers=()),
                    )
                ],
            )
        )

        assert list(keyed) == ["pass"]

    def test_ambiguous_and_unknown_features_are_unresolved_not_ordered(self) -> None:
        tree = build_tree(
            [
                folder(
                    DETAIL,
                    feature("Hole1", "HoleWzd"),
                    feature("Ice1", "ICE"),
                    feature("Widget1", "Frobnicate"),
                )
            ]
        )
        keyed = by_outcome(RULES[self.RULE].fn(tree))

        assert sorted(keyed) == ["pass", "unresolved"]
        assert names(tree, keyed["unresolved"]) == ["Ice1", "Widget1"]
        assert keyed["unresolved"].reason is not None
        assert "ambiguous" in keyed["unresolved"].reason
        assert "unknown" in keyed["unresolved"].reason


# --- rms.modify.transform_before_replicate ----------------------------------------


class TestTransformBeforeReplicate:
    RULE = "rms.modify.transform_before_replicate"

    def test_no_modify_group_skips(self) -> None:
        keyed = by_outcome(run(self.RULE, [folder(CORE, feature("Draft1", "Draft"))]))

        assert keyed["skip"].reason == "no Modify group"

    def test_no_draft_skips_naming_what_is_absent(self) -> None:
        keyed = by_outcome(run(self.RULE, [folder(MODIFY, feature("Pattern1", "LPattern"))]))

        assert keyed["skip"].reason == "no draft in Modify"

    def test_no_pattern_skips_naming_what_is_absent(self) -> None:
        keyed = by_outcome(run(self.RULE, [folder(MODIFY, feature("Draft1", "Draft"))]))

        assert keyed["skip"].reason == "no pattern in Modify"

    def test_neither_draft_nor_pattern_names_both(self) -> None:
        keyed = by_outcome(run(self.RULE, [folder(MODIFY, feature("Boss1", "Extrusion"))]))

        assert keyed["skip"].reason == "no draft and no pattern in Modify"

    def test_draft_before_pattern_passes(self) -> None:
        result, subjects = subject_names(
            self.RULE,
            [folder(MODIFY, feature("Draft1", "Draft"), feature("Pattern1", "LPattern"))],
            "pass",
        )

        assert result.outcome == "pass"
        assert subjects == ["Draft1", "Pattern1"]

    def test_pattern_before_draft_warns(self) -> None:
        result, subjects = subject_names(
            self.RULE,
            [folder(MODIFY, feature("Pattern1", "CirPattern"), feature("Draft1", "Draft"))],
            "warn",
        )

        assert subjects == ["Pattern1", "Draft1"]
        assert result.result is not None
        assert "Pattern1" in result.result.observed
        assert "Draft1" in result.result.observed


# --- rms.quarantine.chamfers_before_fillets ---------------------------------------


class TestChamfersBeforeFillets:
    RULE = "rms.quarantine.chamfers_before_fillets"

    def test_no_quarantine_group_skips(self) -> None:
        keyed = by_outcome(run(self.RULE, [folder(CORE, fillet_feature("Fillet1"))]))

        assert keyed["skip"].reason == "no Quarantine group"

    def test_an_empty_quarantine_skips(self) -> None:
        keyed = by_outcome(run(self.RULE, [folder(CORE), folder(QUARANTINE)]))

        assert keyed["skip"].reason == "Quarantine is empty"

    def test_chamfers_first_passes(self) -> None:
        result, subjects = subject_names(
            self.RULE,
            [
                folder(
                    QUARANTINE,
                    feature("Chamfer1", "Chamfer"),
                    fillet_feature("Fillet1"),
                )
            ],
            "pass",
        )

        assert result.outcome == "pass"
        assert subjects == ["Chamfer1", "Fillet1"]

    def test_a_fillet_before_a_chamfer_fails(self) -> None:
        result, subjects = subject_names(
            self.RULE,
            [
                folder(
                    QUARANTINE,
                    fillet_feature("Fillet1"),
                    feature("Chamfer1", "Chamfer"),
                )
            ],
            "fail",
        )

        assert subjects == ["Fillet1", "Chamfer1"]
        assert result.result is not None
        assert "Fillet1" in result.result.observed
        assert "Chamfer1" in result.result.observed


# --- rms.quarantine.largest_fillet_first ------------------------------------------


class TestLargestFilletFirst:
    RULE = "rms.quarantine.largest_fillet_first"

    def test_no_quarantine_group_skips(self) -> None:
        keyed = by_outcome(run(self.RULE, [folder(CORE, fillet_feature("Fillet1"))]))

        assert keyed["skip"].reason == "no Quarantine group"

    def test_one_readable_radius_skips(self) -> None:
        keyed = by_outcome(
            run(self.RULE, [folder(QUARANTINE, fillet_feature("Fillet1", radius_m=0.005))])
        )

        assert keyed["skip"].reason == "fewer than two readable fillet radii in Quarantine"

    def test_the_skip_reason_names_the_unreadable_fillets(self) -> None:
        keyed = by_outcome(
            run(
                self.RULE,
                [
                    folder(
                        QUARANTINE,
                        fillet_feature("Fillet1", radius_m=0.005),
                        fillet_feature("Fillet2", radius_m=None),
                    )
                ],
            )
        )

        assert keyed["skip"].reason is not None
        assert "Fillet2" in keyed["skip"].reason
        assert "radius unreadable" in keyed["skip"].reason

    def test_non_increasing_radii_pass(self) -> None:
        result, subjects = subject_names(
            self.RULE,
            [
                folder(
                    QUARANTINE,
                    fillet_feature("Fillet1", radius_m=0.008),
                    fillet_feature("Fillet2", radius_m=0.005),
                    fillet_feature("Fillet3", radius_m=0.005),
                )
            ],
            "pass",
        )

        assert result.outcome == "pass"
        assert subjects == ["Fillet1", "Fillet2", "Fillet3"]

    def test_an_increasing_radius_fails_naming_the_pair(self) -> None:
        result, subjects = subject_names(
            self.RULE,
            [
                folder(
                    QUARANTINE,
                    fillet_feature("Fillet1", radius_m=0.005),
                    fillet_feature("Fillet2", radius_m=0.008),
                )
            ],
            "fail",
        )

        assert subjects == ["Fillet1", "Fillet2"]
        assert result.result is not None
        assert "Fillet2" in result.result.observed
        assert "0.008" in result.result.observed

    def test_an_unreadable_radius_is_unresolved_when_the_rule_still_runs(self) -> None:
        tree = build_tree(
            [
                folder(
                    QUARANTINE,
                    fillet_feature("Fillet1", radius_m=0.008),
                    fillet_feature("Fillet2", radius_m=0.005),
                    fillet_feature("Fillet3", radius_m=None),
                )
            ]
        )
        keyed = by_outcome(RULES[self.RULE].fn(tree))

        assert sorted(keyed) == ["pass", "unresolved"]
        assert names(tree, keyed["unresolved"]) == ["Fillet3"]
        assert names(tree, keyed["pass"]) == ["Fillet1", "Fillet2"]


# --- rms.quarantine.only_fillets_and_chamfers -------------------------------------


class TestOnlyFilletsAndChamfers:
    RULE = "rms.quarantine.only_fillets_and_chamfers"

    def test_no_quarantine_group_skips(self) -> None:
        keyed = by_outcome(run(self.RULE, [folder(CORE, fillet_feature("Fillet1"))]))

        assert keyed["skip"].reason == "no Quarantine group"

    def test_an_empty_quarantine_skips(self) -> None:
        keyed = by_outcome(run(self.RULE, [folder(CORE), folder(QUARANTINE)]))

        assert keyed["skip"].reason == "Quarantine is empty"

    def test_fillets_and_chamfers_pass(self) -> None:
        result, subjects = subject_names(
            self.RULE,
            [folder(QUARANTINE, fillet_feature("Fillet1"), feature("Chamfer1", "Chamfer"))],
            "pass",
        )

        assert result.outcome == "pass"
        assert subjects == ["Fillet1", "Chamfer1"]

    def test_anything_else_fails(self) -> None:
        result, subjects = subject_names(
            self.RULE,
            [folder(QUARANTINE, fillet_feature("Fillet1"), feature("Boss1", "Extrusion"))],
            "fail",
        )

        assert subjects == ["Boss1"]
        assert result.result is not None
        assert "Boss1 [Extrusion]" in result.result.observed

    def test_unknown_and_ambiguous_classes_are_unresolved(self) -> None:
        tree = build_tree(
            [
                folder(
                    QUARANTINE,
                    fillet_feature("Fillet1"),
                    feature("Widget1", "Frobnicate"),
                    feature("Ice1", "ICE"),
                )
            ]
        )
        keyed = by_outcome(RULES[self.RULE].fn(tree))

        assert sorted(keyed) == ["pass", "unresolved"]
        assert names(tree, keyed["unresolved"]) == ["Widget1", "Ice1"]
        assert names(tree, keyed["pass"]) == ["Fillet1"]


# --- rms.refs.direction -----------------------------------------------------------


class TestRefsDirection:
    RULE = "rms.refs.direction"

    def test_a_dependent_in_a_later_group_passes(self) -> None:
        result, subjects = subject_names(
            self.RULE,
            [
                folder(CORE, sketch_feature("Sketch1", consumers=("Boss1",))),
                folder(DETAIL, feature("Boss1", "Extrusion", parent_names=("Sketch1",))),
            ],
            "pass",
        )

        assert result.outcome == "pass"
        assert subjects == ["Sketch1", "Boss1"]

    def test_a_dependent_in_an_earlier_group_fails(self) -> None:
        result, subjects = subject_names(
            self.RULE,
            [
                folder(DETAIL, feature("Boss1", "Extrusion")),
                folder(MODIFY, feature("Draft1", "Draft", child_names=("Boss1",))),
            ],
            "fail",
        )

        assert subjects == ["Boss1", "Draft1"]
        assert result.result is not None
        assert result.result.severity == "high"
        assert f"Boss1 in {DETAIL}" in result.result.observed
        assert f"Draft1 in {MODIFY}" in result.result.observed

    def test_unreadable_children_are_unresolved(self) -> None:
        tree = build_tree(
            [
                folder(
                    CORE,
                    feature("Boss1", "Extrusion", child_names=None),
                    feature("Cut1", "Cut"),
                )
            ]
        )
        keyed = by_outcome(RULES[self.RULE].fn(tree))

        assert sorted(keyed) == ["pass", "unresolved"]
        assert names(tree, keyed["unresolved"]) == ["Boss1"]
        assert keyed["unresolved"].reason is not None
        assert "children unavailable" in keyed["unresolved"].reason

    def test_a_feature_outside_every_group_is_not_compared(self) -> None:
        keyed = by_outcome(
            run(
                self.RULE,
                [
                    feature("Boss1", "Extrusion"),
                    folder(CORE, feature("Cut1", "Cut", child_names=("Boss1",))),
                ],
            )
        )

        assert list(keyed) == ["pass"]

    def test_a_loose_feature_with_unreadable_children_is_unresolved(self) -> None:
        """The contract's unresolved condition is "per feature whose `child_ids` is
        null", unqualified: a feature the rule cannot compare because it is in no group
        is still a feature whose children were not read, and a missing input is never
        silently dropped (constitution Principle I)."""
        tree = build_tree(
            [
                feature("Boss1", "Extrusion", child_names=None),
                folder(CORE, feature("Cut1", "Cut")),
            ]
        )
        keyed = by_outcome(RULES[self.RULE].fn(tree))

        assert sorted(keyed) == ["pass", "unresolved"]
        assert names(tree, keyed["unresolved"]) == ["Boss1"]
        assert names(tree, keyed["pass"]) == ["Cut1"]
        assert keyed["unresolved"].reason is not None
        assert "children unavailable" in keyed["unresolved"].reason


# --- rms.refs.quarantine_has_no_children ------------------------------------------


class TestQuarantineHasNoChildren:
    RULE = "rms.refs.quarantine_has_no_children"

    def test_no_quarantine_group_skips(self) -> None:
        keyed = by_outcome(run(self.RULE, [folder(CORE, feature("Boss1", "Extrusion"))]))

        assert keyed["skip"].reason == "no Quarantine group"

    def test_a_childless_quarantine_passes(self) -> None:
        result, subjects = subject_names(
            self.RULE, [folder(QUARANTINE, fillet_feature("Fillet1"))], "pass"
        )

        assert result.outcome == "pass"
        assert subjects == ["Fillet1"]

    def test_a_dependent_of_a_quarantine_feature_fails(self) -> None:
        result, subjects = subject_names(
            self.RULE,
            [
                folder(
                    QUARANTINE,
                    fillet_feature("Fillet1", child_names=("Chamfer1",)),
                    feature("Chamfer1", "Chamfer", parent_names=("Fillet1",)),
                )
            ],
            "fail",
        )

        assert subjects == ["Fillet1", "Chamfer1"]
        assert result.result is not None
        assert result.result.severity == "high"
        assert "Fillet1" in result.result.observed
        assert "Chamfer1" in result.result.observed

    def test_unreadable_children_are_unresolved(self) -> None:
        tree = build_tree(
            [
                folder(
                    QUARANTINE,
                    fillet_feature("Fillet1", child_names=None),
                    fillet_feature("Fillet2"),
                )
            ]
        )
        keyed = by_outcome(RULES[self.RULE].fn(tree))

        assert sorted(keyed) == ["pass", "unresolved"]
        assert names(tree, keyed["unresolved"]) == ["Fillet1"]


# --- rms.detail.no_internal_references --------------------------------------------


class TestNoInternalReferences:
    RULE = "rms.detail.no_internal_references"

    def test_no_detail_group_skips(self) -> None:
        keyed = by_outcome(run(self.RULE, [folder(CORE, feature("Boss1", "Extrusion"))]))

        assert keyed["skip"].reason == "no Detail group"

    def test_a_detail_feature_depending_on_another_fails(self) -> None:
        result, subjects = subject_names(
            self.RULE,
            [
                folder(
                    DETAIL,
                    feature("Boss1", "Extrusion", child_names=("Cut1",)),
                    feature("Cut1", "Cut", parent_names=("Boss1",)),
                )
            ],
            "fail",
        )

        assert subjects == ["Boss1", "Cut1"]
        assert result.result is not None
        assert "Cut1" in result.result.observed
        assert "Boss1" in result.result.observed

    def test_a_dependent_outside_detail_passes(self) -> None:
        keyed = by_outcome(
            run(
                self.RULE,
                [
                    folder(DETAIL, feature("Boss1", "Extrusion", child_names=("Pattern1",))),
                    folder(MODIFY, feature("Pattern1", "LPattern", parent_names=("Boss1",))),
                ],
            )
        )

        assert list(keyed) == ["pass"]

    @pytest.mark.parametrize("shape", SHAPES)
    def test_a_sketch_with_exactly_one_consumer_is_exempt(self, shape: str) -> None:
        keyed = by_outcome(
            run(
                self.RULE,
                [
                    folder(
                        DETAIL,
                        sketch_feature("Sketch1", consumers=("Boss1",)),
                        feature("Boss1", "Extrusion", parent_names=("Sketch1",)),
                    )
                ],
                shape=shape,
            )
        )

        assert list(keyed) == ["pass"]

    def test_a_sketch_with_two_consumers_is_not_exempt(self) -> None:
        _, subjects = subject_names(
            self.RULE,
            [
                folder(
                    DETAIL,
                    sketch_feature("Sketch1", consumers=("Boss1", "Cut1")),
                    feature("Boss1", "Extrusion", parent_names=("Sketch1",)),
                    feature("Cut1", "Cut", parent_names=("Sketch1",)),
                )
            ],
            "fail",
        )

        assert subjects == ["Sketch1", "Boss1", "Cut1"]

    def test_a_sketch_of_an_unlisted_type_keeps_the_carve_out(self) -> None:
        """The carve-out asks the extractor's own fact (`Feature.sketch`), not the type
        table: a sketch whose type name the table does not list is still a sketch, and
        this rule needs no class at all (`rules.md`, "Class vocabulary")."""
        keyed = by_outcome(
            run(
                self.RULE,
                [
                    folder(
                        DETAIL,
                        sketch_feature(
                            "Sketch1",
                            type_name="NewProfileFeature",
                            consumers=("Boss1",),
                        ),
                        feature("Boss1", "Extrusion", parent_names=("Sketch1",)),
                    )
                ],
            )
        )

        assert list(keyed) == ["pass"]

    @pytest.mark.parametrize("shape", SHAPES)
    def test_a_coupled_pair_in_one_derived_subfolder_is_exempt(self, shape: str) -> None:
        keyed = by_outcome(
            run(
                self.RULE,
                [
                    folder(
                        DETAIL,
                        folder(
                            "Coupled",
                            feature("Boss1", "Extrusion", child_names=("Cut1",)),
                            feature("Cut1", "Cut", parent_names=("Boss1",)),
                        ),
                    )
                ],
                shape=shape,
            )
        )

        assert list(keyed) == ["pass"]

    @pytest.mark.parametrize("shape", SHAPES)
    def test_features_in_two_different_subfolders_are_not_a_coupled_pair(
        self, shape: str
    ) -> None:
        _, subjects = subject_names(
            self.RULE,
            [
                folder(
                    DETAIL,
                    folder("CoupledA", feature("Boss1", "Extrusion", child_names=("Cut1",))),
                    folder("CoupledB", feature("Cut1", "Cut", parent_names=("Boss1",))),
                )
            ],
            "fail",
            shape=shape,
        )

        assert subjects == ["Boss1", "Cut1"]

    def test_two_features_loose_in_detail_are_not_a_coupled_pair(self) -> None:
        _, subjects = subject_names(
            self.RULE,
            [
                folder(
                    DETAIL,
                    feature("Boss1", "Extrusion", child_names=("Cut1",)),
                    feature("Cut1", "Cut", parent_names=("Boss1",)),
                )
            ],
            "fail",
        )

        assert subjects == ["Boss1", "Cut1"]

    def test_unreadable_children_are_unresolved(self) -> None:
        tree = build_tree(
            [
                folder(
                    DETAIL,
                    feature("Boss1", "Extrusion", child_names=None),
                    feature("Cut1", "Cut"),
                )
            ]
        )
        keyed = by_outcome(RULES[self.RULE].fn(tree))

        assert sorted(keyed) == ["pass", "unresolved"]
        assert names(tree, keyed["unresolved"]) == ["Boss1"]


# --- rms.intent.every_feature_described -------------------------------------------


class TestEveryFeatureDescribed:
    RULE = "rms.intent.every_feature_described"

    def test_described_content_passes(self) -> None:
        result, subjects = subject_names(
            self.RULE,
            [folder(CORE, feature("Boss1", "Extrusion", description="the core block"))],
            "pass",
        )

        assert result.outcome == "pass"
        assert subjects == ["Boss1"]

    def test_a_blank_description_fails(self) -> None:
        result, subjects = subject_names(
            self.RULE,
            [
                folder(
                    CORE,
                    feature("Boss1", "Extrusion", description=""),
                    feature("Cut1", "Cut", description="   "),
                    feature("Cut2", "Cut", description="clears the boss"),
                )
            ],
            "fail",
        )

        assert subjects == ["Boss1", "Cut1"]
        assert result.result is not None
        assert "Boss1" in result.result.observed
        assert "Cut2" not in result.result.observed

    def test_an_unknown_class_feature_still_needs_a_description(self) -> None:
        _, subjects = subject_names(
            self.RULE,
            [folder(CORE, feature("Widget1", "Frobnicate", description=""))],
            "fail",
        )

        assert subjects == ["Widget1"]

    def test_folders_end_tags_and_tolerated_types_are_not_content(self) -> None:
        keyed = by_outcome(
            run(
                self.RULE,
                [
                    feature("Front Plane", "RefPlane", description=""),
                    feature("Sensors", "SensorFolder", description=""),
                    folder(CORE, feature("Boss1", "Extrusion")),
                    end_tag(CORE),
                ],
            )
        )

        assert list(keyed) == ["pass"]

    def test_an_unreadable_description_is_unresolved(self) -> None:
        tree = build_tree(
            [
                folder(
                    CORE,
                    feature("Boss1", "Extrusion", description=None),
                    feature("Cut1", "Cut"),
                )
            ]
        )
        keyed = by_outcome(RULES[self.RULE].fn(tree))

        assert sorted(keyed) == ["pass", "unresolved"]
        assert names(tree, keyed["unresolved"]) == ["Boss1"]
        assert keyed["unresolved"].reason is not None
        assert "description unreadable" in keyed["unresolved"].reason


# --- rms.sketches.fully_defined ---------------------------------------------------


class TestSketchesFullyDefined:
    RULE = "rms.sketches.fully_defined"

    def test_a_fully_defined_sketch_passes(self) -> None:
        result, subjects = subject_names(
            self.RULE,
            [folder(CORE, sketch_feature("Sketch1", raw_status=3, consumers=()))],
            "pass",
        )

        assert result.outcome == "pass"
        assert subjects == ["Sketch1"]

    def test_only_under_defined_fails(self) -> None:
        result, subjects = subject_names(
            self.RULE,
            [
                folder(
                    CORE,
                    sketch_feature("Sketch1", raw_status=2, consumers=("Boss1",)),
                    feature("Boss1", "Extrusion", parent_names=("Sketch1",)),
                    sketch_feature("Sketch2", raw_status=4, consumers=()),
                )
            ],
            "fail",
        )

        assert subjects == ["Sketch1", "Boss1"]
        assert result.result is not None
        assert "Sketch1" in result.result.observed
        assert "under_defined" in result.result.observed
        assert "Sketch2" not in result.result.observed

    @pytest.mark.parametrize("raw_status", [1, 7, 99, None])
    def test_unknown_and_unavailable_statuses_are_unresolved(
        self, raw_status: int | None
    ) -> None:
        tree = build_tree(
            [folder(CORE, sketch_feature("Sketch1", raw_status=raw_status, consumers=()))]
        )
        keyed = by_outcome(RULES[self.RULE].fn(tree))

        assert list(keyed) == ["unresolved"]
        assert names(tree, keyed["unresolved"]) == ["Sketch1"]
        assert keyed["unresolved"].reason is not None
        expected = "unavailable" if raw_status is None else "unknown"
        assert expected in keyed["unresolved"].reason

    def test_a_part_with_no_sketch_passes_vacuously(self) -> None:
        keyed = by_outcome(run(self.RULE, [folder(CORE, feature("Boss1", "Extrusion"))]))

        assert list(keyed) == ["pass"]
        assert keyed["pass"].subjects == []


# --- rms.sketches.not_over_defined ------------------------------------------------


class TestSketchesNotOverDefined:
    RULE = "rms.sketches.not_over_defined"

    @pytest.mark.parametrize("raw_status", [2, 3])
    def test_defined_and_under_defined_pass(self, raw_status: int) -> None:
        keyed = by_outcome(
            run(
                self.RULE,
                [folder(CORE, sketch_feature("Sketch1", raw_status=raw_status, consumers=()))],
            )
        )

        assert list(keyed) == ["pass"]

    @pytest.mark.parametrize(("raw_status", "status"), [(4, "over_defined"), (5, "solver_error")])
    def test_over_defined_and_solver_error_fail(self, raw_status: int, status: str) -> None:
        result, subjects = subject_names(
            self.RULE,
            [
                folder(
                    CORE,
                    sketch_feature("Sketch1", raw_status=raw_status, consumers=("Boss1",)),
                    feature("Boss1", "Extrusion", parent_names=("Sketch1",)),
                )
            ],
            "fail",
        )

        assert subjects == ["Sketch1", "Boss1"]
        assert result.result is not None
        assert result.result.severity == "high"
        assert status in result.result.observed

    @pytest.mark.parametrize("raw_status", [1, 7, None])
    def test_unknown_and_unavailable_statuses_are_unresolved(
        self, raw_status: int | None
    ) -> None:
        keyed = by_outcome(
            run(
                self.RULE,
                [folder(CORE, sketch_feature("Sketch1", raw_status=raw_status, consumers=()))],
            )
        )

        assert list(keyed) == ["unresolved"]


# --- rms.sketches.one_sketch_per_feature ------------------------------------------


class TestOneSketchPerFeature:
    RULE = "rms.sketches.one_sketch_per_feature"

    def test_a_sketch_with_no_consumer_passes(self) -> None:
        result, subjects = subject_names(
            self.RULE, [folder(CORE, sketch_feature("Sketch1", consumers=()))], "pass"
        )

        assert result.outcome == "pass"
        assert subjects == ["Sketch1"]

    def test_a_sketch_with_one_consumer_passes(self) -> None:
        keyed = by_outcome(
            run(
                self.RULE,
                [
                    folder(
                        CORE,
                        sketch_feature("Sketch1", consumers=("Boss1",)),
                        feature("Boss1", "Extrusion", parent_names=("Sketch1",)),
                    )
                ],
            )
        )

        assert list(keyed) == ["pass"]

    def test_a_shared_sketch_fails_naming_its_consumers(self) -> None:
        result, subjects = subject_names(
            self.RULE,
            [
                folder(
                    CORE,
                    sketch_feature("Sketch1", consumers=("Boss1", "Cut1")),
                    feature("Boss1", "Extrusion", parent_names=("Sketch1",)),
                    feature("Cut1", "Cut", parent_names=("Sketch1",)),
                )
            ],
            "fail",
        )

        assert subjects == ["Sketch1", "Boss1", "Cut1"]
        assert result.result is not None
        assert "Sketch1" in result.result.observed
        assert "Boss1, Cut1" in result.result.observed

    def test_unreadable_consumers_are_unresolved(self) -> None:
        tree = build_tree(
            [
                folder(
                    CORE,
                    sketch_feature("Sketch1", consumers=None, child_names=()),
                    sketch_feature("Sketch2", consumers=()),
                )
            ]
        )
        keyed = by_outcome(RULES[self.RULE].fn(tree))

        assert sorted(keyed) == ["pass", "unresolved"]
        assert names(tree, keyed["unresolved"]) == ["Sketch1"]
        assert keyed["unresolved"].reason is not None
        assert "consumers unavailable" in keyed["unresolved"].reason


# --- rms.detail.individually_suppressible (US4 boundary) --------------------------


class TestIndividuallySuppressible:
    RULE = "rms.detail.individually_suppressible"

    def test_without_a_run_every_detail_content_feature_is_unresolved(self) -> None:
        tree = build_tree(
            [
                folder(CORE, feature("Boss1", "Extrusion")),
                folder(DETAIL, feature("Cut1", "Cut"), sketch_feature("Sketch1", consumers=())),
            ]
        )
        keyed = by_outcome(RULES[self.RULE].fn(tree))

        assert list(keyed) == ["unresolved"]
        assert names(tree, keyed["unresolved"]) == ["Cut1", "Sketch1"]
        assert keyed["unresolved"].reason == "no suppress-test run"

    def test_a_run_for_another_document_is_no_run(self) -> None:
        other = suppress_run(document_id="doc:9", rows=[])
        tree = build_tree([folder(DETAIL, feature("Cut1", "Cut"))], suppress_test=other)
        keyed = by_outcome(RULES[self.RULE].fn(tree))

        assert keyed["unresolved"].reason == "no suppress-test run"

    def test_no_detail_group_skips(self) -> None:
        keyed = by_outcome(run(self.RULE, [folder(CORE, feature("Boss1", "Extrusion"))]))

        assert keyed["skip"].reason == "no Detail group"

    def test_a_run_for_this_document_is_graded(self) -> None:
        """The rest of the outcome table is `test_rms_suppress_rule.py`; this is the seam."""
        rows = build_tree([folder(DETAIL, feature("Cut1", "Cut"))]).rows
        detail = next(row for row in rows if row.name == "Cut1")
        tree = build_tree(
            [folder(DETAIL, feature("Cut1", "Cut"))],
            suppress_test=suppress_run(
                document_id=DOCUMENT, rows=[suppress_row(detail, "ok")], group=DETAIL
            ),
        )
        keyed = by_outcome(RULES[self.RULE].fn(tree))

        assert names(tree, keyed["pass"]) == ["Cut1"]


# --- evaluate_part ----------------------------------------------------------------


class TestEvaluatePart:
    def evaluate(self, specs: Sequence[FeatureSpec], **kwargs: Any) -> list[RuleResult]:
        tree = build_tree(specs, **kwargs)
        return evaluate_part(
            tree.document_id, tree.rows, TABLE, tree.assignment, tree.package
        )

    def test_every_part_rule_lands_in_at_least_one_bucket(self) -> None:
        results = self.evaluate(
            [
                folder(REFERENCE, feature("Axis1", "RefAxis")),
                folder(CONSTRUCTION, feature("Surface1", "SurfaceExtrude")),
                folder(
                    CORE,
                    sketch_feature("Sketch1", consumers=("Boss1",)),
                    feature("Boss1", "Extrusion", parent_names=("Sketch1",)),
                    feature("Shell1", "Shell"),
                ),
                folder(DETAIL, feature("Hole1", "HoleWzd")),
                folder(MODIFY, feature("Draft1", "Draft"), feature("Pattern1", "LPattern")),
                folder(QUARANTINE, fillet_feature("Fillet1", radius_m=0.008)),
            ]
        )

        assert {result.rule_id for result in results} == set(PART_RULE_IDS)
        assert not [result for result in results if result.outcome in ("fail", "warn")]

    def test_a_part_with_no_groups_fails_grouping_and_skips_the_per_group_rules(self) -> None:
        results = self.evaluate(
            [
                feature("Boss1", "Extrusion"),
                feature("Shell1", "Shell"),
                feature("Widget1", "Frobnicate"),
            ]
        )
        by_rule = {result.rule_id: result for result in results if result.outcome != "pass"}

        grouping = by_rule["rms.grouping.all_features_in_a_group"]
        assert grouping.outcome == "fail"
        assert grouping.result is not None
        assert len(grouping.subjects) == 3

        assert by_rule["rms.core.shell_last"].reason == "no Core group"
        assert by_rule["rms.detail.holes_last"].reason == "no Detail group"
        assert by_rule["rms.modify.transform_before_replicate"].reason == "no Modify group"
        for rule_id in (
            "rms.quarantine.chamfers_before_fillets",
            "rms.quarantine.largest_fillet_first",
            "rms.quarantine.only_fillets_and_chamfers",
            "rms.refs.quarantine_has_no_children",
        ):
            assert by_rule[rule_id].outcome == "skip"
            assert by_rule[rule_id].reason == "no Quarantine group"

    def test_a_suppressed_feature_is_evaluated_as_present_and_marked(self) -> None:
        results = self.evaluate(
            [folder(CORE, feature("Boss1", "Extrusion", description="", suppressed=True))]
        )
        described = next(
            result
            for result in results
            if result.rule_id == "rms.intent.every_feature_described"
        )

        assert described.outcome == "fail"
        assert described.result is not None
        assert "Boss1 is suppressed in Default" in described.result.observed
        assert any(
            "suppressed in Default" in limit for limit in described.result.coverage_limits
        )

    @pytest.mark.parametrize("shape", SHAPES)
    def test_end_tags_are_never_subjects(self, shape: str) -> None:
        tree = build_tree(
            [
                folder(CORE, feature("Boss1", "Extrusion", description="")),
                folder(QUARANTINE, fillet_feature("Fillet1", description="")),
            ],
            shape=shape,
        )
        results = evaluate_part(
            tree.document_id, tree.rows, TABLE, tree.assignment, tree.package
        )
        end_tags = {row.id for row in tree.rows if TABLE.is_end_tag(row)}

        assert end_tags if shape == "flat" else not end_tags
        for result in results:
            assert not end_tags & set(result.subjects)

    def test_a_document_with_no_rows_and_no_resolved_instance_is_unresolved(self) -> None:
        results = self.evaluate(
            [], instances=[InstanceSpec("housing-1", suppression="lightweight")]
        )

        assert {result.rule_id for result in results} == set(PART_RULE_IDS) | set(
            EQUATION_RULE_IDS
        )
        assert {result.outcome for result in results} == {"unresolved"}
        assert {result.reason for result in results} == {
            "component housing-1 lightweight; tree not read"
        }
        assert all(result.subjects == [] for result in results)

    @pytest.mark.parametrize("entity_id", [DOCUMENT, None])
    def test_a_resolved_instance_whose_tree_was_not_read_is_unresolved(
        self, entity_id: str | None
    ) -> None:
        # The other half of "tree not read": the component resolved, so the extractor did
        # reach it, but its tree was dropped whole (a failed walk, a feature with no
        # persistent reference) or never read at all (`--features none`, which records the
        # gap with no entity id). Graded as an empty tree, this document would report a
        # pass for six fail-severity rules about a tree nobody opened.
        results = self.evaluate(
            [],
            gaps=[
                Gap(
                    kind="not_extracted",
                    entity_kind="feature_tree_unavailable",
                    entity_id=entity_id,
                    reason="The feature tree of housing.SLDPRT was not read: the walk failed.",
                    error=None,
                )
            ],
        )

        assert {result.rule_id for result in results} == set(PART_RULE_IDS) | set(
            EQUATION_RULE_IDS
        )
        assert {result.outcome for result in results} == {"unresolved"}
        assert {result.reason for result in results} == {
            "The feature tree of housing.SLDPRT was not read: the walk failed."
        }

    def test_a_component_gap_does_not_speak_for_a_document_that_was_read(self) -> None:
        # `feature_tree_unavailable` naming a COMPONENT is the per-instance state gap, and
        # an unreadable instance says nothing about a document another instance carried.
        results = self.evaluate(
            [folder(CORE, feature("Boss1", "Extrusion"))],
            instances=[
                InstanceSpec("housing-1", suppression="resolved"),
                InstanceSpec("housing-2", suppression="lightweight"),
            ],
        )

        assert "pass" in {result.outcome for result in results}

    def test_an_empty_tree_that_was_read_is_not_unresolved(self) -> None:
        # A part with no features at all is a real answer, not a missing one, so it is
        # evaluated: the absence of a gap is what separates the two.
        results = self.evaluate([])

        assert {result.rule_id for result in results} == set(PART_RULE_IDS)
        assert "unresolved" not in {result.outcome for result in results}

    def test_one_resolved_instance_is_evaluated_normally(self) -> None:
        results = self.evaluate(
            [folder(CORE, feature("Boss1", "Extrusion"))],
            instances=[
                InstanceSpec("housing-1", suppression="resolved"),
                InstanceSpec("housing-2", suppression="lightweight"),
            ],
        )

        assert {result.rule_id for result in results} == set(PART_RULE_IDS)
        assert "pass" in {result.outcome for result in results}

    def test_rows_from_another_document_are_refused(self) -> None:
        tree = build_tree([folder(CORE, feature("Boss1", "Extrusion"))])

        with pytest.raises(ValueError, match="doc:9"):
            evaluate_part("doc:9", tree.rows, TABLE, tree.assignment, tree.package)

    def test_equations_do_not_reach_the_part_rules(self) -> None:
        results = self.evaluate(
            [folder(CORE, feature("Boss1", "Extrusion"))],
            equations=[equation('"width" = 40', is_global=True)],
        )

        assert not set(EQUATION_RULE_IDS) & {result.rule_id for result in results}
