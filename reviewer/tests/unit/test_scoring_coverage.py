"""The expected-coverage reader's tests (feature 014, `contracts/scoring.md` sections 4 and 11).

This half holds `goal_readings` (T075; plan decisions RF-23, SR-11): the state decision the
report's goal lines are built from, extracted so the scorer reads a goal's `GoalReason` key and
never the words file's display text (`words.goal_reasons`, "evidence missing" and the like).
Each reading here is the one `_goal_line` decided before the extraction, on sessions built as
data, with the row it was taken from. That `goal_lines`' output does not move is the report's own
tests (`test_review_goals.py`, `test_finding_groups.py` and the fixtures), unchanged.

The scorer's half (T086, at the end; US3-3, US3-4; FR-018, D6): `scorecard.coverage_mismatches`
reads each expected-coverage entry's goal through `goal_readings`, by section 4's table, and lists
an entry whose reading is outside its `statuses`, naming the entry, the item and the reading.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from swreview.benchmark import scorecard
from swreview.benchmark.answer_key_model import ExpectedCoverage
from swreview.benchmark.scorecard import CoverageMismatch
from swreview.findings import Finding
from swreview.report import finding_groups
from swreview.report.finding_groups import GoalReading, goal_lines, goal_readings
from swreview.report.session import ReviewSession
from swreview.report.summary import load_words
from tests.support.attention import CoverageRow, CoverageSpec, FindingSpec
from tests.unit.test_answer_key import coverage
from tests.unit.test_attention import spec
from tests.unit.test_review_summary import session_of


def readings_of(
    name: str, specs: Sequence[FindingSpec] = (), **buckets: object
) -> tuple[ReviewSession, list[GoalReading]]:
    """A session built as data, named so its id is stable, and its goal readings."""
    session = session_of(name, list(specs), CoverageSpec(**buckets))  # type: ignore[arg-type]
    return session, goal_readings(session, load_words())


def reading_of(readings: Sequence[GoalReading], goal: str) -> GoalReading:
    return next(one for one in readings if one.goal.id == goal)


def row(check: str, reason: str | None = None) -> CoverageRow:
    return CoverageRow(check=check, reason=reason or f"{check} was recorded for this goal.")


def taken(one: GoalReading) -> tuple[str, str | None]:
    return (one.state, one.reason)


# --- one reading per goal, its reason the key ----------------------------------------------------


def test_there_is_one_reading_per_goal_in_the_words_files_order() -> None:
    _, readings = readings_of("readings-order")

    assert [one.goal for one in readings] == load_words().goals


def test_a_reading_is_a_frozen_value() -> None:
    _, readings = readings_of("readings-frozen")

    with pytest.raises(AttributeError):
        readings[0].state = "checked"  # type: ignore[misc]


def mixed_session() -> tuple[ReviewSession, list[GoalReading]]:
    """One goal for each state and each reason, the rest with nothing (`no_check`)."""
    return readings_of(
        "readings-mixed",
        [spec("hole.coaxiality")],
        checked=[row("provenance")],
        unresolved=[row("interfaces.fit", "the fit has no limits.")],
        skipped=[row("fasteners", "no fastener in the package.")],
        failed=[row("interference", "the tool timed out.")],
        out_of_scope=[row("standards.part.material_assigned", "no part document was graded.")],
    )


def test_each_reason_is_the_goal_reason_key_and_never_the_words_files_text() -> None:
    _, readings = mixed_session()

    assert {one.goal.id: taken(one) for one in readings} == {
        "interference": ("not_reached", "failed"),
        "fasteners": ("not_reached", "skipped"),
        "hole_alignment": ("issues", None),
        "fits_and_stacks": ("not_reached", "unresolved"),
        "tool_access": ("not_reached", "no_check"),
        "mass_and_material": ("not_applicable", "out_of_scope"),
        "hygiene": ("checked", None),
        "standards": ("not_reached", "no_check"),
        "drawings": ("not_reached", "no_check"),
        "modelling_practice": ("not_reached", "no_check"),
    }
    display = {text for key, text in load_words().goal_reasons.items() if text != key}
    assert display == {"evidence missing", "a check failed", "out of scope", "no check ran"}
    assert not display & {one.reason for one in readings}


def test_the_goal_lines_are_built_from_the_readings() -> None:
    """Each line's state, its reason's words and its detail are its goal's reading's."""
    session, readings = mixed_session()
    words = load_words()

    for one, line in zip(readings, goal_lines(session, words), strict=True):
        assert (line.goal, line.title, line.state) == (one.goal.id, one.goal.title, one.state)
        assert line.reason == (None if one.reason is None else words.goal_reasons[one.reason])
        assert line.detail == (None if one.row is None else one.row.reason)


def test_each_goal_s_findings_other_than_a_pass_are_filtered_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reading's state and the line's findings count read one list: `goal_lines` and
    `goal_readings` each filter a goal's findings once, and a line counts what its reading
    read."""
    session, readings = mixed_session()
    words = load_words()
    filtered: list[int] = []
    real = finding_groups._issues

    def spy(mapped: Sequence[Finding]) -> list[Finding]:
        issues = real(mapped)
        filtered.append(len(issues))
        return issues

    monkeypatch.setattr(finding_groups, "_issues", spy)

    lines = goal_lines(session, words)
    assert len(filtered) == len(lines)
    assert [line.findings for line in lines] == filtered
    filtered.clear()
    assert goal_readings(session, words) == readings
    assert len(filtered) == len(readings)


# --- each reading _goal_line decides -------------------------------------------------------------


def test_a_finding_other_than_a_pass_reads_issues_with_no_reason_and_no_row() -> None:
    _, readings = readings_of(
        "readings-issues",
        [spec("hole.coaxiality"), spec("hole.coaxiality", status="checked_within_scope")],
        unresolved=[row("holes.alignment", "the joint map was not read.")],
    )
    one = reading_of(readings, "hole_alignment")

    assert (*taken(one), one.row) == ("issues", None, None)


def test_a_suspected_finding_alone_reads_issues() -> None:
    _, readings = readings_of(
        "readings-suspected", [spec("interference.static", status="suspected")]
    )

    assert taken(reading_of(readings, "interference")) == ("issues", None)


def test_a_checked_row_reads_checked_with_no_reason_and_no_row() -> None:
    _, readings = readings_of("readings-checked", checked=[row("interference")])
    one = reading_of(readings, "interference")

    assert (*taken(one), one.row) == ("checked", None, None)


def test_a_pass_alone_reads_checked_and_not_issues() -> None:
    _, readings = readings_of(
        "readings-pass", [spec("interference.static", status="checked_within_scope")]
    )
    one = reading_of(readings, "interference")

    assert (*taken(one), one.row) == ("checked", None, None)


@pytest.mark.parametrize("bucket", ["unresolved", "skipped", "failed"])
@pytest.mark.parametrize("check", ["interfaces.fit", "fit.clearance"], ids=["closeout", "rule"])
def test_a_goals_only_row_in_a_not_reached_bucket_reads_not_reached_with_that_bucket(
    bucket: str, check: str
) -> None:
    session, readings = readings_of(
        f"readings-{bucket}-{check}", **{bucket: [row(check, f"the {bucket} sentence.")]}
    )
    one = reading_of(readings, "fits_and_stacks")

    assert taken(one) == ("not_reached", bucket)
    assert one.row is getattr(session.coverage, bucket)[0]


def test_a_closeout_row_on_a_goal_item_is_taken_before_a_rule_row() -> None:
    """The rule row sits in an earlier bucket; the goal's own item still speaks first."""
    session, readings = readings_of(
        "readings-closeout-first",
        unresolved=[row("standards.assembly.one_fixed", "the assembly has no fixed part.")],
        failed=[row("standards.release", "the release check failed.")],
    )
    one = reading_of(readings, "standards")

    assert taken(one) == ("not_reached", "failed")
    assert one.row is session.coverage.failed[0]


def test_a_closeout_row_beats_a_checked_rule_row() -> None:
    session, readings = readings_of(
        "readings-closeout-checked",
        checked=[row("rms.sketches.fully_defined")],
        skipped=[row("modeling.resilience", "the part trees were not read.")],
    )
    one = reading_of(readings, "modelling_practice")

    assert taken(one) == ("not_reached", "skipped")
    assert one.row is session.coverage.skipped[0]


def test_the_closeout_row_is_the_first_in_unresolved_skipped_failed_order() -> None:
    session, readings = readings_of(
        "readings-closeout-order",
        skipped=[row("interfaces.stack", "the stack was skipped.")],
        failed=[row("interfaces.fit", "the fit failed.")],
        unresolved=[row("interfaces.stack", "the stack has no limits.")],
    )
    one = reading_of(readings, "fits_and_stacks")

    assert taken(one) == ("not_reached", "unresolved")
    assert one.row is session.coverage.unresolved[0]


def test_no_row_and_no_finding_reads_not_reached_no_check_with_no_row() -> None:
    _, readings = readings_of("readings-nothing")

    assert all((*taken(one), one.row) == ("not_reached", "no_check", None) for one in readings)


def test_only_out_of_scope_rows_read_not_applicable_from_the_goals_first_row() -> None:
    """The first out-of-scope row of the goal, not of the bucket: the drawings row is not its."""
    session, readings = readings_of(
        "readings-out-of-scope",
        out_of_scope=[
            row("standards.drawing.revision_matches", "no drawing was supplied."),
            row("standards.part.material_assigned", "no part document was graded."),
            row("mass.total", "no mass was asked for."),
        ],
    )
    one = reading_of(readings, "mass_and_material")

    assert taken(one) == ("not_applicable", "out_of_scope")
    assert one.row is session.coverage.out_of_scope[1]


def test_an_unresolved_rule_row_beside_an_out_of_scope_one_reads_not_reached() -> None:
    """The case the contract's four rows leave open: the rule row speaks, not the out of scope."""
    session, readings = readings_of(
        "readings-rule-beside-out-of-scope",
        unresolved=[row("standards.part.material_assigned", "one part has no material.")],
        out_of_scope=[row("standards.part.material_assigned", "the assembly has none.")],
    )
    one = reading_of(readings, "mass_and_material")

    assert taken(one) == ("not_reached", "unresolved")
    assert one.row is session.coverage.unresolved[0]


# --- the scorer's reading of a goal (scoring.md 4; T086) ----------------------------------------

INTERFERENCE = ExpectedCoverage.model_validate(coverage())
"""`CV-1`: interference expected unresolved or skipped (R-5, US3-3)."""


def mismatches_of(
    name: str,
    entries: Sequence[ExpectedCoverage] = (INTERFERENCE,),
    specs: Sequence[FindingSpec] = (),
    **buckets: object,
) -> list[CoverageMismatch]:
    session, _ = readings_of(name, specs, **buckets)
    return scorecard.coverage_mismatches(session, entries, load_words())


def mismatch(entry: str, item: str, read: str) -> CoverageMismatch:
    return CoverageMismatch.model_validate({"entry": entry, "item": item, "read": read})


def test_r_5_interference_marked_checked_is_one_mismatch_naming_the_item() -> None:
    """The off arm's model marks interference checked: read `checked` (US3-3)."""
    assert mismatches_of("cv-r5-checked", checked=[row("interference")]) == [
        mismatch("CV-1", "interference", "checked")
    ]


@pytest.mark.parametrize(
    "buckets",
    [
        {"skipped": [row("coverage.prerun.interference", "no part was read.")]},
        {"unresolved": [row("interference", "the pins were not read.")]},
    ],
    ids=["the pre-run's skipped row", "finalization's unresolved row"],
)
def test_the_on_arm_s_rows_read_within_the_entry(buckets: dict[str, object]) -> None:
    assert mismatches_of("cv-r5-" + next(iter(buckets)), **buckets) == []


def test_an_item_whose_only_row_failed_reads_unresolved() -> None:
    """US3-4."""
    failed = {"failed": [row("interference", "the tool timed out.")]}
    expects_checked = ExpectedCoverage.model_validate(coverage(statuses=["checked"]))

    assert mismatches_of("cv-failed", **failed) == []
    assert mismatches_of("cv-failed-checked", (expects_checked,), **failed) == [
        mismatch("CV-1", "interference", "unresolved")
    ]


def test_no_row_and_no_finding_reads_not_reported_always_a_mismatch() -> None:
    every = ExpectedCoverage.model_validate(
        coverage(statuses=["checked", "unresolved", "skipped", "out_of_scope"])
    )

    assert mismatches_of("cv-nothing", (every,)) == [
        mismatch("CV-1", "interference", "not_reported")
    ]


def test_out_of_scope_reads_out_of_scope() -> None:
    entry = ExpectedCoverage.model_validate(
        coverage(item="mass.material", statuses=["out_of_scope"])
    )
    checked = ExpectedCoverage.model_validate(coverage(item="mass.material", statuses=["checked"]))
    out = {"out_of_scope": [row("mass.material", "no mass was asked for.")]}

    assert mismatches_of("cv-out", (entry,), **out) == []
    assert mismatches_of("cv-out-checked", (checked,), **out) == [
        mismatch("CV-1", "mass.material", "out_of_scope")
    ]


def test_a_goal_holding_a_finding_reads_checked() -> None:
    """`issues` reads `checked`: the item was examined (SR-11)."""
    entry = ExpectedCoverage.model_validate(coverage(item="holes.alignment", statuses=["skipped"]))

    assert mismatches_of("cv-issues", (entry,), [spec("hole.coaxiality")]) == [
        mismatch("CV-1", "holes.alignment", "checked")
    ]


def test_interfaces_fit_is_read_through_the_fits_and_stacks_goal() -> None:
    """One expectation per goal: a row on `interfaces.stack` sets the goal's one state."""
    entry = ExpectedCoverage.model_validate(coverage(item="interfaces.fit", statuses=["checked"]))

    assert mismatches_of(
        "cv-fits", (entry,), unresolved=[row("interfaces.stack", "the stack has no limits.")]
    ) == [mismatch("CV-1", "interfaces.fit", "unresolved")]


def test_a_coverage_prerun_fastener_joints_row_is_read_by_no_goal() -> None:
    """Of the pre-run's `coverage.prerun.<family>` rows only interference and standards are goal
    items (research §8.4): the fasteners goal reads nothing, so it is not reported."""
    entry = ExpectedCoverage.model_validate(coverage(item="fasteners", statuses=["skipped"]))

    assert mismatches_of(
        "cv-fastener-joints",
        (entry,),
        skipped=[row("coverage.prerun.fastener_joints", "no joint was placed.")],
    ) == [mismatch("CV-1", "fasteners", "not_reported")]


@pytest.mark.parametrize(
    ("buckets", "read"),
    [
        ({"checked": [row("interference")]}, "checked"),
        ({"unresolved": [row("interference")]}, "unresolved"),
        ({"failed": [row("interference")]}, "unresolved"),
        ({"skipped": [row("interference")]}, "skipped"),
        ({"out_of_scope": [row("interference")]}, "out_of_scope"),
        ({}, "not_reported"),
    ],
    ids=["checked", "unresolved", "failed", "skipped", "out_of_scope", "no_check"],
)
def test_every_goal_reading_reads_as_section_4_s_table_says(
    buckets: dict[str, object], read: str
) -> None:
    _, readings = readings_of("cv-table-" + read + "-" + "-".join(buckets), **buckets)

    assert scorecard.coverage_read(reading_of(readings, "interference")) == read


def test_each_entry_is_read_in_key_order() -> None:
    entries = (
        ExpectedCoverage.model_validate(coverage(id="CV-1", item="hygiene", statuses=["checked"])),
        ExpectedCoverage.model_validate(coverage(id="CV-2", statuses=["checked"])),
    )

    assert mismatches_of("cv-order", entries) == [
        mismatch("CV-1", "hygiene", "not_reported"),
        mismatch("CV-2", "interference", "not_reported"),
    ]
