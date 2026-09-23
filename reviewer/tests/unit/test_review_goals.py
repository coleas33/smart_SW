"""The goal lines of the summary (feature 009 T010), against `contracts/review-summary.md` 3.

One line per check goal says whether the review reached it, in a few words with the
recorded sentence behind them (research R2.4). The rules this pins:

- **a check belongs to one goal**: the goal whose `items` name it, else the goal with the
  longest prefix it starts with - `fastener.head_clearance` is tool access, not fasteners;
- **the state is a fixed precedence**, first match winning: issues found, then not reached
  (a close-out row of the goal's items is unresolved, skipped or failed, or nothing speaks
  for the goal at all), then checked, then not applicable;
- **not reached before checked**, so a run whose own close-out says an item was not closed
  never reads "checked" because one rule row was;
- **the reason is a word, the detail the whole sentence**, verbatim and never cut.

One case the contract's four rows leave open is closed here and in section 3: a goal whose
only rows are rule rows that are unresolved, skipped or failed (and perhaps out of scope)
is `not_reached`, its reason from the first such row, rather than no state at all.
"""

from __future__ import annotations

import pytest

from swreview.report.summary import GoalLine, goal_of, load_words
from tests.support.attention import CoverageRow, CoverageSpec
from tests.unit.test_attention import spec
from tests.unit.test_review_summary import session_of, summary_of

GOAL_IDS = [goal.id for goal in load_words().goals]

LONG_REASON = (
    "The package carries no drawing for any of the four parts, so no fit class, tolerance "
    "or surface finish could be read; the shaft and bore diameters are modelled at nominal "
    "size only, and the mates that would locate the pins name faces whose tolerances live "
    "on drawings that were not supplied. Supply the part drawings and the fits can be "
    "computed against their limits rather than guessed at from nominal geometry, today."
)


def line(summary: object, goal: str) -> GoalLine:
    return next(one for one in summary.goals if one.goal == goal)  # type: ignore[attr-defined]


def goal_line(name: str, goal: str, specs: list | None = None, **buckets: object) -> GoalLine:
    session = session_of(name, specs or [], CoverageSpec(**buckets))  # type: ignore[arg-type]
    return line(summary_of(session), goal)


def row(check: str, reason: str | None = None) -> CoverageRow:
    return CoverageRow(check=check, reason=reason or f"{check} was recorded for this goal.")


def state_of(one: GoalLine) -> tuple[str, str, str | None, str | None]:
    return (one.state, one.state_label, one.reason, one.detail)


# --- 1. which goal a check belongs to --------------------------------------------------------


@pytest.mark.parametrize(
    ("check", "goal"),
    [
        ("fastener.head_clearance", "tool_access"),
        ("fastener.head_fit", "tool_access"),
        ("fastener.bottoming", "fasteners"),
        ("standards.drawing.revision_matches", "drawings"),
        ("standards.part.material_assigned", "mass_and_material"),
        ("standards.assembly.one_fixed", "hygiene"),
        ("rms.drawing.model_items_preferred", "drawings"),
        ("rms.sketches.fully_defined", "modelling_practice"),
        ("interference.static", "interference"),
        ("hole.coaxiality", "hole_alignment"),
        ("fit.clearance", "fits_and_stacks"),
        ("stack.gap", "fits_and_stacks"),
        ("mass.total", "mass_and_material"),
        ("provenance.version", "hygiene"),
        ("drawing.manufacturing_inputs", "drawings"),
    ],
)
def test_a_check_belongs_to_the_goal_of_its_longest_prefix(check: str, goal: str) -> None:
    found = goal_of(check, load_words().goals)
    assert found is not None and found.id == goal


@pytest.mark.parametrize(
    ("check", "goal"),
    [
        ("interference", "interference"),
        ("coverage.prerun.interference", "interference"),
        ("fasteners", "fasteners"),
        ("holes.alignment", "hole_alignment"),
        ("interfaces.fit", "fits_and_stacks"),
        ("interfaces.stack", "fits_and_stacks"),
        ("provenance", "hygiene"),
        ("standards.release", "hygiene"),
        ("coverage.prerun.standards", "hygiene"),
        ("modeling.resilience", "modelling_practice"),
    ],
)
def test_a_close_out_item_belongs_to_the_goal_that_names_it(check: str, goal: str) -> None:
    found = goal_of(check, load_words().goals)
    assert found is not None and found.id == goal


@pytest.mark.parametrize("check", ["coverage.closeout", "coverage.evidence_request", "tool.x", ""])
def test_a_check_no_goal_names_belongs_to_none(check: str) -> None:
    assert goal_of(check, load_words().goals) is None


# --- 2. each state ------------------------------------------------------------------------------


def test_a_demonstrated_finding_gives_issues_with_its_count() -> None:
    specs = [spec("hole.coaxiality"), spec("hole.coaxiality", status="checked_within_scope")]
    found = goal_line("issues", "hole_alignment", specs)

    assert state_of(found) == ("issues", "issues found", None, None)
    assert found.findings == 1, "a within-scope finding is not an issue"


def test_an_unresolved_close_out_row_gives_not_reached_with_its_sentence_uncut() -> None:
    assert len(LONG_REASON) > 400
    found = goal_line(
        "unresolved", "fits_and_stacks", unresolved=[row("interfaces.fit", LONG_REASON)]
    )

    assert state_of(found) == ("not_reached", "not reached", "evidence missing", LONG_REASON)
    assert found.findings == 0


def test_a_skipped_close_out_row_gives_not_reached_skipped() -> None:
    found = goal_line(
        "skipped", "fasteners", skipped=[row("fasteners", "no fastener in the package.")]
    )

    assert state_of(found) == (
        "not_reached",
        "not reached",
        "skipped",
        "no fastener in the package.",
    )


def test_a_failed_close_out_row_gives_not_reached_a_check_failed() -> None:
    found = goal_line("failed", "interference", failed=[row("interference", "the tool timed out.")])

    assert state_of(found) == (
        "not_reached",
        "not reached",
        "a check failed",
        "the tool timed out.",
    )


def test_the_close_out_reason_is_the_first_row_in_unresolved_skipped_failed_order() -> None:
    found = goal_line(
        "precedence",
        "fits_and_stacks",
        skipped=[row("interfaces.stack", "the stack was skipped.")],
        failed=[row("interfaces.fit", "the fit failed.")],
        unresolved=[row("interfaces.stack", "the stack has no limits.")],
    )

    assert (found.reason, found.detail) == ("evidence missing", "the stack has no limits.")


def test_nothing_at_all_gives_not_reached_no_check_ran() -> None:
    found = goal_line("nothing", "tool_access")

    assert state_of(found) == ("not_reached", "not reached", "no check ran", None)


def test_a_checked_row_gives_checked() -> None:
    found = goal_line("checked", "interference", checked=[row("interference")])

    assert state_of(found) == ("checked", "checked, no issue", None, None)


def test_a_checked_rule_row_gives_checked() -> None:
    found = goal_line("checked-rule", "hygiene", checked=[row("standards.assembly.one_fixed")])

    assert state_of(found) == ("checked", "checked, no issue", None, None)


def test_only_a_within_scope_finding_gives_checked() -> None:
    specs = [spec("interference.static", status="checked_within_scope")]
    found = goal_line("within", "interference", specs)

    assert state_of(found) == ("checked", "checked, no issue", None, None)
    assert found.findings == 0


def test_only_out_of_scope_rows_give_not_applicable() -> None:
    found = goal_line(
        "out-of-scope",
        "mass_and_material",
        out_of_scope=[row("standards.part.material_assigned", "no part document was graded.")],
    )

    assert state_of(found) == (
        "not_applicable",
        "not applicable",
        "out of scope",
        "no part document was graded.",
    )


def test_an_unresolved_close_out_row_beats_a_checked_rule_row() -> None:
    """Not reached before checked: the run's own close-out outranks one passing rule."""
    found = goal_line(
        "closeout-beats-checked",
        "modelling_practice",
        checked=[row("rms.sketches.fully_defined")],
        unresolved=[row("modeling.resilience", "the part trees were not read.")],
    )

    assert state_of(found) == (
        "not_reached",
        "not reached",
        "evidence missing",
        "the part trees were not read.",
    )


def test_a_skipped_rule_row_beside_a_checked_one_still_reads_checked() -> None:
    """Only a close-out row of the goal's items can say the goal was not reached."""
    found = goal_line(
        "rule-skip",
        "modelling_practice",
        checked=[row("rms.sketches.fully_defined")],
        skipped=[row("rms.core.shell_last", "the part has no shell.")],
    )

    assert found.state == "checked"


def test_findings_with_no_coverage_row_give_issues() -> None:
    """The interference shape where the family wrote findings and no coverage row."""
    specs = [spec("interference.static"), spec("interference.static", status="suspected")]
    found = goal_line("no-row", "interference", specs)

    assert (found.state, found.findings) == ("issues", 2)


def test_the_skipped_prerun_interference_row_gives_not_reached_with_its_sentence() -> None:
    sentence = "Live interference detection was not run before the review: no bridge was attached."
    found = goal_line(
        "prerun", "interference", skipped=[row("coverage.prerun.interference", sentence)]
    )

    assert state_of(found) == ("not_reached", "not reached", "skipped", sentence)


def test_issues_beat_every_close_out_row() -> None:
    found = goal_line(
        "issues-first",
        "interference",
        [spec("interference.static")],
        unresolved=[row("interference", "truncated pairs were left.")],
    )

    assert state_of(found) == ("issues", "issues found", None, None)


# --- 3. the case the four rows leave open --------------------------------------------------


def test_an_unresolved_rule_row_beside_an_out_of_scope_one_is_not_reached() -> None:
    found = goal_line(
        "rule-unresolved",
        "mass_and_material",
        unresolved=[row("standards.part.material_assigned", "one part has no material.")],
        out_of_scope=[row("standards.part.material_assigned", "the assembly has none.")],
    )

    assert state_of(found) == (
        "not_reached",
        "not reached",
        "evidence missing",
        "one part has no material.",
    )


def test_only_a_skipped_rule_row_is_not_reached_skipped() -> None:
    found = goal_line(
        "rule-skipped", "hygiene", skipped=[row("standards.assembly.one_fixed", "no assembly.")]
    )

    assert state_of(found) == ("not_reached", "not reached", "skipped", "no assembly.")


# --- 4. one goal per row, and the table's order ------------------------------------------------


def test_a_coverage_row_counts_for_its_one_goal_only() -> None:
    """`standards.drawing.*` is drawings; it does not also speak for hygiene."""
    session = session_of(
        "one-goal",
        [],
        CoverageSpec(out_of_scope=[row("standards.drawing.revision_matches", "no drawing.")]),
    )
    summary = summary_of(session)

    assert line(summary, "drawings").state == "not_applicable"
    assert state_of(line(summary, "hygiene")) == (
        "not_reached",
        "not reached",
        "no check ran",
        None,
    )


def test_the_goal_lines_come_in_table_order_with_the_words_files_labels() -> None:
    summary = summary_of(session_of("order", []))
    states = load_words().goal_states

    assert [one.goal for one in summary.goals] == GOAL_IDS
    assert [one.title for one in summary.goals] == [goal.title for goal in load_words().goals]
    assert all(one.state_label == states[one.state] for one in summary.goals)
