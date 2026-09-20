"""Export a bounded, local handoff bundle for one review run.

The exporter is deliberately an allowlist rather than a folder copier.  A run folder may
sit beside native CAD files, credentials, screenshots, or temporary SDK state; none of
those become part of a handoff by discovery.  The package and report can still contain
paths to the real design, so the manifest says that those references remain external.

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
from typing import Any

from pydantic import SecretStr

from swreview.agent.settings import MASK, redact
from swreview.ir.loader import reject_answer_key_path
from swreview.secrets import KEY_SHAPES

__all__ = [
    "HANDOFF_SCHEMA",
    "HandoffExportError",
    "MAX_ARTIFACT_BYTES",
    "MAX_TOTAL_BYTES",
    "OPTIONAL_ARTIFACTS",
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
    "run-provenance.json",
    "check.json",
    "chat-log.jsonl",
    "extract.log",
    "extractor.log",
    "extraction.log",
    "check.log",
    "checks.log",
    "extractor.jsonl",
    "check.jsonl",
)
"""Known supplementary records; arbitrary files and recursive folders are excluded."""

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

    ``run_dir`` is the sole input tree.  Only :data:`REQUIRED_ARTIFACTS` and the exact
    names in :data:`OPTIONAL_ARTIFACTS` are read.  ``out_zip`` must be outside that tree.
    ``repo_dir`` identifies the checkout whose revision is recorded; when omitted, the
    run directory is used and a non-checkout simply records unknown build identity.
    ``exported_at`` is injectable so a manifest and ZIP can be reproduced in tests or by
    an archival caller that already has an export timestamp.
    """
    source = _checked_run_dir(run_dir)
    target = _checked_output(out_zip, source)
    timestamp = (exported_at or datetime.now(UTC)).astimezone(UTC)
    secret_values = tuple(secrets)
    files, missing, excluded, scan = _collect(source, secret_values)

    manifest = _manifest(
        source,
        files,
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
    source: Path, secrets: Iterable[str | SecretStr | None]
) -> tuple[
    list[tuple[str, bytes, int, bool]],
    list[str],
    list[dict[str, str]],
    dict[str, Any],
]:
    selected = (*REQUIRED_ARTIFACTS, *OPTIONAL_ARTIFACTS)
    files: list[tuple[str, bytes, int, bool]] = []
    missing: list[str] = []
    excluded: list[dict[str, str]] = []
    redacted_files: list[str] = []
    detector_hits: dict[str, list[str]] = {name: [] for name, _ in _SHAPE_DETECTORS}
    total = 0
    for relative in selected:
        path = source / relative
        if path.is_symlink():
            raise HandoffExportError(f"allowlisted artifact must not be a symlink: {relative}")
        if not path.exists() or not path.is_file():
            if relative in REQUIRED_ARTIFACTS:
                missing.append(relative)
            continue
        resolved = path.resolve()
        if resolved.parent != source:
            raise HandoffExportError(f"allowlisted artifact escapes the run directory: {relative}")
        try:
            size = path.stat().st_size
        except OSError as exc:
            if relative in REQUIRED_ARTIFACTS:
                missing.append(relative)
            else:
                excluded.append({"path": relative, "reason": f"unreadable: {type(exc).__name__}"})
            continue
        if size > MAX_ARTIFACT_BYTES:
            if relative in REQUIRED_ARTIFACTS:
                raise HandoffExportError(
                    f"required artifact {relative} exceeds {MAX_ARTIFACT_BYTES} bytes"
                )
            excluded.append({"path": relative, "reason": "exceeds per-artifact size limit"})
            continue
        try:
            with path.open("rb") as handle:
                raw = handle.read(MAX_ARTIFACT_BYTES + 1)
            if len(raw) > MAX_ARTIFACT_BYTES:
                if relative in REQUIRED_ARTIFACTS:
                    raise HandoffExportError(
                        f"required artifact {relative} exceeds {MAX_ARTIFACT_BYTES} bytes"
                    )
                excluded.append({"path": relative, "reason": "exceeds per-artifact size limit"})
                continue
            text = raw.decode("utf-8")
        except HandoffExportError:
            raise
        except (OSError, UnicodeDecodeError) as exc:
            if relative in REQUIRED_ARTIFACTS:
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
            if relative in REQUIRED_ARTIFACTS:
                raise HandoffExportError(
                    f"selected required artifacts exceed {MAX_TOTAL_BYTES} bytes"
                )
            excluded.append({"path": relative, "reason": "exceeds total size limit"})
            continue
        total += len(data)
        files.append((relative, data, len(data), changed))
    scan = {
        "method": "configured secret substrings and provider-key shape detectors",
        "configured_values_checked": bool(tuple(secrets)),
        "redacted_files": sorted(redacted_files),
        "shape_hits": {key: sorted(value) for key, value in detector_hits.items() if value},
        "coverage": "best_effort_unknown_secrets_may_remain",
    }
    return files, missing, excluded, scan


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
    missing: list[str],
    excluded: list[dict[str, str]],
    scan: dict[str, Any],
    timestamp: datetime,
    repo_dir: Path,
    artifact_data: Mapping[str, bytes],
) -> dict[str, Any]:
    records = [
        {
            "path": relative,
            "size_bytes": size,
            "sha256": hashlib.sha256(data).hexdigest(),
            "redacted": redacted,
        }
        for relative, data, size, redacted in files
    ]
    session = _json_object_bytes(artifact_data.get("session.json"))
    provenance = _json_object_bytes(artifact_data.get("run-provenance.json"))
    return {
        "schema": HANDOFF_SCHEMA,
        "exported_at": timestamp.isoformat(),
        "source_run": str(source),
        "source_reference_policy": (
            "package and report may contain real-design paths; native CAD files, machine "
            "settings, credentials and arbitrary neighboring files are excluded"
        ),
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
    except (UnicodeDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _session_summary(session: Mapping[str, Any] | None) -> dict[str, Any] | None:
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
    return {
        key: session.get(key)
        for key in ("session_id", "package_id", "design_id", "started_at", "ended_at", "model")
    } | {
        "provider_info": provider_safe or None,
        "efficiency": session.get("efficiency"),
        "explanations": {
            "enabled": bool(session.get("explanations_enabled", False)),
            "fingerprint": session.get("finding_explanation_fingerprint"),
            "count": len(session.get("finding_explanations", {}))
            if isinstance(session.get("finding_explanations"), Mapping)
            else 0,
        },
        "coverage_counts": coverage_counts,
        "coverage_status": coverage_status,
        "evidence_request_counts": request_counts,
        "evidence_request_status": request_status,
        "usage": session.get("usage"),
    }


def _provenance_summary(provenance: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if provenance is None:
        return None
    keys = (
        "commit", "lever", "arm", "rep", "provider", "model", "effort", "max_steps",
        "checklist_digest", "set_digest", "started_at", "set_too_small_override", "efficiency",
        "explanations_enabled",
    )
    return {key: provenance.get(key) for key in keys if key in provenance}


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
