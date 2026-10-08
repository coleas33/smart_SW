"""Focused tests for the bounded local handoff exporter."""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import swreview.handoff as handoff
from swreview.agent.providers import ProviderName
from swreview.agent.settings import pane_defaults
from swreview.benchmark.runner import PROVENANCE_FILE, RunProvenance
from swreview.checks.standards.profile import load_profile
from swreview.handoff import HandoffExportError, export_handoff
from tests.support.local_paths import scan_file
from tests.unit.test_benchmark_run_options import SAVED_SET_FILE, two_package_set
from tests.unit.test_run_provenance import (
    example_profile_copy,
    one_package_set,
    read_record,
    run_arm,
    spellings,
)

STAMP = datetime(2026, 9, 20, 14, 30, tzinfo=UTC)
SECRET = "session-secret-123"
SHAPED_KEY = "sk-" + "a" * 24


def write_run(
    run_dir: Path, *, complete: bool = True, explanations: dict[str, str] | None = None
) -> None:
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
                "finding_explanations": explanations if explanations is not None else {
                    "F-001": "text"
                },
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


def write_remodel_run(run_dir: Path, *, planned: bool) -> None:
    """A Remodel run folder as a Plan leaves it, or as an open that stopped at the baseline does."""
    run_dir.mkdir()
    (run_dir / "remodel-open.jsonl").write_text('{"phase": "copy_open.begin"}\n', encoding="utf-8")
    (run_dir / "remodel.log").write_text("id=1 command=remodel.open begin\n", encoding="utf-8")
    (run_dir / "source-attestation.json").write_text(
        json.dumps({"path": r"C:\Designs\bracket.SLDPRT", "copy_path": r"C:\runs\x\copy\b.SLDPRT"}),
        encoding="utf-8",
    )
    copy = run_dir / "copy"
    copy.mkdir()
    (copy / "bracket-RMS.SLDPRT").write_bytes(b"native copy must not be copied")
    if planned:
        (run_dir / "open.json").write_text('{"copy_path": "x"}', encoding="utf-8")
        (run_dir / "package-before.json").write_text('{"design_id": "d"}', encoding="utf-8")
        (run_dir / "plan.json").write_text('{"state": "planned"}', encoding="utf-8")
        (run_dir / "exceptions.json").write_text("{}", encoding="utf-8")


def test_a_remodel_run_is_exported_with_its_own_records_and_missing_list(
    tmp_path: Path,
) -> None:
    """General review of 2026-09-28 (default taken 2026-09-28, the owner may revise): a Remodel
    run folder is judged by a Remodel run's records - the open, the attestation, the baseline
    package and the plan - so its missing list says what the run did not reach, not which
    review files a Remodel run never writes. The native copy is never included."""
    run_dir = tmp_path / "20260928-181400-plate-remodel"
    write_remodel_run(run_dir, planned=True)

    archive = export_handoff(run_dir, tmp_path / "handoff.zip", exported_at=STAMP)
    entries = read_zip(archive)
    manifest = json.loads(entries["handoff-manifest.json"])

    assert manifest["run_kind"] == "remodel"
    assert manifest["missing_artifacts"] == []
    assert {
        "remodel-open.jsonl", "remodel.log", "source-attestation.json", "open.json",
        "package-before.json", "plan.json", "exceptions.json",
    } <= set(entries)
    assert not any(name.lower().endswith(".sldprt") for name in entries)
    assert b"native copy" not in b"".join(entries.values())
    assert "remodel" in manifest["source_reference_policy"]
    assert "open.json" in manifest["source_reference_policy"]


def test_a_remodel_run_that_stopped_at_the_baseline_names_what_it_did_not_reach(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "20260928-181400-plate-remodel"
    write_remodel_run(run_dir, planned=False)

    archive = export_handoff(run_dir, tmp_path / "handoff.zip", exported_at=STAMP)
    manifest = json.loads(read_zip(archive)["handoff-manifest.json"])

    assert manifest["run_kind"] == "remodel"
    assert manifest["missing_artifacts"] == ["open.json", "package-before.json", "plan.json"]


def test_a_review_run_keeps_the_review_shape(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    write_run(run_dir)

    archive = export_handoff(run_dir, tmp_path / "handoff.zip", exported_at=STAMP)
    manifest = json.loads(read_zip(archive)["handoff-manifest.json"])

    assert manifest["run_kind"] == "review"


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


def test_a_legacy_fallback_sentence_is_not_counted_as_an_explanation(tmp_path: Path) -> None:
    """Feature 013 (its `contracts/sources.md` section 4, FR-043): a run folder written before
    013 may hold the explanation pass's fallback sentence for a row it did not explain; the
    summary counts the explanations the model wrote, not the sentence that stood in for one."""
    from swreview.report.attention import EXPLANATION_UNAVAILABLE

    run_dir = tmp_path / "run"
    write_run(run_dir, explanations={"F-001": "text", "F-002": EXPLANATION_UNAVAILABLE})

    archive = export_handoff(run_dir, tmp_path / "handoff.zip", exported_at=STAMP)

    manifest = json.loads(read_zip(archive)["handoff-manifest.json"])
    assert manifest["session_summary"]["explanations"]["count"] == 1


# --- a benchmark package export (feature 014 T070) ---------------------------------
#
# `specs/014-design-review-eval/contracts/provenance.md` 7 and 8 (PROV-13, RF-42; US2-9): a
# benchmark run keeps its record at the run root, which holds no session, and each package's
# session and events in `<run>/<package>/`, which holds no record. Each test exports
# `<run>/<package>` of a folder a scripted `benchmark run --provider fake` wrote.


def pane_defaults_run(tmp_path: Path, set_path: Path) -> tuple[Path, Path]:
    """A scripted `benchmark run --pane-defaults` of `set_path` with a copy of the example
    profile kept in a folder of its own beside the runs: the run root and the profile's path."""
    profile = example_profile_copy(tmp_path / "profiles")
    run_root = tmp_path / "runs" / "pane"
    result = run_arm(set_path, run_root, "--pane-defaults", "--standards-profile", str(profile))
    assert result.exit_code == 0, result.stdout + result.stderr
    return run_root, profile


def manifest_of(entries: dict[str, bytes]) -> dict[str, Any]:
    manifest: dict[str, Any] = json.loads(entries["handoff-manifest.json"])
    return manifest


def test_a_pane_defaults_benchmark_run_exports_its_provenance_fields_and_never_the_profile_path(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    """US2-9: the record the bundle carries is the run root's, read beside the package's own
    records; the profile travels as its digest, never as where it lives."""
    run_root, profile = pane_defaults_run(tmp_path, one_package_set(tmp_path, tmp_package_dir))

    entries = read_zip(
        export_handoff(run_root / "cover", tmp_path / "handoff.zip", exported_at=STAMP)
    )

    assert entries[PROVENANCE_FILE] == (run_root / PROVENANCE_FILE).read_bytes()
    provenance = manifest_of(entries)["recorded_run_provenance"]
    assert provenance["model_view"] == pane_defaults(ProviderName.FAKE).model_view.model_dump(
        mode="json"
    )
    assert provenance["profile_digest"] == load_profile(profile).identity.sha256
    assert provenance["pane_defaults"] is True
    assert provenance["live_tools"] is False
    for name, data in entries.items():
        text = data.decode("utf-8")
        for path in (profile, profile.parent):
            for form in spellings(path) | spellings(path.resolve()):
                assert form not in text, f"{name} names {form}"


def test_the_session_summary_carries_the_model_view(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    """The model view the session already holds, the one `compare` cross-checks against the
    record (PP-3); a session that predates the model view holds none and reads `None`."""
    run_root, _ = pane_defaults_run(tmp_path, one_package_set(tmp_path, tmp_package_dir))
    session = json.loads((run_root / "cover" / "session.json").read_text(encoding="utf-8"))

    entries = read_zip(
        export_handoff(run_root / "cover", tmp_path / "pane.zip", exported_at=STAMP)
    )

    summary = manifest_of(entries)["session_summary"]
    assert summary["model_view"] == session["model_view"]
    assert summary["model_view"] == pane_defaults(ProviderName.FAKE).model_view.model_dump(
        mode="json"
    )

    older = tmp_path / "older"
    write_run(older)
    entries = read_zip(export_handoff(older, tmp_path / "older.zip", exported_at=STAMP))
    assert manifest_of(entries)["session_summary"]["model_view"] is None


def test_the_handoff_allowlist_names_every_provenance_field(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    """RF-42: the allowlist stays a literal tuple, the guard that keeps a later field out until
    it is named, held equal to the record's fields at every slice so that no recorded field
    silently misses the bundle; and no value a scripted run records is a path (FR-013, FR-051)."""
    assert sorted(handoff._PROVENANCE_FIELDS) == sorted(RunProvenance.model_fields)

    run_root, _ = pane_defaults_run(tmp_path, one_package_set(tmp_path, tmp_package_dir))
    entries = read_zip(
        export_handoff(run_root / "cover", tmp_path / "handoff.zip", exported_at=STAMP)
    )

    carried = manifest_of(entries)["recorded_run_provenance"]
    assert carried == read_record(run_root)
    carried_file = tmp_path / "carried-provenance.json"
    carried_file.write_text(json.dumps(carried), encoding="utf-8")
    assert scan_file(carried_file) == []


def test_a_package_export_reads_only_the_run_roots_provenance_and_status(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    """The parity half (the robustness slice adds `run-status.json`): from the run root only
    `run-provenance.json` is read, and from no parent that is not a run root; nothing else of the
    run root or of another package reaches the archive, which lies outside the run root as well
    as outside the package folder."""
    run_root, _ = pane_defaults_run(tmp_path, two_package_set(tmp_path, tmp_package_dir))
    package, other = run_root / "cover", run_root / "cover-copy"
    root_marker, other_marker = "only-in-the-run-root", "only-in-another-package"
    (run_root / "check.log").write_text(root_marker, encoding="utf-8")
    (other / "check.log").write_text(other_marker, encoding="utf-8")
    package_files = {
        name
        for name in (*handoff.REQUIRED_ARTIFACTS, *handoff.OPTIONAL_ARTIFACTS)
        if (package / name).is_file()
    }

    entries = read_zip(export_handoff(package, tmp_path / "handoff.zip", exported_at=STAMP))

    assert set(entries) == package_files | {PROVENANCE_FILE, "handoff-manifest.json"}
    assert entries[PROVENANCE_FILE] == (run_root / PROVENANCE_FILE).read_bytes()
    assert all(entries[name] == (package / name).read_bytes() for name in package_files)
    joined = b"".join(entries.values())
    assert root_marker.encode() not in joined
    assert other_marker.encode() not in joined
    assert (run_root / SAVED_SET_FILE).read_bytes() not in joined
    assert (other / "session.json").read_bytes() not in joined

    for kept in (PROVENANCE_FILE, SAVED_SET_FILE):
        parent = tmp_path / f"parent-holding-{kept}-alone"
        shutil.copytree(package, parent / "cover")
        shutil.copyfile(run_root / kept, parent / kept)
        (parent / "check.log").write_text(root_marker, encoding="utf-8")

        alone = read_zip(
            export_handoff(parent / "cover", tmp_path / f"{kept}.zip", exported_at=STAMP)
        )

        assert set(alone) == package_files | {"handoff-manifest.json"}
        assert manifest_of(alone)["recorded_run_provenance"] is None
        assert root_marker.encode() not in b"".join(alone.values())

    for inside in (run_root / "inside.zip", other / "inside.zip", package / "inside.zip"):
        with pytest.raises(HandoffExportError, match="outside"):
            export_handoff(package, inside, exported_at=STAMP)
        assert not inside.exists()


def test_each_artifact_record_names_the_folder_it_was_read_from(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    """The manifest's record of a name read from a benchmark run's root says so, `source`
    `run_root`, and every name read from the exported folder says `run_dir`: the archive holds
    both at its top level, so only the record tells them apart. A review folder holding its own
    `run-provenance.json` reads it as `run_dir`."""
    run_root, _ = pane_defaults_run(tmp_path, one_package_set(tmp_path, tmp_package_dir))

    entries = read_zip(
        export_handoff(run_root / "cover", tmp_path / "package.zip", exported_at=STAMP)
    )

    sources = {record["path"]: record["source"] for record in manifest_of(entries)["artifacts"]}
    assert set(sources) == set(entries) - {"handoff-manifest.json"}
    assert sources.pop(PROVENANCE_FILE) == "run_root"
    assert sources and set(sources.values()) == {"run_dir"}

    review = tmp_path / "review"
    write_run(review)
    entries = read_zip(export_handoff(review, tmp_path / "review.zip", exported_at=STAMP))

    records = manifest_of(entries)["artifacts"]
    assert PROVENANCE_FILE in {record["path"] for record in records}
    assert {record["source"] for record in records} == {"run_dir"}
