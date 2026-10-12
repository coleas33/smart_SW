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

`os.replace` is patched through `swreview.atomic.os`, the module's own `import os`, which is
how the writers' failure tests reach it once they move here (T011).
"""

from __future__ import annotations

import fnmatch
import os
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
