"""Pane presentation settings remain attributable in CLI reviews and A/B runs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from swreview.benchmark.compare import CompareError, compare_runs, render_ledger_md
from swreview.benchmark.runner import PROVENANCE_FILE, run_benchmark
from swreview.cli import app
from swreview.report.session import load_session
from tests.support.studies import RunSpec, write_run
from tests.unit.test_benchmark_runner import FAKE_MODEL, write_set


@pytest.mark.parametrize("command", ["review", "benchmark"])
@pytest.mark.parametrize("enabled", [False, True])
def test_cli_records_the_requested_explanation_mode(
    tmp_path: Path, tmp_package_dir: Path, command: str, enabled: bool
) -> None:
    out = tmp_path / "run"
    if command == "review":
        args = ["review", str(tmp_package_dir)]
        session_dir = out
    else:
        set_path = write_set(tmp_path / "set.json", tmp_package_dir)
        args = ["benchmark", "run", "--set", str(set_path)]
        session_dir = out / "cover"
    args += ["--out", str(out), "--provider", "fake"]
    if enabled:
        args += ["--explain-findings"]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert load_session(session_dir / "session.json").explanations_enabled is enabled
    if command == "benchmark":
        provenance = json.loads((out / PROVENANCE_FILE).read_text())
        assert provenance["explanations_enabled"] is enabled


def test_library_benchmark_default_provider_receives_explanations(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    set_path = write_set(tmp_path / "set.json", tmp_package_dir)
    run_benchmark(
        set_path, tmp_path / "run", provider="fake", model=FAKE_MODEL,
        effort="high", explain_findings=True,
    )
    assert load_session(tmp_path / "run" / "cover" / "session.json").explanations_enabled


def _set_mode(run: Path, enabled: bool, *, session: bool = True) -> None:
    paths = [run / PROVENANCE_FILE]
    if session:
        paths.append(run / "rms-part" / "session.json")
    for path in paths:
        data = json.loads(path.read_text())
        data["explanations_enabled"] = enabled
        path.write_text(json.dumps(data), encoding="utf-8")


def test_compare_refuses_provenance_that_disagrees_with_session(tmp_path: Path) -> None:
    run = write_run(tmp_path, RunSpec(run="off-1", arm="off"))
    _set_mode(run, True, session=False)
    with pytest.raises(CompareError, match="explanations_enabled"):
        compare_runs([run])


def test_compare_refuses_mixed_presentation_settings_within_a_study(tmp_path: Path) -> None:
    off = write_run(tmp_path, RunSpec(run="off-1", arm="off"))
    on = write_run(tmp_path, RunSpec(run="on-1", arm="on"))
    _set_mode(on, True)
    with pytest.raises(CompareError, match="explanations_enabled differs"):
        compare_runs([off, on])


def test_legacy_provenance_and_session_mean_explanations_off(tmp_path: Path) -> None:
    run = write_run(tmp_path, RunSpec(run="off-1", arm="off"))
    path = run / PROVENANCE_FILE
    data = json.loads(path.read_text())
    data.pop("explanations_enabled", None)
    path.write_text(json.dumps(data), encoding="utf-8")
    assert not compare_runs([run]).runs[0].explanations_enabled


def test_ledger_exposes_presentation_mode(tmp_path: Path) -> None:
    run = write_run(tmp_path, RunSpec(run="off-1", arm="off"))
    _set_mode(run, True)
    ledger = compare_runs([run])
    assert ledger.runs[0].explanations_enabled
    assert "| explanations |" in render_ledger_md(ledger)


def test_compare_refuses_different_step_budgets(tmp_path: Path) -> None:
    off = write_run(tmp_path, RunSpec(run="off-1", arm="off"))
    on = write_run(tmp_path, RunSpec(run="on-1", arm="on"))
    path = on / PROVENANCE_FILE
    data = json.loads(path.read_text())
    data["max_steps"] = 20
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(CompareError, match="max_steps differs"):
        compare_runs([off, on])


def test_compact_query_experiment_can_be_compared(tmp_path: Path) -> None:
    off = write_run(tmp_path, RunSpec(run="off-1", arm="off", lever="compact_queries"))
    on = write_run(tmp_path, RunSpec(run="on-1", arm="on", lever="compact_queries"))
    ledger = compare_runs([off, on])
    assert ledger.levers[0].lever == "compact_queries"
    assert "compact discovery" in ledger.levers[0].lever_counter.name
