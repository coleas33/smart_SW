"""One fresh backend and one disk capture for restart, crash and kill tests (015).

A raise inside the original app is not a crash or a kill: it runs write_atomic's cleanup,
the runner's _run_turn exception path and the server's _play rendering, all of which a kill
skips. The original app also still holds the earlier chat, which a restarted backend does
not. disk_at observes the bytes at the named point without interrupting execution; read
that copied disk through restarted_app to test what a fresh backend would actually see.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from typing import Any
from unittest.mock import patch

from starlette.testclient import TestClient

from swreview import atomic
from swreview.chat.server import create_app

BEFORE_REPLACE = "before-replace"
"""After write_atomic closes its whole temporary, before it replaces the canonical file."""


@contextmanager
def restarted_app(
    run_root: Path, settings: Mapping[str, Any], *, raise_server_exceptions: bool = True
) -> Iterator[TestClient]:
    """A fresh create_app over this root, authenticated as its configured pane.

    With `raise_server_exceptions` false, an unexpected failure is answered as the pane meets
    it, Starlette's bare `500`, rather than raised into the test.
    """
    options = {**settings, "run_root": run_root}
    app = create_app(**options)
    headers = {
        "Authorization": f"Bearer {settings['token']}",
        "Origin": settings["allow_origin"],
    }
    with TestClient(
        app, headers=headers, raise_server_exceptions=raise_server_exceptions
    ) as client:
        yield client


class _DiskCapture:
    """The one-shot callable a test places at its custom cut point."""

    def __init__(self, source: Path, root: Path) -> None:
        self.root = root
        self.folder = root / source.name
        self._source = source
        self._captured = False
        self._lock = Lock()

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        with self._lock:
            if not self._captured:
                shutil.copytree(self._source, self.folder)
                self._captured = True


@contextmanager
def disk_at(folder: Path, hook: str) -> Iterator[_DiskCapture]:
    """Capture this whole run once at a custom callable or the named replace point.

    Custom names leave placement to the caller. BEFORE_REPLACE installs the observation
    through atomic.os, copies only for a destination inside this run folder, then delegates
    to the held replace. Its success or exception proceeds normally. Both the patch and the
    copied scratch root end with the context.
    """
    source = folder.resolve()
    with TemporaryDirectory(prefix="swreview-disk-at-") as temporary:
        capture = _DiskCapture(source, Path(temporary))
        if hook == BEFORE_REPLACE:
            held_replace = atomic.os.replace

            def replace(src: Any, dst: Any, *args: Any, **kwargs: Any) -> None:
                if Path(dst).resolve().is_relative_to(source):
                    capture()
                held_replace(src, dst, *args, **kwargs)

            with patch.object(atomic.os, "replace", replace):
                yield capture
        else:
            yield capture
