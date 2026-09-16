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
