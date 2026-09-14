"""`chat-log.jsonl`: one line per MCP tool call, and the `RecordingSink` that writes it.

This is the general-chat half of the pluggable sink `tools/registry.py` was built with
(T013). A review records a call as an `InvestigationStep` on the session; general chat has
no session, so it records the same `ToolCallRecord` here instead - the wrapper above both
is identical, which is the point.

Two decisions are worth stating, because both are load-bearing:

**The file is opened and closed per line, in append mode.** A CLI session is minutes of
idling punctuated by a few calls, so the cost is nothing, and the pane's Terminal tab (and
an engineer with a text editor) can read a complete file at any moment rather than whatever
happened to have been flushed. Two CLIs pointed at one run folder append to one log for the
same reason a review and its retry share `events.jsonl`: the run folder is the unit.

**A write that fails is not swallowed.** `RecordedTool` promises never to raise past its
caller, and it keeps that promise for everything the *tool* did; a log write happens after
that, and SC-003 ("no missing call, including failures") is exactly the promise a silently
dropped line would break. So an `OSError` here propagates and the `tools/call` fails
visibly, rather than a call that nothing recorded coming back looking like a success.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from swreview.tools.registry import ToolCallRecord

__all__ = ["CHAT_LOG_FILE_NAME", "UNKNOWN_CLI", "ChatLogSink", "chat_log_path"]

CHAT_LOG_FILE_NAME = "chat-log.jsonl"
"""The file, in the run folder, beside `package.json` (data-model section 6)."""

UNKNOWN_CLI = "unknown"
"""The `cli` of a client that did not say who it is; a line is never written without one."""


@dataclass
class ChatLogSink:
    """Appends one `{at, cli, tool, arguments, status, result_summary, elapsed_s, error}`.

    `cli` is mutable because it is not known until a client has introduced itself: the
    server sets it from the MCP `clientInfo` of the connection making the call, so a log
    an engineer reads afterwards says which CLI asked, not merely that something did.
    """

    path: Path
    cli: str = UNKNOWN_CLI

    def record(self, record: ToolCallRecord) -> None:
        """Write one call. The field order is the contract's, so the file reads as documented."""
        line: dict[str, Any] = {
            "at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "cli": self.cli,
            "tool": record.tool,
            "arguments": record.arguments,
            "status": record.status,
            "result_summary": record.result_summary,
            "elapsed_s": round(record.elapsed_s, 6),
            "error": record.error,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")


def chat_log_path(run_dir: Path | str) -> Path:
    """Where the chat log of `run_dir` lives."""
    return Path(run_dir) / CHAT_LOG_FILE_NAME
