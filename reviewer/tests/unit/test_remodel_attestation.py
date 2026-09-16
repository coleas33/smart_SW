"""`source-attestation.json`: the recorded half, the re-check, and the hard failure (T086).

The three values - byte length, `LastWriteTimeUtc` and content hash - are recorded by the
C# side at copy time (`RemodelCopy.RecordSource`, pinned by T050) and re-checked here at
report time. This module's tests pin the Python half: the artifact's shape, the re-check,
and what a difference means.

The claims, each its own case because each is a separate thing that could regress:

- **the recorded half claims nothing.** `matches` and `rechecked_at` are `null` until the
  re-check runs, so a run that died before its report can never be read as having proved
  the source untouched;
- **the recorded half is not measured here.** `attestation_from_open` reads the numbers
  the bridge reply carries and touches no file at all - asserted against a filesystem that
  fails every open - which is what "the attestation is written before any document handle
  to the source could exist" means on this side of the wire: the recording happened in C#
  before the copy, and Python only files it;
- **all three values are re-checked, and every difference is reported**, not just the
  first, so an engineer who saves over the source between plan time and report time is
  told which of the three moved rather than being sent back twice;
- **a difference is a hard failure**, raised as `SourceChanged` and recorded as
  `matches: false`, never a warning and never a note beside a passing run;
- **the source is opened for reading and in no other mode**: the re-check hashes it with
  `"rb"` and a guarded `Path.open` fails the test on anything else (SC-001);
- **"could not check" is never "unchanged"** (constitution Principle I): a source that has
  gone missing, or that cannot be read, fails the run rather than passing it.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import warnings
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from swreview.remodel.attestation import (
    ATTESTATION_FILE_NAME,
    RECORDED_FIELDS,
    AttestationCheck,
    SourceChanged,
    attestation_from_open,
    read_attestation,
    recheck,
    require_source_unchanged,
    write_attestation,
)
from swreview.remodel.plan import SourceAttestation

RECORDED_AT = datetime(2026, 9, 16, 14, 22, 1, tzinfo=UTC)
RECHECKED_AT = datetime(2026, 9, 16, 14, 41, 55, tzinfo=UTC)
CONTENT = b"the engineer's file, byte for byte"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def last_write_utc(path: Path) -> datetime:
    """The file's last-write time truncated to whole microseconds.

    The finest precision `datetime` carries, and therefore the precision both halves of
    the comparison are made at: a .NET tick has a seventh decimal digit that no Python
    datetime can hold, and a difference below a microsecond is not a write anyone made.
    """
    seconds, nanoseconds = divmod(path.stat().st_mtime_ns, 1_000_000_000)
    return datetime.fromtimestamp(seconds, UTC) + timedelta(microseconds=nanoseconds // 1000)


def source_file(tmp_path: Path, content: bytes = CONTENT) -> Path:
    path = tmp_path / "bracket.SLDPRT"
    path.write_bytes(content)
    return path


def reply(source: Path, **overrides: Any) -> dict[str, Any]:
    """`remodel.open`'s `source_attestation` block, as the bridge hands it over."""
    body: dict[str, Any] = {
        "path": str(source),
        "length_bytes": source.stat().st_size,
        "last_write_utc": last_write_utc(source).isoformat().replace("+00:00", "Z"),
        "sha256": sha256_of(source),
        "source_design_id": "dsn:4f2a91c0d3b7",
        "recorded_at": RECORDED_AT.isoformat().replace("+00:00", "Z"),
        "copy_path": str(source.parent / "run" / "copy" / "bracket-RMS.SLDPRT"),
        "vault_path": None,
        "vault_revision": None,
    }
    body.update(overrides)
    return body


# --- the recorded half ------------------------------------------------------------


def test_the_recorded_half_carries_the_three_values_and_claims_no_verdict(
    tmp_path: Path,
) -> None:
    source = source_file(tmp_path)

    recorded = attestation_from_open(reply(source))

    assert recorded.path == str(source)
    assert recorded.length_bytes == len(CONTENT)
    assert recorded.last_write_utc == last_write_utc(source)
    assert recorded.sha256 == sha256_of(source)
    assert recorded.source_design_id == "dsn:4f2a91c0d3b7"
    assert recorded.recorded_at == RECORDED_AT
    assert (recorded.rechecked_at, recorded.matches, recorded.copy_sha256_after_save) == (
        None,
        None,
        None,
    )


def test_the_recorded_half_names_the_nine_fields_the_bridge_records(tmp_path: Path) -> None:
    """The C# record and this reader agree field for field (`data-model.md` section 5)."""
    source = source_file(tmp_path)

    assert set(reply(source)) == set(RECORDED_FIELDS)


@pytest.mark.parametrize("field", sorted(RECORDED_FIELDS))
def test_a_reply_missing_any_recorded_field_is_refused(tmp_path: Path, field: str) -> None:
    """No default is written for any of them: an absent hash is not an empty hash."""
    source = source_file(tmp_path)
    body = reply(source)
    del body[field]

    with pytest.raises(ValueError, match=field):
        attestation_from_open(body)


def test_a_reply_that_already_claims_a_verdict_is_refused(tmp_path: Path) -> None:
    """The verdict is this module's to write, at report time, and nobody else's."""
    source = source_file(tmp_path)

    with pytest.raises(ValueError, match="matches"):
        attestation_from_open(reply(source, matches=True))


def test_a_reply_whose_copy_is_the_source_is_refused(tmp_path: Path) -> None:
    """The copy is never the source (SC-001): a record saying it is is a defect, not a run."""
    source = source_file(tmp_path)

    with pytest.raises(ValueError, match="copy"):
        attestation_from_open(reply(source, copy_path=str(source).upper()))


def test_recording_the_attestation_opens_no_file_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The three values were measured in C# before the copy and before any handle existed.

    Python files them; it does not re-measure them here, because a second measurement at
    plan time would be a second answer to the question the attestation exists to settle.
    """
    source = source_file(tmp_path)
    body = reply(source)
    real_open, real_stat = pathlib.Path.open, pathlib.Path.stat

    def guarded_open(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.is_relative_to(tmp_path):
            raise AssertionError(f"recording the attestation opened {self}")
        return real_open(self, *args, **kwargs)

    def guarded_stat(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.is_relative_to(tmp_path):
            raise AssertionError(f"recording the attestation measured {self}")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "open", guarded_open)
    monkeypatch.setattr(pathlib.Path, "read_bytes", guarded_open)
    monkeypatch.setattr(pathlib.Path, "stat", guarded_stat)

    recorded = attestation_from_open(body)

    assert recorded.sha256 == body["sha256"]


# --- the artifact -----------------------------------------------------------------


def test_the_artifact_is_written_into_the_run_folder_and_reads_back(tmp_path: Path) -> None:
    source = source_file(tmp_path)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    recorded = attestation_from_open(reply(source))

    written = write_attestation(run_dir, recorded)

    assert written == run_dir / ATTESTATION_FILE_NAME
    assert json.loads(written.read_text(encoding="utf-8"))["matches"] is None
    assert read_attestation(run_dir) == recorded


def test_the_writer_opens_nothing_but_the_artifact_it_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = source_file(tmp_path)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    recorded = attestation_from_open(reply(source))
    artifact = run_dir / ATTESTATION_FILE_NAME
    real_open = pathlib.Path.open

    def guarded_open(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self != artifact:
            raise AssertionError(f"the writer opened {self}, which is not the artifact")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "open", guarded_open)

    write_attestation(run_dir, recorded)

    monkeypatch.undo()
    assert source.read_bytes() == CONTENT


# --- the re-check -----------------------------------------------------------------


def test_an_untouched_source_re_checks_clean(tmp_path: Path) -> None:
    source = source_file(tmp_path)
    recorded = attestation_from_open(reply(source))

    check = recheck(recorded, at=RECHECKED_AT)

    assert check.differences == ()
    assert check.attestation.matches is True
    assert check.attestation.rechecked_at == RECHECKED_AT


def test_the_re_check_keeps_the_recorded_values_word_for_word(tmp_path: Path) -> None:
    """Both halves live in one artifact: the re-check adds a verdict, it never rewrites
    what was recorded, so the file still says what the source was at plan time."""
    source = source_file(tmp_path)
    recorded = attestation_from_open(reply(source))
    source.write_bytes(CONTENT + b" and then some")

    check = recheck(recorded, at=RECHECKED_AT)

    for field in RECORDED_FIELDS:
        assert getattr(check.attestation, field) == getattr(recorded, field)


def test_the_re_check_records_the_saved_copys_hash_beside_the_verdict(tmp_path: Path) -> None:
    source = source_file(tmp_path)
    recorded = attestation_from_open(reply(source))

    check = recheck(recorded, at=RECHECKED_AT, copy_sha256_after_save="b" * 64)

    assert check.attestation.copy_sha256_after_save == "b" * 64


def test_a_source_that_grew_fails_on_its_length(tmp_path: Path) -> None:
    """The last-write time is put back, so this case is about the length and the hash
    alone: a filesystem that writes both files inside one timestamp tick would otherwise
    decide which of the three assertions ran."""
    source = source_file(tmp_path)
    recorded = attestation_from_open(reply(source))
    stamp = source.stat()
    source.write_bytes(CONTENT + b"!")
    os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))

    check = recheck(recorded, at=RECHECKED_AT)

    assert check.attestation.matches is False
    assert [difference.field for difference in check.differences] == ["length_bytes", "sha256"]
    length = check.differences[0]
    assert (length.recorded, length.observed) == (str(len(CONTENT)), str(len(CONTENT) + 1))


def test_a_source_saved_with_the_same_bytes_fails_on_its_last_write_time(
    tmp_path: Path,
) -> None:
    """Same length, same hash, a new save: the engineer wrote to the file during the run,
    and the run can no longer claim it did not."""
    source = source_file(tmp_path)
    recorded = attestation_from_open(reply(source))
    moved = last_write_utc(source) + timedelta(seconds=90)
    os.utime(source, ns=(source.stat().st_atime_ns, int(moved.timestamp() * 1_000_000_000)))

    check = recheck(recorded, at=RECHECKED_AT)

    assert check.attestation.matches is False
    assert [difference.field for difference in check.differences] == ["last_write_utc"]


def test_a_source_rewritten_to_the_same_length_and_time_still_fails_on_its_hash(
    tmp_path: Path,
) -> None:
    """The hash is checked on its own account, so a change that hid behind the metadata
    is still caught. This is the case the hash exists for."""
    source = source_file(tmp_path)
    recorded = attestation_from_open(reply(source))
    stamp = source.stat()
    source.write_bytes(b"X" * len(CONTENT))
    os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))

    check = recheck(recorded, at=RECHECKED_AT)

    assert check.attestation.matches is False
    assert [difference.field for difference in check.differences] == ["sha256"]
    assert check.differences[0].recorded == hashlib.sha256(CONTENT).hexdigest()


def test_every_difference_is_reported_and_not_only_the_first(tmp_path: Path) -> None:
    source = source_file(tmp_path)
    recorded = attestation_from_open(
        reply(source, length_bytes=1, sha256="c" * 64, last_write_utc="2020-01-01T00:00:00Z")
    )

    check = recheck(recorded, at=RECHECKED_AT)

    assert [difference.field for difference in check.differences] == [
        "length_bytes",
        "last_write_utc",
        "sha256",
    ]


def test_a_last_write_time_below_a_microsecond_apart_is_the_same_write(tmp_path: Path) -> None:
    """A .NET tick carries a seventh decimal digit no `datetime` can hold, so both halves
    are compared truncated to whole microseconds. Anything coarser would be a tolerance on
    engineering evidence; anything finer would fail every run on Windows."""
    source = source_file(tmp_path)
    stamp = source.stat()
    os.utime(source, ns=(stamp.st_atime_ns, (stamp.st_mtime_ns // 1000) * 1000 + 700))
    recorded = attestation_from_open(reply(source))

    check = recheck(recorded, at=RECHECKED_AT)

    assert check.differences == ()
    assert check.attestation.matches is True


# --- the hard failure -------------------------------------------------------------


def test_a_difference_raises_rather_than_warning(tmp_path: Path) -> None:
    source = source_file(tmp_path)
    recorded = attestation_from_open(reply(source))
    source.write_bytes(b"something else entirely")

    check = recheck(recorded, at=RECHECKED_AT)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(SourceChanged) as failure:
            require_source_unchanged(check)

    assert caught == []
    assert failure.value.differences == check.differences
    assert failure.value.attestation.matches is False


def test_the_failure_names_the_file_and_every_value_that_moved(tmp_path: Path) -> None:
    source = source_file(tmp_path)
    recorded = attestation_from_open(reply(source))
    source.write_bytes(b"something else entirely")

    check = recheck(recorded, at=RECHECKED_AT)
    with pytest.raises(SourceChanged) as failure:
        require_source_unchanged(check)

    message = str(failure.value)
    assert str(source) in message
    assert "failed" in message
    for difference in check.differences:
        assert difference.field in message
        assert difference.recorded in message
        assert difference.observed in message


def test_a_clean_re_check_passes_through_untouched(tmp_path: Path) -> None:
    source = source_file(tmp_path)
    recorded = attestation_from_open(reply(source))

    check = recheck(recorded, at=RECHECKED_AT)

    assert require_source_unchanged(check) is check


def test_a_source_that_has_gone_missing_fails_the_run(tmp_path: Path) -> None:
    """Moved, renamed or deleted mid-run: not an answer we can call unchanged."""
    source = source_file(tmp_path)
    recorded = attestation_from_open(reply(source))
    source.unlink()

    check = recheck(recorded, at=RECHECKED_AT)

    assert check.attestation.matches is False
    assert [difference.field for difference in check.differences] == ["path"]
    assert "no file" in check.differences[0].observed
    with pytest.raises(SourceChanged):
        require_source_unchanged(check)


def test_a_source_that_cannot_be_read_is_never_reported_as_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Principle I: "could not check" is not "unchanged". A locked source fails the run."""
    source = source_file(tmp_path)
    recorded = attestation_from_open(reply(source))

    def locked(self: Path, *args: Any, **kwargs: Any) -> Any:
        raise PermissionError(13, "the file is in use by another process")

    monkeypatch.setattr(pathlib.Path, "open", locked)

    check = recheck(recorded, at=RECHECKED_AT)

    assert check.attestation.matches is False
    assert [difference.field for difference in check.differences] == ["path"]
    assert "in use by another process" in check.differences[0].observed


def test_the_source_is_opened_for_reading_and_in_no_other_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one time the Python side touches the engineer's file, and it reads it (SC-001)."""
    source = source_file(tmp_path)
    recorded = attestation_from_open(reply(source))
    before = (source.stat().st_size, source.stat().st_mtime_ns, sha256_of(source))
    real_open = pathlib.Path.open
    modes: list[str] = []

    def guarded_open(self: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        modes.append(mode)
        if self == source and mode != "rb":
            raise AssertionError(f"the re-check opened the source as {mode!r}")
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "open", guarded_open)

    check = recheck(recorded, at=RECHECKED_AT)

    monkeypatch.undo()
    assert check.attestation.matches is True
    assert modes == ["rb"]
    assert (source.stat().st_size, source.stat().st_mtime_ns, sha256_of(source)) == before


def test_the_check_is_a_value_the_report_can_file_before_it_raises(tmp_path: Path) -> None:
    """The artifact is written with `matches: false` and *then* the run fails, so the
    evidence survives the failure it is evidence of."""
    source = source_file(tmp_path)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    recorded = attestation_from_open(reply(source))
    write_attestation(run_dir, recorded)
    source.write_bytes(b"overwritten by the engineer")

    check = recheck(recorded, at=RECHECKED_AT)
    write_attestation(run_dir, check.attestation)

    assert isinstance(check, AttestationCheck)
    assert json.loads((run_dir / ATTESTATION_FILE_NAME).read_text(encoding="utf-8"))["matches"] is (
        False
    )
    assert read_attestation(run_dir).matches is False
    with pytest.raises(SourceChanged):
        require_source_unchanged(check)


def test_the_artifact_round_trips_through_both_halves(tmp_path: Path) -> None:
    source = source_file(tmp_path)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    recorded = attestation_from_open(
        reply(source, vault_path=r"\\vault\Designs\bracket.SLDPRT", vault_revision="B")
    )
    check = recheck(recorded, at=RECHECKED_AT, copy_sha256_after_save="d" * 64)

    write_attestation(run_dir, check.attestation)

    read_back = read_attestation(run_dir)
    assert read_back == check.attestation
    assert (read_back.vault_path, read_back.vault_revision) == (
        r"\\vault\Designs\bracket.SLDPRT",
        "B",
    )


def test_a_stored_artifact_missing_a_field_is_refused(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    source = source_file(tmp_path)
    body = json.loads(
        write_attestation(run_dir, attestation_from_open(reply(source))).read_text(
            encoding="utf-8"
        )
    )
    del body["sha256"]
    (run_dir / ATTESTATION_FILE_NAME).write_text(json.dumps(body), encoding="utf-8")

    with pytest.raises(ValueError, match="sha256"):
        read_attestation(run_dir)


def test_the_recorded_half_is_the_type_the_plan_carries(tmp_path: Path) -> None:
    """One `SourceAttestation`, defined in `plan.py` and re-used here: a second definition
    is how `plan.json` and `source-attestation.json` start to disagree."""
    source = source_file(tmp_path)

    assert isinstance(attestation_from_open(reply(source)), SourceAttestation)
