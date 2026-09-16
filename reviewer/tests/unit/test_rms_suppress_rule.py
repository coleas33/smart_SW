"""Unit tests for `rms.detail.individually_suppressible` (T056).

The rule has no tree shape of its own: it grades the Detail content features of one part
against the `suppress-test` run the package carries, so the contract that matters is the
outcome table of `specs/003-resilient-modeling/contracts/rules.md` ("Suppress-test
outcome table"), and there is one test per row of it plus the coverage line the last row
of that table requires.

Three things are asserted throughout, because they are what the table says rather than
what any one row says:

- **the Detail content set is the tree's, not the run's.** A row naming a feature that is
  not a Detail content feature of this document is ignored and reported as unused; a
  Detail content feature with no row is unresolved, never a pass;
- **one `RuleResult` per outcome.** `graded` refuses a second result in a bucket, so the
  rule cannot report one document twice in the same bucket of the report;
- **the coverage line.** Every reason the rule writes for a document that has a run ends
  with `<tested>/<present>`, and when the run left nothing else to explain the line is a
  `skip` of its own, so the count is never absent from the report.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from swreview.checks.rms import RULES
from swreview.checks.rms.groups import assign_groups
from swreview.checks.rms.part import PartTree, part_tree
from swreview.checks.rms.results import RuleResult
from swreview.checks.rms_types import load_table
from swreview.ir.models import Feature, SuppressTestRow
from tests.support.features import (
    FeatureSpec,
    PartSpec,
    feature,
    folder,
    rms_package,
    sketch_feature,
    suppress_row,
    suppress_run,
)

RULE = "rms.detail.individually_suppressible"
TABLE = load_table()
DOCUMENT = "doc:2"
CONFIGURATION = "Default"

REFERENCE, CONSTRUCTION, CORE, DETAIL, MODIFY, QUARANTINE = TABLE.groups
ROLE = "Detail"
"""What a reason calls the Detail group; `DETAIL` is the folder name in the tree."""


# --- helpers ----------------------------------------------------------------------


@dataclass(frozen=True)
class Row:
    """One planned row of a run, naming the feature it tested by tree name."""

    name: str
    outcome: str
    whats_wrong_count: int | None = None
    messages: Sequence[str] = ()
    messages_truncated: int = 0
    error: str | None = None


DEFAULT_SPECS: tuple[FeatureSpec, ...] = (
    folder(CORE, feature("Boss-Extrude1", "Extrusion")),
    folder(
        DETAIL,
        feature("Cut-Extrude1", "Cut"),
        feature("Cut-Extrude2", "Cut"),
        feature("Hole1", "HoleWzd"),
    ),
)
"""Three Detail content features and one Core feature, which is what most rows need."""


def _tree(specs: Sequence[FeatureSpec], suppress_test: Any = None) -> PartTree:
    package = rms_package(
        parts=[
            PartSpec(
                document_id=DOCUMENT,
                name="housing",
                features=specs,
                configuration=CONFIGURATION,
            )
        ],
        suppress_test=suppress_test,
    )
    rows = [row for row in package.features if row.document_id == DOCUMENT]
    return part_tree(DOCUMENT, rows, TABLE, assign_groups(rows, TABLE), package)


def build(
    rows: Sequence[Row] = (),
    *,
    specs: Sequence[FeatureSpec] = DEFAULT_SPECS,
    run_document_id: str = DOCUMENT,
    **run_kwargs: Any,
) -> PartTree:
    """A part tree whose package carries a run over the features `rows` names.

    The tree is built twice: once to learn the ids the builder allocated, and once with
    the run those ids let us write, because a row identifies its feature by `feature_id`.
    """
    by_name: Mapping[str, Feature] = {row.name: row for row in _tree(specs).rows}
    built: list[SuppressTestRow] = [
        suppress_row(
            by_name[row.name],
            row.outcome,  # type: ignore[arg-type]
            whats_wrong_count=row.whats_wrong_count,
            messages=row.messages,
            messages_truncated=row.messages_truncated,
            error=row.error,
        )
        for row in rows
    ]
    run = suppress_run(document_id=run_document_id, rows=built, group=DETAIL, **run_kwargs)
    return _tree(specs, suppress_test=run)


def graded(tree: PartTree) -> dict[str, RuleResult]:
    """The rule's results keyed by outcome, refusing two results in one bucket."""
    rule = RULES[RULE]
    assert rule.fn is not None
    keyed: dict[str, RuleResult] = {}
    for result in rule.fn(tree):
        assert result.rule_id == RULE
        assert result.document_id == DOCUMENT
        assert result.outcome not in keyed, f"two {result.outcome} results for one document"
        keyed[result.outcome] = result
    return keyed


def names(tree: PartTree, result: RuleResult) -> list[str]:
    return [tree.by_id[subject].name for subject in result.subjects]


def coverage(tested: int, present: int) -> str:
    return f"suppress-test tested {tested}/{present} {ROLE} content feature(s)"


# --- no run, or a run for another document ----------------------------------------


class TestNoRun:
    def test_without_a_run_every_detail_content_feature_is_unresolved(self) -> None:
        tree = _tree(DEFAULT_SPECS)
        keyed = graded(tree)

        assert list(keyed) == ["unresolved"]
        assert keyed["unresolved"].reason == "no suppress-test run"
        assert names(tree, keyed["unresolved"]) == ["Cut-Extrude1", "Cut-Extrude2", "Hole1"]

    def test_a_run_for_another_document_is_no_run(self) -> None:
        tree = build([], run_document_id="doc:9")
        keyed = graded(tree)

        assert list(keyed) == ["unresolved"]
        assert keyed["unresolved"].reason == "no suppress-test run"
        assert names(tree, keyed["unresolved"]) == ["Cut-Extrude1", "Cut-Extrude2", "Hole1"]

    def test_no_detail_group_skips_before_the_run_is_read(self) -> None:
        keyed = graded(_tree([folder(CORE, feature("Boss-Extrude1", "Extrusion"))]))

        assert list(keyed) == ["skip"]
        assert keyed["skip"].reason == f"no {ROLE} group"

    def test_an_empty_detail_group_skips(self) -> None:
        keyed = graded(
            _tree([folder(CORE, feature("Boss-Extrude1", "Extrusion")), folder(DETAIL)])
        )

        assert list(keyed) == ["skip"]
        assert keyed["skip"].reason == f"{ROLE} holds no content feature"


# --- the whole-run conditions -----------------------------------------------------


class TestWholeRunConditions:
    def test_a_run_in_another_configuration_is_unresolved_for_every_feature(self) -> None:
        tree = build(
            [Row("Cut-Extrude1", "ok"), Row("Cut-Extrude2", "ok"), Row("Hole1", "ok")],
            configuration="Simplified",
        )
        keyed = graded(tree)

        assert list(keyed) == ["unresolved"]
        assert names(tree, keyed["unresolved"]) == ["Cut-Extrude1", "Cut-Extrude2", "Hole1"]
        reason = keyed["unresolved"].reason
        assert reason is not None
        assert "Simplified" in reason
        assert CONFIGURATION in reason
        assert reason.endswith(coverage(3, 3))

    def test_restore_not_verified_is_unresolved_for_every_feature(self) -> None:
        tree = build(
            [
                Row("Cut-Extrude1", "ok"),
                Row("Cut-Extrude2", "rebuild_errors", 2),
                Row("Hole1", "ok"),
            ],
            restore_verified=False,
            unrestored_feature_ids=["feat:0003"],
        )
        keyed = graded(tree)

        assert list(keyed) == ["unresolved"]
        assert names(tree, keyed["unresolved"]) == ["Cut-Extrude1", "Cut-Extrude2", "Hole1"]
        reason = keyed["unresolved"].reason
        assert reason is not None
        assert reason.startswith("restore not verified")
        assert reason.endswith(coverage(3, 3))


# --- one row per outcome ----------------------------------------------------------


class TestRowOutcomes:
    def test_ok_rows_pass(self) -> None:
        tree = build([Row("Cut-Extrude1", "ok"), Row("Cut-Extrude2", "ok"), Row("Hole1", "ok")])
        keyed = graded(tree)

        assert sorted(keyed) == ["pass", "skip"]
        assert names(tree, keyed["pass"]) == ["Cut-Extrude1", "Cut-Extrude2", "Hole1"]
        assert keyed["skip"].reason == coverage(3, 3)
        assert keyed["skip"].subjects == []

    def test_rebuild_errors_fails_with_counts_and_messages_in_observed(self) -> None:
        tree = build(
            [
                Row("Cut-Extrude1", "ok"),
                Row(
                    "Cut-Extrude2",
                    "rebuild_errors",
                    whats_wrong_count=2,
                    messages=["Cut-Extrude2: dangling edge", "Hole1: face not found"],
                    messages_truncated=3,
                ),
                Row("Hole1", "ok"),
            ]
        )
        keyed = graded(tree)

        assert sorted(keyed) == ["fail", "pass", "skip"]
        assert names(tree, keyed["fail"]) == ["Cut-Extrude2"]
        assert names(tree, keyed["pass"]) == ["Cut-Extrude1", "Hole1"]

        result = keyed["fail"].result
        assert result is not None
        assert result.check == RULE
        assert result.status == "demonstrated"
        assert result.severity == "medium"
        assert "Cut-Extrude2" in result.observed
        assert "2 rebuild error(s)" in result.observed
        assert "dangling edge" in result.observed
        assert "face not found" in result.observed
        assert "+3 more" in result.observed
        assert len(result.inputs) == 1
        assert result.recommended_action

    def test_a_rebuild_errors_row_with_no_message_says_so(self) -> None:
        tree = build(
            [
                Row("Cut-Extrude1", "rebuild_errors", whats_wrong_count=1),
                Row("Cut-Extrude2", "ok"),
                Row("Hole1", "ok"),
            ]
        )
        result = graded(tree)["fail"].result

        assert result is not None
        assert "no message recorded" in result.observed

    def test_a_rebuild_errors_row_without_a_count_is_unresolved(self) -> None:
        """No count is a missing input, and a missing input is never a fail."""
        tree = build(
            [
                Row("Cut-Extrude1", "rebuild_errors", whats_wrong_count=None),
                Row("Cut-Extrude2", "ok"),
                Row("Hole1", "ok"),
            ]
        )
        keyed = graded(tree)

        assert sorted(keyed) == ["pass", "unresolved"]
        assert names(tree, keyed["unresolved"]) == ["Cut-Extrude1"]
        reason = keyed["unresolved"].reason
        assert reason is not None
        assert "rebuild_errors" in reason
        assert "no rebuild-error count" in reason

    def test_already_suppressed_and_truncated_skip_with_the_outcome_as_reason(self) -> None:
        tree = build(
            [
                Row("Cut-Extrude1", "already_suppressed"),
                Row("Cut-Extrude2", "truncated"),
                Row("Hole1", "ok"),
            ]
        )
        keyed = graded(tree)

        assert sorted(keyed) == ["pass", "skip"]
        assert names(tree, keyed["skip"]) == ["Cut-Extrude1", "Cut-Extrude2"]
        reason = keyed["skip"].reason
        assert reason is not None
        assert "Cut-Extrude1: already_suppressed" in reason
        assert "Cut-Extrude2: truncated" in reason
        assert reason.endswith(coverage(1, 3))

    def test_not_applied_and_aborted_are_unresolved_with_the_outcome_and_error(self) -> None:
        tree = build(
            [
                Row("Cut-Extrude1", "not_applied", error="SetSuppression2 returned false"),
                Row("Cut-Extrude2", "aborted", error="timed out after 600 s"),
                Row("Hole1", "ok"),
            ]
        )
        keyed = graded(tree)

        assert sorted(keyed) == ["pass", "unresolved"]
        assert names(tree, keyed["unresolved"]) == ["Cut-Extrude1", "Cut-Extrude2"]
        reason = keyed["unresolved"].reason
        assert reason is not None
        assert "Cut-Extrude1: not_applied: SetSuppression2 returned false" in reason
        assert "Cut-Extrude2: aborted: timed out after 600 s" in reason

    def test_an_outcome_row_without_an_error_reports_the_outcome_alone(self) -> None:
        tree = build(
            [Row("Cut-Extrude1", "aborted"), Row("Cut-Extrude2", "ok"), Row("Hole1", "ok")]
        )
        reason = graded(tree)["unresolved"].reason

        assert reason is not None
        assert "Cut-Extrude1: aborted;" in reason

    def test_a_detail_content_feature_with_no_row_is_unresolved_as_not_tested(self) -> None:
        tree = build([Row("Cut-Extrude1", "ok"), Row("Cut-Extrude2", "ok")])
        keyed = graded(tree)

        assert sorted(keyed) == ["pass", "unresolved"]
        assert names(tree, keyed["pass"]) == ["Cut-Extrude1", "Cut-Extrude2"]
        assert names(tree, keyed["unresolved"]) == ["Hole1"]
        reason = keyed["unresolved"].reason
        assert reason is not None
        assert "Hole1: not tested" in reason
        assert reason.endswith(coverage(2, 3))

    def test_a_truncated_row_does_not_count_as_tested(self) -> None:
        tree = build(
            [
                Row("Cut-Extrude1", "ok"),
                Row("Cut-Extrude2", "truncated"),
                Row("Hole1", "truncated"),
            ]
        )
        reason = graded(tree)["skip"].reason

        assert reason is not None
        assert reason.endswith(coverage(1, 3))

    def test_an_already_suppressed_row_does_not_count_as_tested(self) -> None:
        """`<tested>` counts answers, not rows the run walked past.

        The feature was suppressed before the run, so the run learned nothing about
        whether it can be suppressed alone; counting it would let the one line the
        outcome table requires say `skipped` and `covered` about the same feature.
        """
        tree = build(
            [
                Row("Cut-Extrude1", "ok"),
                Row("Cut-Extrude2", "already_suppressed"),
                Row("Hole1", "already_suppressed"),
            ]
        )
        reason = graded(tree)["skip"].reason

        assert reason is not None
        assert reason.endswith(coverage(1, 3))

    def test_not_applied_and_aborted_rows_do_not_count_as_tested(self) -> None:
        """Neither outcome produced an answer either, and both stay unresolved."""
        tree = build(
            [
                Row("Cut-Extrude1", "not_applied", error="SetSuppression2 returned false"),
                Row("Cut-Extrude2", "aborted", error="timed out after 600 s"),
                Row("Hole1", "rebuild_errors", whats_wrong_count=1, messages=["Hole1: broken"]),
            ]
        )
        reason = graded(tree)["unresolved"].reason

        assert reason is not None
        assert reason.endswith(coverage(1, 3))


# --- rows the tree does not account for, and the coverage line --------------------


class TestCoverage:
    SPECS: tuple[FeatureSpec, ...] = (
        folder(CORE, feature("Boss-Extrude1", "Extrusion")),
        folder(
            DETAIL,
            sketch_feature("Sketch1", consumers=()),
            feature("Cut-Extrude1", "Cut"),
        ),
    )

    def test_a_row_for_a_feature_outside_detail_is_ignored_and_named_unused(self) -> None:
        tree = build(
            [Row("Sketch1", "ok"), Row("Cut-Extrude1", "ok"), Row("Boss-Extrude1", "ok")],
            specs=self.SPECS,
        )
        keyed = graded(tree)

        assert sorted(keyed) == ["pass", "skip"]
        assert names(tree, keyed["pass"]) == ["Sketch1", "Cut-Extrude1"]
        reason = keyed["skip"].reason
        assert reason is not None
        assert reason.startswith(coverage(2, 2))
        assert "unused" in reason
        assert "Boss-Extrude1" in reason

    def test_an_unused_row_is_reported_even_when_every_graded_feature_passes(self) -> None:
        """Nothing else writes a reason here, so the coverage line is the whole report."""
        tree = build(
            [Row("Sketch1", "ok"), Row("Cut-Extrude1", "ok"), Row("Boss-Extrude1", "aborted")],
            specs=self.SPECS,
        )
        keyed = graded(tree)

        assert sorted(keyed) == ["pass", "skip"]
        assert keyed["skip"].subjects == []
        reason = keyed["skip"].reason
        assert reason is not None
        assert "Boss-Extrude1" in reason

    def test_the_coverage_line_ends_every_reason_the_rule_writes(self) -> None:
        tree = build(
            [
                Row("Sketch1", "already_suppressed"),
                Row("Cut-Extrude1", "aborted", error="timed out"),
            ],
            specs=self.SPECS,
        )
        keyed = graded(tree)

        assert sorted(keyed) == ["skip", "unresolved"]
        for outcome in ("skip", "unresolved"):
            reason = keyed[outcome].reason
            assert reason is not None, outcome
            assert reason.endswith(coverage(0, 2)), outcome
