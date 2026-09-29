"""A stopped native baseline read leaves its entered phase and keeps cleanup semantics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swreview.chat.remodel import OPEN_DIAGNOSTICS_FILE, OPEN_FILE_NAME, RemodelServer
from swreview.handoff import export_handoff
from tests.unit.test_chat_remodel_routes import PACKAGE, ProbingBridge, seat
from tests.unit.test_handoff import read_zip


def phases(run_dir: Path) -> list[str]:
    records = (run_dir / OPEN_DIAGNOSTICS_FILE).read_text(encoding="utf-8").splitlines()
    return [json.loads(line)["phase"] for line in records]


def setup_run(tmp_path: Path) -> tuple[RemodelServer, ProbingBridge, Path, Path]:
    source = tmp_path / "fictional-source.SLDPRT"
    source.write_bytes(b"fictional native part")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    bridge = ProbingBridge(
        seat(PACKAGE), source=source,
        copy_path=str(run_dir / "copy" / "fictional-source-RMS.SLDPRT"),
    )
    server = RemodelServer(
        run_root=tmp_path, redact=lambda text: text,
        settings=lambda body: pytest.fail("open must not construct a provider"),
    )
    return server, bridge, run_dir, source


def test_baseline_begin_is_on_disk_before_the_native_call_and_open_is_not_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, bridge, run_dir, source = setup_run(tmp_path)
    original_geometry = bridge.geometry

    def geometry():
        assert phases(run_dir)[-1] == "baseline_geometry.begin"
        assert (run_dir / "source-attestation.json").exists()
        assert not (run_dir / OPEN_FILE_NAME).exists()
        return original_geometry()

    monkeypatch.setattr(bridge, "geometry", geometry)
    result = server._open(bridge, run_dir, str(source), "probe:1", "Default")
    assert result["copy_present"] is True
    assert phases(run_dir)[-2:] == ["baseline_geometry.returned", "open_record.written"]
    assert (run_dir / OPEN_FILE_NAME).exists()


def test_baseline_failure_records_cleanup_without_claiming_open_or_leaking_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, bridge, run_dir, source = setup_run(tmp_path)

    def geometry():
        assert phases(run_dir)[-1] == "baseline_geometry.begin"
        raise RuntimeError("private failure detail")

    monkeypatch.setattr(bridge, "geometry", geometry)
    with pytest.raises(RuntimeError, match="private failure detail"):
        server._open(bridge, run_dir, str(source), "probe:1", "Default")
    assert phases(run_dir)[-3:] == ["open_record.failed", "cleanup.begin", "cleanup.returned"]
    assert "baseline_geometry.returned" not in phases(run_dir)
    assert not (run_dir / OPEN_FILE_NAME).exists()
    assert "remodel.close" in bridge.commands
    text = (run_dir / OPEN_DIAGNOSTICS_FILE).read_text(encoding="utf-8")
    assert "private failure detail" not in text
    assert source.name not in text
    assert source.read_bytes() == b"fictional native part"


def test_unwritable_diagnostics_do_not_prevent_session_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, bridge, run_dir, source = setup_run(tmp_path)
    (run_dir / OPEN_DIAGNOSTICS_FILE).mkdir()

    def geometry():
        raise RuntimeError("native read failed")

    monkeypatch.setattr(bridge, "geometry", geometry)
    with pytest.raises(RuntimeError, match="native read failed"):
        server._open(bridge, run_dir, str(source), "probe:1", "Default")
    assert "remodel.close" in bridge.commands
    assert not (run_dir / OPEN_FILE_NAME).exists()


def test_partial_remodel_handoff_keeps_diagnostics_and_excludes_the_native_copy(
    tmp_path: Path,
) -> None:
    server, bridge, run_dir, source = setup_run(tmp_path)
    server._open(bridge, run_dir, str(source), "probe:1", "Default")
    (run_dir / "remodel.log").write_text(
        "member=CreateMassProperty2 phase=begin\n", encoding="utf-8",
    )
    archive = export_handoff(run_dir, tmp_path / "handoff.zip")
    entries = read_zip(archive)
    assert {
        OPEN_DIAGNOSTICS_FILE, "remodel.log", "source-attestation.json", OPEN_FILE_NAME,
    } <= entries.keys()
    assert not any(name.lower().endswith(".sldprt") for name in entries)
    manifest = json.loads(entries["handoff-manifest.json"])
    assert "package.json" in manifest["missing_artifacts"]
