"""The one atomic writer, `atomic.write_atomic(path, data)` (T008, for T009).

Every record feature 014 writes goes through it, and the product's three older copies of
the rule move onto it (plan decisions RF-31, RF-88; owner decision 34A; `benchmark-run.md`
4), so what it promises is pinned here once:

1. **The bytes as given.** Nothing is encoded or translated: `\\n` stays `\\n` on Windows,
   where a text-mode write gives `\\r\\n` and would move a digest, and a packed stream's
   compressed bytes land unchanged.
2. **Whole or not at all.** The bytes go to a temporary file in the target's own folder,
   named `.{name}.<random>.tmp` as the attention record's writer names its own (so that
   record's tests keep their glob when T011 moves it here), and `os.replace` puts the
   finished file in place: a reader sees the previous file or the new one, never a part.
3. **No debris.** When the write or the replace fails, the target keeps its old bytes (or
   stays absent), the temporary is removed, and the error reaches the caller, even when
   the removal fails as well.
4. **A reader's moment is waited out** (002 cycle 25). Windows refuses the replace while
   another handle holds the target (WinError 5, whatever its share mode) or the temporary
   (WinError 32); the writer tries again after short waits, about 2 s in all, from the same
   whole temporary, and past them the refusal reaches the caller as before. Any other
   error, and every other platform's, which names no WinError, raises at once.

`os.replace` is patched through `swreview.atomic.os`, the module's own `import os`, which is
how the writers' failure tests reach it once they move here (T011); the waits are recorded
through `time.sleep`, which the module calls through its own `import time`.
"""

from __future__ import annotations

import errno
import fnmatch
import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from swreview import atomic
from swreview.atomic import write_atomic

REAL_REPLACE = os.replace


def _temporaries(folder: Path, name: str) -> list[Path]:
    """Every temporary `write_atomic` could have left beside `name` in `folder`."""
    return list(folder.glob(f".{name}.*.tmp"))


def _fail_replace(source: object, destination: object) -> None:
    raise OSError(f"cannot replace {destination} from {source}")


# --- the bytes as given -----------------------------------------------------------


def test_it_writes_exactly_the_bytes_given_with_lf_kept(tmp_path: Path) -> None:
    """Read back with `read_bytes`: no `\\r` appears on any platform."""
    target = tmp_path / "run-status.json"
    data = '{\n  "name": "étude"\n}\n'.encode()

    write_atomic(target, data)

    assert target.read_bytes() == data
    assert b"\r" not in target.read_bytes()


def test_it_translates_nothing_in_bytes_that_are_not_text(tmp_path: Path) -> None:
    """A packed stream's compressed bytes are written as given (`benchmark-run.md` 4):
    a `\\r\\n` pair, a lone `\\n`, a NUL and a byte past ASCII all land unchanged."""
    target = tmp_path / "events.jsonl.gz"
    data = b"\x1f\x8b\x08\x00\r\n\n\x00\xff\x1a\r"

    write_atomic(target, data)

    assert target.read_bytes() == data


def test_it_writes_an_empty_file_for_empty_bytes(tmp_path: Path) -> None:
    target = tmp_path / "empty.json"

    write_atomic(target, b"")

    assert target.is_file()
    assert target.read_bytes() == b""


# --- whole or not at all -----------------------------------------------------------


def test_it_replaces_an_existing_file_whole(tmp_path: Path) -> None:
    """A shorter record over a longer one leaves none of the old tail behind."""
    target = tmp_path / "answer-log.json"
    target.write_bytes(b'{"answers": ["a long previous record"]}\n')

    write_atomic(target, b"{}\n")

    assert target.read_bytes() == b"{}\n"


def test_its_temporary_is_in_the_target_s_folder_named_after_it_and_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The temporary lies in `path.parent`, is named `.{name}.<random>.tmp`, and holds
    every byte, flushed and closed, by the time `os.replace` moves it onto the target."""
    target = tmp_path / "attention.json"
    data = b'{"rows": []}\n'
    replaced: list[tuple[Path, Path, bytes]] = []

    def spy_replace(source: str, destination: Path) -> None:
        replaced.append((Path(source), Path(destination), Path(source).read_bytes()))
        REAL_REPLACE(source, destination)

    monkeypatch.setattr(atomic.os, "replace", spy_replace)
    write_atomic(target, data)

    assert len(replaced) == 1
    temporary, destination, held = replaced[0]
    assert temporary.parent == tmp_path
    assert fnmatch.fnmatchcase(temporary.name, ".attention.json.*.tmp")
    random_part = temporary.name.removeprefix(".attention.json.").removesuffix(".tmp")
    assert random_part
    assert destination == target
    assert held == data
    assert target.read_bytes() == data


def test_a_successful_write_leaves_only_the_target_in_its_folder(tmp_path: Path) -> None:
    target = tmp_path / "prompts.json"

    write_atomic(target, b"[]\n")
    write_atomic(target, b'["second"]\n')

    assert sorted(path.name for path in tmp_path.iterdir()) == ["prompts.json"]


# --- no debris -------------------------------------------------------------------------


def test_a_failed_replace_keeps_the_old_bytes_removes_the_temporary_and_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "run-provenance.json"
    target.write_bytes(b'{"previous": true}\n')

    monkeypatch.setattr(atomic.os, "replace", _fail_replace)
    with pytest.raises(OSError, match="cannot replace"):
        write_atomic(target, b'{"previous": false}\n')

    assert target.read_bytes() == b'{"previous": true}\n'
    assert not _temporaries(tmp_path, target.name)
    assert sorted(path.name for path in tmp_path.iterdir()) == ["run-provenance.json"]


def test_a_clean_up_that_fails_too_never_hides_the_replace_s_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The temporary is removed while the replace's error is in flight; when the removal
    raises as well (a scanner holding the file open on Windows), the caller is still told
    why the write failed, not why its temporary could not be removed."""
    target = tmp_path / "event-streams.json"
    target.write_bytes(b'{"previous": true}\n')
    unlinked: list[Path] = []

    def fail_unlink(self: Path, missing_ok: bool = False) -> None:
        unlinked.append(self)
        raise PermissionError(f"cannot unlink {self}")

    monkeypatch.setattr(atomic.os, "replace", _fail_replace)
    monkeypatch.setattr(Path, "unlink", fail_unlink)
    with pytest.raises(OSError, match="cannot replace"):
        write_atomic(target, b'{"previous": false}\n')

    assert target.read_bytes() == b'{"previous": true}\n'
    assert _temporaries(tmp_path, target.name) == unlinked, (
        "the removal was tried once, on the temporary, which is all that is left beside it"
    )


def test_a_failed_replace_over_no_file_leaves_the_folder_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A first write that fails leaves neither a target nor a temporary."""
    target = tmp_path / "noise-floor.json"

    monkeypatch.setattr(atomic.os, "replace", _fail_replace)
    with pytest.raises(OSError, match="cannot replace"):
        write_atomic(target, b"{}\n")

    assert list(tmp_path.iterdir()) == []


def test_a_failed_write_keeps_the_old_bytes_and_removes_the_temporary(tmp_path: Path) -> None:
    """Text is refused by the binary temporary before anything is replaced: the writer
    takes bytes only, so no caller's text is encoded behind its back."""
    target = tmp_path / "pilot-measurement.json"
    target.write_bytes(b'{"previous": true}\n')

    with pytest.raises(TypeError):
        write_atomic(target, '{"previous": false}\n')  # type: ignore[arg-type]

    assert target.read_bytes() == b'{"previous": true}\n'
    assert sorted(path.name for path in tmp_path.iterdir()) == ["pilot-measurement.json"]


def test_a_missing_folder_is_an_error_and_is_not_made(tmp_path: Path) -> None:
    """The caller makes the folder, as each of the product's three writers does first;
    the writer creates nothing outside the folder it is given."""
    target = tmp_path / "absent" / "event-streams.json"

    with pytest.raises(FileNotFoundError):
        write_atomic(target, b"{}\n")

    assert not (tmp_path / "absent").exists()


# --- a reader's moment is waited out ---------------------------------------------------

ACCESS_DENIED = 5
"""`ERROR_ACCESS_DENIED`: a replace over a target another handle holds, whatever its share."""
SHARING_VIOLATION = 32
"""`ERROR_SHARING_VIOLATION`: a replace from a temporary another handle holds."""
PATH_NOT_FOUND = 3
NETWORK_ACCESS_DENIED = 65
FILE_SHARE_READ_WRITE_DELETE = 0x1 | 0x2 | 0x4
"""`FileShare.ReadWrite | FileShare.Delete`, as the add-in opens a session head
(`RunFolders.OpenSessionHead`)."""


def _error(kind: type[OSError], code: int, winerror: int | None) -> OSError:
    """`kind` as Windows raises it, its `winerror` set by hand: only Windows sets one, so a
    stub reads the same on every platform. `None` is another platform's error."""
    error = kind(code, os.strerror(code))
    if winerror is not None:
        error.winerror = winerror
    return error


def _waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """The writer's waits, recorded instead of slept."""
    waits: list[float] = []
    monkeypatch.setattr(time, "sleep", waits.append)
    return waits


@pytest.mark.parametrize(
    "winerror", [ACCESS_DENIED, SHARING_VIOLATION], ids=["the-target-held", "the-temporary-held"]
)
def test_a_replace_refused_twice_for_another_handle_then_accepted_lands_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, winerror: int
) -> None:
    """A reader holds a record for about a millisecond: the writer waits briefly and tries
    again, from the one temporary, whole at every try, and the record lands."""
    target = tmp_path / "session.json"
    target.write_bytes(b'{"previous": true}\n')
    data = b'{"previous": false}\n'
    tries: list[tuple[Path, bytes]] = []

    def refused_twice(source: str, destination: Path) -> None:
        tries.append((Path(source), Path(source).read_bytes()))
        if len(tries) <= 2:
            raise _error(PermissionError, errno.EACCES, winerror)
        REAL_REPLACE(source, destination)

    waits = _waits(monkeypatch)
    monkeypatch.setattr(atomic.os, "replace", refused_twice)
    write_atomic(target, data)

    assert target.read_bytes() == data
    assert len(tries) == 3
    assert {temporary for temporary, _ in tries} == {tries[0][0]}, "one temporary, every try"
    assert all(held == data for _, held in tries), "whole at every try"
    assert waits == list(atomic.REPLACE_WAITS_S[:2]), "the two shortest waits"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["session.json"]


def test_a_refusal_past_the_bound_raises_that_refusal_and_leaves_no_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reader that holds on past about 2 s of waits fails the save as before: the last
    refusal itself reaches the caller, unwrapped, the old bytes stay, the temporary goes."""
    target = tmp_path / "attention.json"
    target.write_bytes(b'{"previous": true}\n')
    refusals: list[OSError] = []

    def always_refused(source: str, destination: Path) -> None:
        refusals.append(_error(PermissionError, errno.EACCES, ACCESS_DENIED))
        raise refusals[-1]

    waits = _waits(monkeypatch)
    monkeypatch.setattr(atomic.os, "replace", always_refused)
    with pytest.raises(PermissionError) as raised:
        write_atomic(target, b'{"previous": false}\n')

    assert raised.value is refusals[-1], "the refusal itself, unwrapped"
    assert 1.5 <= sum(waits) <= 2.5, "about 2 s of waits in all"
    assert len(refusals) == len(waits) + 1, "a try after every wait"
    assert waits == list(atomic.REPLACE_WAITS_S)
    assert target.read_bytes() == b'{"previous": true}\n'
    assert sorted(path.name for path in tmp_path.iterdir()) == ["attention.json"]


def test_a_refusal_followed_by_another_error_raises_that_error_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only another handle's refusal is waited out: a try that meets anything else - here
    the folder gone - raises it at once, and nothing is tried after it."""
    target = tmp_path / "package.json"
    target.write_bytes(b'{"previous": true}\n')
    gone = _error(FileNotFoundError, errno.ENOENT, PATH_NOT_FOUND)
    outcomes = [_error(PermissionError, errno.EACCES, ACCESS_DENIED), gone]
    tries: list[OSError] = []

    def refused_then_gone(source: str, destination: Path) -> None:
        tries.append(outcomes[len(tries)])
        raise tries[-1]

    waits = _waits(monkeypatch)
    monkeypatch.setattr(atomic.os, "replace", refused_then_gone)
    with pytest.raises(FileNotFoundError) as raised:
        write_atomic(target, b'{"previous": false}\n')

    assert raised.value is gone
    assert tries == outcomes
    assert len(waits) == 1
    assert target.read_bytes() == b'{"previous": true}\n'
    assert sorted(path.name for path in tmp_path.iterdir()) == ["package.json"]


@pytest.mark.parametrize(
    ("kind", "code", "winerror"),
    [
        (PermissionError, errno.EACCES, None),
        (PermissionError, errno.EACCES, NETWORK_ACCESS_DENIED),
        (FileNotFoundError, errno.ENOENT, PATH_NOT_FOUND),
    ],
    ids=["another-platforms-refusal", "a-shares-refusal", "the-folder-gone"],
)
def test_an_error_that_is_not_another_handles_is_tried_once_and_raises_at_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: type[OSError],
    code: int,
    winerror: int | None,
) -> None:
    """Nothing but WinError 5 or 32 is waited out: another platform's refusal, which names
    no WinError, keeps failing at once, as every error did before cycle 25."""
    target = tmp_path / "run-status.json"
    target.write_bytes(b'{"previous": true}\n')
    errors: list[OSError] = []

    def refused(source: str, destination: Path) -> None:
        errors.append(_error(kind, code, winerror))
        raise errors[-1]

    waits = _waits(monkeypatch)
    monkeypatch.setattr(atomic.os, "replace", refused)
    with pytest.raises(kind) as raised:
        write_atomic(target, b'{"previous": false}\n')

    assert raised.value is errors[0]
    assert len(errors) == 1
    assert waits == []
    assert target.read_bytes() == b'{"previous": true}\n'
    assert sorted(path.name for path in tmp_path.iterdir()) == ["run-status.json"]


def _held_as_python_opens(path: Path) -> Callable[[], None]:
    """A reader as the backend's own are, cycle 17's match among them: sharing read and
    write, not delete."""
    handle = path.open("rb")
    return handle.close


def _held_as_the_add_in_opens(path: Path) -> Callable[[], None]:
    """A reader as the add-in's session-head read is: sharing read, write and delete."""
    import _winapi  # Windows alone, as the one test that calls it

    handle = _winapi.CreateFile(
        str(path),
        _winapi.GENERIC_READ,
        FILE_SHARE_READ_WRITE_DELETE,
        0,  # no security attributes
        _winapi.OPEN_EXISTING,
        0,  # no flags
        0,  # no template
    )
    return lambda: _winapi.CloseHandle(handle)


@pytest.mark.skipif(sys.platform != "win32", reason="only Windows refuses a replace over a reader")
@pytest.mark.parametrize(
    "hold",
    [_held_as_python_opens, _held_as_the_add_in_opens],
    ids=["a-python-read", "the-add-ins-session-head-read"],
)
def test_a_real_reader_holding_the_record_for_100_ms_does_not_fail_the_save(
    tmp_path: Path, hold: Callable[[Path], Callable[[], None]]
) -> None:
    """Nothing stubbed: a reader on another thread opens the record, holds it 100 ms and
    lets go; the save, begun while it holds it, waits it out and lands."""
    target = tmp_path / "session.json"
    target.write_bytes(b'{"previous": true}\n')
    held = threading.Event()

    def reader() -> None:
        release = hold(target)
        held.set()
        time.sleep(0.1)
        release()

    thread = threading.Thread(target=reader)
    thread.start()
    try:
        assert held.wait(5), "the reader holds the record"
        write_atomic(target, b'{"previous": false}\n')
    finally:
        thread.join()

    assert target.read_bytes() == b'{"previous": false}\n'
    assert sorted(path.name for path in tmp_path.iterdir()) == ["session.json"]
