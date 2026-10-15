"""A kept attempt reports a failed promotion without losing the review outcome."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from swreview import cli
from swreview.agent.providers.fake import ScriptedTurn
from swreview.benchmark import runner
from tests.unit.test_benchmark_attempts import (
    MODEL,
    driver_row,
    driver_status,
    install_driver_providers,
    prepare_driver_set,
    provider_stop,
)


@pytest.mark.parametrize("behavioural", [False, True])
def test_a_failed_promotion_preserves_the_outcome_message_and_reports_its_safe_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, behavioural: bool,
) -> None:
    preflighted = prepare_driver_set(tmp_path)
    out = tmp_path / "run"
    real_rename = Path.rename
    notifications: list[dict[str, Any]] = []

    def rename(path: Path, target: Any) -> Path:
        if path == out / "attempts/fict-a/1":
            raise PermissionError(f"fict secret rename\n held {path}")
        return real_rename(path, target)

    def body(*args: Any, **options: Any) -> None:
        if behavioural:
            raise provider_stop("content_filter")

    monkeypatch.setattr(Path, "rename", rename)
    assert runner.run_benchmark(
        preflighted, out, provider="fake", model=MODEL, effort="high", review_fn=body,
        redact=lambda text: text.replace("fict secret", "<masked>"),
        on_package_done=lambda **facts: notifications.append(facts),
    ) == []

    row = driver_row(out)
    assert row["kind"] == ("behavioural" if behavioural else "completed")
    assert driver_status(out)["packages"]["fict-a"]["kept_attempt"] == 1
    assert row["folder"] == "attempts/fict-a/1"
    assert (out / row["folder"]).is_dir()
    if behavioural:
        assert "fict provider stopped" in row["message"]
    assert "promotion failed: <masked> rename held <run>" in row["message"]
    assert str(out) not in row["message"] and "fict secret" not in row["message"]
    assert len(row["message"].splitlines()) == 1
    assert notifications[0]["promotion_error"].replace("\\", "/") == (
        "<masked> rename held <run>/attempts/fict-a/1"
    )


@pytest.mark.parametrize("json_output", [False, True])
def test_a_failed_promotion_prints_one_safe_line_and_continues_the_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, json_output: bool,
) -> None:
    prepare_driver_set(tmp_path, ("fict-a", "fict-b"))
    install_driver_providers(
        monkeypatch,
        [[ScriptedTurn(text="Reviewed first.")], [ScriptedTurn(text="Reviewed last.")]],
    )
    out = tmp_path / "run"
    real_rename = Path.rename

    def rename(path: Path, target: Any) -> Path:
        if path == out / "attempts/fict-a/1":
            raise PermissionError(f"fict rename\n held {path}")
        return real_rename(path, target)

    monkeypatch.setattr(Path, "rename", rename)
    arguments = [
        "benchmark", "run", "--set", str(tmp_path / "set.json"), "--out", str(out),
        "--provider", "fake",
    ]
    if json_output:
        arguments.append("--json")
    result = CliRunner().invoke(cli.app, arguments)
    assert result.exit_code == 1, result.stdout + result.stderr
    lines = [
        line for line in result.stderr.splitlines() if line.startswith("fict-a: promotion failed: ")
    ]
    assert len(lines) == 1, result.stderr
    assert "fict rename held <run>" in lines[0]
    assert str(out) not in lines[0]
    assert (out / "fict-b/session.json").is_file()
    assert "swreview benchmark resume" in result.stderr
