"""The per-run tool-name histogram, and the lever 2 gate that reads it (T057, T059).

The token count is arithmetic: it falls out of the trim and nobody has to watch it. **The
thing that actually needs watching is which tool the model picks.** A trim that changed the
answer will usually show first as a call-pattern change - the model that used to call
`check_rms_part` once with no argument starting to call it per document, or a check tool
dropping out of its repertoire altogether - and none of that moves `valid_findings`,
`missed_known_defects` or the token totals enough for the general gate to fire. Whether it
happens at all is UNVERIFIED; this histogram is what makes it observable.

Two surfaces, one number:

- `PackageScore.tool_calls_by_name` is the histogram of one package's `session.steps`, in
  the scorecard beside the tokens and the findings, so it survives the run directory and
  can be read back long after the process is gone.
- the ledger's **lever-specific counter** column reads those histograms per arm: how many
  distinct tool names each arm called, and, by name, every tool some off-run called that
  **no** on-run called at all. That list is T059's gate, and it is a list rather than a
  count because "recall fell by one tool" is not a sentence an owner can act on.

`session.steps` records every call the model made, failed calls included, because the
question is which tool it *picked*, not which call succeeded.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from swreview.benchmark.compare import compare_runs
from swreview.benchmark.scorecard import tool_histogram
from swreview.report.session import InvestigationStep, ReviewSession, Timing
from tests.support.contracts import contract_validator
from tests.support.packages import build_package
from tests.support.studies import PackageSpec, RunSpec, write_run
from tests.unit.test_benchmark_compare import lever_row
from tests.unit.test_scorecard_usage import score

TRIM = "trim_tool_descriptions"

STARTED_AT = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)
PACKAGE = build_package()


def step(index: int, tool: str, *, status: str = "ok") -> InvestigationStep:
    return InvestigationStep(
        index=index,
        tool=tool,
        arguments={},
        result_summary="ok",
        status=status,  # type: ignore[arg-type]
        error="boom" if status == "error" else None,
        elapsed_s=0.1,
    )


def session_with(*tools: str) -> ReviewSession:
    """A session whose steps are exactly these calls, in this order."""
    return ReviewSession(
        session_id=uuid5(NAMESPACE_URL, "histogram"),
        package_id=PACKAGE.package_id,
        design_id=PACKAGE.design.design_id,
        started_at=STARTED_AT,
        model="gpt-5.6",
        steps=[step(index, tool) for index, tool in enumerate(tools)],
        timing=Timing(
            baseline_minutes=None,
            assisted_supervision_minutes=0.0,
            assisted_verification_minutes=0.0,
            false_alarm_handling_minutes=0.0,
            unattended_runtime_minutes=0.0,
        ),
    )


# --- the histogram itself -------------------------------------------------------------


def test_the_histogram_counts_every_step_by_tool_name() -> None:
    session = session_with("list_holes", "check_fit", "list_holes", "list_holes")

    assert tool_histogram(session) == {"list_holes": 3, "check_fit": 1}


def test_the_histogram_is_ordered_most_called_first_then_by_name() -> None:
    """Deterministic order, so two runs of one arm produce comparable JSON."""
    session = session_with("b_tool", "a_tool", "c_tool", "c_tool")

    assert list(tool_histogram(session)) == ["c_tool", "a_tool", "b_tool"]


def test_a_session_that_called_nothing_has_an_empty_histogram() -> None:
    """Empty, not absent: a run that called no tool is a measurement worth keeping."""
    assert tool_histogram(session_with()) == {}


def test_a_failed_call_still_counts_towards_the_tool_that_was_picked() -> None:
    """The question is which tool the model chose, not which call came back clean."""
    session = session_with("check_fit")
    session.steps.append(step(1, "check_fit", status="error"))

    assert tool_histogram(session) == {"check_fit": 2}


# --- on the scorecard -------------------------------------------------------------------


def test_the_package_score_carries_the_histogram_of_its_session(tmp_path: Path) -> None:
    steps = [step(0, "list_holes"), step(1, "check_fit"), step(2, "list_holes")]

    scorecard = score(tmp_path, steps=steps)

    assert scorecard.per_package[0].tool_calls_by_name == {"list_holes": 2, "check_fit": 1}


def test_a_package_whose_session_called_nothing_scores_an_empty_histogram(
    tmp_path: Path,
) -> None:
    assert score(tmp_path).per_package[0].tool_calls_by_name == {}


def test_the_scorecard_still_validates_against_the_contract(tmp_path: Path) -> None:
    """`tool_calls_by_name` is an additive property with its own entry in `required`."""
    scorecard = score(tmp_path, steps=[step(0, "list_holes")])

    contract_validator("scorecard.schema.json").validate(json.loads(scorecard.model_dump_json()))


# --- in the ledger -----------------------------------------------------------------------

REPERTOIRE = ("check_fit", "check_rms_part", "list_holes")


def study(
    off_tools: tuple[str, ...] = REPERTOIRE, on_tools: tuple[str, ...] = REPERTOIRE
) -> list[RunSpec]:
    """Three off runs and three on runs of lever 2, each calling the tools it is given."""
    return [
        RunSpec(
            run=f"{arm}-{rep}",
            arm=arm,
            rep=rep,
            lever=TRIM,
            packages=(PackageSpec(tool_names=tools, tool_calls=len(tools) * 2),),
        )
        for arm, tools in (("off", off_tools), ("on", on_tools))
        for rep in (1, 2, 3)
    ]


def ledger_row(tmp_path: Path, specs: list[RunSpec], lever: str = TRIM):  # type: ignore[no-untyped-def]
    dirs = [write_run(tmp_path, spec) for spec in specs]
    return lever_row(compare_runs(dirs), lever)


def test_the_lever_2_counter_is_the_histogram_and_names_itself(tmp_path: Path) -> None:
    """The column `LEVER_COUNTERS` promised lands here rather than staying unknown."""
    row = ledger_row(tmp_path, study())

    assert "tool name" in row.lever_counter.name
    assert row.lever_counter.off == len(REPERTOIRE)
    assert row.lever_counter.on == len(REPERTOIRE)


def test_a_check_tool_the_on_arm_stopped_calling_is_named(tmp_path: Path) -> None:
    """T059's gate: the general rule plus *this*, because the tokens will look fine."""
    row = ledger_row(tmp_path, study(on_tools=("check_fit", "list_holes")))

    assert row.lever_counter.dropped_tools == ["check_rms_part"]
    assert row.lever_counter.on == 2


def test_nothing_is_named_when_the_repertoire_held(tmp_path: Path) -> None:
    """An empty list, so the column is read as "measured and clean", not as "not measured"."""
    assert ledger_row(tmp_path, study()).lever_counter.dropped_tools == []


def test_a_tool_only_the_on_arm_called_is_not_a_loss(tmp_path: Path) -> None:
    """The gate is asymmetric on purpose: a tool gained is not a tool lost."""
    row = ledger_row(tmp_path, study(on_tools=(*REPERTOIRE, "bounding_box")))

    assert row.lever_counter.dropped_tools == []
    assert row.lever_counter.on == len(REPERTOIRE) + 1


def test_a_tool_dropped_by_only_one_on_run_is_still_not_a_loss(tmp_path: Path) -> None:
    """A run of the arm still called it, so the repertoire held. Worst case is by arm."""
    specs = study()
    specs[3] = replace(
        specs[3], packages=(PackageSpec(tool_names=("check_fit",), tool_calls=2),)
    )

    assert ledger_row(tmp_path, specs).lever_counter.dropped_tools == []


def test_an_arm_that_never_ran_leaves_the_counter_unknown(tmp_path: Path) -> None:
    """`None`, never `0`: nothing was measured, which is not the same as nothing called."""
    row = ledger_row(tmp_path, [spec for spec in study() if spec.arm == "off"])

    assert row.lever_counter.on is None
    assert row.lever_counter.off == len(REPERTOIRE)
    assert row.lever_counter.dropped_tools == []


def test_another_lever_s_counter_is_untouched(tmp_path: Path) -> None:
    """Lever 6's counter is still tool calls; lever 2 did not take the column over."""
    specs = [
        RunSpec(run=f"{arm}-{rep}", arm=arm, rep=rep)
        for arm in ("off", "on")
        for rep in (1, 2, 3)
    ]

    row = ledger_row(tmp_path, specs, lever="parallel_tool_calls")

    assert row.lever_counter.dropped_tools == []
    assert row.lever_counter.off == 31


# --- the gate counter, levers 5 and 11 (T054, FR-034, SC-010) -----------------------------

GATE_LEVERS: tuple[str, ...] = ("prerun_checks", "procedural_gate")
"""The two levers whose gate is the same number. Lever 11 implies lever 5, so an arm of
either runs the deterministic checks before the first turn, and the risk they share is the
one thing the token counts cannot show: a model told what has already been checked stops
reaching for `check_fit` and `check_axial_stack`, which no rule can enumerate and only it
can call."""

GATE_COUNTER_NAME = "check_fit and check_axial_stack calls per run (must not fall)"
GATE_TOOLS: tuple[str, ...] = ("check_fit", "check_axial_stack")
OTHER_TOOL = "list_holes"


def fit_calls(count: int, package_id: str = "rms-part") -> PackageSpec:
    """A package that called `check_fit` `count` times, and a non-gate tool as often.

    `step_tools` cycles `tool_names` over `tool_calls`, so two names over `2 * count` steps
    is `count` of each - which also makes the non-gate half of every run a control on the
    sum below.
    """
    return PackageSpec(
        package_id=package_id, tool_names=("check_fit", OTHER_TOOL), tool_calls=count * 2
    )


def gate_study(
    off_calls: tuple[int, ...], on_calls: tuple[int, ...], lever: str
) -> list[RunSpec]:
    """One run per element, each calling `check_fit` that many times."""
    return [
        RunSpec(run=f"{arm}-{rep}", arm=arm, rep=rep, lever=lever, packages=(fit_calls(calls),))
        for arm, counts in (("off", off_calls), ("on", on_calls))
        for rep, calls in enumerate(counts, start=1)
    ]


@pytest.mark.parametrize("lever", GATE_LEVERS)
def test_the_gate_counter_is_named_and_is_the_arm_medians(tmp_path: Path, lever: str) -> None:
    """Both levers get the number, and lever 5's placeholder string goes with it."""
    row = ledger_row(tmp_path, gate_study((6, 8, 10), (5, 7, 9), lever), lever=lever)

    assert row.lever_counter.name == GATE_COUNTER_NAME
    assert (row.lever_counter.off, row.lever_counter.on) == (8.0, 7.0)


@pytest.mark.parametrize("lever", GATE_LEVERS)
def test_the_placeholder_string_is_gone(tmp_path: Path, lever: str) -> None:
    """"arrives with lever 5" was a column naming the number nobody could compute yet."""
    row = ledger_row(tmp_path, gate_study((4, 4, 4), (4, 4, 4), lever), lever=lever)

    assert "arrives with" not in row.lever_counter.name


def test_only_the_two_gate_tools_are_counted(tmp_path: Path) -> None:
    """Every run here also called `list_holes` as often as `check_fit`, and it is not in
    the sum: a lever that traded one of these tools for another would still be caught."""
    row = ledger_row(tmp_path, gate_study((6,), (6,), "procedural_gate"), lever="procedural_gate")

    assert (row.lever_counter.off, row.lever_counter.on) == (6.0, 6.0)


def test_both_gate_tools_are_summed_into_one_number(tmp_path: Path) -> None:
    """`check_axial_stack` counts exactly as `check_fit` does; the gate is the pair."""
    both = PackageSpec(tool_names=GATE_TOOLS, tool_calls=8)
    specs = [
        RunSpec(run=f"{arm}-1", arm=arm, rep=1, lever="procedural_gate", packages=(both,))
        for arm in ("off", "on")
    ]

    row = ledger_row(tmp_path, specs, lever="procedural_gate")

    assert (row.lever_counter.off, row.lever_counter.on) == (8.0, 8.0)


def test_the_number_is_the_sum_over_every_package_of_one_run(tmp_path: Path) -> None:
    """Per run, not per package: the row is one line per arm, not one per package."""
    packages = (fit_calls(3), fit_calls(4, package_id="rms-assembly"))
    specs = [
        RunSpec(run=f"{arm}-1", arm=arm, rep=1, lever="procedural_gate", packages=packages)
        for arm in ("off", "on")
    ]

    row = ledger_row(tmp_path, specs, lever="procedural_gate")

    assert (row.lever_counter.off, row.lever_counter.on) == (7.0, 7.0)


# --- the worst case, which is what the gate is actually read on ---------------------------


def test_an_on_run_below_the_off_arm_s_minimum_is_named(tmp_path: Path) -> None:
    """SC-010 is a worst case, not a median: one run that stopped checking fits is a failed
    gate whatever the token saving, so the row names the run rather than counting it."""
    row = ledger_row(
        tmp_path, gate_study((8, 9, 10), (9, 5, 9), "procedural_gate"), lever="procedural_gate"
    )

    assert row.lever_counter.fell_in_runs == ["on-2"]


def test_the_median_can_hold_while_the_gate_fails(tmp_path: Path) -> None:
    """The case a median-only column would pass: the on arm's median is the off arm's and
    one run of it still fell. The list is the assertion, not the two numbers beside it."""
    row = ledger_row(
        tmp_path, gate_study((9, 9, 9), (12, 9, 4), "procedural_gate"), lever="procedural_gate"
    )

    assert (row.lever_counter.off, row.lever_counter.on) == (9.0, 9.0)
    assert row.lever_counter.fell_in_runs == ["on-3"]


def test_every_on_run_that_fell_is_named_in_run_order(tmp_path: Path) -> None:
    row = ledger_row(
        tmp_path, gate_study((8, 9, 10), (3, 9, 2), "procedural_gate"), lever="procedural_gate"
    )

    assert row.lever_counter.fell_in_runs == ["on-1", "on-3"]


def test_an_on_run_equal_to_the_off_arm_s_minimum_has_not_fallen(tmp_path: Path) -> None:
    """The threshold is strict: "must not fall" is below it, not below or equal to it."""
    row = ledger_row(
        tmp_path, gate_study((8, 9, 10), (8, 8, 8), "procedural_gate"), lever="procedural_gate"
    )

    assert row.lever_counter.fell_in_runs == []


def test_nothing_is_named_when_every_on_run_held(tmp_path: Path) -> None:
    """Empty means measured and clean, exactly as an empty `dropped_tools` does."""
    row = ledger_row(
        tmp_path, gate_study((6, 6, 6), (7, 8, 9), "procedural_gate"), lever="procedural_gate"
    )

    assert row.lever_counter.fell_in_runs == []


def test_an_arm_that_never_ran_leaves_the_numbers_unknown_and_the_list_empty(
    tmp_path: Path,
) -> None:
    """`None` and `[]`, never `0` and never a name: there was no arm to fall below."""
    specs = [spec for spec in gate_study((6, 6, 6), (1,), "procedural_gate") if spec.arm == "off"]

    row = ledger_row(tmp_path, specs, lever="procedural_gate")

    assert row.lever_counter.on is None
    assert row.lever_counter.off == 6.0
    assert row.lever_counter.fell_in_runs == []


def test_a_run_that_called_neither_tool_counts_zero_rather_than_unknown(
    tmp_path: Path,
) -> None:
    """A run that never called them is the failure the gate is looking for, and `0` is a
    measurement of it; `unknown` would read as "this arm did not run"."""
    silent = PackageSpec(tool_names=(OTHER_TOOL,), tool_calls=4)
    specs = [
        RunSpec(run="off-1", arm="off", rep=1, lever="procedural_gate", packages=(fit_calls(5),)),
        RunSpec(run="on-1", arm="on", rep=1, lever="procedural_gate", packages=(silent,)),
    ]

    row = ledger_row(tmp_path, specs, lever="procedural_gate")

    assert (row.lever_counter.off, row.lever_counter.on) == (5.0, 0.0)
    assert row.lever_counter.fell_in_runs == ["on-1"]


def test_the_gate_counter_leaves_dropped_tools_empty(tmp_path: Path) -> None:
    """The two list fields are different questions, and only lever 2 answers the first."""
    row = ledger_row(
        tmp_path, gate_study((8, 9, 10), (2, 2, 2), "procedural_gate"), lever="procedural_gate"
    )

    assert row.lever_counter.dropped_tools == []
    assert row.lever_counter.fell_in_runs == ["on-1", "on-2", "on-3"]


def test_lever_two_s_counter_names_no_run_as_fallen(tmp_path: Path) -> None:
    """The reverse guard: the gate's list did not leak into the histogram counter."""
    assert ledger_row(tmp_path, study()).lever_counter.fell_in_runs == []
