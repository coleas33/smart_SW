"""`source-attestation.json`: the recorded half, the re-check and the verdict (T087).

`data-model.md` section 5 is normative for every field name here, and the type itself is
`plan.py`'s `SourceAttestation` - the plan carries the same record, so a second definition
is how the two artifacts would start to disagree. This module is what writes the file,
reads it back, and re-checks the three values at report time.

**Two halves, one file.** The recorded half - path, byte length, `LastWriteTimeUtc`,
content hash, the source's design id, the vault fields and the copy path - is measured in
C# by `RemodelCopy.RecordSource` **before the copy is made and before any document handle
to the source could exist**, and arrives here inside `remodel.open`'s reply. Nothing in
this module measures it a second time: `attestation_from_open` opens no file at all, so
there is exactly one answer to the question the attestation exists to settle. The report
half - `rechecked_at`, `matches` and the saved copy's hash - is written by `recheck`.

**A difference is a hard failure of the run** (FR-040, SC-001), whatever the copy looks
like: it means something wrote to the engineer's file while the run was going on, and the
run can no longer claim it did not. The call order is deliberate and is the caller's to
follow: `recheck`, then `write_attestation` with the completed record, then the failure -
`require_source_unchanged` where the caller can only stop, and `apply.verify` recording
`source_changed`'s sentence as a verification reason where the run still has a copy to
discard and a report to write - so the evidence is on disk before the run fails on it.

**"Could not check" is never "unchanged"** (constitution Principle I). A source that has
gone missing, or that cannot be read because something holds it open, is reported as a
difference on `path` and fails the run: the alternative is a passing run whose central
claim was never tested.

**The source is read and never written.** The one filesystem access this module makes to
the engineer's file is a chunked `open(..., "rb")` for the hash, beside a `stat()`; every
other access it makes is inside the run folder.

**Precision.** `LastWriteTimeUtc` is compared truncated to whole microseconds on both
sides. A .NET tick has a seventh decimal digit that no Python `datetime` can hold, so an
exact comparison would fail every run on Windows for a difference nobody made; a coarser
one would be a tolerance on engineering evidence. Length and hash are compared exactly.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from swreview.remodel.plan import SourceAttestation

__all__ = [
    "ATTESTATION_FILE_NAME",
    "RECHECKED_FIELDS",
    "RECORDED_FIELDS",
    "AttestationCheck",
    "AttestationDifference",
    "DifferenceField",
    "SourceChanged",
    "attestation_from_open",
    "read_attestation",
    "recheck",
    "require_source_unchanged",
    "source_changed",
    "write_attestation",
]

ATTESTATION_FILE_NAME = "source-attestation.json"
"""The run folder's copy of the record (`contracts/run-artifacts.md`)."""

RECORDED_FIELDS: tuple[str, ...] = (
    "path",
    "length_bytes",
    "last_write_utc",
    "sha256",
    "source_design_id",
    "recorded_at",
    "copy_path",
    "vault_path",
    "vault_revision",
)
"""What the C# side records at copy time, in `data-model.md` section 5's order. Every one
of them is required in the reply: an absent hash is not an empty hash, and nothing here
writes a default for a value the run's central claim rests on."""

RECHECKED_FIELDS: tuple[str, ...] = ("rechecked_at", "matches", "copy_sha256_after_save")
"""The half `recheck` writes. A reply that already carries one of them is refused: the
verdict is written at report time, by this module, and by nothing else."""

_CHUNK = 1 << 20

DifferenceField = Literal["path", "length_bytes", "last_write_utc", "sha256"]
"""The three re-checked values, plus `path` for a source that could not be re-read at all
- missing, renamed, or held open by something else. That last one is a difference and not
an exception because the artifact has to record it: a run whose source could not be
re-checked failed, and the file says so."""


class AttestationDifference(BaseModel):
    """One value that is not what it was, rendered for the report.

    Both sides are strings so a byte count, a timestamp and a hash all file the same way
    and the report prints them without knowing which it has.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    field: DifferenceField
    recorded: str
    observed: str


class AttestationCheck(BaseModel):
    """The completed record and every difference behind its verdict.

    Every failing value is listed, not just the first: an engineer told only that "the
    hash differs" goes and looks, fixes that, and comes back to find the length differs
    too.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    attestation: SourceAttestation
    differences: tuple[AttestationDifference, ...]


class SourceChanged(RuntimeError):
    """The engineer's file is not what it was: a hard failure of the run.

    Carries the completed record and the differences so a caller that catches it can file
    both without re-deriving either.
    """

    def __init__(self, check: AttestationCheck) -> None:
        self.attestation = check.attestation
        self.differences = check.differences
        super().__init__(source_changed(check))


def source_changed(check: AttestationCheck) -> str:
    """The sentence a source that is not what it was fails the run with.

    One sentence in one place: `SourceChanged` raises it where the caller can only stop
    (`replay.py`'s fallback) and `apply.verify` records it as a verification reason where
    the run still has a report to write. A second wording is how the exception and the
    report would start to describe one difference two ways.
    """
    moved = "; ".join(
        f"{difference.field}: recorded {difference.recorded}, now {difference.observed}"
        for difference in check.differences
    )
    return (
        f"the source '{check.attestation.path}' is not what it was when the copy was "
        f"made ({moved}), so this run is failed: it cannot claim the engineer's file "
        f"was untouched"
    )


# --- the recorded half ------------------------------------------------------------


def attestation_from_open(payload: Mapping[str, Any]) -> SourceAttestation:
    """The recorded half, read from `remodel.open`'s `source_attestation` block.

    Opens nothing: the three values were measured in C# before the copy existed, and a
    second measurement here would be a second answer. The verdict fields are `None`,
    because the re-check has not run.
    """
    body = _required(payload, RECORDED_FIELDS, "remodel.open's source_attestation")
    path = _text(body["path"], "path")
    copy_path = _text(body["copy_path"], "copy_path")
    if _normalized(path) == _normalized(copy_path):
        raise ValueError(
            f"the attestation records '{path}' as both the source and the copy; the copy "
            f"is a new file in the run folder and is never the engineer's file"
        )
    return SourceAttestation(
        path=path,
        length_bytes=_count(body["length_bytes"], "length_bytes"),
        last_write_utc=_utc(body["last_write_utc"], "last_write_utc"),
        sha256=_text(body["sha256"], "sha256"),
        source_design_id=_text(body["source_design_id"], "source_design_id"),
        recorded_at=_utc(body["recorded_at"], "recorded_at"),
        rechecked_at=None,
        matches=None,
        vault_path=_optional_text(body["vault_path"], "vault_path"),
        vault_revision=_optional_text(body["vault_revision"], "vault_revision"),
        copy_path=copy_path,
        copy_sha256_after_save=None,
    )


# --- the artifact -----------------------------------------------------------------


def write_attestation(run_dir: Path, attestation: SourceAttestation) -> Path:
    """Write `source-attestation.json` into `run_dir` and return the path written.

    Called twice in a run: once at plan time with the recorded half, once at report time
    with the completed record. It touches nothing outside the run folder.
    """
    target = run_dir / ATTESTATION_FILE_NAME
    target.write_text(attestation.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return target


def read_attestation(run_dir: Path) -> SourceAttestation:
    """Read the artifact back, refusing a file missing any field of section 5.

    The pane and the exceptions carry-forward both read this file rather than the run's
    memory, so a truncated or hand-edited one is refused here rather than half-read.
    """
    body = json.loads((run_dir / ATTESTATION_FILE_NAME).read_text(encoding="utf-8"))
    if not isinstance(body, Mapping):
        raise ValueError(f"{ATTESTATION_FILE_NAME} does not hold an object")
    stored = _required(body, RECORDED_FIELDS + RECHECKED_FIELDS, ATTESTATION_FILE_NAME)
    return SourceAttestation(
        path=_text(stored["path"], "path"),
        length_bytes=_count(stored["length_bytes"], "length_bytes"),
        last_write_utc=_utc(stored["last_write_utc"], "last_write_utc"),
        sha256=_text(stored["sha256"], "sha256"),
        source_design_id=_text(stored["source_design_id"], "source_design_id"),
        recorded_at=_utc(stored["recorded_at"], "recorded_at"),
        rechecked_at=None
        if stored["rechecked_at"] is None
        else _utc(stored["rechecked_at"], "rechecked_at"),
        matches=_verdict(stored["matches"]),
        vault_path=_optional_text(stored["vault_path"], "vault_path"),
        vault_revision=_optional_text(stored["vault_revision"], "vault_revision"),
        copy_path=_text(stored["copy_path"], "copy_path"),
        copy_sha256_after_save=_optional_text(
            stored["copy_sha256_after_save"], "copy_sha256_after_save"
        ),
    )


# --- the re-check -----------------------------------------------------------------


def recheck(
    attestation: SourceAttestation,
    *,
    at: datetime,
    copy_sha256_after_save: str | None = None,
) -> AttestationCheck:
    """Re-read the source and compare all three recorded values.

    Returns the completed record beside every difference; it raises nothing, so the caller
    writes the artifact before failing the run on it. The recorded values are carried
    across word for word - the file still says what the source was at plan time.
    """
    differences = _differences(attestation)
    return AttestationCheck(
        attestation=attestation.model_copy(
            update={
                "rechecked_at": at,
                "matches": not differences,
                "copy_sha256_after_save": copy_sha256_after_save,
            }
        ),
        differences=differences,
    )


def require_source_unchanged(check: AttestationCheck) -> AttestationCheck:
    """Return `check` unchanged, or raise `SourceChanged` if the source moved.

    The hard failure of FR-040 and SC-001, raised rather than logged: a run whose source
    changed is failed however well the copy came out, and a warning beside a passing run
    is exactly the artifact Principle I exists to prevent.
    """
    if check.differences:
        raise SourceChanged(check)
    return check


def _differences(attestation: SourceAttestation) -> tuple[AttestationDifference, ...]:
    source = Path(attestation.path)
    try:
        stat = source.stat()
    except OSError as exc:
        return (_unreadable(attestation.path, exc),)
    differences: list[AttestationDifference] = []
    if stat.st_size != attestation.length_bytes:
        differences.append(
            AttestationDifference(
                field="length_bytes",
                recorded=str(attestation.length_bytes),
                observed=str(stat.st_size),
            )
        )
    observed_write = _last_write_utc(stat.st_mtime_ns)
    if observed_write != attestation.last_write_utc.astimezone(UTC):
        differences.append(
            AttestationDifference(
                field="last_write_utc",
                recorded=_stamp(attestation.last_write_utc),
                observed=_stamp(observed_write),
            )
        )
    try:
        observed_hash = _sha256(source)
    except OSError as exc:
        return (_unreadable(attestation.path, exc),)
    if observed_hash != attestation.sha256:
        differences.append(
            AttestationDifference(
                field="sha256", recorded=attestation.sha256, observed=observed_hash
            )
        )
    return tuple(differences)


def _unreadable(path: str, exc: OSError) -> AttestationDifference:
    """A source that could not be re-read at all is a difference, never a pass."""
    observed = (
        "no file at this path"
        if isinstance(exc, FileNotFoundError)
        else f"could not be read: {exc.strerror or exc}"
    )
    return AttestationDifference(field="path", recorded=path, observed=observed)


def _sha256(source: Path) -> str:
    """The content hash, read in chunks. The only mode the source is ever opened in."""
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _last_write_utc(mtime_ns: int) -> datetime:
    """The file's last-write time truncated - never rounded - to whole microseconds.

    The recorded half is truncated the same way and by the same rule: `datetime` holds no
    seventh decimal digit, so `fromisoformat` drops the .NET tick's last digit when the
    reply is read. Both sides therefore lose the same thing, and a file nobody wrote to
    compares equal.
    """
    seconds, nanoseconds = divmod(mtime_ns, 1_000_000_000)
    return datetime.fromtimestamp(seconds, UTC) + timedelta(microseconds=nanoseconds // 1000)


# --- reading the two documents this module is handed ------------------------------


def _required(body: Mapping[str, Any], fields: tuple[str, ...], what: str) -> Mapping[str, Any]:
    missing = [field for field in fields if field not in body]
    if missing:
        raise ValueError(f"{what} is missing {', '.join(missing)}")
    unexpected = sorted(set(body) - set(fields))
    if unexpected:
        raise ValueError(f"{what} carries {', '.join(unexpected)}, which it may not set here")
    return body


def _normalized(path: str) -> str:
    """A path as `DocumentIds.DesignId` normalizes it: trimmed, `/` to `\\`, lowercased.

    The same normalization, so "the copy is not the source" is decided the way the ids
    beside it are and a difference in case or slash cannot smuggle one past the other.
    """
    return path.strip().replace("/", "\\").lower()


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} is {value!r}, which is not a value to attest to")
    return value


def _optional_text(value: Any, field: str) -> str | None:
    return None if value is None else _text(value, field)


def _count(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} is {value!r}, which is not a byte count")
    return value


def _verdict(value: Any) -> bool | None:
    if value is not None and not isinstance(value, bool):
        raise ValueError(f"matches is {value!r}, which is neither a verdict nor 'not yet'")
    return value


def _utc(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field} is {value!r}, which is not a timestamp") from exc
    else:
        raise ValueError(f"{field} is {value!r}, which is not a timestamp")
    if moment.tzinfo is None:
        raise ValueError(
            f"{field} is {value!r}, which names no time zone; the attestation records UTC"
        )
    return moment.astimezone(UTC)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")
