"""The handoff command collects local evidence without credentials or overwrite."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from swreview.cli import app


def test_cli_exports_partial_run_and_masks_named_bridge_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "local-bridge-fixture-secret"
    monkeypatch.setenv("SWREVIEW_TEST_BRIDGE", secret)
    run = tmp_path / "run"
    run.mkdir()
    (run / "report.md").write_text(f"# Report\nbridge failed: {secret}\n", encoding="utf-8")
    out = tmp_path / "handoff.zip"
    result = CliRunner().invoke(app, [
        "handoff", str(run), "--out", str(out),
        "--bridge-secret-env", "SWREVIEW_TEST_BRIDGE", "--json",
    ])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["archive"] == str(out.resolve())
    assert "session.json" in payload["manifest"]["missing_artifacts"]
    assert payload["manifest"]["build_identity"]["source"] == "export-time"
    assert secret not in result.output
    with zipfile.ZipFile(out) as archive:
        assert secret.encode() not in b"".join(archive.read(name) for name in archive.namelist())
    assert secret in (run / "report.md").read_text()


def test_cli_lists_missing_artifacts_and_refuses_overwrite(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "report.md").write_text("# Partial report\n", encoding="utf-8")
    out = tmp_path / "handoff.zip"
    args = ["handoff", str(run), "--out", str(out)]
    first = CliRunner().invoke(app, args)
    assert first.exit_code == 0, first.output
    assert "Missing artifacts:" in first.stdout
    before = out.read_bytes()
    second = CliRunner().invoke(app, args)
    assert second.exit_code == 1
    assert "overwrite" in second.output
    assert out.read_bytes() == before


def test_cli_missing_run_exits_cleanly_without_creating_archive(tmp_path: Path) -> None:
    out = tmp_path / "handoff.zip"
    result = CliRunner().invoke(app, ["handoff", str(tmp_path / "missing"), "--out", str(out)])
    assert result.exit_code == 1
    assert not out.exists()
