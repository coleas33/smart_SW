"""The run-folder index lever 9 looks a package up in, and its bounded fallback (T091).

`run_root/package-index.json` holds one line per successful dump - the reuse key, the run
folder, when it was written, the dump profile and the package's size (data-model.md 9.4).
The extractor appends a line; this module and its C# counterpart
(`SwReview.Extractor.Dump.PackageIndex`, read through `RunFolders`) read it.

**Why an index at all** (all VERIFIED): `RunFolders.Create` always makes a fresh timestamped
folder (`Review/RunFolders.cs:296-317`), "the pane's latest run" is an in-memory field
cleared on detach (`Review/ReviewHost.cs:258,271,288,380`), and `RunFolders.ProfileOf` reads
only the first 8 KiB of one `package.json` (`:52,125-186`) **because** a full package is tens
of megabytes and the read happens on the SOLIDWORKS application thread. A lookup that parsed
every package under the run root is the thing those classes were written to avoid.

Three rules, each one a way this can fail badly:

- a missing, unreadable or unparseable index is a **miss, never an error**: the index is a
  cache of what is already on disk, and a review that failed because a cache was corrupt
  would be a lever that made the product less reliable than not having it;
- the lookup **verifies the folder and its `package.json` still exist**, because the index
  cannot know that an engineer deleted a folder in Explorer;
- the fallback, when there is no index, is a **bounded head scan** of the N most recent
  folders using the `ProfileOf` technique, which is why `reuse_key` is written near the top
  of a package.

`reusable_for` is the whole decision: the key from `reuse.py`, the refusals from `reuse.py`,
and then the lookup. A package that matches can still be one that must not be reused.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from swreview.benchmark.reuse import DumpOptions, may_reuse, package_reuse_key
from swreview.ir.models import EvidencePackage

INDEX_FILE_NAME = "package-index.json"
"""One JSON object per line, appended. A partial last line costs only that line."""

PACKAGE_FILE_NAME = "package.json"

SCAN_FOLDER_LIMIT = 20
"""How many folders the fallback scan may open, most recent first.

A run root accumulates one folder per review, so an unbounded scan would get slower every
week on the one thread SOLIDWORKS is waiting on. Past the cap the answer is "no reuse",
which costs one dump; a stall costs the engineer's afternoon.
"""

HEAD_BYTES = 8 * 1024
"""How much of a `package.json` the scan reads - the `RunFolders.ProfileOf` budget."""

_REUSE_KEY = re.compile(r'"reuse_key"\s*:\s*"([0-9a-f]{64})"')
_PROFILE = re.compile(r'"profile"\s*:\s*"([a-z_]+)"')


class PackageIndexRow(BaseModel):
    """One dump's line in the index (data-model.md 9.4)."""

    model_config = ConfigDict(strict=False, extra="forbid")

    reuse_key: str
    folder: str
    """Run folder name, relative to `run_root`."""

    written_at: datetime
    """When the package was written; the "(age)" the pane's status line prints."""

    profile: str
    """So a profile mismatch is rejected before any file is opened."""

    package_bytes: int = Field(ge=0)
    """So the copy cost is known before it is paid."""


def index_path(run_root: Path | str) -> Path:
    return Path(run_root) / INDEX_FILE_NAME


def append_row(run_root: Path | str, row: PackageIndexRow) -> None:
    """Append one row. Appending rather than rewriting: a dump that dies mid-write must
    not be able to cost every earlier folder its row."""
    target = index_path(run_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as index:
        index.write(row.model_dump_json() + "\n")


def read_index(run_root: Path | str) -> list[PackageIndexRow]:
    """Every readable row, in the order they were appended. Never raises.

    A line that is not JSON, or is JSON that is not a row, is skipped: the last line of an
    index is written by a dump that may have been killed halfway through it, and the rows
    before it are still true.
    """
    try:
        text = index_path(run_root).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    rows: list[PackageIndexRow] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            rows.append(PackageIndexRow.model_validate_json(line))
        except ValidationError:
            continue
    return rows


def find_reusable(
    run_root: Path | str,
    reuse_key: str,
    profile: str,
    *,
    scan_limit: int = SCAN_FOLDER_LIMIT,
) -> PackageIndexRow | None:
    """The most recent run folder holding a package with this key and profile, or `None`.

    The index first, because it answers without opening a package at all; the bounded head
    scan when the index names nothing usable, because an index that was never written -
    or was written by a build that did not have one - is a reason to look, not a reason to
    fail.
    """
    root = Path(run_root)

    for row in sorted(read_index(root), key=lambda row: row.written_at, reverse=True):
        if row.reuse_key != reuse_key or row.profile != profile:
            continue
        if _package_of(root, row) is not None:
            return row

    return _scan(root, reuse_key, profile, scan_limit)


def reusable_for(
    package: EvidencePackage,
    options: DumpOptions,
    run_root: Path | str,
    *,
    unsaved_changes: bool | None,
) -> PackageIndexRow | None:
    """The run folder `package` may be reused from, or `None`.

    The key says whether anything matches and `reuse_refusals` says whether matching is
    enough; both have to answer before a dump is skipped. The key is computed from the
    package in hand - at reuse time, from the live document's references now - and never
    read back from a file that claims one.
    """
    if not may_reuse(package, unsaved_changes=unsaved_changes):
        return None

    return find_reusable(
        run_root, package_reuse_key(package, options), package.extractor.profile
    )


def head_of(package_file: Path) -> tuple[str | None, str | None]:
    """`(reuse_key, profile)` from the first `HEAD_BYTES` of a package, or `(None, None)`.

    Only the head is read, and it is searched rather than parsed: the head of a package is
    by definition truncated JSON, and `reuse_key` and `extractor.profile` are both written
    near the top of the file so that this bounded read can answer.
    """
    try:
        with package_file.open("rb") as handle:
            head = handle.read(HEAD_BYTES).decode("utf-8", errors="ignore")
    except OSError:
        return (None, None)

    key = _REUSE_KEY.search(head)
    profile = _PROFILE.search(head)
    return (key.group(1) if key else None, profile.group(1) if profile else None)


def _scan(
    run_root: Path, reuse_key: str, profile: str, scan_limit: int
) -> PackageIndexRow | None:
    """The fallback: the `ProfileOf` technique over the N most recent folders."""
    for folder in _recent_folders(run_root, scan_limit):
        package_file = folder / PACKAGE_FILE_NAME
        found_key, found_profile = head_of(package_file)
        if found_key != reuse_key or found_profile != profile:
            continue
        try:
            stat = package_file.stat()
        except OSError:
            continue
        return PackageIndexRow(
            reuse_key=reuse_key,
            folder=folder.name,
            written_at=datetime.fromtimestamp(stat.st_mtime, UTC),
            profile=profile,
            package_bytes=stat.st_size,
        )
    return None


def _recent_folders(run_root: Path, scan_limit: int) -> list[Path]:
    """Run folders, most recent first, capped. Names start `yyyyMMdd-HHmmss`, so the name
    orders them without a stat per folder."""
    try:
        folders = [child for child in run_root.iterdir() if child.is_dir()]
    except OSError:
        return []
    return sorted(folders, key=lambda folder: folder.name, reverse=True)[:scan_limit]


def _package_of(run_root: Path, row: PackageIndexRow) -> Path | None:
    """The row's `package.json`, or `None` when the row no longer describes a run folder.

    A folder name that leaves the run root is refused rather than followed: a row nobody
    wrote on purpose must not be able to name a directory somewhere else on the machine.
    """
    folder = (run_root / row.folder).resolve()
    try:
        folder.relative_to(run_root.resolve())
    except ValueError:
        return None
    if folder == run_root.resolve():
        return None

    package_file = folder / PACKAGE_FILE_NAME
    return package_file if package_file.is_file() else None
