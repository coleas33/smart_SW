"""Focused tests for the bounded local handoff exporter."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

import swreview.handoff as handoff
from swreview.handoff import HandoffExportError, export_handoff

STAMP = datetime(2026, 9, 20, 14, 30, tzinfo=UTC)
SECRET = "session-secret-123"
SHAPED_KEY = "sk-" + "a" * 24


def write_run(run_dir: Path, *, complete: bool = True) -> None:
    run_dir.mkdir()
    (run_dir / "package.json").write_text(
        json.dumps({"design_id": "design-1", "source": r"C:\Designs\assembly.SLDASM"}),
        encoding="utf-8",
    )
    (run_dir / "session.json").write_text(
        json.dumps(
            {
                "session_id": "00000000-0000-0000-0000-000000000001",
                "package_id": "00000000-0000-0000-0000-000000000002",
                "design_id": "design-1",
                "started_at": "2026-09-20T14:00:00Z",
                "ended_at": "2026-09-20T14:01:00Z",
                "model": SECRET,
                "provider_info": {
                    "provider": "fake",
                    "model": "fake-scripted",
                    "key_source": "none",
                },
                "efficiency": {"prompt_cache_key": False, "coverage_stop": True},
                "explanations_enabled": True,
                "finding_explanation_fingerprint": "a" * 64,
                "finding_explanations": {"F-001": "text"},
                "coverage": {"checked": [{"check": "x"}], "unresolved": []},
                "evidence_requests": [{"status": "open"}],
                "usage": {"rounds": 2, "turns": 1},
            }
        ),
        encoding="utf-8",
    )
    if complete:
        (run_dir / "attention.json").write_text("{\"rows\": []}\n", encoding="utf-8")
        (run_dir / "report.md").write_text(
            f"# Report\nsecret={SECRET}\nkey={SHAPED_KEY}\n", encoding="utf-8"
        )
        (run_dir / "events.jsonl").write_text(
            json.dumps({"type": "error", "message": SECRET, "key": SHAPED_KEY}) + "\n",
            encoding="utf-8",
        )
    (run_dir / "run-provenance.json").write_text(
        json.dumps(
            {
                "commit": "abc123",
                "provider": "fake",
                "model": SHAPED_KEY,
                "efficiency": {"coverage_stop": True},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "check.log").write_text(f"check complete: {SECRET}\n", encoding="utf-8")
    (run_dir / "native.SLDASM").write_bytes(b"native design must not be copied")
    (run_dir / "settings.json").write_text('{"api_key":"do-not-copy"}', encoding="utf-8")


def read_zip(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_export_contains_allowlist_manifest_summary_hashes_and_redacts_known_secrets(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    write_run(run_dir)

    archive = export_handoff(
        run_dir,
        tmp_path / "handoff.zip",
        secrets=[SECRET],
        exported_at=STAMP,
    )
    entries = read_zip(archive)
    assert set(entries) == {
        "attention.json",
        "check.log",
        "events.jsonl",
        "handoff-manifest.json",
        "package.json",
        "report.md",
        "run-provenance.json",
        "session.json",
    }
    joined = b"".join(entries.values())
    assert SECRET.encode() not in joined
    assert SHAPED_KEY.encode() not in joined
    assert b"native.SLDASM" not in joined
    manifest = json.loads(entries["handoff-manifest.json"])
    assert manifest["schema"] == "swreview.handoff.v1"
    assert manifest["missing_artifacts"] == []
    assert manifest["session_summary"]["usage"]["rounds"] == 2
    assert manifest["session_summary"]["coverage_counts"] == {
        "checked": 1,
        "skipped": 0,
        "unresolved": 0,
        "failed": 0,
        "out_of_scope": 0,
    }
    assert manifest["session_summary"]["explanations"]["count"] == 1
    assert manifest["source_reference_policy"].startswith("package and report may")
    report_record = next(item for item in manifest["artifacts"] if item["path"] == "report.md")
    assert report_record["sha256"] == hashlib.sha256(entries["report.md"]).hexdigest()
    assert report_record["redacted"] is True
    assert manifest["secret_scan"]["coverage"] == "best_effort_unknown_secrets_may_remain"


def test_incomplete_run_remains_exportable_and_lists_missing_required_artifacts(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    write_run(run_dir, complete=False)

    archive = export_handoff(run_dir, tmp_path / "handoff.zip", exported_at=STAMP)
    manifest = json.loads(read_zip(archive)["handoff-manifest.json"])
    assert manifest["missing_artifacts"] == ["attention.json", "events.jsonl", "report.md"]
    assert "package.json" in {item["path"] for item in manifest["artifacts"]}


def test_export_is_reproducible_with_a_fixed_timestamp_and_refuses_overwrite(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    write_run(run_dir)
    first = export_handoff(run_dir, tmp_path / "one.zip", exported_at=STAMP)
    second = export_handoff(run_dir, tmp_path / "two.zip", exported_at=STAMP)
    assert first.read_bytes() == second.read_bytes()

    with pytest.raises(HandoffExportError, match="overwrite"):
        export_handoff(run_dir, first, exported_at=STAMP)

    with pytest.raises(HandoffExportError, match="outside"):
        export_handoff(run_dir, run_dir / "inside.zip", exported_at=STAMP)


def test_symlinked_allowlisted_artifact_is_rejected(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    write_run(run_dir)
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    (run_dir / "attention.json").unlink()
    try:
        (run_dir / "attention.json").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this filesystem")

    with pytest.raises(HandoffExportError, match="symlink"):
        export_handoff(run_dir, tmp_path / "handoff.zip", exported_at=STAMP)


def test_malformed_session_summary_is_explicitly_unreadable(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    write_run(run_dir)
    (run_dir / "session.json").write_text(
        json.dumps({"coverage": {"checked": None}, "evidence_requests": [None]}),
        encoding="utf-8",
    )

    entries = read_zip(export_handoff(run_dir, tmp_path / "handoff.zip", exported_at=STAMP))
    summary = json.loads(entries["handoff-manifest.json"])["session_summary"]
    assert summary["coverage_status"] == "unreadable"
    assert summary["coverage_counts"]["checked"] is None
    assert summary["evidence_request_status"] == "unreadable"
    assert summary["evidence_request_counts"] == {"open": None, "answered": None}


def test_required_and_optional_size_limits_are_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run"
    write_run(run_dir)
    monkeypatch.setattr(handoff, "MAX_ARTIFACT_BYTES", 4096)
    (run_dir / "attention.json").write_bytes(b"x" * 4097)
    with pytest.raises(HandoffExportError, match="attention.json"):
        export_handoff(run_dir, tmp_path / "required.zip", exported_at=STAMP)

    (run_dir / "attention.json").write_text("{\"rows\": []}\n", encoding="utf-8")
    monkeypatch.setattr(handoff, "MAX_ARTIFACT_BYTES", 4096)
    (run_dir / "check.log").write_bytes(b"x" * 4097)
    archive = export_handoff(run_dir, tmp_path / "optional.zip", exported_at=STAMP)
    manifest = json.loads(read_zip(archive)["handoff-manifest.json"])
    assert {item["path"] for item in manifest["excluded_artifacts"]} == {"check.log"}


def test_total_limit_keeps_required_evidence_honest_and_skips_optional_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run"
    write_run(run_dir)
    monkeypatch.setattr(handoff, "MAX_ARTIFACT_BYTES", 4096)
    monkeypatch.setattr(handoff, "MAX_TOTAL_BYTES", 1200)
    (run_dir / "check.log").write_bytes(b"x" * 700)
    archive = export_handoff(run_dir, tmp_path / "optional-total.zip", exported_at=STAMP)
    manifest = json.loads(read_zip(archive)["handoff-manifest.json"])
    assert {item["path"] for item in manifest["excluded_artifacts"]} == {"check.log"}


def test_failed_publication_cleans_the_temporary_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run"
    write_run(run_dir)

    def fail_link(*args: object, **kwargs: object) -> None:
        raise OSError("link refused")

    monkeypatch.setattr(handoff.os, "link", fail_link)
    with pytest.raises(HandoffExportError, match="atomically publish"):
        export_handoff(run_dir, tmp_path / "failed.zip", exported_at=STAMP)
    assert not (tmp_path / "failed.zip").exists()
    assert not list(tmp_path.glob(".*.tmp"))
