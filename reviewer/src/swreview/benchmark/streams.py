"""Pack finished runs without parsing or rewriting their event streams (28A; RF-82).

Every run is checked before any is changed. Packed bytes land first, their digest
record second, and plain streams are deleted last, so another pack can finish an
interrupted one. Event readers continue to use event_stream and replay_events.
"""

from __future__ import annotations

import gzip
import json
import zlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator

from swreview.agent.events import EVENTS_FILE_NAME, PACKED_EVENTS_FILE_NAME
from swreview.atomic import write_atomic
from swreview.benchmark.digest import sha256_of_bytes
from swreview.benchmark.runner import (
    PROVENANCE_FILE,
    load_run_status,
    package_outcome,
    resolve_attempt_folder,
    validate_attempt_folder,
)
from swreview.findings import ReviewModel

EVENT_STREAMS_FILE = "event-streams.json"
StreamDigest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class EventStreams(ReviewModel):
    """The plain-byte digest of each packed stream, keyed by its run-relative path."""

    event_streams_version: Literal[1] = 1
    streams: dict[str, StreamDigest] = Field(default_factory=dict)

    @field_validator("streams")
    @classmethod
    def _relative_stream_paths(cls, streams: dict[str, str]) -> dict[str, str]:
        for path in streams:
            folder, separator, filename = path.rpartition("/")
            try:
                validate_attempt_folder(folder)
                if not separator or filename != PACKED_EVENTS_FILE_NAME:
                    raise ValueError("not a packed stream")
            except ValueError:
                raise ValueError(f"{path!r} is not a run-relative packed stream path") from None
        return streams


@dataclass(frozen=True)
class _Stream:
    plain: Path
    packed: Path
    data: bytes | None


@dataclass(frozen=True)
class _Pack:
    run_dir: Path
    streams: tuple[_Stream, ...]
    record: bytes | None


def _unpack(path: Path) -> bytes:
    try:
        return gzip.decompress(path.read_bytes())
    except (OSError, EOFError, zlib.error) as exc:
        raise ValueError(f"{path}: the packed stream is unreadable") from exc


def _prepare_pack(run_dir: Path) -> _Pack:
    if not (run_dir / PROVENANCE_FILE).is_file():
        raise ValueError(f"{run_dir} is not a run folder")
    status = load_run_status(run_dir)
    if status is None:
        raise ValueError(
            f"{run_dir} was made before runs recorded their status; it cannot be packed"
        )
    for package_id, package in status.packages.items():
        for attempt in package.attempts:
            if attempt.kind is None:
                raise ValueError(
                    f"attempt {attempt.attempt} of {package_id} has no outcome: "
                    f"run `swreview benchmark resume {run_dir}` first"
                )
        package_outcome(run_dir, package_id)

    record_path = run_dir / EVENT_STREAMS_FILE
    previous = (
        EventStreams.model_validate_json(record_path.read_bytes())
        if record_path.is_file() else EventStreams()
    )
    rows = dict(previous.streams)
    folders: set[Path] = set()
    for package_id in status.packages:
        folders.add(resolve_attempt_folder(run_dir, package_id))
        # Validate the parent before enumerating it, including a link whose
        # numbered children would otherwise lead the pack outside this run.
        attempts = resolve_attempt_folder(run_dir, f"attempts/{package_id}/1").parent
        if attempts.is_dir():
            for folder in attempts.iterdir():
                if (
                    folder.name.isascii() and folder.name.isdecimal()
                    and not folder.name.startswith("0")
                ):
                    checked = resolve_attempt_folder(
                        run_dir, folder.relative_to(run_dir).as_posix(),
                    )
                    if checked.is_dir():
                        folders.add(checked)

    streams: list[_Stream] = []
    for folder in sorted(folders):
        plain = folder / EVENTS_FILE_NAME
        packed = folder / PACKED_EVENTS_FILE_NAME
        relative = packed.relative_to(run_dir).as_posix()
        if not plain.is_file():
            if packed.is_file() and relative not in rows:
                raise ValueError(f"{packed} is packed but unrecorded")
            continue
        data = plain.read_bytes()
        digest = sha256_of_bytes(data)
        already_written = packed.is_file()
        if already_written and _unpack(packed) != data:
            raise ValueError(f"{packed}: the packed stream differs from the plain one beside it")
        if relative in rows and rows[relative] != digest:
            raise ValueError(f"{plain}: its recorded digest differs from the stream")
        rows.setdefault(relative, digest)
        compressed = None
        if not already_written:
            compressed = gzip.compress(data, compresslevel=9, mtime=0)
            if gzip.decompress(compressed) != data:
                raise ValueError(f"{packed}: the packed stream differs from its source bytes")
        streams.append(_Stream(plain, packed, compressed))

    record = None
    if not record_path.is_file() or rows != previous.streams:
        model = EventStreams(streams=rows)
        record = (json.dumps(model.model_dump(), sort_keys=True, indent=2) + "\n").encode("utf-8")
    return _Pack(run_dir, tuple(streams), record)


def _pack(prepared: _Pack) -> bool:
    for stream in prepared.streams:
        if stream.data is not None:
            write_atomic(stream.packed, stream.data)
    if prepared.record is not None:
        write_atomic(prepared.run_dir / EVENT_STREAMS_FILE, prepared.record)
    for stream in prepared.streams:
        stream.plain.unlink()
    return bool(prepared.streams)


def pack_run(run_dir: Path | str) -> bool:
    """Pack one finished run; return whether any plain streams were packed or deleted.

    A run that failed before its first event still gets an empty digest record.
    """
    return _pack(_prepare_pack(Path(run_dir)))


def pack_runs(run_dirs: Iterable[Path | str]) -> list[tuple[Path, bool]]:
    """Check every named run before packing the first, accepting repeated paths once."""
    prepared: list[_Pack] = []
    seen: set[Path] = set()
    for run_dir in map(Path, run_dirs):
        resolved = run_dir.resolve()
        if resolved not in seen:
            prepared.append(_prepare_pack(run_dir))
            seen.add(resolved)
    return [(run.run_dir, _pack(run)) for run in prepared]
