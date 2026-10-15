"""Private engineering context persistence, separate from source CAD."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import ValidationError

from swreview.atomic import write_atomic
from swreview.engineering_context.models import (
    AppliedForceRecord,
    ConfirmationReceipt,
    ContextArtifact,
    EngineeringRecord,
    EvidenceBaseline,
    canonical_bytes,
    context_digest,
    dependency_digest,
    record_digest,
)
from swreview.ir.loader import AnswerKeyAccessError, reject_answer_key_path


class ContextStoreError(ValueError):
    """A context artifact cannot be safely loaded or published."""


def _reject_link(path: Path) -> None:
    for candidate in (path, *path.parents):
        try:
            entry = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(entry.st_mode) or (
            getattr(entry, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ContextStoreError("Context storage cannot use a link or reparse point.")


def check_store_directory(
    directory: Path | str,
    *,
    source_paths: Iterable[Path | str] = (),
    source_roots: Iterable[Path | str] = (),
) -> Path:
    """Validate private storage without creating it or naming source CAD in errors."""
    original = Path(directory).absolute()
    try:
        private = reject_answer_key_path(original, "engineering context uses public evidence")
    except AnswerKeyAccessError:
        raise ContextStoreError(
            "Engineering context cannot access withheld benchmark inputs."
        ) from None
    _reject_link(original)
    cad_suffixes = {".sldprt", ".sldasm", ".slddrw"}
    if private.suffix.casefold() in cad_suffixes:
        raise ContextStoreError("Context storage must be separate from source CAD.")
    if private.exists() and not private.is_dir():
        raise ContextStoreError("Context storage must be a directory.")
    roots = [Path(root).resolve() for root in source_roots]
    roots.extend(Path(source).resolve().parent for source in source_paths)
    if any(private.is_relative_to(root) for root in roots):
        raise ContextStoreError("Context storage must be separate from source CAD.")
    for candidate in (private, private.parent):
        if candidate.is_dir() and any(
            child.suffix.casefold() in cad_suffixes for child in candidate.iterdir()
        ):
            raise ContextStoreError("Context storage must be separate from source CAD.")
    return private


class ContextStoreBusy(ContextStoreError):
    """Another publisher owns the lock; old locks require explicit operator recovery."""


class ContextStoreConflict(ContextStoreError):
    """The presented head or input digest no longer matches."""


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def _decode(data: bytes) -> ContextArtifact:
    try:
        raw = json.loads(data, object_pairs_hook=_unique_keys)
        if not isinstance(raw, dict) or raw.get("schema_version") != "1.0.0":
            raise ContextStoreError("Unsupported engineering context schema version.")
        # JSON validation re-runs nested validators even after model_copy/model_construct.
        return ContextArtifact.model_validate_json(data)
    except (ValidationError, ValueError, UnicodeError) as error:
        if isinstance(error, ContextStoreError):
            raise
        raise ContextStoreError("Invalid engineering context artifact.") from None


def _validated(artifact: ContextArtifact) -> ContextArtifact:
    try:
        return _decode(artifact.model_dump_json(warnings=False).encode("utf-8"))
    except (TypeError, ValueError, AttributeError):
        raise ContextStoreError("Invalid engineering context artifact or schema version.") from None


def _check_confirmable(record: EngineeringRecord) -> None:
    if (
        not record.anchor.document_id
        or not record.anchor.configuration
        or record.provenance.kind == "unknown"
    ):
        raise ContextStoreError("Engineering input is incomplete and cannot be confirmed.")
    if isinstance(record, AppliedForceRecord) and (
        record.magnitude.state != "known" or record.direction is None or record.frame is None
    ):
        raise ContextStoreError("Applied force is incomplete and cannot be confirmed.")
    if isinstance(record, AppliedForceRecord):
        from swreview.engineering_context.binding import force_in_root

        try:
            force_in_root(record)
        except ValueError:
            raise ContextStoreError(
                "Applied force has no representable canonical quantity or point."
            ) from None


def _check_next(previous: ContextArtifact | None, candidate: ContextArtifact) -> None:
    if previous is None:
        if candidate.revision != 1 or candidate.previous_digest is not None:
            raise ContextStoreError("The first context revision must be one without a predecessor.")
        previous_records = {}
        old_receipts = ()
    else:
        if candidate.baseline != previous.baseline:
            raise ContextStoreError("A changed evidence baseline requires a new context.")
        if (
            candidate.context_id != previous.context_id
            or candidate.revision != previous.revision + 1
            or candidate.previous_digest != context_digest(previous)
        ):
            raise ContextStoreError(
                "Context revision or predecessor does not match the published head."
            )
        previous_records = {record.record_id: record for record in previous.records}
        old_receipts = previous.confirmations
    current_records = {record.record_id: record for record in candidate.records}
    if not previous_records.keys() <= current_records.keys():
        raise ContextStoreError("Removing engineering records is not supported in this increment.")
    for record in candidate.records:
        old = previous_records.get(record.record_id)
        if old is None and record.revision != 1:
            raise ContextStoreError("A new engineering record must begin at revision one.")
        if old is not None:
            same = record_digest(record) == record_digest(old)
            if (same and record.revision != old.revision) or (
                not same and record.revision != old.revision + 1
            ):
                raise ContextStoreError("An edited engineering record requires the next revision.")
    if candidate.confirmations[: len(old_receipts)] != old_receipts:
        raise ContextStoreError(
            "Historical confirmation receipts must remain unchanged and ordered."
        )
    for receipt in candidate.confirmations[len(old_receipts) :]:
        record = current_records[receipt.record_id]
        if (
            receipt.record_revision != record.revision
            or receipt.record_digest != record_digest(record)
            or receipt.dependency_digest != dependency_digest(candidate.baseline, record)
        ):
            raise ContextStoreError(
                "A confirmation receipt does not match the presented input revision."
            )
        if receipt.decision == "confirmed":
            _check_confirmable(record)


class ContextStore:
    """An atomic head with immutable revision files and a cross-process compare-and-swap.

    Interrupted publication can leave an unreferenced revision file. Only an identical
    retry may use it; the store never overwrites it or treats it as a published decision.
    A process that dies while holding the lock leaves an explicit recovery condition.
    """

    def __init__(self, directory: Path | str, *, source_roots: Iterable[Path | str] = ()):
        self.source_roots = tuple(Path(root) for root in source_roots)
        self.directory = check_store_directory(directory, source_roots=self.source_roots)
        self.head_path = self.directory / "engineering-context.json"
        self.lock_path = self.directory / ".engineering-context.lock"
        self.history_directory = self.directory / "revisions"

    def _check_paths(self) -> None:
        check_store_directory(self.directory, source_roots=self.source_roots)
        for path in (self.head_path, self.lock_path, self.history_directory):
            _reject_link(path)
        if self.history_directory.exists() and not self.history_directory.is_dir():
            raise ContextStoreError("Context revision history must be a directory.")

    def _revision_path(self, revision: int) -> Path:
        path = self.history_directory / f"{revision:08d}.json"
        _reject_link(path)
        return path

    def _read(self, path: Path) -> ContextArtifact:
        _reject_link(path)
        try:
            return _decode(path.read_bytes())
        except OSError:
            raise ContextStoreError(
                "Unable to read a published engineering context artifact."
            ) from None

    def _chain(self) -> tuple[ContextArtifact, ...]:
        self._check_paths()
        if not self.head_path.exists():
            return ()
        head = self._read(self.head_path)
        history: list[ContextArtifact] = []
        previous = None
        for revision in range(1, head.revision + 1):
            current = self._read(self._revision_path(revision))
            if current.revision != revision:
                raise ContextStoreError("Published context history has an invalid revision.")
            _check_next(previous, current)
            history.append(current)
            previous = current
        if history[-1] != head:
            raise ContextStoreError("The context head differs from its immutable revision history.")
        return tuple(history)

    def load(self) -> ContextArtifact | None:
        """Load only a validated published head; corruption never falls back silently."""
        history = self._chain()
        return history[-1] if history else None

    def load_revision(self, revision: int) -> ContextArtifact:
        """Read historical evidence without making its decisions currently applicable."""
        history = self._chain()
        if (
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or not 1 <= revision <= len(history)
        ):
            raise ContextStoreError("The requested context revision has not been published.")
        return history[revision - 1]

    @contextmanager
    def _publication_lock(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self._check_paths()
        try:
            descriptor = os.open(self.lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise ContextStoreBusy(
                "Context publication lock is held; explicit recovery may be needed."
            ) from None
        except OSError:
            raise ContextStoreError("Unable to acquire the context publication lock.") from None
        completed = False
        try:
            yield
            completed = True
        finally:
            os.close(descriptor)
            try:
                self.lock_path.unlink()
            except OSError:
                if completed:
                    raise ContextStoreError(
                        "Unable to release the context publication lock."
                    ) from None

    def publish(self, artifact: ContextArtifact, *, expected_head: str | None) -> ContextArtifact:
        """Publish exactly one successor, refusing stale edits and replacing no history."""
        candidate = _validated(artifact)
        with self._publication_lock():
            current = self.load()
            actual = context_digest(current) if current is not None else None
            if actual != expected_head:
                raise ContextStoreConflict("The expected context head no longer matches.")
            _check_next(current, candidate)
            self.history_directory.mkdir(exist_ok=True)
            history_path = self._revision_path(candidate.revision)
            data = canonical_bytes(candidate)
            try:
                if history_path.exists():
                    if history_path.read_bytes() != data:
                        raise ContextStoreConflict(
                            "An immutable context revision already holds different data."
                        )
                else:
                    write_atomic(history_path, data)
                write_atomic(self.head_path, data)
            except OSError:
                raise ContextStoreError(
                    "Unable to publish engineering context; the old head is preserved."
                ) from None
        return candidate


def next_artifact(
    current: ContextArtifact,
    *,
    records: tuple[EngineeringRecord, ...] | None = None,
    confirmations: tuple[ConfirmationReceipt, ...] | None = None,
    baseline: EvidenceBaseline | None = None,
    now: datetime | None = None,
) -> ContextArtifact:
    """Create a successor proposal; publishing performs the immutable-history checks."""
    current = _validated(current)
    if baseline is not None and baseline != current.baseline:
        raise ContextStoreError("A changed evidence baseline requires a new context.")
    proposal = current.model_copy(
        update={
            "revision": current.revision + 1,
            "previous_digest": context_digest(current),
            "records": current.records if records is None else records,
            "confirmations": current.confirmations if confirmations is None else confirmations,
            "baseline": current.baseline if baseline is None else baseline,
            "updated_at": now or datetime.now(UTC),
        }
    )
    return _validated(proposal)


def put_record(
    current: ContextArtifact, record: EngineeringRecord, *, now: datetime | None = None
) -> ContextArtifact:
    """Add or replace a typed input; existing confirmations remain historical evidence."""
    records = tuple(
        record if item.record_id == record.record_id else item for item in current.records
    )
    if not any(item.record_id == record.record_id for item in current.records):
        records += (record,)
    proposed = next_artifact(current, records=records, now=now)
    _check_next(_validated(current), proposed)
    return proposed


def confirm_record(
    current: ContextArtifact,
    record_id: str,
    *,
    actor: str,
    expected_record_digest: str,
    expected_dependency_digest: str,
    now: datetime | None = None,
    decision: Literal["confirmed", "rejected"] = "confirmed",
) -> ContextArtifact:
    """Record an explicit decision on the exact input shown, without certifying CAD state."""
    current = _validated(current)
    record = next((item for item in current.records if item.record_id == record_id), None)
    if record is None:
        raise ContextStoreError("The engineering input record does not exist.")
    if (
        record_digest(record) != expected_record_digest
        or dependency_digest(current.baseline, record) != expected_dependency_digest
    ):
        raise ContextStoreConflict("The presented input or dependency digest no longer matches.")
    if not isinstance(actor, str) or not actor.strip():
        raise ContextStoreError("An explicit engineer actor is required for a decision.")
    if decision == "confirmed":
        _check_confirmable(record)
    try:
        receipt = ConfirmationReceipt(
            receipt_id=uuid4(),
            record_id=record.record_id,
            record_revision=record.revision,
            record_digest=expected_record_digest,
            dependency_digest=expected_dependency_digest,
            actor=actor,
            confirmed_at=now or datetime.now(UTC),
            decision=decision,
        )
    except ValidationError:
        raise ContextStoreError("Invalid engineering confirmation receipt.") from None
    return next_artifact(current, confirmations=(*current.confirmations, receipt), now=now)
