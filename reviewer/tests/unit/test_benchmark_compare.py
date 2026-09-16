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
from collections.abc import Iterator
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from swreview import cli
from swreview.agent.settings import EfficiencySettings
from swreview.benchmark.adoption import (
    ADOPT,
    CONTROL_UNSTABLE,
    KEEP_OFF,
    NO_RECALL,
    SET_TOO_SMALL,
)
from swreview.benchmark.compare import (
    LEDGER_BEGIN,
    LEDGER_END,
    LEDGER_JSON,
    LEDGER_MD,
    UNKNOWN,
    CompareError,
    carry_sign_offs,
    compare_runs,
    recorded_runs,
    render_ledger_md,
    splice_ledger,
    write_ledger,
)
from swreview.benchmark.runner import PROVENANCE_FILE
from tests.support.studies import (
    COMMIT,
    PackageSpec,
    RunSpec,
    study_specs,
    write_run,
    write_study,
)

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


def test_the_lever_specific_counter_is_named_on_every_row(tmp_path: Path) -> None:
    dirs = write_study(tmp_path, study_specs(on=CHEAPER))

    row = lever_row(compare_runs(dirs), "parallel_tool_calls")

    assert row.lever_counter.name
    assert row.lever_counter.off is not None


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
    specs = study_specs(on={"set_too_small_override": True, **CHEAPER})
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
    assert payload["ledger_schema"] == "1.0"
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
