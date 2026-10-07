"""The one atomic writer: a file's new bytes, whole or not at all (plan decision RF-31).

`write_atomic` writes to a temporary file in the target's own folder and `os.replace`s it
onto the target, so a reader sees the previous file or the complete new one, never a
truncated document; on a failure the target keeps its old bytes and the temporary is
removed. The temporary is named `.{name}.<random>.tmp`, the attention record's naming
(owner decision 34A), and `os` is imported as a module so a test patches the replace
through `swreview.atomic.os`.

It takes bytes only, never text: a text-mode write gives `\\r\\n` on Windows and would move
a digest, so the caller encodes and the bytes land as given.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_atomic(path: Path, data: bytes) -> None:
    """Write `data` to `path` through a temporary in `path.parent`, then `os.replace`.

    The folder must exist: the caller makes it. Any error, from the write or the
    replace, reaches the caller after the temporary is removed.
    """
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
