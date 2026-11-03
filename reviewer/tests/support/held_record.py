"""A record's first save held until a later save of it lands (002 cycle 25).

`atomic.write_atomic` waits out a replace another handle refused, about 2 s at most, so a
save that met a reader can land after a later save of the same record: two writers of one
record must order their saves, or the earlier one's bytes land over the later one's (the
must-fix of cycle 25's Tier 2 review). `hold_the_first_save` stubs the writer's replace
through `swreview.atomic.os`, as `test_atomic.py` does: the first save of the record it
names is refused as Windows refuses a replace over a file a reader holds (`PermissionError`,
WinError 5) - once, when a later save of the record has landed or `HELD_S` has passed - and
every other replace goes through. `hold_the_first_store_save` holds the first
`ExceptionStore.save` the same way, before it writes: an accept reads the store, adds its
exception and writes the store whole, so two accepts nothing orders each write the store
they read, and one exception is lost (cycle 25's read-only check).

The refusals Windows gives are built here once (`ACCESS_DENIED`, `SHARING_VIOLATION`,
`_error`), for the stub and for `test_atomic.py`.
"""

from __future__ import annotations

import errno
import os
import threading
from pathlib import Path

import pytest

from swreview import atomic
from swreview.exceptions import ExceptionStore

HELD_S = 0.5
"""How long the first save waits for a later one. A later save nothing orders behind it lands
within milliseconds; one ordered behind it cannot land first, so the wait runs out, the first
save lands, and the later one lands after it."""

ACCESS_DENIED = 5
"""`ERROR_ACCESS_DENIED`: a replace over a target another handle holds, whatever its share."""
SHARING_VIOLATION = 32
"""`ERROR_SHARING_VIOLATION`: a replace from a temporary another handle holds."""


def _error(kind: type[OSError], code: int, winerror: int | None) -> OSError:
    """`kind` as Windows raises it, its `winerror` set by hand: only Windows sets one, so a
    stub reads the same on every platform. `None` is another platform's error."""
    error = kind(code, os.strerror(code))
    if winerror is not None:
        error.winerror = winerror
    return error


def hold_the_first_save(monkeypatch: pytest.MonkeyPatch, name: str) -> threading.Event:
    """Stub the replace for the record named `name` (`session.json`, say) in any folder.

    The event returned is set when the first save meets the reader, so a test starts the
    later save only then. A later save is told from the first's own tries by its temporary:
    the writer tries again from the one temporary it wrote.
    """
    replace = atomic.os.replace
    met_the_reader = threading.Event()
    later_landed = threading.Event()
    first: list[Path] = []

    def held_replace(source: str, destination: Path) -> None:
        if Path(destination).name != name:
            replace(source, destination)
            return
        if not first:
            first.append(Path(source))
            met_the_reader.set()
            later_landed.wait(HELD_S)
            raise _error(PermissionError, errno.EACCES, ACCESS_DENIED)
        replace(source, destination)
        if Path(source) != first[0]:
            later_landed.set()

    monkeypatch.setattr(atomic.os, "replace", held_replace)
    return met_the_reader


def hold_the_first_store_save(monkeypatch: pytest.MonkeyPatch) -> threading.Event:
    """Stub `ExceptionStore.save` so that its first call waits, before it writes, until a
    later save of a store has landed or `HELD_S` has passed; every later one writes at once.

    The event returned is set when the first save is held, so a test starts the later save
    only then.
    """
    save = ExceptionStore.save
    held = threading.Event()
    later_landed = threading.Event()

    def held_save(store: ExceptionStore) -> Path:
        if not held.is_set():
            held.set()
            later_landed.wait(HELD_S)
            return save(store)
        path = save(store)
        later_landed.set()
        return path

    monkeypatch.setattr(ExceptionStore, "save", held_save)
    return held
