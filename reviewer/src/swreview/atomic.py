"""The one atomic writer: a file's new bytes, whole or not at all (plan decision RF-31).

`write_atomic` writes to a temporary file in the target's own folder and `os.replace`s it
onto the target, so a reader sees the previous file or the complete new one, never a
truncated document; on a failure the target keeps its old bytes and the temporary is
removed. The temporary is named `.{name}.<random>.tmp`, the attention record's naming
(owner decision 34A), and `os` is imported as a module so a test patches the replace
through `swreview.atomic.os`.

Windows refuses the replace (`MoveFileExW`) while another handle holds the target,
whatever its share mode, or the temporary, and a reader holds a record for about a
millisecond, so such a refusal is tried again after each of `REPLACE_WAITS_S`, the
temporary whole meanwhile (002 research, cycle 25); a target no wait lets through, a
folder at its name or a file marked read-only, raises at once. `time` is imported as a
module too, so a test records the waits through `swreview.atomic.time`.

It takes bytes only, never text: a text-mode write gives `\\r\\n` on Windows and would move
a digest, so the caller encodes and the bytes land as given.
"""

from __future__ import annotations

import contextlib
import os
import stat
import tempfile
import time
from pathlib import Path

REPLACE_WAITS_S = (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0)
"""The waits before each further try of a replace another handle refused: 1.88 s in all."""

HELD_ELSEWHERE = frozenset({5, 32})
"""The `winerror`s of a replace another handle refused: `ERROR_ACCESS_DENIED`, the target
held, and `ERROR_SHARING_VIOLATION`, the temporary held."""


def write_atomic(path: Path, data: bytes) -> None:
    """Write `data` to `path` through a temporary in `path.parent`, then `os.replace`.

    The folder must exist: the caller makes it. Any error, from the write or the
    replace, reaches the caller after the temporary is removed; a removal that fails as
    well is swallowed, so it never masks that error. A replace another handle refused is
    tried again first (`_replace`).
    """
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
        _replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)


def _replace(temporary: Path, path: Path) -> None:
    """`os.replace`, tried again after each of `REPLACE_WAITS_S` while another handle
    refuses it; any other error, a target no wait lets through (`_never_takes`), and the
    refusal after the last wait raise as they are.

    Only Windows names a `winerror`, so on every other platform nothing is tried again.
    """
    for wait in REPLACE_WAITS_S:
        try:
            os.replace(temporary, path)
            return
        except PermissionError as refusal:
            if getattr(refusal, "winerror", None) not in HELD_ELSEWHERE or _never_takes(path):
                raise
        time.sleep(wait)
    os.replace(temporary, path)


def _never_takes(path: Path) -> bool:
    """Whether `path` is a target no wait lets a replace through: a folder at its name, or
    a file marked read-only, each of which Windows refuses with the `ERROR_ACCESS_DENIED` a
    held file gives. One absent - a first write, whose temporary is held - or unreadable is
    waited for as a held one is; an access list that denies the write is told from neither.
    """
    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    return stat.S_ISDIR(mode) or not mode & stat.S_IWRITE
