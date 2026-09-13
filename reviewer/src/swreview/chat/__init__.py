"""The loopback chat backend the Task Pane talks to (`contracts/chat-api.md`).

`sessions.py` is the state of one chat - its state machine, its event file and its live
fan-out - and `server.py` is the Starlette application around it. `__main__.py` is the
program the pane launches (`swreview chat serve --port 0`).

Nothing here imports a provider SDK: a session is handed the adapter it runs, so the
backend starts on a workstation with no credentials at all. The two launch defaults live
in this module, which imports nothing at all, so `cli.py` can name them on the `chat serve`
command line without pulling `starlette` and `uvicorn` into every other command.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["DEFAULT_ALLOW_ORIGIN", "DEFAULT_RUN_ROOT"]

DEFAULT_ALLOW_ORIGIN = "https://swreview.invalid"
"""The add-in's virtual host (`contracts/pane-host-messages.md`); the only origin served."""

DEFAULT_RUN_ROOT = Path.home() / "Documents" / "SwReview" / "runs"
"""Where runs live when `--run-root` is not given; the settings default (data-model 4)."""
