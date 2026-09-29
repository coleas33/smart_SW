"""A stopped native baseline read leaves its entered phase and keeps cleanup semantics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from swreview.bridge.client import BridgeError
from swreview.bridge.remodel_client import RemodelError
from swreview.chat.remodel import (
    OPEN_DIAGNOSTICS_FILE,
    OPEN_FILE_NAME,
    PREEXISTING_REBUILD_ERRORS,
    RemodelServer,
    RunFolderFailed,
    ScopeRefused,
)
from swreview.handoff import export_handoff
from swreview.remodel.attestation import read_attestation
from tests.unit.test_chat_remodel_routes import PACKAGE, ProbingBridge, reading, seat
from tests.unit.test_handoff import read_zip


def phases(run_dir: Path) -> list[str]:
    records = (run_dir / OPEN_DIAGNOSTICS_FILE).read_text(encoding="utf-8").splitlines()
    return [json.loads(line)["phase"] for line in records]


def setup_run(
    tmp_path: Path, **bridge_options: Any,
) -> tuple[RemodelServer, ProbingBridge, Path, Path]:
    source = tmp_path / "fictional-source.SLDPRT"
    source.write_bytes(b"fictional native part")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    bridge = ProbingBridge(
        seat(PACKAGE), source=source,
        copy_path=str(run_dir / "copy" / "fictional-source-RMS.SLDPRT"),
        **bridge_options,
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


@pytest.mark.parametrize(
    ("failure", "overrides"),
    [
        ("status", {"status": 1, "volume_m3": None}),
        ("no body", {"status": 2, "recalculated": False, "volume_m3": None}),
        ("recalculate", {"recalculated": False, "volume_m3": None}),
    ],
)
def test_a_baseline_that_is_not_a_usable_reading_refuses_open_and_ends_the_session(
    tmp_path: Path, failure: str, overrides: dict[str, Any],
) -> None:
    """U27 (default taken 2026-09-28, the owner may revise): a baseline the bridge measured
    but could not use - a status other than OK, or Recalculate false - is not a baseline.
    Open refuses before `open.json` exists and ends the bridge's session, instead of filing a
    run whose later reading the gate could only refuse as a subject mismatch."""
    server, bridge, run_dir, source = setup_run(tmp_path)
    bridge.readings[0] = reading(**overrides)

    with pytest.raises(RunFolderFailed, match="no usable baseline"):
        server._open(bridge, run_dir, str(source), "probe:1", "Default")

    assert not (run_dir / OPEN_FILE_NAME).exists()
    assert "remodel.close" in bridge.commands
    assert phases(run_dir)[-4:] == [
        "baseline_geometry.returned", "open_record.failed", "cleanup.begin", "cleanup.returned",
    ]
    assert source.read_bytes() == b"fictional native part"

    # U26: the attestation written before the baseline is re-checked once the session ended.
    checked = read_attestation(run_dir)
    assert checked.rechecked_at is not None
    assert checked.matches is True


def test_a_baseline_that_set_no_accuracy_is_accepted(tmp_path: Path) -> None:
    """Since U27 the copy is read the review dump's way and sets no accuracy of its own, so
    its reading carries `accuracy_level: null`; that is a usable baseline."""
    server, bridge, run_dir, source = setup_run(tmp_path)
    bridge.readings[0] = reading(accuracy_level=None)

    result = server._open(bridge, run_dir, str(source), "probe:1", "Default")

    assert result["copy_present"] is True
    record = json.loads((run_dir / OPEN_FILE_NAME).read_text(encoding="utf-8"))
    assert record["geometry_before"]["accuracy_level"] is None


def test_a_bridge_refusal_records_the_refused_phase_and_answers_the_refusal(
    tmp_path: Path,
) -> None:
    server, bridge, run_dir, source = setup_run(
        tmp_path, open_raises=RemodelError("the copy differs", "scope_changed"),
    )

    with pytest.raises(ScopeRefused):
        server._open(bridge, run_dir, str(source), "probe:1", "Default")

    assert phases(run_dir) == ["copy_open.begin", "copy_open.refused"]
    assert "remodel.close" not in bridge.commands


def test_preexisting_rebuild_errors_are_an_answer_after_the_refused_phase(
    tmp_path: Path,
) -> None:
    server, bridge, run_dir, source = setup_run(
        tmp_path,
        open_raises=RemodelError(
            "two errors", PREEXISTING_REBUILD_ERRORS, {"rebuild_error_count": 2},
        ),
    )

    result = server._open(bridge, run_dir, str(source), "probe:1", "Default")

    assert result == {
        "copy_path": str(run_dir / "copy" / "fictional-source-RMS.SLDPRT"),
        "rebuild_error_count": 2,
        "copy_present": False,
    }
    assert phases(run_dir) == ["copy_open.begin", "copy_open.refused"]
    assert not (run_dir / OPEN_FILE_NAME).exists()


def test_a_bridge_that_fails_records_the_failed_phase(tmp_path: Path) -> None:
    server, bridge, run_dir, source = setup_run(
        tmp_path, open_raises=BridgeError("the pipe closed"),
    )

    with pytest.raises(Exception, match="remodel.open"):
        server._open(bridge, run_dir, str(source), "probe:1", "Default")

    assert phases(run_dir) == ["copy_open.begin", "copy_open.failed"]


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
    # A Remodel run's own records decide what is missing: an open that returned leaves the
    # baseline package and the plan to come (the general review of 2026-09-28).
    assert manifest["run_kind"] == "remodel"
    assert manifest["missing_artifacts"] == ["package-before.json", "plan.json"]
