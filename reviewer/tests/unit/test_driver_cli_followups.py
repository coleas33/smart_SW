"""Attempt driver regressions at the CLI body and command boundaries."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from swreview import cli
from swreview.agent.providers import usage_body
from swreview.agent.providers.fake import SYNTHETIC_USAGE, FakeProvider, ScriptedTurn
from swreview.agent.runner import ReviewRun
from swreview.benchmark.answers import read_answer_log
from tests.unit.test_benchmark_attempts import (
    driver_events,
    driver_row,
    driver_run,
    install_driver_providers,
    prepare_driver_set,
)


@pytest.mark.parametrize("during", ["setup", "prompts"])
def test_a_stop_before_the_opening_turn_sends_no_provider_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, during: str,
) -> None:
    preflighted = prepare_driver_set(tmp_path)
    built = install_driver_providers(monkeypatch, [[ScriptedTurn(text="Fict review.")]])
    stopped: list[ReviewRun] = []
    start = cli.start_review
    end = ReviewRun.end_stopped
    write_prompts = cli.report_page.write_prompts_record
    active: list[ReviewRun] = []
    prompts_written = False

    def setup(package_dir: Path, folder: Path, **options: Any) -> ReviewRun:
        run = start(package_dir, folder, **options)
        active.append(run)
        if during == "setup":
            options["callbacks"][0].stop.set()
        return run

    def prompts(run: ReviewRun, folder: Path) -> Any:
        nonlocal prompts_written
        if during == "prompts" and not prompts_written:
            # A pre-run hook can request Stop after start_review has returned.
            run.sink.emit("usage", usage_body(
                SYNTHETIC_USAGE, round_index=0, provider="fake", model=run.provider.model,
                served_model="fict-wrong-model",
            ))
        prompts_written = True
        return write_prompts(run, folder)

    def ending(run: ReviewRun) -> Any:
        stopped.append(run)
        return end(run)

    monkeypatch.setattr(cli, "start_review", setup)
    monkeypatch.setattr(cli.report_page, "write_prompts_record", prompts)
    monkeypatch.setattr(ReviewRun, "end_stopped", ending)
    out = tmp_path / "run"
    driver_run(preflighted, out)

    assert built[0]._turn_index == 0
    assert stopped == active
    folder = out / driver_row(out)["folder"]
    assert [event.body["reason"] for event in driver_events(folder)
            if event.type == "turn.ended"] == ["stopped"]
    log = read_answer_log(folder)
    assert log.ended == "stopped"
    assert log.last_turn_end == "stopped"
    assert log.points == []


@pytest.mark.parametrize("root_name", ["fict-checkout", "fict  checkout"])
def test_the_body_scrubs_the_same_checkout_root_as_the_driver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, root_name: str,
) -> None:
    root = tmp_path / root_name
    preflighted = replace(prepare_driver_set(tmp_path), root=root)

    class BrokenProvider(FakeProvider):
        def run(self, **options: Any) -> Any:
            raise PermissionError(f"cannot read {root / 'models' / 'fict-part.json'}")

    install_driver_providers(monkeypatch, [[ScriptedTurn(text="")]], kind=BrokenProvider)
    out = tmp_path / "run"
    assert driver_run(preflighted, out) == []
    folder = out / driver_row(out)["folder"]
    errors = [event.body["message"] for event in driver_events(folder) if event.type == "error"]
    assert errors
    assert all("<repo>" in message and "fict-checkout" not in message for message in errors)
    assert "<repo>" in driver_row(out)["message"]


def test_ctrl_c_prints_a_clear_interruption_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_driver_set(tmp_path)
    install_driver_providers(monkeypatch, [[ScriptedTurn(text="")]])

    def interrupt(*args: Any, **options: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "run_benchmark", interrupt)
    result = CliRunner().invoke(cli.app, [
        "benchmark", "run", "--set", str(tmp_path / "set.json"),
        "--out", str(tmp_path / "run"), "--provider", "fake",
    ])
    assert result.exit_code == 1
    assert result.stderr.splitlines() == ["error: interrupted (Ctrl-C)"]


def test_a_missing_run_status_is_an_explicit_command_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_driver_set(tmp_path)
    install_driver_providers(monkeypatch, [[ScriptedTurn(text="Fict review.")]])
    monkeypatch.setattr(cli, "load_run_status", lambda folder: None)
    result = CliRunner().invoke(cli.app, [
        "benchmark", "run", "--set", str(tmp_path / "set.json"),
        "--out", str(tmp_path / "run"), "--provider", "fake",
    ])
    assert result.exit_code == 1
    assert result.stderr.splitlines() == ["error: benchmark run status is missing"]
