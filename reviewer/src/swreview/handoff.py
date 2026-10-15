"""Export a bounded, local handoff bundle for one review, check or Remodel run.

The exporter is deliberately an allowlist rather than a folder copier.  A run folder may
sit beside native CAD files, credentials, screenshots, or temporary SDK state; none of
those become part of a handoff by discovery.  The package and report - and a Remodel run's
open record, attestation, plan and log - can still contain paths to the real design, so the
manifest says that those references remain external.

A Remodel run folder is judged by a Remodel run's records (``REMODEL_REQUIRED_ARTIFACTS``),
so its missing list says what the run did not reach rather than naming review files it
never writes; the manifest's ``run_kind`` says which list applied.

A benchmark run's package folder is exported with its run's record: ``benchmark run`` keeps
``run-provenance.json`` at the run root, beside ``benchmark-set.json``, and each package's
session and events in ``<run>/<package>/``, so that one name is read from the parent and
nothing else of the run root or of another package.

The secret scan is a safety net, not a proof that a bundle is secret-free.  Configured
secret values are redacted with the product redactor and the provider-key shapes used by
``audit-secrets`` are masked too.  Unknown or undiscoverable secrets may still require
the engineer to inspect the exported evidence before sharing it.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import zipfile
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args
from uuid import UUID

from pydantic import SecretStr

from swreview.agent.settings import MASK, redact
from swreview.benchmark.runner import PROVENANCE_FILE, SAVED_SET_FILE
from swreview.ir.loader import reject_answer_key_path
from swreview.report.attention import EXPLANATION_UNAVAILABLE
from swreview.report.attention_record import StaleAttentionRecord, read_attention_record
from swreview.report.session import ModelStatus
from swreview.secrets import KEY_SHAPES

__all__ = [
    "HANDOFF_SCHEMA",
    "HandoffExportError",
    "MAX_ARTIFACT_BYTES",
    "MAX_TOTAL_BYTES",
    "OPTIONAL_ARTIFACTS",
    "REMODEL_OPTIONAL_ARTIFACTS",
    "REMODEL_REQUIRED_ARTIFACTS",
    "REQUIRED_ARTIFACTS",
    "export_handoff",
]

HANDOFF_SCHEMA = "swreview.handoff.v1"
REQUIRED_ARTIFACTS: tuple[str, ...] = (
    "package.json",
    "session.json",
    "attention.json",
    "report.md",
    "events.jsonl",
)
"""The core run records. Missing files are recorded rather than making a partial run useless."""

OPTIONAL_ARTIFACTS: tuple[str, ...] = (
    PROVENANCE_FILE,
    "extraction-progress.jsonl",
    "check.json",
    "chat-log.jsonl",
    "extract.log",
    "extractor.log",
    "extraction.log",
    "check.log",
    "checks.log",
    "extractor.jsonl",
    "check.jsonl",
    "remodel.log",
    "remodel-open.jsonl",
    "open.json",
    "source-attestation.json",
)
"""Known supplementary records; arbitrary files and recursive folders are excluded."""

REMODEL_REQUIRED_ARTIFACTS: tuple[str, ...] = (
    "remodel-open.jsonl",
    "remodel.log",
    "source-attestation.json",
    "open.json",
    "package-before.json",
    "plan.json",
)
"""What a Remodel run that reached its plan leaves (004 `contracts/run-artifacts.md`): the open's
phases and log, the attestation, the open record, the baseline package and the plan. Added
2026-09-28 on review (default taken 2026-09-28, the owner may revise): a missing one is what
the run did not reach."""

REMODEL_OPTIONAL_ARTIFACTS: tuple[str, ...] = (
    "extraction-progress.jsonl",
    "exceptions.json",
    "changes.jsonl",
    "geometry.json",
    "grades.json",
    "package-after.json",
    "rms-before.json",
    "rms-after.json",
    "report.md",
    "events.jsonl",
    "session.json",
    PROVENANCE_FILE,
)
"""A Remodel run's later records, present only once a run went further than its plan. The
native copy under ``copy/`` is never among them."""

_REMODEL_MARKERS: tuple[str, ...] = ("remodel-open.jsonl", "source-attestation.json", "open.json")
"""Files only a Remodel run writes: any one of them, or a folder named ``...-remodel`` as
``RunFolders.CreateForRemodel`` names one, makes the run a Remodel run."""

_RUN_ROOT_MARKERS: tuple[str, ...] = (PROVENANCE_FILE, SAVED_SET_FILE)
"""What a benchmark run's root holds beside its package folders: the run's record and its saved
set. A folder whose parent holds both is one of a benchmark run's package folders."""

_RUN_ROOT_ARTIFACTS: tuple[str, ...] = (PROVENANCE_FILE,)
"""What a benchmark package export reads from its run root, and nothing else of it: the run keeps
its record at the root, which holds no session, and each package's session and events in
``<run>/<package>/``, which holds no record (014 `contracts/provenance.md` section 7)."""

_FROM_RUN_DIR = "run_dir"
"""An artifact record's ``source`` for a name read from the input tree."""

_FROM_RUN_ROOT = "run_root"
"""An artifact record's ``source`` for a name in ``_RUN_ROOT_ARTIFACTS`` read from a benchmark
run's root: the archive holds both at its top level, so only the record tells them apart (014
`contracts/provenance.md` section 7)."""

_SOURCE_REFERENCE_POLICY = (
    "package and report may contain real-design paths, and so may a remodel run's open.json, "
    "source-attestation.json, plan.json, packages and remodel.log; native CAD files, machine "
    "settings, credentials and arbitrary neighboring files are excluded"
)

MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024

_SHAPE_DETECTORS = KEY_SHAPES


class HandoffExportError(ValueError):
    """The requested handoff cannot be safely produced."""


def export_handoff(
    run_dir: Path | str,
    out_zip: Path | str,
    *,
    secrets: Iterable[str | SecretStr | None] = (),
    repo_dir: Path | str | None = None,
    exported_at: datetime | None = None,
) -> Path:
    """Write one no-overwrite, atomically published handoff ZIP and return its path.

    ``run_dir`` is the input tree.  Only :data:`REQUIRED_ARTIFACTS` and the exact
    names in :data:`OPTIONAL_ARTIFACTS` are read.  When ``run_dir`` is a benchmark run's
    package folder (its parent holds ``run-provenance.json`` beside ``benchmark-set.json``),
    the names in ``_RUN_ROOT_ARTIFACTS`` are read from that run root instead, and nothing
    else of it.  ``out_zip`` must be outside every tree read: the run root as well as
    ``run_dir``.
    ``repo_dir`` identifies the checkout whose revision is recorded; when omitted, the
    run directory is used and a non-checkout simply records unknown build identity.
    ``exported_at`` is injectable so a manifest and ZIP can be reproduced in tests or by
    an archival caller that already has an export timestamp.

    Reports and attention records naming another session than ``session.json`` are
    excluded and named in the manifest. A legacy report without a ``- Session:`` line
    is exported as today; malformed records that cannot establish identity retain their
    existing export handling, as do runs without a readable session id.
    """
    source = _checked_run_dir(run_dir)
    run_root = _benchmark_run_root(source)
    # The run root holds the package folder, so an archive outside it is outside both trees.
    target = _checked_output(out_zip, run_root if run_root is not None else source)
    timestamp = (exported_at or datetime.now(UTC)).astimezone(UTC)
    secret_values = tuple(secrets)
    run_kind = "remodel" if _is_remodel_run(source) else "review"
    required, optional = (
        (REMODEL_REQUIRED_ARTIFACTS, REMODEL_OPTIONAL_ARTIFACTS)
        if run_kind == "remodel"
        else (REQUIRED_ARTIFACTS, OPTIONAL_ARTIFACTS)
    )
    files, sources, missing, excluded, scan = _collect(
        source, secret_values, required, optional, run_root=run_root
    )

    manifest = _manifest(
        source,
        files,
        sources=sources,
        run_kind=run_kind,
        missing=missing,
        excluded=excluded,
        scan=scan,
        timestamp=timestamp,
        repo_dir=Path(repo_dir) if repo_dir is not None else source,
        artifact_data={relative: data for relative, data, _, _ in files},
    )
    manifest_bytes = _json_bytes(manifest, secrets=secret_values)
    entries = [*files, ("handoff-manifest.json", manifest_bytes, len(manifest_bytes), False)]
    _publish_zip(target, entries)
    return target


def _checked_run_dir(run_dir: Path | str) -> Path:
    original = Path(run_dir)
    if original.is_symlink():
        raise HandoffExportError(f"run directory must not be a symlink: {original}")
    try:
        source = reject_answer_key_path(original, "handoff export input")
    except OSError as exc:
        raise HandoffExportError(f"cannot resolve run directory {original}: {exc}") from exc
    if not source.is_dir():
        raise HandoffExportError(f"run directory is not a directory: {source}")
    return source


def _benchmark_run_root(source: Path) -> Path | None:
    """``source``'s parent when it holds a benchmark run's record beside its saved set, so that
    ``source`` is one of the run's package folders; otherwise ``None``, and nothing of the
    parent is read."""
    parent = source.parent
    if parent != source and all((parent / name).is_file() for name in _RUN_ROOT_MARKERS):
        return parent
    return None


def _is_remodel_run(source: Path) -> bool:
    """Whether ``source`` is a Remodel run folder: named as one, or holding a record only a
    Remodel run writes."""
    return source.name.endswith("-remodel") or any(
        (source / name).is_file() for name in _REMODEL_MARKERS
    )


def _checked_output(out_zip: Path | str, source: Path) -> Path:
    target = Path(out_zip)
    if target.is_symlink() or target.exists():
        raise HandoffExportError(f"refusing to overwrite existing archive: {target}")
    lexical = Path(os.path.abspath(target))
    if lexical == source or source in lexical.parents:
        raise HandoffExportError("handoff archive must be outside the run directory")
    parent = target.parent.resolve()
    resolved = parent / target.name
    if resolved == source or source in resolved.parents:
        raise HandoffExportError("handoff archive must be outside the run directory")
    parent.mkdir(parents=True, exist_ok=True)
    return resolved


def _collect(
    source: Path,
    secrets: Iterable[str | SecretStr | None],
    required: tuple[str, ...] = REQUIRED_ARTIFACTS,
    optional: tuple[str, ...] = OPTIONAL_ARTIFACTS,
    *,
    run_root: Path | None = None,
) -> tuple[
    list[tuple[str, bytes, int, bool]],
    dict[str, str],
    list[str],
    list[dict[str, str]],
    dict[str, Any],
]:
    # Each name with the folder it is read from: a benchmark package folder's run-root names
    # come from its run root alone, never from the package folder.
    selected: list[tuple[str, Path]] = [(relative, source) for relative in (*required, *optional)]
    if run_root is not None:
        selected = [item for item in selected if item[0] not in _RUN_ROOT_ARTIFACTS]
        selected += [(relative, run_root) for relative in _RUN_ROOT_ARTIFACTS]
    files: list[tuple[str, bytes, int, bool]] = []
    sources: dict[str, str] = {}
    missing: list[str] = []
    excluded: list[dict[str, str]] = []
    redacted_files: list[str] = []
    detector_hits: dict[str, list[str]] = {name: [] for name, _ in _SHAPE_DETECTORS}
    session_artifacts: dict[str, bytes] = {}
    total = 0
    for relative, folder in selected:
        path = folder / relative
        if path.is_symlink():
            raise HandoffExportError(f"allowlisted artifact must not be a symlink: {relative}")
        if not path.exists() or not path.is_file():
            if relative in required:
                missing.append(relative)
            continue
        resolved = path.resolve()
        if resolved.parent != folder:
            raise HandoffExportError(f"allowlisted artifact escapes the run directory: {relative}")
        try:
            size = path.stat().st_size
        except OSError as exc:
            if relative in required:
                missing.append(relative)
            else:
                excluded.append({"path": relative, "reason": f"unreadable: {type(exc).__name__}"})
            continue
        if size > MAX_ARTIFACT_BYTES:
            if relative in required:
                raise HandoffExportError(
                    f"required artifact {relative} exceeds {MAX_ARTIFACT_BYTES} bytes"
                )
            excluded.append({"path": relative, "reason": "exceeds per-artifact size limit"})
            continue
        try:
            with path.open("rb") as handle:
                raw = handle.read(MAX_ARTIFACT_BYTES + 1)
            if len(raw) > MAX_ARTIFACT_BYTES:
                if relative in required:
                    raise HandoffExportError(
                        f"required artifact {relative} exceeds {MAX_ARTIFACT_BYTES} bytes"
                    )
                excluded.append({"path": relative, "reason": "exceeds per-artifact size limit"})
                continue
            text = raw.decode("utf-8")
        except HandoffExportError:
            raise
        except (OSError, UnicodeDecodeError) as exc:
            if relative in required:
                missing.append(relative)
            else:
                excluded.append({"path": relative, "reason": f"unreadable: {type(exc).__name__}"})
            continue
        safe, hits = _sanitize(text, secrets)
        for detector, matched in hits.items():
            if matched:
                detector_hits[detector].append(relative)
        changed = safe != text
        if changed:
            redacted_files.append(relative)
        data = safe.encode("utf-8")
        if total + len(data) > MAX_TOTAL_BYTES:
            if relative in required:
                raise HandoffExportError(
                    f"selected required artifacts exceed {MAX_TOTAL_BYTES} bytes"
                )
            excluded.append({"path": relative, "reason": "exceeds total size limit"})
            continue
        total += len(data)
        files.append((relative, data, len(data), changed))
        sources[relative] = _FROM_RUN_DIR if folder == source else _FROM_RUN_ROOT
        if relative in ("session.json", "attention.json", "report.md"):
            session_artifacts[relative] = raw
    stale = _stale_session_artifacts(session_artifacts)
    if stale:
        files = [item for item in files if item[0] not in stale]
        for relative in stale:
            sources.pop(relative)
        excluded.extend(
            {"path": relative, "reason": "names another session than session.json"}
            for relative in sorted(stale)
        )
        redacted_files = [name for name in redacted_files if name not in stale]
        detector_hits = {
            detector: [name for name in names if name not in stale]
            for detector, names in detector_hits.items()
        }
    scan = {
        "method": "configured secret substrings and provider-key shape detectors",
        "configured_values_checked": bool(tuple(secrets)),
        "redacted_files": sorted(redacted_files),
        "shape_hits": {key: sorted(value) for key, value in detector_hits.items() if value},
        "coverage": "best_effort_unknown_secrets_may_remain",
    }
    return files, sources, missing, excluded, scan


def _session_uuid(value: Any) -> UUID | None:
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            pass
    return None


def _stale_session_artifacts(artifacts: Mapping[str, bytes]) -> set[str]:
    """Check the original bounded bytes, before redaction can change their session ids.

    The attention reader owns its stale-session comparison. Give it only the captured
    bytes so it cannot read unbounded files or a later re-run's replacements. Malformed
    records keep the existing export handling when identity cannot be established.
    """
    session = _json_object_bytes(artifacts.get("session.json"))
    session_id = _session_uuid(session.get("session_id")) if session is not None else None
    if session_id is None:
        return set()
    stale: set[str] = set()
    if "attention.json" in artifacts:
        try:
            with tempfile.TemporaryDirectory(prefix="swreview-handoff-") as directory:
                snapshot = Path(directory)
                for name in ("session.json", "attention.json"):
                    (snapshot / name).write_bytes(artifacts[name])
                read_attention_record(snapshot)
        except StaleAttentionRecord:
            stale.add("attention.json")
        except (OSError, ValueError, RecursionError):
            pass
    for line in artifacts.get("report.md", b"").decode("utf-8").splitlines():
        if line.startswith("- Session:"):
            report_id = _session_uuid(line.removeprefix("- Session:").strip())
            if report_id is not None and report_id != session_id:
                stale.add("report.md")
                break
    return stale


def _sanitize(text: str, secrets: Iterable[str | SecretStr | None]) -> tuple[str, dict[str, bool]]:
    safe = redact(text, secrets)
    hits: dict[str, bool] = {}
    for name, detector in _SHAPE_DETECTORS:
        found = bool(detector.search(safe))
        hits[name] = found
        if found:
            safe = detector.sub(MASK, safe)
    return safe, hits


def _manifest(
    source: Path,
    files: list[tuple[str, bytes, int, bool]],
    *,
    sources: Mapping[str, str],
    missing: list[str],
    excluded: list[dict[str, str]],
    scan: dict[str, Any],
    timestamp: datetime,
    repo_dir: Path,
    artifact_data: Mapping[str, bytes],
    run_kind: str = "review",
) -> dict[str, Any]:
    records = [
        {
            "path": relative,
            "size_bytes": size,
            "sha256": hashlib.sha256(data).hexdigest(),
            "redacted": redacted,
            "source": sources[relative],
        }
        for relative, data, size, redacted in files
    ]
    session = _json_object_bytes(artifact_data.get("session.json"))
    provenance = _json_object_bytes(artifact_data.get(PROVENANCE_FILE))
    return {
        "schema": HANDOFF_SCHEMA,
        "exported_at": timestamp.isoformat(),
        "source_run": str(source),
        "run_kind": run_kind,
        "source_reference_policy": _SOURCE_REFERENCE_POLICY,
        "build_identity": {**_git_identity(repo_dir), "captured_at": timestamp.isoformat()},
        "artifacts": records,
        "missing_artifacts": sorted(missing),
        "excluded_artifacts": excluded,
        "recorded_run_provenance": _provenance_summary(provenance),
        "session_summary": _session_summary(session),
        "secret_scan": scan,
    }


def _json_object_bytes(data: bytes | None) -> dict[str, Any] | None:
    if data is None:
        return None
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


# The states a session's model_status may hold, read from the one model that defines them.
_MODEL_STATES: tuple[str, ...] = get_args(ModelStatus.model_fields["state"].annotation)


def _session_summary(session: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Carry only a recognized model-status state beside the provider information.

    Missing or null model status adds no key. A non-mapping status or missing, non-string
    or unknown state adds model_status=None without blocking the export.
    """
    if session is None:
        return None
    coverage = session.get("coverage")
    coverage_counts: dict[str, int | None] = {}
    coverage_status = "valid"
    if not isinstance(coverage, Mapping):
        coverage_status = "unreadable"
    else:
        for name in ("checked", "skipped", "unresolved", "failed", "out_of_scope"):
            if name not in coverage:
                coverage_counts[name] = 0
                continue
            bucket = coverage[name]
            if isinstance(bucket, list):
                coverage_counts[name] = len(bucket)
            else:
                coverage_counts[name] = None
                coverage_status = "unreadable"
    requests = session.get("evidence_requests")
    request_status = "valid"
    if not isinstance(requests, list) or any(
        not isinstance(item, Mapping) for item in requests
    ):
        request_counts: dict[str, int | None] = {"open": None, "answered": None}
        request_status = "unreadable"
    else:
        request_counts = {
            "open": sum(item.get("status") == "open" for item in requests),
            "answered": sum(item.get("status") == "answered" for item in requests),
        }
    provider = session.get("provider_info")
    provider_safe = {
        key: provider.get(key)
        for key in ("provider", "model", "effort_mapping", "key_source")
        if isinstance(provider, Mapping) and key in provider
    }
    model_status = session.get("model_status")
    model_state = model_status.get("state") if isinstance(model_status, Mapping) else None
    if not isinstance(model_state, str) or model_state not in _MODEL_STATES:
        model_state = None
    return {
        key: session.get(key)
        for key in ("session_id", "package_id", "design_id", "started_at", "ended_at", "model")
    } | {
        "provider_info": provider_safe or None,
        **({"model_status": model_state} if model_status is not None else {}),
        "efficiency": session.get("efficiency"),
        "model_view": session.get("model_view"),
        "explanations": {
            "enabled": bool(session.get("explanations_enabled", False)),
            "fingerprint": session.get("finding_explanation_fingerprint"),
            "count": _explanation_count(session.get("finding_explanations")),
        },
        "coverage_counts": coverage_counts,
        "coverage_status": coverage_status,
        "evidence_request_counts": request_counts,
        "evidence_request_status": request_status,
        "usage": session.get("usage"),
    }


def _explanation_count(explanations: Any) -> int:
    """How many explanations the model wrote: a run folder written before feature 013 may hold
    the pass's fallback sentence for a row it did not explain, which is not one (013
    `contracts/sources.md` section 4, FR-043)."""
    if not isinstance(explanations, Mapping):
        return 0
    return sum(1 for text in explanations.values() if text != EXPLANATION_UNAVAILABLE)


_PROVENANCE_FIELDS: tuple[str, ...] = (
    "commit", "lever", "arm", "rep", "provider", "model", "effort", "max_steps",
    "checklist_digest", "set_digest", "started_at", "set_too_small_override", "efficiency",
    "explanations_enabled", "provenance_schema", "pane_defaults", "model_view", "profile_digest",
    "profile_is_example", "live_tools", "inert_settings", "prompt_digest", "tree_dirty",
    "max_answer_turns",
    "package_time_limit_s", "stream_activity_window_s", "stop_grace_s", "retry_policy",
)
"""The run provenance fields a bundle carries: a literal tuple, so a field the record gains
reaches the bundle only once it is named here, and a test holds it equal to
``RunProvenance.model_fields`` (014 `contracts/provenance.md` section 7). None is a path."""


def _provenance_summary(provenance: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if provenance is None:
        return None
    return {key: provenance.get(key) for key in _PROVENANCE_FIELDS if key in provenance}


def _git_identity(repo_dir: Path) -> dict[str, Any]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_dir), capture_output=True, text=True, check=False, timeout=10,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=str(repo_dir), capture_output=True, text=True, check=False, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return {"git_revision": None, "dirty": None, "source": "export-time"}
    return {
        "git_revision": revision.stdout.strip() if revision.returncode == 0 else None,
        "dirty": bool(status.stdout) if status.returncode == 0 else None,
        "source": "export-time",
    }


def _json_bytes(
    value: Mapping[str, Any], *, secrets: Iterable[str | SecretStr | None] = ()
) -> bytes:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    safe, _ = _sanitize(text, secrets)
    return safe.encode("utf-8")


def _publish_zip(
    target: Path, entries: Iterable[tuple[str, bytes, int, bool]]
) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{target.name}.", suffix=".tmp", dir=target.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data, _, _ in sorted(entries, key=lambda item: item[0]):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data)
        with temporary.open("rb+") as handle:
            os.fsync(handle.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError as exc:
            raise HandoffExportError(f"refusing to overwrite existing archive: {target}") from exc
        except OSError as exc:
            raise HandoffExportError(
                f"could not atomically publish handoff archive: {exc}"
            ) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
