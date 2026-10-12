"""The results ledger: N run folders in, two tables out (T039, T040, for T041).

`swreview benchmark compare` is the **one reader** of a study. Its job is not arithmetic
- the scorer already did that - but validation and rendering:

1. **Every column has exactly one source and no column is computed twice.** The token
   counts come from `session.json` `usage.totals` verbatim; `uncached in` and the cached
   share are derived in the scorecard only and read through; `wall clock` and `s to 1st
   finding` are `PackageScore`; `tool calls` is `len(session.steps)` and is never
   confused with `rounds`; `lever`, `arm`, `rep` and `commit` are the provenance record.
2. **Two independent writers, cross-checked** (RK-20). `session.efficiency` is the
   runner's resolved settings; the provenance record is what `cli.py` was told to run. A
   run whose two records disagree is refused and the message names the field. One writer
   could only agree with itself.
3. **Null is null.** A token total no provider reported renders as `unknown`, never as
   `0` and never as a blank cell.

The per-run rows are the raw ledger and always render: a run with no provenance record is
a row with four null columns rather than an error, and a smoke-test run carrying
`set_too_small_override` still gets its raw rows - it is the *decision row* that the
override blocks (T043).

No provider, no answer key, no run: every input here is a file this module wrote.
"""

from __future__ import annotations

import json
import shutil
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from swreview import cli
from swreview.agent.settings import (
    MODEL_VIEW_OFF,
    MODEL_VIEW_PANE,
    PANE_STUDY,
    PRIVATE_PANE_STUDY,
    EfficiencySettings,
    ModelViewSettings,
)
from swreview.benchmark import scorecard as scorecard_module
from swreview.benchmark import sets
from swreview.benchmark.adoption import (
    ADOPT,
    BASELINE,
    CONTROL_UNSTABLE,
    KEEP_OFF,
    NO_RECALL,
    SET_TOO_SMALL,
)
from swreview.benchmark.compare import (
    ACROSS_ARMS,
    ACROSS_PANE_ARMS,
    LEDGER_BEGIN,
    LEDGER_END,
    LEDGER_JSON,
    LEDGER_MD,
    LEVER_COLUMNS,
    MUST_MATCH,
    NOT_RECORDED_WHEN_ABSENT,
    RECORD_ONLY,
    RUN_COLUMNS,
    RUN_IDENTITY,
    STUDY_KEY_FIELDS,
    UNKNOWN,
    CompareError,
    carry_sign_offs,
    compare_runs,
    recorded_runs,
    render_ledger_md,
    settings_differed,
    splice_ledger,
    write_ledger,
)
from swreview.benchmark.runner import PROVENANCE_FILE, RunProvenance
from swreview.benchmark.scorecard import NOT_ASSESSED, SCORECARD_FILE, Scorecard
from swreview.checks.standards.profile import display_digest
from tests.support.studies import (
    COMMIT,
    EXAMPLE_PROFILE_DIGEST,
    PRIVATE_PROFILE_DIGEST,
    STARTED_AT,
    PackageSpec,
    RunSpec,
    pane_baseline_spec,
    pane_run_spec,
    pane_study_specs,
    profile_stamp,
    saved_set_entries,
    study_specs,
    write_run,
    write_study,
)
from tests.unit.test_run_provenance import git

runner = CliRunner()

CHEAPER = {"packages": (PackageSpec(total_tokens=209_000, wall_clock_s=250.0),)}
"""An on arm that halved the bill and lost nothing: the only shape that may `adopt`."""


def cells_of(rendered: str, run: str) -> dict[str, str]:
    """One raw row of the rendered table, keyed by its column heading.

    By heading rather than by position, so a column added later moves nothing and a
    reordered table fails loudly rather than asserting the wrong cell.
    """
    lines = rendered.splitlines()
    header = next(line for line in lines if line.startswith("| run | commit |"))
    row = next(line for line in lines if line.startswith(f"| {run} |"))
    names = [cell.strip() for cell in header.strip().strip("|").split("|")]
    values = [cell.strip() for cell in row.strip().strip("|").split("|")]
    assert len(names) == len(values), (names, values)
    return dict(zip(names, values, strict=True))


def rows_of(ledger: Any, run: str) -> list[Any]:
    return [row for row in ledger.runs if row.run == run]


def one_row(ledger: Any, run: str) -> Any:
    rows = rows_of(ledger, run)
    assert len(rows) == 1, rows
    return rows[0]


def lever_row(ledger: Any, lever: str) -> Any:
    rows = [row for row in ledger.levers if row.lever == lever]
    assert len(rows) == 1, rows
    return rows[0]


def lever_cells_of(rendered: str, lever: str) -> dict[str, str]:
    """One decision row of the rendered table, keyed by its column heading."""
    lines = rendered.splitlines()
    header = next(line for line in lines if line.startswith("| Lever | Provider and model |"))
    row = next(line for line in lines if line.startswith(f"| {lever} |"))
    names = [cell.strip() for cell in header.strip().strip("|").split("|")]
    values = [cell.strip() for cell in row.strip().strip("|").split("|")]
    assert len(names) == len(values), (names, values)
    return dict(zip(names, values, strict=True))


def signed(rendered: str) -> str:
    """The owner's hand edit: `yes` and a date in the two cells beside the computed one."""
    edited = rendered.replace("| adopt | no | unknown |", "| adopt | yes | 2026-09-16 |")
    assert edited != rendered, rendered
    return edited


# --- the per-run rows, the raw ledger (T039) -------------------------------------


def test_every_column_comes_from_its_one_source(tmp_path: Path) -> None:
    spec = RunSpec(run="off-1", arm="off", rep=1)
    write_run(tmp_path, spec)

    ledger = compare_runs([tmp_path / "off-1"])

    row = one_row(ledger, "off-1")
    assert (row.lever, row.arm, row.rep, row.commit) == ("parallel_tool_calls", "off", 1, COMMIT)
    assert (row.provider, row.model, row.effort) == ("openai", "gpt-5.6", "high")
    assert row.package_id == "rms-part"
    package = spec.packages[0]
    assert row.input_tokens == package.input_tokens
    assert row.cached_input_tokens == package.cached_input_tokens
    assert row.output_tokens == package.output_tokens
    assert row.reasoning_tokens == package.reasoning_tokens
    assert row.tool_result_input_tokens is None
    assert row.total_tokens == package.total_tokens
    assert row.rounds == package.rounds
    assert row.uncached_input_tokens == package.input_tokens - package.cached_input_tokens
    assert row.cached_input_share == package.cached_input_tokens / package.input_tokens
    assert row.wall_clock_s == package.wall_clock_s
    assert row.seconds_to_first_finding == package.seconds_to_first_finding
    assert row.valid_findings == package.valid_findings
    assert row.missed_known_defects == 0
    assert row.false_alarms == package.false_alarms
    assert row.unresolved_count == package.unresolved
    assert row.coverage_bucket_mix == {
        "checked": package.coverage_checked,
        "skipped": 0,
        "unresolved": package.coverage_unresolved,
        "failed": 0,
        "out_of_scope": 0,
    }


def test_the_raw_row_reads_the_unresolved_count_as_two_numbers(tmp_path: Path) -> None:
    """FR-054 on the raw ledger: lever 4 is allowed to raise the withheld half and nothing
    else, and a single `unresolved` column cannot show which half moved.

    Both come from `PackageScore`, the one source, and they sum to the unresolved bucket of
    the mix beside them - never to `unresolved_count`, which counts findings.
    """
    spec = RunSpec(
        run="on-1", arm="on", lever="tool_tiers", packages=(PackageSpec(coverage_withheld=1),)
    )
    write_run(tmp_path, spec)

    row = one_row(compare_runs([tmp_path / "on-1"]), "on-1")

    package = spec.packages[0]
    assert row.unresolved_because_withheld == 1
    assert row.unresolved_other == package.coverage_unresolved - 1
    assert (
        row.unresolved_because_withheld + row.unresolved_other
        == row.coverage_bucket_mix["unresolved"]
    )


def test_both_unresolved_numbers_are_rendered_columns(tmp_path: Path) -> None:
    """A number only `ledger.json` carries is a number the owner does not read."""
    write_run(tmp_path, RunSpec(run="on-1", arm="on", packages=(PackageSpec(coverage_withheld=2),)))

    cells = cells_of(render_ledger_md(compare_runs([tmp_path / "on-1"])), "on-1")

    assert cells["unresolved withheld"] == "2"
    assert cells["unresolved other"] == "1"


def test_the_lever_four_counter_reads_the_withheld_half(tmp_path: Path) -> None:
    """Lever 4's gate number, computed now that lever 4 has landed (FR-054, T062).

    The counter was a placeholder naming a number nobody could compute; a study of the
    lever now renders the median withheld count per arm, which is the half the lever is
    expected to raise.
    """
    dirs = write_study(
        tmp_path,
        study_specs(
            lever="tool_tiers",
            off={"packages": (PackageSpec(coverage_withheld=0),)},
            on={"packages": (PackageSpec(coverage_withheld=2),)},
        ),
    )

    row = lever_row(compare_runs(dirs), "tool_tiers")

    assert row.lever_counter.name == "unresolved because withheld"
    assert (row.lever_counter.off, row.lever_counter.on) == (0.0, 2.0)


def test_tool_calls_and_rounds_are_two_different_numbers(tmp_path: Path) -> None:
    """Lever 6 makes them diverge by exactly the amount it is trying to save."""
    write_run(tmp_path, RunSpec(run="on-1", arm="on", packages=(PackageSpec(rounds=4),)))

    row = one_row(compare_runs([tmp_path / "on-1"]), "on-1")

    assert (row.rounds, row.tool_calls) == (4, 31)


def test_other_levers_on_comes_from_the_session_settings(tmp_path: Path) -> None:
    write_run(
        tmp_path,
        RunSpec(run="on-1", arm="on", other_levers=("prompt_cache_key", "tool_tiers")),
    )

    row = one_row(compare_runs([tmp_path / "on-1"]), "on-1")

    assert row.other_levers_on == ["prompt_cache_key", "tool_tiers"]


def test_a_run_with_no_provenance_record_renders_with_those_four_null(tmp_path: Path) -> None:
    """A run made before the convention existed is still a real run."""
    write_run(tmp_path, RunSpec(run="ancient"), with_provenance=False)

    ledger = compare_runs([tmp_path / "ancient"])

    row = one_row(ledger, "ancient")
    assert (row.lever, row.arm, row.rep, row.commit) == (None, None, None, None)
    assert row.total_tokens == 418_000
    assert cells_of(render_ledger_md(ledger), "ancient")["lever"] == UNKNOWN


def test_a_null_token_total_renders_as_unknown_and_never_as_zero(tmp_path: Path) -> None:
    write_run(
        tmp_path,
        RunSpec(run="off-1", packages=(PackageSpec(total_tokens=None, reasoning_tokens=None),)),
    )

    ledger = compare_runs([tmp_path / "off-1"])

    row = one_row(ledger, "off-1")
    assert row.total_tokens is None
    assert row.reasoning_tokens is None
    cells = cells_of(render_ledger_md(ledger), "off-1")
    assert cells["total"] == UNKNOWN
    assert cells["reasoning/thoughts"] == UNKNOWN
    assert cells["input"] == "400000"


def test_the_cached_share_renders_unknown_until_probe_l1_is_recorded(tmp_path: Path) -> None:
    """FR-047: a ratio is a share only once containment has been measured."""
    write_run(tmp_path, RunSpec(run="off-1"))

    rendered = render_ledger_md(compare_runs([tmp_path / "off-1"]))

    row_line = next(line for line in rendered.splitlines() if line.startswith("| off-1 "))
    assert "80%" not in row_line
    assert UNKNOWN in row_line


def test_the_raw_rows_still_render_for_a_smoke_test_study(tmp_path: Path) -> None:
    """The override blocks the decision row (T043), never the raw rows."""
    specs = study_specs(off={"set_too_small_override": True}, on={"set_too_small_override": True})
    write_study(tmp_path, specs)

    ledger = compare_runs([tmp_path / spec.run for spec in specs])

    assert len(ledger.runs) == 6
    assert all(row.set_too_small_override for row in ledger.runs)


def test_compare_is_idempotent_over_the_same_folders(tmp_path: Path) -> None:
    specs = study_specs()
    dirs = write_study(tmp_path, specs)

    first = compare_runs(dirs)
    second = compare_runs(dirs)

    assert first == second
    assert render_ledger_md(first) == render_ledger_md(second)


# --- the refusals, which are the point of the command (RK-20) --------------------


def test_a_session_with_no_efficiency_at_all_is_refused(tmp_path: Path) -> None:
    write_run(tmp_path, RunSpec(run="off-1"), session_edit={"efficiency": None})

    with pytest.raises(CompareError) as excinfo:
        compare_runs([tmp_path / "off-1"])

    assert "predates the flag carrier" in str(excinfo.value)


def test_a_session_whose_settings_disagree_with_the_record_is_refused(tmp_path: Path) -> None:
    write_run(
        tmp_path,
        RunSpec(run="on-1", arm="on"),
        session_edit={
            "efficiency": {
                "trim_tool_descriptions": False,
                "tool_tiers": True,
                "prompt_cache_key": False,
                "gemini_explicit_cache": False,
                "prerun_checks": False,
                "parallel_tool_calls": True,
                "coverage_stop": False,
                "package_reuse": False,
                "lazy_meshes": False,
                "carry_over_rms": False,
            }
        },
    )

    with pytest.raises(CompareError) as excinfo:
        compare_runs([tmp_path / "on-1"])

    assert "tool_tiers" in str(excinfo.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [("model", "gpt-5.5"), ("provider", "gemini")],
)
def test_a_session_whose_provider_info_disagrees_with_the_record_is_refused(
    tmp_path: Path, field: str, value: str
) -> None:
    run_dir = write_run(tmp_path, RunSpec(run="off-1"))
    session_path = run_dir / "rms-part" / "session.json"
    payload = json.loads(session_path.read_text(encoding="utf-8"))
    payload["provider_info"][field] = value
    session_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(CompareError) as excinfo:
        compare_runs([run_dir])

    assert field in str(excinfo.value)


def test_an_arm_on_whose_studied_lever_is_off_is_refused_naming_the_lever(
    tmp_path: Path,
) -> None:
    write_run(tmp_path, RunSpec(run="on-1", arm="on", efficiency=None, lever="coverage_stop"))
    # The settings say coverage_stop is on; retype the arm's own lever as a different one.
    path = tmp_path / "on-1" / PROVENANCE_FILE
    record = json.loads(path.read_text(encoding="utf-8"))
    record["lever"] = "prerun_checks"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(CompareError) as excinfo:
        compare_runs([tmp_path / "on-1"])

    assert "prerun_checks" in str(excinfo.value)


def test_an_arm_off_whose_studied_lever_is_on_is_refused(tmp_path: Path) -> None:
    write_run(
        tmp_path,
        RunSpec(run="off-1", arm="off", efficiency=None, other_levers=("coverage_stop",)),
    )
    path = tmp_path / "off-1" / PROVENANCE_FILE
    record = json.loads(path.read_text(encoding="utf-8"))
    record["lever"] = "coverage_stop"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(CompareError) as excinfo:
        compare_runs([tmp_path / "off-1"])

    assert "coverage_stop" in str(excinfo.value)


def test_a_baseline_run_with_every_flag_off_is_accepted(tmp_path: Path) -> None:
    write_run(tmp_path, RunSpec(run="baseline-1", arm="baseline", lever="none"))

    row = one_row(compare_runs([tmp_path / "baseline-1"]), "baseline-1")

    assert (row.lever, row.arm) == ("none", "baseline")
    assert row.other_levers_on == []


def test_a_baseline_run_with_a_flag_on_is_refused(tmp_path: Path) -> None:
    write_run(
        tmp_path,
        RunSpec(run="baseline-1", arm="baseline", lever="none", other_levers=("tool_tiers",)),
    )

    with pytest.raises(CompareError) as excinfo:
        compare_runs([tmp_path / "baseline-1"])

    assert "tool_tiers" in str(excinfo.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("commit", "0e28d52"),
        ("effort", "medium"),
        ("set_digest", "9" * 64),
        ("checklist_digest", "9" * 64),
    ],
)
def test_two_runs_of_one_study_that_differ_are_refused_naming_the_field(
    tmp_path: Path, field: str, value: str
) -> None:
    """No declared exception, lever 2 included: its off arm is its flag off."""
    write_run(tmp_path, RunSpec(run="off-1", arm="off", rep=1))
    write_run(tmp_path, replace(RunSpec(run="on-1", arm="on", rep=1), **{field: value}))

    with pytest.raises(CompareError) as excinfo:
        compare_runs([tmp_path / "off-1", tmp_path / "on-1"])

    assert field in str(excinfo.value)


def test_two_runs_of_one_study_scored_against_two_versions_of_a_key_are_refused(
    tmp_path: Path,
) -> None:
    """Feature 014 INT-16 (`scoring.md` 11's test 15): an arm scored against an edited key
    measures the edit, so the refusal names the package whose key moved."""
    write_run(tmp_path, RunSpec(run="off-1", arm="off", rep=1))
    write_run(tmp_path, RunSpec(run="on-1", arm="on", rep=1, key_sha256="f" * 64))

    with pytest.raises(CompareError) as excinfo:
        compare_runs([tmp_path / "off-1", tmp_path / "on-1"])

    message = str(excinfo.value)
    assert "rms-part" in message
    assert "key_sha256" in message


def test_two_runs_of_one_study_scored_against_one_key_are_accepted(tmp_path: Path) -> None:
    write_run(tmp_path, RunSpec(run="off-1", arm="off", rep=1, key_sha256="f" * 64))
    write_run(tmp_path, RunSpec(run="on-1", arm="on", rep=1, key_sha256="f" * 64))

    ledger = compare_runs([tmp_path / "off-1", tmp_path / "on-1"])

    assert len(ledger.levers) == 1


def test_a_run_with_no_scorecard_is_refused(tmp_path: Path) -> None:
    run_dir = write_run(tmp_path, RunSpec(run="off-1"))
    (run_dir / "scorecard.json").unlink()

    with pytest.raises(CompareError) as excinfo:
        compare_runs([run_dir])

    assert "benchmark score" in str(excinfo.value)


def test_compare_reads_no_file_under_the_answer_keys_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Principle VI and FR-025: `compare` reads `scorecard.json`, never an answer key."""
    answer_keys = tmp_path / "benchmarks" / "answer_keys"
    answer_keys.mkdir(parents=True)
    (answer_keys / "rms-part.json").write_text("{}", encoding="utf-8")
    dirs = write_study(tmp_path, study_specs())
    read: list[Path] = []

    for name in ("read_bytes", "read_text"):
        original = getattr(Path, name)

        def recorder(self: Path, *args: Any, _original: Any = original, **kwargs: Any) -> Any:
            read.append(self)
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(Path, name, recorder)

    compare_runs(dirs)

    assert read
    assert not [path for path in read if answer_keys in path.resolve().parents]


# --- the decision rows, the summary the owner reads (T040) -----------------------


def test_one_decision_row_per_lever_per_provider_and_model(tmp_path: Path) -> None:
    dirs = write_study(tmp_path, study_specs(on=CHEAPER))

    ledger = compare_runs(dirs)

    row = lever_row(ledger, "parallel_tool_calls")
    assert (row.provider, row.model) == ("openai", "gpt-5.6")
    assert (row.commit_off, row.commit_on) == (COMMIT, COMMIT)
    assert row.reps == 3
    assert row.other_levers_on == []
    assert len(row.run_dirs) == 6


def test_the_decision_row_reports_median_min_and_max_off_and_on(tmp_path: Path) -> None:
    specs = study_specs(on=CHEAPER)
    specs[1] = replace(specs[1], packages=(PackageSpec(total_tokens=200_000),))
    dirs = write_study(tmp_path, specs)

    row = lever_row(compare_runs(dirs), "parallel_tool_calls")

    assert row.total_tokens.off_median == 418_000
    assert row.total_tokens.on_min == 200_000
    assert row.total_tokens.on_max == 209_000
    assert row.total_tokens.on_median == 209_000
    assert row.total_tokens.delta_pct == pytest.approx((209_000 - 418_000) / 418_000)
    assert row.round_trips.off_median == 9


def test_a_lever_that_loses_a_defect_in_one_on_run_is_kept_off(tmp_path: Path) -> None:
    specs = study_specs(on=CHEAPER)
    specs[3] = replace(
        specs[3], packages=(PackageSpec(matched=("D-1",), missed=("D-2",), total_tokens=209_000),)
    )
    dirs = write_study(tmp_path, specs)

    row = lever_row(compare_runs(dirs), "parallel_tool_calls")

    assert row.decision == KEEP_OFF
    assert row.worst_case_defects_lost == 1
    assert "D-2" in row.decision_reason


def test_a_lever_that_pays_for_itself_is_computed_adopt_and_stays_unsigned(
    tmp_path: Path,
) -> None:
    dirs = write_study(tmp_path, study_specs(on=CHEAPER))

    row = lever_row(compare_runs(dirs), "parallel_tool_calls")

    assert row.decision == ADOPT
    assert row.owner_signed_off is False
    assert row.owner_signed_off_at is None


def test_the_median_net_saved_minutes_column_reads_the_scorecard_aggregate(
    tmp_path: Path,
) -> None:
    """FR-006, research R2.9: the cell is the median across the arm's runs of each run's
    own per-package median, and `n=` says how many runs carried timing at all."""
    timed = PackageSpec(total_tokens=209_000, wall_clock_s=250.0, baseline_minutes=90.0)
    specs = study_specs(on={"packages": (timed,)})
    specs[0] = replace(
        specs[0],
        packages=(PackageSpec(baseline_minutes=90.0, assisted_minutes=85.0),),
    )
    dirs = write_study(tmp_path, specs)

    ledger = compare_runs(dirs)

    row = lever_row(ledger, "parallel_tool_calls")
    assert row.median_net_saved_minutes.off_median == 5.0
    assert row.median_net_saved_minutes.off_rows == 1
    assert row.median_net_saved_minutes.on_median == 90.0
    assert row.median_net_saved_minutes.on_rows == 3
    cell = lever_cells_of(render_ledger_md(ledger), "parallel_tool_calls")[
        "Median net saved minutes off -> on"
    ]
    assert "n=1" in cell
    assert "n=3" in cell


def test_a_study_that_carried_no_timing_renders_the_median_as_unknown(
    tmp_path: Path,
) -> None:
    """No real run has ever recorded a baseline; `unknown` is the honest cell, never `0`."""
    dirs = write_study(tmp_path, study_specs(on=CHEAPER))

    ledger = compare_runs(dirs)

    row = lever_row(ledger, "parallel_tool_calls")
    assert row.median_net_saved_minutes.off_median is None
    assert row.median_net_saved_minutes.off_rows == 0
    cell = lever_cells_of(render_ledger_md(ledger), "parallel_tool_calls")[
        "Median net saved minutes off -> on"
    ]
    assert UNKNOWN in cell
    assert "n=0" in cell


def test_the_median_net_saved_minutes_column_turns_no_decision(tmp_path: Path) -> None:
    """The column is read, never gated on (FR-006): the same runs decide the same way
    whether or not they carried timing."""
    plain = write_study(tmp_path / "plain", study_specs(on=CHEAPER))
    cheaper_and_timed = PackageSpec(
        total_tokens=209_000, wall_clock_s=250.0, baseline_minutes=90.0
    )
    timed = write_study(
        tmp_path / "timed", study_specs(on={"packages": (cheaper_and_timed,)})
    )

    plain_row = lever_row(compare_runs(plain), "parallel_tool_calls")
    timed_row = lever_row(compare_runs(timed), "parallel_tool_calls")

    assert plain_row.median_net_saved_minutes.on_median is None
    assert timed_row.median_net_saved_minutes.on_median == 90.0
    assert (timed_row.decision, timed_row.decision_reason) == (
        plain_row.decision,
        plain_row.decision_reason,
    )


def test_the_lever_specific_counter_is_named_on_every_row(tmp_path: Path) -> None:
    dirs = write_study(tmp_path, study_specs(on=CHEAPER))

    row = lever_row(compare_runs(dirs), "parallel_tool_calls")

    assert row.lever_counter.name
    assert row.lever_counter.off is not None


# --- how the counter column renders (T054, FR-034) ----------------------------------------


def gate_packages(fit_calls: int) -> dict[str, Any]:
    """One package of a gate study, calling `check_fit` `fit_calls` times."""
    return {
        "packages": (
            PackageSpec(tool_names=("check_fit", "list_holes"), tool_calls=fit_calls * 2),
        )
    }


def counter_cell(tmp_path: Path, lever: str, off: int, on: int) -> str:
    dirs = write_study(
        tmp_path,
        study_specs(lever=lever, off=gate_packages(off), on=gate_packages(on)),
    )

    return lever_cells_of(render_ledger_md(compare_runs(dirs)), lever)["Lever-specific counter"]


def test_the_counter_cell_holds_the_name_and_the_two_medians(tmp_path: Path) -> None:
    cell = counter_cell(tmp_path, "procedural_gate", off=9, on=9)

    assert cell == "check_fit and check_axial_stack calls per run (must not fall): 9 -> 9"


def test_the_runs_that_fell_are_rendered_after_the_medians(tmp_path: Path) -> None:
    """The same shape lever 2's `dropped_tools` renders in: the numbers, then the names,
    so a reader who scans the column sees the gate's verdict without opening the JSON."""
    cell = counter_cell(tmp_path, "procedural_gate", off=9, on=4)

    assert cell.startswith("check_fit and check_axial_stack calls per run (must not fall): 9 -> 4")
    assert cell.endswith("; fell below the off arm in: on-1, on-2, on-3")


def test_lever_five_s_cell_computes_rather_than_naming_a_missing_number(
    tmp_path: Path,
) -> None:
    """It read "check_fit and check_axial_stack call counts (arrives with lever 5)": a
    column saying which number was missing. Lever 11 brought the number with it."""
    cell = counter_cell(tmp_path, "prerun_checks", off=6, on=6)

    assert "arrives with" not in cell
    assert cell.endswith(": 6 -> 6")


def test_another_lever_s_counter_cell_names_no_fallen_run(tmp_path: Path) -> None:
    dirs = write_study(tmp_path, study_specs(on=CHEAPER))

    cell = lever_cells_of(render_ledger_md(compare_runs(dirs)), "parallel_tool_calls")[
        "Lever-specific counter"
    ]

    assert "fell below" not in cell


def test_a_baseline_study_renders_a_distribution_and_no_decision(tmp_path: Path) -> None:
    specs = [
        RunSpec(run=f"baseline-{rep}", arm="baseline", rep=rep, lever="none") for rep in (1, 2, 3)
    ]
    dirs = write_study(tmp_path, specs)

    ledger = compare_runs(dirs)

    row = lever_row(ledger, "none")
    assert row.decision is None
    assert row.total_tokens.off_median == 418_000
    assert row.total_tokens.on_median is None
    assert "baseline" in row.decision_reason.lower()


def test_a_study_that_can_produce_no_recall_number_gets_no_decision_row(
    tmp_path: Path,
) -> None:
    """SC-011 over today's single-package set: no held-out package, `recall` null."""
    not_held_out = {"packages": (PackageSpec(package_id="cover-blind-tap", held_out=False),)}
    dirs = write_study(tmp_path, study_specs(off=not_held_out, on=not_held_out))

    ledger = compare_runs(dirs)

    row = lever_row(ledger, "parallel_tool_calls")
    assert row.decision is None
    assert NO_RECALL in row.decision_reason
    assert len(ledger.runs) == 6


def test_a_study_carrying_the_too_small_override_gets_no_decision_row(tmp_path: Path) -> None:
    """Both arms carry it (owner decision 44A): `set_too_small_override` must match across a
    study, so one arm carrying it alone is refused at the study, before any decision row."""
    specs = study_specs(
        off={"set_too_small_override": True},
        on={"set_too_small_override": True, **CHEAPER},
    )
    dirs = write_study(tmp_path, specs)

    row = lever_row(compare_runs(dirs), "parallel_tool_calls")

    assert row.decision is None
    assert SET_TOO_SMALL in row.decision_reason
    assert "on-1" in row.decision_reason


def test_an_unstable_control_arm_is_re_measure_and_never_a_pass(tmp_path: Path) -> None:
    specs = study_specs(on=CHEAPER)
    specs[2] = replace(specs[2], packages=(PackageSpec(matched=("D-1",), missed=("D-2",)),))
    dirs = write_study(tmp_path, specs)

    row = lever_row(compare_runs(dirs), "parallel_tool_calls")

    assert row.decision == "re-measure"
    assert CONTROL_UNSTABLE in row.decision_reason


# --- the rendered ledger and the command -----------------------------------------


def test_render_ledger_md_holds_both_tables(tmp_path: Path) -> None:
    dirs = write_study(tmp_path, study_specs(on=CHEAPER))

    rendered = render_ledger_md(compare_runs(dirs))

    assert "| run | commit | lever | arm | rep |" in rendered
    assert "| Lever | Provider and model |" in rendered
    assert "| off-1 |" in rendered
    assert "| parallel_tool_calls |" in rendered
    assert rendered.endswith("\n")


def test_render_ledger_md_over_no_runs_says_so_rather_than_raising() -> None:
    rendered = render_ledger_md(compare_runs([]))

    assert "| run | commit | lever | arm | rep |" in rendered
    assert "no run directories" in rendered.lower()


def test_write_ledger_writes_both_files(tmp_path: Path) -> None:
    dirs = write_study(tmp_path, study_specs(on=CHEAPER))
    out = tmp_path / "ledger"

    json_path, md_path = write_ledger(compare_runs(dirs), out)

    assert json_path == out / LEDGER_JSON
    assert md_path == out / LEDGER_MD
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["ledger_schema"] == "1.1"
    assert len(payload["runs"]) == 6
    assert payload["levers"][0]["owner_signed_off"] is False


def invoke(*args: str) -> Any:
    return runner.invoke(cli.app, list(args))


def test_the_command_writes_the_ledger_and_exits_zero(tmp_path: Path) -> None:
    dirs = write_study(tmp_path, study_specs(on=CHEAPER))
    out = tmp_path / "ledger"

    result = invoke("benchmark", "compare", *[str(one) for one in dirs], "--out", str(out))

    assert result.exit_code == 0, result.stdout + result.stderr
    assert (out / LEDGER_JSON).is_file()
    assert (out / LEDGER_MD).is_file()


def test_the_command_exits_non_zero_when_a_decision_row_is_refused(tmp_path: Path) -> None:
    not_held_out = {"packages": (PackageSpec(package_id="cover-blind-tap", held_out=False),)}
    dirs = write_study(tmp_path, study_specs(off=not_held_out, on=not_held_out))
    out = tmp_path / "ledger"

    result = invoke("benchmark", "compare", *[str(one) for one in dirs], "--out", str(out))

    assert result.exit_code == 1
    assert NO_RECALL in (out / LEDGER_MD).read_text(encoding="utf-8")
    assert "| off-1 |" in (out / LEDGER_MD).read_text(encoding="utf-8")


def test_the_command_refuses_a_mismatched_pair_with_exit_one(tmp_path: Path) -> None:
    write_run(tmp_path, RunSpec(run="off-1", arm="off"))
    write_run(tmp_path, replace(RunSpec(run="on-1", arm="on"), commit="0e28d52"))

    result = invoke(
        "benchmark",
        "compare",
        str(tmp_path / "off-1"),
        str(tmp_path / "on-1"),
        "--out",
        str(tmp_path / "ledger"),
    )

    assert result.exit_code == 1
    assert "commit" in result.stdout + result.stderr


# --- a six-run set that is really one run (RK-20) --------------------------------


def test_the_same_run_directory_may_not_be_compared_twice(tmp_path: Path) -> None:
    """Three copies of one folder are one measurement, and may not stand in for three."""
    dirs = write_study(tmp_path, study_specs(reps=1, on=CHEAPER))
    off, on = dirs[0], dirs[1]

    with pytest.raises(CompareError) as excinfo:
        compare_runs([off, on, off, on, off, on])

    assert "off-1" in str(excinfo.value)


def test_two_runs_of_one_arm_at_the_same_repetition_are_refused(tmp_path: Path) -> None:
    specs = study_specs(on=CHEAPER)
    specs[2] = replace(specs[2], rep=1)
    dirs = write_study(tmp_path, specs)

    with pytest.raises(CompareError) as excinfo:
        compare_runs(dirs)

    assert "off" in str(excinfo.value)
    assert "rep 1" in str(excinfo.value)


def test_three_repetitions_that_are_all_rep_one_cannot_compute_adopt(tmp_path: Path) -> None:
    """The MIN_REPS guard counts runs; without this it is satisfied by copies."""
    specs = [RunSpec(run=f"off-{index}", arm="off", rep=1) for index in (1, 2, 3)]
    specs += [RunSpec(run=f"on-{index}", arm="on", rep=1, **CHEAPER) for index in (1, 2, 3)]
    dirs = write_study(tmp_path, specs)

    with pytest.raises(CompareError) as excinfo:
        compare_runs(dirs)

    assert "rep 1" in str(excinfo.value)


def test_a_gated_arm_run_with_no_repetition_index_is_refused(tmp_path: Path) -> None:
    specs = study_specs(on=CHEAPER)
    specs[0] = replace(specs[0], rep=None)
    dirs = write_study(tmp_path, specs)

    with pytest.raises(CompareError) as excinfo:
        compare_runs(dirs)

    assert "off-1" in str(excinfo.value)
    assert "--rep" in str(excinfo.value)


# --- the worst case is a measurement, or it is unknown (RK-1) --------------------


def test_an_unstable_control_row_renders_the_worst_case_as_unknown(tmp_path: Path) -> None:
    specs = study_specs(on=CHEAPER)
    specs[2] = replace(specs[2], packages=(PackageSpec(matched=("D-1",), missed=("D-2",)),))
    dirs = write_study(tmp_path, specs)

    ledger = compare_runs(dirs)

    row = lever_row(ledger, "parallel_tool_calls")
    assert row.decision == "re-measure"
    assert row.worst_case_defects_lost is None
    cells = lever_cells_of(render_ledger_md(ledger), "parallel_tool_calls")
    assert cells["Worst-case defects lost"] == UNKNOWN


def test_a_baseline_row_renders_the_worst_case_as_unknown(tmp_path: Path) -> None:
    specs = [
        RunSpec(run=f"baseline-{rep}", arm="baseline", rep=rep, lever="none") for rep in (1, 2, 3)
    ]
    dirs = write_study(tmp_path, specs)

    ledger = compare_runs(dirs)

    assert lever_row(ledger, "none").worst_case_defects_lost is None
    assert lever_cells_of(render_ledger_md(ledger), "none")["Worst-case defects lost"] == UNKNOWN


def test_a_refused_decision_row_renders_the_worst_case_as_unknown(tmp_path: Path) -> None:
    not_held_out = {"packages": (PackageSpec(package_id="cover-blind-tap", held_out=False),)}
    dirs = write_study(tmp_path, study_specs(off=not_held_out, on=not_held_out))

    ledger = compare_runs(dirs)

    assert lever_row(ledger, "parallel_tool_calls").worst_case_defects_lost is None
    cells = lever_cells_of(render_ledger_md(ledger), "parallel_tool_calls")
    assert cells["Worst-case defects lost"] == UNKNOWN


def test_a_row_whose_comparison_ran_and_found_nothing_renders_zero(tmp_path: Path) -> None:
    """`0` still means measured and nothing lost - the fix does not blur that."""
    dirs = write_study(tmp_path, study_specs(on=CHEAPER))

    ledger = compare_runs(dirs)

    assert lever_row(ledger, "parallel_tool_calls").worst_case_defects_lost == 0
    cells = lever_cells_of(render_ledger_md(ledger), "parallel_tool_calls")
    assert cells["Worst-case defects lost"] == "0"


# --- the owner's sign-off, carried forward and never computed (T043, FR-027) -----


def test_an_unsigned_row_renders_no_and_an_unknown_date(tmp_path: Path) -> None:
    dirs = write_study(tmp_path, study_specs(on=CHEAPER))

    cells = lever_cells_of(render_ledger_md(compare_runs(dirs)), "parallel_tool_calls")

    assert cells["Decision"] == ADOPT
    assert cells["Owner signed off"] == "no"
    assert cells["Owner signed off at"] == UNKNOWN


def test_a_hand_written_sign_off_survives_regeneration(tmp_path: Path) -> None:
    """The T043 workflow: the owner writes `yes` and a date, `compare` re-renders them."""
    dirs = write_study(tmp_path, study_specs(on=CHEAPER))
    hand_signed = signed(render_ledger_md(compare_runs(dirs)))

    carried = carry_sign_offs(compare_runs(dirs), hand_signed)

    row = lever_row(carried, "parallel_tool_calls")
    assert row.owner_signed_off is True
    assert row.owner_signed_off_at == date(2026, 9, 16)
    assert row.decision == ADOPT
    assert render_ledger_md(carried) == hand_signed
    assert not any(EfficiencySettings().model_dump().values())


def test_carrying_a_sign_off_forward_computes_nothing(tmp_path: Path) -> None:
    """A row nobody signed stays false; `compare` never derives a sign-off from a run."""
    dirs = write_study(tmp_path, study_specs(on=CHEAPER))
    rendered = render_ledger_md(compare_runs(dirs))

    carried = carry_sign_offs(compare_runs(dirs), rendered)

    row = lever_row(carried, "parallel_tool_calls")
    assert row.owner_signed_off is False
    assert row.owner_signed_off_at is None


def test_a_sign_off_cell_that_is_neither_yes_nor_no_is_refused(tmp_path: Path) -> None:
    dirs = write_study(tmp_path, study_specs(on=CHEAPER))
    rendered = render_ledger_md(compare_runs(dirs))

    with pytest.raises(CompareError) as excinfo:
        carry_sign_offs(compare_runs(dirs), rendered.replace("| adopt | no |", "| adopt | YES |"))

    assert "parallel_tool_calls" in str(excinfo.value)


def _document(rendered: str) -> str:
    return f"# head\n\n{LEDGER_BEGIN}\n\n{rendered}\n{LEDGER_END}\n\ntail\n"


def test_check_stays_green_on_a_hand_signed_document(tmp_path: Path) -> None:
    dirs = write_study(tmp_path, study_specs(on=CHEAPER))
    doc = tmp_path / "options.md"
    doc.write_text(_document(signed(render_ledger_md(compare_runs(dirs)))), encoding="utf-8")
    before = doc.read_text(encoding="utf-8")

    result = invoke(
        "benchmark", "compare", *[str(one) for one in dirs], "--into", str(doc), "--check"
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert doc.read_text(encoding="utf-8") == before


def test_regenerating_into_a_signed_document_keeps_the_sign_off(tmp_path: Path) -> None:
    dirs = write_study(tmp_path, study_specs(on=CHEAPER))
    doc = tmp_path / "options.md"
    doc.write_text(_document(signed(render_ledger_md(compare_runs(dirs)))), encoding="utf-8")
    before = doc.read_text(encoding="utf-8")

    result = invoke("benchmark", "compare", *[str(one) for one in dirs], "--into", str(doc))

    assert result.exit_code == 0, result.stdout + result.stderr
    assert doc.read_text(encoding="utf-8") == before
    assert "| adopt | yes | 2026-09-16 |" in before


def test_rewriting_the_out_directory_keeps_the_sign_off(tmp_path: Path) -> None:
    dirs = write_study(tmp_path, study_specs(on=CHEAPER))
    out = tmp_path / "ledger"
    args = ["benchmark", "compare", *[str(one) for one in dirs], "--out", str(out)]
    assert invoke(*args).exit_code == 0
    (out / LEDGER_MD).write_text(
        signed((out / LEDGER_MD).read_text(encoding="utf-8")), encoding="utf-8"
    )

    assert invoke(*args).exit_code == 0

    assert "| adopt | yes | 2026-09-16 |" in (out / LEDGER_MD).read_text(encoding="utf-8")
    payload = json.loads((out / LEDGER_JSON).read_text(encoding="utf-8"))
    assert payload["levers"][0]["owner_signed_off"] is True
    assert payload["levers"][0]["owner_signed_off_at"] == "2026-09-16"


# --- the record's cross-checks (feature 014 T064; `contracts/provenance.md` 2) --------------


def refusal_of(run_dirs: Sequence[Path]) -> str:
    """The one-line refusal `compare_runs` raises over `run_dirs`."""
    with pytest.raises(CompareError) as excinfo:
        compare_runs(run_dirs)
    return str(excinfo.value)


STANDARDS_FINDING = "F-001 (standards.document.data_card_complete)"
"""The first standards finding `RunSpec.standards_stamps` writes, as a refusal names it."""


@pytest.mark.parametrize(
    "written",
    [MODEL_VIEW_PANE.model_dump(), None],
    ids=["another-model-view", "no-model-view"],
)
def test_compare_refuses_a_session_whose_model_view_differs_from_the_record(
    tmp_path: Path, written: dict[str, Any] | None
) -> None:
    """PP-3: the runner writes the session's model view, `cli.py` the record's. A schema-2 record
    against a session with none is refused too: this build's runner always writes one."""
    run_dir = write_run(tmp_path, RunSpec(run="off-1"), session_edit={"model_view": written})

    message = refusal_of([run_dir])

    assert message.startswith(
        f"{run_dir} / rms-part: session.json and the provenance record disagree on model_view: "
    )
    assert repr(MODEL_VIEW_OFF) in message


def test_a_record_older_than_the_model_view_is_not_cross_checked_on_it(tmp_path: Path) -> None:
    """A schema-1 record recorded no model view (`contracts/provenance.md` 1: absent reads "not
    recorded"), so there is nothing to hold the session's against."""
    spec = RunSpec(run="off-1", provenance_schema=1, model_view=None)
    run_dir = write_run(tmp_path, spec, session_edit={"model_view": MODEL_VIEW_OFF.model_dump()})

    assert one_row(compare_runs([run_dir]), "off-1").package_id == "rms-part"


@pytest.mark.parametrize("old_form", [False, True], ids=["file-name-stamp", "path-stamp"])
def test_compare_refuses_a_standards_stamp_whose_digest_differs_from_the_record(
    tmp_path: Path, old_form: bool
) -> None:
    """US2-3: every standards finding stamps the profile it was graded against, read through
    `stamped_profile_digest` in either form, and it is the profile the record names."""
    spec = RunSpec(
        run="off-1",
        profile_digest=EXAMPLE_PROFILE_DIGEST,
        profile_is_example=True,
        standards_stamps=(profile_stamp(PRIVATE_PROFILE_DIGEST, old_form=old_form),),
    )
    run_dir = write_run(tmp_path, spec)

    assert refusal_of([run_dir]) == (
        f"{run_dir} / rms-part: {STANDARDS_FINDING} and the provenance record disagree on "
        f"profile_digest: {PRIVATE_PROFILE_DIGEST!r} against {EXAMPLE_PROFILE_DIGEST!r}"
    )


@pytest.mark.parametrize("old_form", [False, True], ids=["file-name-stamp", "path-stamp"])
def test_compare_refuses_a_stamp_on_a_run_that_recorded_no_profile(
    tmp_path: Path, old_form: bool
) -> None:
    spec = RunSpec(
        run="off-1", standards_stamps=(profile_stamp(EXAMPLE_PROFILE_DIGEST, old_form=old_form),)
    )
    run_dir = write_run(tmp_path, spec)

    assert refusal_of([run_dir]) == (
        f"{run_dir} / rms-part: {STANDARDS_FINDING} stamps the profile "
        f"{EXAMPLE_PROFILE_DIGEST!r}, but the provenance record recorded no profile"
    )


def test_stamps_of_the_recorded_profile_are_accepted_in_either_form(tmp_path: Path) -> None:
    spec = RunSpec(
        run="off-1",
        profile_digest=EXAMPLE_PROFILE_DIGEST,
        profile_is_example=True,
        standards_stamps=(
            profile_stamp(EXAMPLE_PROFILE_DIGEST),
            profile_stamp(EXAMPLE_PROFILE_DIGEST, old_form=True),
        ),
    )
    run_dir = write_run(tmp_path, spec)

    assert one_row(compare_runs([run_dir]), "off-1").package_id == "rms-part"


@pytest.mark.parametrize(
    ("package", "flag", "held"),
    [(PackageSpec(held_out=False), True, 0), (PackageSpec(held_out=True), False, 2)],
    ids=["marked-held-out-holding-none", "marked-tuned-on-holding-two"],
)
def test_compare_refuses_a_set_flag_that_disagrees_with_the_scored_items(
    tmp_path: Path, package: PackageSpec, flag: bool, held: int
) -> None:
    """RF-39: the flag is derived from the key, which compare never reads, so it reads the
    scorecard's copy of the key's tags, `graded_items`."""
    saved = [{"package_id": "rms-part", "path": "benchmarks/packages/rms-part", "held_out": flag}]
    run_dir = write_run(tmp_path, RunSpec(run="off-1", packages=(package,)), saved_packages=saved)

    assert refusal_of([run_dir]) == (
        f"{run_dir}: the saved set marks rms-part held_out={json.dumps(flag)}, but its scored "
        f"items hold {held} held-out items; the flag is derived from the key"
    )


def test_compare_refuses_a_scored_package_missing_from_the_saved_set(tmp_path: Path) -> None:
    """RF-62. A run with no saved copy runs neither set check, as it runs no digest check: the
    workstation harness writes none."""
    run_dir = write_run(tmp_path / "missing", RunSpec(run="off-1"), saved_packages=[])
    no_copy = write_run(tmp_path / "no-copy", RunSpec(run="off-1"), with_saved_set=False)

    assert refusal_of([run_dir]) == (
        f"{run_dir}: rms-part is scored but not in the run's saved set"
    )
    assert one_row(compare_runs([no_copy]), "off-1").held_out is True


def test_a_saved_entry_with_no_score_is_no_refusal(tmp_path: Path) -> None:
    """A package that failed has a saved entry and no `PackageScore` (`scoring.md` 7); `score`
    checked its flag against its key."""
    spec = RunSpec(run="off-1")
    failed = {"package_id": "rms-assembly", "path": "benchmarks/packages/rms-assembly"}
    run_dir = write_run(
        tmp_path, spec, saved_packages=[*saved_set_entries(spec), {**failed, "held_out": True}]
    )

    assert len(compare_runs([run_dir]).runs) == 1


def test_compare_reads_the_saved_set_against_the_root_read_at_call_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`compare_runs` and the command take the checkout root as a keyword, defaulting to
    `sets.REPO_ROOT` read at call time (`contracts/provenance.md` 6.1), so a test points both at
    a temporary checkout."""
    run_dir = write_run(tmp_path / "runs", RunSpec(run="smoke", arm=None, rep=None, lever="none"))
    roots: list[Path] = []
    load_saved_set = sets.load_saved_set

    def spy(path: Path | str, *, root: Path) -> Any:
        roots.append(root)
        return load_saved_set(path, root=root)

    monkeypatch.setattr(sets, "load_saved_set", spy)
    monkeypatch.setattr(sets, "REPO_ROOT", tmp_path / "checkout")

    compare_runs([run_dir])
    compare_runs([run_dir], root=tmp_path / "other")
    result = invoke("benchmark", "compare", str(run_dir), "--out", str(tmp_path / "ledger"))

    assert result.exit_code == 0, result.stdout + result.stderr
    assert roots == [tmp_path / "checkout", tmp_path / "other", tmp_path / "checkout"]


# --- what must match across a study (`contracts/provenance.md` 4) ------------------------------

MUST_MATCH_CHANGES: list[tuple[str, dict[str, Any], str]] = [
    ("commit", {"commit": "0e28d52"}, "commit"),
    ("effort", {"effort": "medium"}, "effort"),
    ("max_steps", {"max_steps": 20}, "max_steps"),
    ("checklist_digest", {"checklist_digest": "9" * 64}, "checklist_digest"),
    ("set_digest", {"set_digest": "9" * 64}, "set_digest"),
    ("set_too_small_override", {"set_too_small_override": True}, "set_too_small_override"),
    ("efficiency", {"other_levers": ("tool_tiers",)}, "efficiency.tool_tiers"),
    ("explanations_enabled", {"explanations_enabled": True}, "explanations_enabled"),
    ("provenance_schema", {"provenance_schema": 1}, "provenance_schema"),
    ("pane_defaults", {"pane_defaults": True}, "pane_defaults"),
    (
        "model_view",
        {"model_view": ModelViewSettings(payload_slimming=True, history_pruning=False)},
        "model_view",
    ),
    ("profile_digest", {"profile_digest": EXAMPLE_PROFILE_DIGEST}, "profile_digest"),
    ("profile_is_example", {"profile_is_example": True}, "profile_is_example"),
    ("inert_settings", {"inert_settings": ("parallel_tool_calls",)}, "inert_settings"),
    ("prompt_digest", {"prompt_digest": "9" * 64}, "prompt_digest"),
    ("tree_dirty", {"tree_dirty": True}, "tree_dirty"),
    ("max_answer_turns", {"max_answer_turns": 0}, "max_answer_turns"),
]
"""Each field a lever study holds equal, the change that moves it on one run, and the name its
refusal reads: `efficiency` flag by flag (`contracts/provenance.md` 4)."""

PAIRS = {
    "across-the-arms": (RunSpec(run="off-1", arm="off", rep=1), RunSpec(run="on-1", arm="on")),
    "within-an-arm": (RunSpec(run="off-1", arm="off", rep=1), RunSpec(run="off-2", rep=2)),
}
"""Two runs of one lever study: an off and an on run, and two off runs. Each run is held against
the first run of its own arm, and the first of each arm against the study's first."""


def recorded(spec: RunSpec, name: str) -> Any:
    """The value a refusal quotes for `name` off this spec's record."""
    record = spec.provenance()
    if name.startswith("efficiency."):
        return getattr(record.efficiency, name.removeprefix("efficiency."))
    return getattr(record, name)


@pytest.mark.parametrize("pair", PAIRS)
@pytest.mark.parametrize(
    ("field", "change", "named"), MUST_MATCH_CHANGES, ids=[one[0] for one in MUST_MATCH_CHANGES]
)
def test_runs_of_one_study_differing_in_any_must_match_field_are_refused_naming_it(
    tmp_path: Path, pair: str, field: str, change: dict[str, Any], named: str
) -> None:
    """US2-6: the first differing field and both values, in the existing message's shape. With
    no saved copy, so the record's `set_digest` is the only one (the copy's own digest check
    would otherwise refuse the edited one first)."""
    first, second = PAIRS[pair]
    second = replace(second, **change)
    dirs = write_study(tmp_path, [first, second], with_saved_set=False)

    assert refusal_of(dirs) == (
        f"{dirs[0]} and {dirs[1]} cannot be placed in one comparison: {named} differs "
        f"({recorded(first, named)!r} against {recorded(second, named)!r})"
    )


def test_the_must_match_cases_name_every_field_a_lever_study_holds_equal() -> None:
    """A field added to the record must-matches until exempted by name, and gets a case here."""
    assert [field for field, _, _ in MUST_MATCH_CHANGES] == [
        name for name in RunProvenance.model_fields if name in (*MUST_MATCH, *ACROSS_PANE_ARMS)
    ]


def test_the_provenance_fields_are_partitioned_into_must_match_and_named_exemptions() -> None:
    """Every field in exactly one set, and each exemption pinned by name (`contracts/provenance.md`
    4's table), so none is added without this test moving."""
    named = (MUST_MATCH, RUN_IDENTITY, RECORD_ONLY, STUDY_KEY_FIELDS, ACROSS_ARMS, ACROSS_PANE_ARMS)

    assert Counter(name for one in named for name in one) == Counter(
        list(RunProvenance.model_fields)
    )
    assert RUN_IDENTITY == ("rep", "started_at")
    assert RECORD_ONLY == ("live_tools",)
    assert STUDY_KEY_FIELDS == ("lever", "provider", "model")
    assert ACROSS_ARMS == ("arm",)
    assert ACROSS_PANE_ARMS == ("efficiency", "model_view", "pane_defaults")


def test_a_lever_studys_off_and_on_runs_pass_the_must_match_loop(tmp_path: Path) -> None:
    """RF-10: the two arms share one study key and differ in `arm` and the studied lever's flag,
    both exempt across the arms; another lever held on in both arms is no difference."""
    held_on = {"other_levers": ("tool_tiers",)}
    dirs = write_study(tmp_path, study_specs(off=held_on, on={**held_on, **CHEAPER}))

    row = lever_row(compare_runs(dirs), "parallel_tool_calls")

    assert row.decision == ADOPT
    assert row.other_levers_on == ["tool_tiers"]


def test_repetition_start_time_and_live_tools_never_refuse(tmp_path: Path) -> None:
    """US2-6, PP-9: run identity and the record-only field move from run to run, within an arm
    and across the arms, and refuse nothing."""
    live = (None, True, False, True, None, False)
    specs = [
        replace(spec, started_at=STARTED_AT + timedelta(hours=index), live_tools=live[index])
        for index, spec in enumerate(study_specs(on=CHEAPER))
    ]
    dirs = write_study(tmp_path, specs)

    assert lever_row(compare_runs(dirs), "parallel_tool_calls").decision == ADOPT


def with_a_case_file(spec: RunSpec, case_file_sha256: str) -> list[dict[str, Any]]:
    """The saved set's entries for `spec`, each naming its committed case file and carrying
    `case_file_sha256`, as a run of the scripted-answers slice saves them."""
    return [
        {
            **entry,
            "case_file": f"benchmarks/case_files/{entry['package_id']}.json",
            "case_file_sha256": case_file_sha256,
        }
        for entry in saved_set_entries(spec)
    ]


def test_a_study_whose_arms_read_different_case_file_bytes_is_refused_naming_set_digest(
    tmp_path: Path,
) -> None:
    """US4-6, QA-7: the saved sets differ only in one case file's digest, which reaches each
    record's `set_digest`, so the existing rule refuses the study with no second must-match
    field."""
    off, on = RunSpec(run="off-1", arm="off", rep=1), RunSpec(run="on-1", arm="on")
    dirs = [
        write_run(tmp_path, off, saved_packages=with_a_case_file(off, "a" * 64)),
        write_run(tmp_path, on, saved_packages=with_a_case_file(on, "b" * 64)),
    ]
    digests = [
        json.loads((run_dir / PROVENANCE_FILE).read_text(encoding="utf-8"))["set_digest"]
        for run_dir in dirs
    ]

    assert refusal_of(dirs) == (
        f"{dirs[0]} and {dirs[1]} cannot be placed in one comparison: set_digest differs "
        f"({digests[0]!r} against {digests[1]!r})"
    )


@pytest.mark.parametrize("pair", sorted(PAIRS))
def test_a_record_older_than_the_bound_against_one_recording_3_reads_not_recorded(
    tmp_path: Path, pair: str
) -> None:
    """D14.3, owner decision 47A: a record written before `max_answer_turns` holds none, which
    reads "not recorded" in the refusal, never 3 and never `None`. The field is the one
    `NOT_RECORDED_WHEN_ABSENT` names, beside the exemptions; every other field's value is quoted
    as it is (the must-match cases above quote a profile digest's `None`)."""
    first, second = PAIRS[pair]
    dirs = write_study(tmp_path, [replace(first, max_answer_turns=None), second])

    assert "max_answer_turns" not in json.loads(
        (dirs[0] / PROVENANCE_FILE).read_text(encoding="utf-8")
    )
    assert refusal_of(dirs) == (
        f"{dirs[0]} and {dirs[1]} cannot be placed in one comparison: max_answer_turns differs "
        "(not recorded against 3)"
    )
    assert NOT_RECORDED_WHEN_ABSENT == ("max_answer_turns",)


def test_a_lever_study_whose_arms_differ_in_another_lever_is_refused(tmp_path: Path) -> None:
    """Section 3.4: every lever but the studied one is held equal across the arms, which the
    ab-harness contract stated and nothing checked."""
    dirs = write_study(
        tmp_path, study_specs(reps=1, on={"other_levers": ("tool_tiers",), **CHEAPER})
    )

    assert refusal_of(dirs) == (
        f"{dirs[0]} and {dirs[1]} cannot be placed in one comparison: efficiency.tool_tiers "
        "differs (False against True)"
    )


# --- the pane studies (`contracts/provenance.md` 3.2) -----------------------------------------


def test_the_pane_study_arms_may_differ_only_in_levers_model_view_and_the_marker(
    tmp_path: Path,
) -> None:
    """US2-4, D5: the on arm's levers, model view and marker are not the off arm's, and the study
    renders its raw rows and no decision row, `decide` never applying to it (FR-045)."""
    dirs = write_study(tmp_path, pane_study_specs())

    ledger = compare_runs(dirs)

    assert len(ledger.runs) == 6
    assert {row.lever for row in ledger.runs} == {PANE_STUDY}
    assert ledger.levers == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("commit", "0e28d52"),
        ("prompt_digest", "9" * 64),
        ("profile_digest", "f" * 64),
        ("set_too_small_override", True),
    ],
)
def test_the_pane_study_arms_match_in_everything_else(
    tmp_path: Path, field: str, value: Any
) -> None:
    dirs = write_study(tmp_path, pane_study_specs(reps=1, on={field: value}))

    assert f": {field} differs (" in refusal_of(dirs)


def test_the_pane_study_refuses_unequal_explanation_settings(tmp_path: Path) -> None:
    """US2-4, PP-2: typed in both arms and held equal."""
    dirs = write_study(tmp_path, pane_study_specs(reps=1, off={"explanations": False}))

    assert refusal_of(dirs) == (
        f"{dirs[0]} and {dirs[1]} cannot be placed in one comparison: explanations_enabled "
        "differs (False against True)"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("efficiency", EfficiencySettings(prerun_checks=True)),
        ("model_view", ModelViewSettings(payload_slimming=True, history_pruning=False)),
    ],
)
def test_two_runs_of_one_pane_arm_may_not_differ_in_the_pane_settings(
    tmp_path: Path, field: str, value: Any
) -> None:
    """What the pane study's arms may differ in, its runs of one arm may not: each run is held
    against the first run of its own arm with no arm exemption."""
    specs = pane_study_specs(reps=2)
    specs[3] = replace(specs[3], **{field: value})
    dirs = write_study(tmp_path, specs)

    message = refusal_of(dirs)

    assert message.startswith(f"{dirs[1]} and {dirs[3]} cannot be placed in one comparison: ")
    assert f": {field}" in message


@pytest.mark.parametrize(
    ("change", "named"),
    [
        ({"pane_defaults": True}, "pane_defaults"),
        ({"other_levers": ("prerun_checks",)}, "prerun_checks"),
        ({"model_view": MODEL_VIEW_PANE}, "model_view"),
    ],
    ids=["the-marker", "a-lever", "the-model-view"],
)
def test_an_off_arm_with_any_change_is_refused(
    tmp_path: Path, change: dict[str, Any], named: str
) -> None:
    """PP-3: every lever off, `MODEL_VIEW_OFF` and the marker false, against those constants."""
    run_dir = write_run(tmp_path, pane_run_spec("off-1", "off", 1, **change))

    assert refusal_of([run_dir]) == (
        f"{run_dir} / rms-part: the off arm of {PANE_STUDY} has every change off, but {named} "
        "is on"
    )


def test_an_on_arm_without_the_marker_is_refused(tmp_path: Path) -> None:
    run_dir = write_run(tmp_path, pane_run_spec("on-1", "on", 1, pane_defaults=False))

    assert refusal_of([run_dir]) == (
        f"{run_dir} / rms-part: the on arm of {PANE_STUDY} is exactly --pane-defaults, but its "
        "record carries pane_defaults false"
    )


def test_an_on_arm_with_every_setting_off_is_refused_as_mislabelled(tmp_path: Path) -> None:
    """PP-3: it would measure nothing. Checked against the constants, never re-derived from
    today's `pane_defaults()`, so a recorded study survives the defaults changing."""
    spec = pane_run_spec(
        "on-1", "on", 1, efficiency=EfficiencySettings(), model_view=MODEL_VIEW_OFF
    )
    run_dir = write_run(tmp_path, spec)

    assert refusal_of([run_dir]) == (
        f"{run_dir} / rms-part: the on arm of {PANE_STUDY} has every lever off and the model "
        "view off: mislabelled, it would measure nothing"
    )


@pytest.mark.parametrize("study", [PANE_STUDY, PRIVATE_PANE_STUDY])
def test_a_run_of_either_pane_study_with_no_arm_is_refused(tmp_path: Path, study: str) -> None:
    """A run-level refusal, read off the record, which aborts the ledger."""
    spec = replace(pane_run_spec("off-1", "off", 1, study=study), arm=None, rep=None)
    run_dir = write_run(tmp_path, spec)

    assert refusal_of([run_dir]) == (
        f"{run_dir}: a run of the {study} study has no arm; name the arm: on or off"
    )


@pytest.mark.parametrize("is_example", [False, None])
def test_a_pane_defaults_run_whose_profile_is_not_the_example_is_refused(
    tmp_path: Path, is_example: bool | None
) -> None:
    """Every committed case is keyed against the example (FR-027); the private study takes the
    real profile and is not refused for it."""
    run_dir = write_run(tmp_path, pane_run_spec("off-1", "off", 1, profile_is_example=is_example))

    assert refusal_of([run_dir]) == (
        f"{run_dir}: a {PANE_STUDY} run grades against the checkout's example profile, and this "
        f"one recorded profile_is_example {is_example!r}"
    )


def test_the_private_pane_study_is_its_own_key_and_renders_as_raw_rows(tmp_path: Path) -> None:
    """23A: one provider and one model, two study keys. One study would be refused: the pairs
    differ in the profile's digest and its likeness to the example, which must match."""
    committed = write_study(tmp_path / "committed", pane_study_specs(reps=1))
    private = write_study(
        tmp_path / "private", pane_study_specs(study=PRIVATE_PANE_STUDY, reps=1)
    )

    ledger = compare_runs([*committed, *private])

    assert sorted(row.lever for row in ledger.runs) == [
        PANE_STUDY,
        PANE_STUDY,
        PRIVATE_PANE_STUDY,
        PRIVATE_PANE_STUDY,
    ]
    assert ledger.levers == []


@pytest.mark.parametrize(
    ("provider", "differed", "inert"),
    [
        (
            "openai",
            (
                "prerun_checks",
                "parallel_tool_calls",
                "withhold_prerun_tools",
                "drop_prior_reasoning",
                "payload_slimming",
                "history_pruning",
            ),
            (),
        ),
        (
            "gemini",
            (
                "prerun_checks",
                "withhold_prerun_tools",
                "drop_prior_reasoning",
                "payload_slimming",
                "history_pruning",
            ),
            ("parallel_tool_calls", "drop_prior_reasoning"),
        ),
    ],
)
def test_settings_differed_returns_the_differing_and_the_inert_settings(
    provider: str, differed: tuple[str, ...], inert: tuple[str, ...]
) -> None:
    """US2-8, FR-052: an OpenAI pane study differs in six settings that act; a Gemini one in five
    recorded settings, of which dropped reasoning is inert, and names parallel calls inert too,
    recorded off in both arms and made in parallel in both (D14.5)."""
    off, on = pane_study_specs(provider=provider, reps=1)

    settings = settings_differed(off.provenance(), on.provenance())

    assert settings.arms_differed_in == differed
    assert settings.inert == inert


# --- the baselines (`contracts/provenance.md` 3.3) --------------------------------------------


def test_a_pane_baseline_and_a_plain_baseline_are_two_rows_with_two_sign_offs(
    tmp_path: Path,
) -> None:
    """US2-5, PP-4: two study keys, `none` and `none (pane defaults)`, each a distribution and no
    decision, each carrying its own sign-off."""
    plain = [
        RunSpec(run=f"baseline-{rep}", arm="baseline", rep=rep, lever="none") for rep in (1, 2)
    ]
    pane = [pane_baseline_spec(f"pane-baseline-{rep}", rep) for rep in (1, 2)]
    ledger = compare_runs(write_study(tmp_path, [*plain, *pane]))

    plain_row, pane_row = lever_row(ledger, "none"), lever_row(ledger, "none (pane defaults)")
    assert (plain_row.decision, pane_row.decision) == (None, None)
    assert plain_row.decision_reason.startswith(BASELINE)
    assert pane_row.decision_reason.startswith(BASELINE)
    assert pane_row.lever_counter.name == plain_row.lever_counter.name
    assert len(ledger.runs) == 4

    rendered = render_ledger_md(ledger)
    line = next(one for one in rendered.splitlines() if one.startswith("| none (pane defaults) |"))
    hand_signed = rendered.replace(
        line, line.replace("| unknown | no | unknown |", "| unknown | yes | 2026-10-07 |")
    )
    assert hand_signed != rendered
    carried = carry_sign_offs(ledger, hand_signed)
    assert lever_row(carried, "none (pane defaults)").owner_signed_off is True
    assert lever_row(carried, "none").owner_signed_off is False


def test_a_plain_baseline_with_a_model_view_switch_is_refused(tmp_path: Path) -> None:
    """Checked as every flag off and `MODEL_VIEW_OFF`."""
    spec = RunSpec(
        run="baseline-1", arm="baseline", lever="none", model_view=MODEL_VIEW_PANE
    )
    run_dir = write_run(tmp_path, spec)

    assert refusal_of([run_dir]) == (
        f"{run_dir} / rms-part: a baseline run has the model view off, but it is "
        f"{MODEL_VIEW_PANE!r}; the pane baseline is --arm baseline --pane-defaults"
    )


def test_a_pane_baseline_with_every_setting_off_is_refused_as_mislabelled(
    tmp_path: Path,
) -> None:
    """Checked by its marker and settings that are not all off."""
    spec = pane_baseline_spec(
        "pane-baseline-1", 1, efficiency=EfficiencySettings(), model_view=MODEL_VIEW_OFF
    )
    run_dir = write_run(tmp_path, spec)

    assert refusal_of([run_dir]) == (
        f"{run_dir} / rms-part: a pane baseline carries pane_defaults, but every lever and the "
        "model view are off: mislabelled, it would measure the plain baseline"
    )


@pytest.mark.parametrize(
    "spec",
    [
        pytest.param(
            pane_baseline_spec("baseline-1", 1, lever="tool_tiers"), id="pane-baseline-a-lever"
        ),
        pytest.param(
            pane_baseline_spec("baseline-1", 1, lever=PANE_STUDY, profile_is_example=True),
            id="pane-baseline-the-pane-study",
        ),
        pytest.param(
            RunSpec(run="baseline-1", arm="baseline", rep=1, lever="tool_tiers"),
            id="plain-baseline-a-lever",
        ),
    ],
)
def test_a_baseline_record_naming_a_lever_is_refused_as_inconsistent(
    tmp_path: Path, spec: RunSpec
) -> None:
    """Section 3.3: a baseline's label is read off its arm and its marker alone, so a record with
    arm baseline and a lever other than none is refused as inconsistent, as `--arm baseline` with
    a study is at run time, rather than labelled: the pane baseline's label would drop the lever,
    and a plain baseline's would place the run in that lever's study, read as its off arm."""
    run_dir = write_run(tmp_path, spec)

    assert refusal_of([run_dir]) == (
        f"{run_dir}: arm baseline with lever {spec.lever!r}: a baseline run is the study with no "
        "lever under test, so its lever is none; the record is inconsistent"
    )


SMOKE = RunSpec(run="smoke", arm=None, rep=None, lever="none")


@pytest.mark.parametrize(
    "spec",
    [
        replace(SMOKE, model_view=MODEL_VIEW_PANE),
        replace(pane_baseline_spec("smoke", 1), arm=None, rep=None),
        replace(SMOKE, other_levers=("tool_tiers",)),
    ],
    ids=["a-model-view-switch", "pane-defaults", "a-lever"],
)
def test_a_no_study_run_with_a_model_view_switch_renders_as_a_raw_row(
    tmp_path: Path, spec: RunSpec
) -> None:
    """Section 3.3: the baseline branch applies to `arm == "baseline"` only, so a no-study smoke
    run is a raw row whatever it switched on, as any run with no arm is."""
    ledger = compare_runs([write_run(tmp_path, spec)])

    assert one_row(ledger, "smoke").arm is None
    assert ledger.levers == []


# --- the ledger 1.1 (feature 014 T066; `contracts/provenance.md` 5, 6.3 and 6.4) -------------


def test_the_run_and_decision_columns_are_section_5s_final_order() -> None:
    """INT-10: both headers pinned whole, in the order fixed up front, so a later slice cannot
    insert a column without failing this, and the committed header is regenerated once. No
    run-status column: its source arrives with the robustness slice."""
    assert RUN_COLUMNS == (
        "run",
        "commit",
        "lever",
        "arm",
        "rep",
        "provider",
        "model",
        "effort",
        "explanations",
        "model view",
        "profile",
        "live tools",
        "package",
        "input",
        "cached in",
        "uncached in",
        "output",
        "reasoning/thoughts",
        "tool-result in",
        "total",
        "rounds",
        "tool calls",
        "cached share",
        "wall clock s",
        "s to 1st finding",
        "valid",
        "missed",
        "flagged",
        "below expected",
        "status mismatch",
        "cleared",
        "false alarms",
        "contradicted",
        "confirmed",
        "unresolved",
        "unresolved withheld",
        "unresolved other",
        "coverage bucket mix",
        "findings by origin",
        "false alarms by origin",
    )
    assert LEVER_COLUMNS == (
        "Lever",
        "Provider and model",
        "Commit",
        "Reps",
        "Other levers on",
        "Input tokens off -> on (median, min-max)",
        "Cached input off -> on",
        "Output off -> on",
        "Reasoning or thoughts off -> on",
        "Total tokens off -> on",
        "Round trips off -> on",
        "Tool calls off -> on",
        "Wall clock off -> on",
        "Dump wall clock off -> on",
        "Valid / missed / false alarms / unresolved off -> on",
        "Recall (held out) off -> on",
        "Recall by producer (held out) off -> on",
        "Median net saved minutes off -> on",
        "Worst-case defects lost",
        "Lever-specific counter",
        "Decision",
        "Owner signed off",
        "Owner signed off at",
        "Decision reason",
        "Link to run dirs",
    )
    lines = render_ledger_md(compare_runs([])).splitlines()
    assert "| " + " | ".join(RUN_COLUMNS) + " |" in lines
    assert "| " + " | ".join(LEVER_COLUMNS) + " |" in lines


def test_the_ledger_record_is_schema_1_1_and_names_no_pane_study_when_none_was_compared(
    tmp_path: Path,
) -> None:
    """One bump (INT-10). The 1.1 record names `pane_studies`, a key omitted when no pane study
    was compared and filled from the verdict slice, which moves neither the version nor the
    header; until then a pane study renders raw rows only."""
    dirs = write_study(tmp_path, pane_study_specs(reps=1))

    json_path, _ = write_ledger(compare_runs(dirs), tmp_path / "ledger")

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["ledger_schema"] == "1.1"
    assert "pane_studies" not in payload


def test_the_closing_notes_say_tool_calls_counts_the_pre_run_and_regrade_steps() -> None:
    """INT-10: `tool calls` stays `len(session.steps)`, not split by the step mark, and the
    ledger says what it counts."""
    rendered = render_ledger_md(compare_runs([]))

    note = next(line for line in rendered.splitlines() if line.startswith("`tool calls`"))
    assert "`len(session.steps)`" in note
    assert "pre-run" in note
    assert "regrade" in note


def rescored(run_dir: Path, **fields: Any) -> Path:
    """Rewrite the one package score of the run at `run_dir` with `fields`: the outcome lists a
    hand-built score leaves empty (`studies.package_score`). Returns `run_dir`."""
    path = run_dir / SCORECARD_FILE
    card = Scorecard.model_validate_json(path.read_text(encoding="utf-8"))
    [score] = card.per_package
    edited = card.model_copy(update={"per_package": [score.model_copy(update=fields)]})
    path.write_text(edited.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return run_dir


def numbered(prefix: str, count: int) -> list[str]:
    """`count` key ids, `<prefix>1` onwards."""
    return [f"{prefix}{number}" for number in range(1, count + 1)]


OUTCOMES: dict[str, Any] = {
    "flagged_defect_ids": numbered("D-", 1),
    "flagged_below_expected_defect_ids": numbered("D-", 2),
    "status_mismatch_defect_ids": numbered("D-", 3),
    "cleared_defect_ids": numbered("D-", 4),
    "contradicted_condition_ids": numbered("C-", 5),
    "confirmed_condition_ids": numbered("C-", 6),
    "false_alarms": 2,
    "false_alarm_finding_ids": ["F-004", "F-005"],
    "finding_origins": {
        "F-001": "prerun",
        "F-002": "prerun",
        "F-003": "prerun",
        "F-004": "configured_check",
        "F-005": "model",
    },
    "not_assessed": {},
}
"""One package's outcome columns, each count distinct so a swapped cell fails."""


def test_the_ledger_shows_model_view_profile_and_live_tools(tmp_path: Path) -> None:
    """US2-3, PP-7 (`contracts/provenance.md` 5): the model view from the session, `off` for
    `MODEL_VIEW_OFF` and for a view with both switches off, `pane` for `MODEL_VIEW_PANE`,
    otherwise its switches; the profile through `display_digest`, `none` with no profile and
    `unknown` with no record; live tools `yes`, `no` or `unknown`. Beside them the scorer's outcome
    columns: the origin cells as mixes in `Origin`'s order with zero origins left out, `none` when
    every origin is zero, and a column the key does not grade reading `not assessed`."""
    smoke = {"arm": None, "rep": None, "lever": "none"}
    specs = [
        RunSpec(run="view-off", **smoke),
        RunSpec(run="view-pane", model_view=MODEL_VIEW_PANE, **smoke),
        RunSpec(
            run="view-slimming",
            model_view=ModelViewSettings(payload_slimming=True, history_pruning=False),
            **smoke,
        ),
        RunSpec(
            run="view-pruning",
            model_view=ModelViewSettings(
                payload_slimming=False, history_pruning=True, prune_after_rounds=3
            ),
            **smoke,
        ),
        RunSpec(
            run="view-both",
            model_view=ModelViewSettings(
                payload_slimming=True, history_pruning=True, prune_after_rounds=1
            ),
            **smoke,
        ),
        RunSpec(
            run="view-no-switch",
            model_view=ModelViewSettings(
                payload_slimming=False, history_pruning=False, prune_after_rounds=5
            ),
            **smoke,
        ),
        RunSpec(
            run="profiled",
            profile_digest=EXAMPLE_PROFILE_DIGEST,
            profile_is_example=True,
            live_tools=True,
            **smoke,
        ),
        RunSpec(run="live-unknown", live_tools=None, **smoke),
        RunSpec(run="no-false-alarm", packages=(PackageSpec(false_alarms=0),), **smoke),
    ]
    dirs = [write_run(tmp_path, spec) for spec in specs]
    dirs.append(write_run(tmp_path, RunSpec(run="no-record", **smoke), with_provenance=False))
    dirs.append(rescored(write_run(tmp_path, RunSpec(run="outcomes", **smoke)), **OUTCOMES))

    ledger = compare_runs(dirs)
    rendered = render_ledger_md(ledger)

    cells = {row.run: cells_of(rendered, row.run) for row in ledger.runs}
    views = {run: cells[run]["model view"] for run in cells if run.startswith("view-")}
    assert views == {
        "view-off": "off",
        "view-pane": "pane",
        "view-slimming": "slimming",
        "view-pruning": "pruning after 3",
        "view-both": "slimming, pruning after 1",
        "view-no-switch": "off",
    }
    assert one_row(ledger, "view-pruning").model_view == specs[3].model_view
    assert one_row(ledger, "profiled").profile_digest == EXAMPLE_PROFILE_DIGEST
    assert cells["profiled"]["profile"] == display_digest(EXAMPLE_PROFILE_DIGEST)
    assert len(cells["profiled"]["profile"]) == 12
    assert cells["view-off"]["profile"] == "none"
    assert cells["no-record"]["profile"] == UNKNOWN
    assert one_row(ledger, "no-record").profile_digest is None
    assert [cells[run]["live tools"] for run in ("profiled", "view-off", "live-unknown")] == [
        "yes",
        "no",
        UNKNOWN,
    ]
    assert cells["no-record"]["live tools"] == UNKNOWN
    assert one_row(ledger, "view-pane").pane_defaults is False
    assert one_row(ledger, "no-record").pane_defaults is None

    outcomes = cells["outcomes"]
    assert {name: outcomes[name] for name in RUN_COLUMNS[RUN_COLUMNS.index("valid") :]} == {
        "valid": "2",
        "missed": "0",
        "flagged": "1",
        "below expected": "2",
        "status mismatch": "3",
        "cleared": "4",
        "false alarms": "2",
        "contradicted": "5",
        "confirmed": "6",
        "unresolved": "3",
        "unresolved withheld": "0",
        "unresolved other": "3",
        "coverage bucket mix": "checked 2 / skipped 0 / unresolved 3 / failed 0 / out_of_scope 0",
        "findings by origin": "prerun 3 / configured_check 1 / model 1",
        "false alarms by origin": "configured_check 1 / model 1",
    }
    plain = cells["view-off"]
    assert (plain["contradicted"], plain["confirmed"]) == (NOT_ASSESSED, NOT_ASSESSED)
    assert (plain["findings by origin"], plain["false alarms by origin"]) == (
        "unknown 1",
        "unknown 1",
    )
    assert one_row(ledger, "view-off").contradictions is None
    assert one_row(ledger, "outcomes").contradictions == 5
    nothing = cells["no-false-alarm"]
    assert (nothing["findings by origin"], nothing["false alarms by origin"]) == ("none", "none")


def test_the_origin_cells_go_through_the_scorecards_one_origin_formatter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ledger's two origin cells and the scorecard's origin line are one formatter,
    `scorecard.fmt_origins`, the separator its one difference: a spy where compare looks it up
    sees both cells, each with the ledger's `/`."""
    seen: list[tuple[str, str]] = []
    real = scorecard_module.fmt_origins

    def spy(counts: Any, *, separator: str) -> str:
        formatted = real(counts, separator=separator)
        seen.append((formatted, separator))
        return formatted

    monkeypatch.setattr("swreview.benchmark.compare.fmt_origins", spy)
    run_dir = rescored(
        write_run(tmp_path, RunSpec(run="outcomes", arm=None, rep=None, lever="none")),
        **OUTCOMES,
    )

    cells = cells_of(render_ledger_md(compare_runs([run_dir])), "outcomes")

    assert seen == [
        ("prerun 3 / configured_check 1 / model 1", " / "),
        ("configured_check 1 / model 1", " / "),
    ]
    origin_cells = (cells["findings by origin"], cells["false alarms by origin"])
    assert origin_cells == (seen[0][0], seen[1][0])


def test_the_origin_cells_count_the_final_state_never_a_withdrawn_hit(tmp_path: Path) -> None:
    """`finding_origins` also names each withdrawn forbidden hit (`scoring.md` 5.5); the row
    counts findings by origin as the scorer's aggregate does, over the final state alone (T087),
    so the withdrawn `F-006` moves neither origin cell."""
    run_dir = rescored(
        write_run(tmp_path, RunSpec(run="withdrawn", arm=None, rep=None, lever="none")),
        **{
            **OUTCOMES,
            "forbidden_hit_finding_ids": [],
            "withdrawn_forbidden_hit_finding_ids": ["F-006"],
            "finding_origins": {**OUTCOMES["finding_origins"], "F-006": "code_only_call"},
        },
    )

    ledger = compare_runs([run_dir])

    row = one_row(ledger, "withdrawn")
    assert row.findings_by_origin["code_only_call"] == 0
    assert sum(row.findings_by_origin.values()) == 5
    assert row.false_alarms_by_origin["code_only_call"] == 0
    cells = cells_of(render_ledger_md(ledger), "withdrawn")
    assert cells["findings by origin"] == "prerun 3 / configured_check 1 / model 1"
    assert cells["false alarms by origin"] == "configured_check 1 / model 1"


def test_a_row_whose_session_predates_the_model_view_reads_off(tmp_path: Path) -> None:
    """`MODEL_VIEW_OFF` is what a session written before feature 008 means
    (`agent/settings.py`), so its row's model view is that constant and reads `off`. Its record,
    older than feature 014's fields, recorded no profile and no live tools: both read `unknown`,
    never `none` or `no`."""
    spec = RunSpec(
        run="ancient-view",
        provenance_schema=1,
        model_view=None,
        live_tools=None,
        inert_settings=None,
        prompt_digest=None,
        tree_dirty=None,
    )
    run_dir = write_run(tmp_path, spec, session_edit={"model_view": None})

    ledger = compare_runs([run_dir])

    assert one_row(ledger, "ancient-view").model_view == MODEL_VIEW_OFF
    cells = cells_of(render_ledger_md(ledger), "ancient-view")
    assert (cells["model view"], cells["profile"], cells["live tools"]) == ("off", UNKNOWN, UNKNOWN)


def test_the_decision_row_reports_recall_by_producer_held_out(tmp_path: Path) -> None:
    """SP-13 A: recall of the held-out known defects per producer, off -> on, reported beside
    the overall recall and never gated on; a producer the keys hold no held-out defect of reads
    unknown."""
    dirs = write_study(tmp_path, study_specs(on=CHEAPER))

    ledger = compare_runs(dirs)

    row = lever_row(ledger, "parallel_tool_calls")
    assert (row.recall_held_out_model.off_median, row.recall_held_out_model.on_median) == (1, 1)
    assert row.recall_held_out_code.off_rows == row.recall_held_out_code.on_rows == 0
    cell = lever_cells_of(render_ledger_md(ledger), "parallel_tool_calls")[
        "Recall by producer (held out) off -> on"
    ]
    assert cell == (
        "model: 1 (1-1, n=3) -> 1 (1-1, n=3), +0.0% ; "
        "code: unknown (unknown-unknown, n=0) -> unknown (unknown-unknown, n=0), unknown"
    )
    assert row.decision == ADOPT


COMMITTED_LEDGER_REFUSAL = (
    "the committed ledger holds only fictional-profile studies over committed cases, from run "
    "folders the repository holds (FR-051): render {run} with --out outside the repository"
)


def committed_ledger_refusal(run_dir: Path) -> str:
    """The one line the command prints refusing `run_dir` for the committed ledger."""
    return "error: CompareError: " + COMMITTED_LEDGER_REFUSAL.format(run=run_dir)

IGNORED_RUNS = "ignored-runs"
"""A folder the temporary checkout's `.gitignore` ignores."""


def committed_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """A temporary checkout the command is pointed at through `sets.REPO_ROOT`, a git repository
    ignoring `IGNORED_RUNS` where git is on the path, holding a ledger document inside it, so
    committable; returns the checkout and the document."""
    root = tmp_path / "checkout"
    document = root / "docs" / "llm-efficiency-options.md"
    document.parent.mkdir(parents=True)
    document.write_text(_document(render_ledger_md(compare_runs([]))), encoding="utf-8")
    (root / ".gitignore").write_text(f"{IGNORED_RUNS}/\n", encoding="utf-8")
    if shutil.which("git") is not None:
        git(root, "init", "-q")
    monkeypatch.setattr(sets, "REPO_ROOT", root)
    return root, document


def guarded_runs(root: Path, tmp_path: Path) -> tuple[list[Path], list[Path]]:
    """The runs the committed ledger refuses and the ones it takes, as `write_run` lays them out:
    another profile than the example, a saved set naming an absolute path, a package's or only a
    case file's, and a folder outside the checkout; no profile, and the example profile, inside
    it."""
    studies = root / "benchmarks" / "studies" / "smoke"
    private = (tmp_path / "private" / "rms-part").as_posix()
    private_case_file = (tmp_path / "private" / "rms-part.json").as_posix()
    refused = [
        write_run(
            studies,
            replace(
                SMOKE,
                run="another-profile",
                profile_digest=PRIVATE_PROFILE_DIGEST,
                profile_is_example=False,
            ),
        ),
        write_run(
            studies,
            replace(SMOKE, run="private-package"),
            saved_packages=[{"package_id": "rms-part", "path": private, "held_out": True}],
        ),
        write_run(
            studies,
            replace(SMOKE, run="private-case-file"),
            saved_packages=[
                {
                    "package_id": "rms-part",
                    "path": "benchmarks/packages/rms-part",
                    "case_file": private_case_file,
                    "case_file_sha256": "0" * 64,
                    "held_out": True,
                }
            ],
        ),
        write_run(tmp_path / "elsewhere", replace(SMOKE, run="outside")),
    ]
    accepted = [
        write_run(studies, replace(SMOKE, run="no-profile")),
        write_run(
            studies,
            replace(
                SMOKE,
                run="example-profile",
                profile_digest=EXAMPLE_PROFILE_DIGEST,
                profile_is_example=True,
            ),
        ),
    ]
    return refused, accepted


def compare_into(run_dirs: Sequence[Path], *destination: str) -> Any:
    return invoke("benchmark", "compare", *[str(one) for one in run_dirs], *destination)


def test_the_committed_ledger_refuses_another_profile_a_private_package_and_an_outside_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """US2-10, FR-051 (`contracts/provenance.md` 6.4): with `--into` or `--out` somewhere the
    repository may commit, and under `--check` too, a run graded against a profile other than the
    fictional example, one whose saved set names an absolute path (a package's, or the case file
    of a committed package) and one whose folder the repository does not hold are each refused,
    exit 1, before anything is written. A run with no
    profile graded against none and is not refused, nor is one graded against the example."""
    root, document = committed_checkout(tmp_path, monkeypatch)
    refused, accepted = guarded_runs(root, tmp_path)
    before = document.read_text(encoding="utf-8")
    out = root / "ledger"

    for run_dir in refused:
        for destination in (
            ("--into", str(document)),
            ("--into", str(document), "--check"),
            ("--out", str(out)),
        ):
            result = compare_into([*accepted, run_dir], *destination)

            assert result.exit_code == 1, (destination, result.stdout + result.stderr)
            assert result.stderr.strip() == committed_ledger_refusal(run_dir), destination
    assert document.read_text(encoding="utf-8") == before
    assert not out.exists()

    written = compare_into(accepted, "--into", str(document))
    assert written.exit_code == 0, written.stdout + written.stderr
    checked = compare_into(accepted, "--into", str(document), "--check")
    assert checked.exit_code == 0, checked.stdout + checked.stderr
    regenerated = document.read_text(encoding="utf-8")
    assert "| no-profile |" in regenerated
    assert "| example-profile |" in regenerated


def test_a_ledger_written_outside_the_repository_accepts_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """US2-10: the same runs rendered into a ledger the repository cannot commit, a folder and a
    document outside the checkout, are taken, every row rendered."""
    root, _ = committed_checkout(tmp_path, monkeypatch)
    refused, accepted = guarded_runs(root, tmp_path)
    notes = tmp_path / "notes.md"
    notes.write_text(_document(render_ledger_md(compare_runs([]))), encoding="utf-8")
    out = tmp_path / "ledger"

    result = compare_into([*accepted, *refused], "--out", str(out), "--into", str(notes))

    assert result.exit_code == 0, result.stdout + result.stderr
    for document in (out / LEDGER_MD, notes):
        text = document.read_text(encoding="utf-8")
        for run_dir in (*accepted, *refused):
            assert f"| {run_dir.name} |" in text, (document, run_dir)


def test_the_committed_ledger_reads_a_folder_git_ignores_as_one_it_does_not_hold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Committable is `runner.committable`'s reading (`contracts/provenance.md` 6.4): a run folder
    inside the checkout that git ignores is refused by the committed ledger, and a ledger written
    into an ignored folder takes every run. Skipped where git is absent, never passed."""
    if shutil.which("git") is None:
        pytest.skip("git is not on the path")
    root, document = committed_checkout(tmp_path, monkeypatch)
    refused, accepted = guarded_runs(root, tmp_path)
    ignored = write_run(root / IGNORED_RUNS, replace(SMOKE, run="ignored"))

    result = compare_into([*accepted, ignored], "--into", str(document))

    assert result.exit_code == 1
    assert result.stderr.strip() == committed_ledger_refusal(ignored)
    out = root / IGNORED_RUNS / "ledger"
    taken = compare_into([*accepted, *refused, ignored], "--out", str(out))
    assert taken.exit_code == 0, taken.stdout + taken.stderr
    assert "| ignored |" in (out / LEDGER_MD).read_text(encoding="utf-8")


def test_run_folders_render_repository_relative_inside_the_checkout(tmp_path: Path) -> None:
    """Section 6.3: `RunRow.run_dir` and `LeverDecision.run_dirs` name a folder inside the checkout
    relative to its root with `/`, however it was typed, so the committed table carries no
    checkout location; a folder outside renders as typed, which only a ledger written outside
    the repository can hold."""
    root = tmp_path / "checkout"
    off, on = study_specs(reps=1, on=CHEAPER)
    write_run(root / "benchmarks" / "studies" / "lever", off)
    write_run(tmp_path / "elsewhere", on)
    inside = root / "benchmarks" / "studies" / ".." / "studies" / "lever" / "off-1"
    outside = tmp_path / "elsewhere" / ".." / "elsewhere" / "on-1"

    ledger = compare_runs([inside, outside], root=root)

    relative = "benchmarks/studies/lever/off-1"
    assert one_row(ledger, "off-1").run_dir == relative
    assert one_row(ledger, "on-1").run_dir == str(outside)
    assert lever_row(ledger, "parallel_tool_calls").run_dirs == [relative, str(outside)]
    cells = lever_cells_of(render_ledger_md(ledger), "parallel_tool_calls")
    assert cells["Link to run dirs"] == f"{relative}, {outside}"


# --- the committed document the ledger is spliced into (T045) --------------------

OPTIONS_DOC = Path(__file__).resolve().parents[3] / "docs" / "llm-efficiency-options.md"


def test_the_committed_results_table_regenerates_byte_identically() -> None:
    """The document cannot drift from the runs it claims to summarize.

    Today there are no recorded runs and the committed ledger is the empty one; the day a
    study lands under `benchmarks/studies/`, this test goes red until the table is
    regenerated, which is the whole point of it.
    """
    document = OPTIONS_DOC.read_text(encoding="utf-8")

    regenerated = splice_ledger(document, render_ledger_md(compare_runs(recorded_runs())))

    assert regenerated == document


def test_check_exits_zero_on_the_committed_document() -> None:
    result = invoke(
        "benchmark",
        "compare",
        *[str(one) for one in recorded_runs()],
        "--into",
        str(OPTIONS_DOC),
        "--check",
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "out of date" not in result.stdout


def test_check_exits_one_on_a_hand_typed_row_and_writes_nothing(tmp_path: Path) -> None:
    drifted = tmp_path / "llm-efficiency-options.md"
    document = OPTIONS_DOC.read_text(encoding="utf-8")
    drifted.write_text(
        document.replace(LEDGER_BEGIN, LEDGER_BEGIN + "\n\n| lever 6 | 40% fewer tokens |"),
        encoding="utf-8",
    )
    before = drifted.read_text(encoding="utf-8")

    result = invoke("benchmark", "compare", "--into", str(drifted), "--check")

    assert result.exit_code == 1
    assert "out of date" in result.stdout
    assert drifted.read_text(encoding="utf-8") == before


@pytest.fixture(autouse=True)
def _no_cached_share_publication() -> Iterator[None]:
    """Probe L1 has not run; nothing here may assume it did."""
    from swreview.agent import providers

    assert providers.CACHED_SHARE_PUBLISHABLE is False
    yield
