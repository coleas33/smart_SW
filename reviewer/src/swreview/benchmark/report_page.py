"""The report page and the record of what a benchmark attempt sent (feature 014
`contracts/report.md`; `contracts/benchmark-run.md` 12).

## The prompts record (FR-057, D11)

The system prompt is built in memory and no event carries it or any user message, so a benchmark
attempt writes `<package folder>/prompts.json`: `prompts_version` 1, `system` (`ReviewRun.system`)
and `user_messages` (every `role: user` entry of `ReviewRun.messages`, in order; message `k`
opens turn `k`). It is written before the first turn and again when the attempt ends, so an
attempt that raised still records what it sent first. Only the benchmark attempt writes it
(`cli._review_fn`): the pane's folders and the `review` command's gain nothing, and no event
carries it (plan decision INT-1). A folder without it reads "not recorded". This section is the
record's one format, one writer and one reader.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

from swreview import atomic
from swreview.findings import ReviewModel

if TYPE_CHECKING:
    from swreview.agent.runner import ReviewRun

__all__ = [
    "PROMPTS_FILE",
    "PROMPTS_VERSION",
    "PromptsRecord",
    "read_prompts_record",
    "write_prompts_record",
]

# --- the prompts record ---------------------------------------------------------------------

PROMPTS_FILE = "prompts.json"
PROMPTS_VERSION = 1


class PromptsRecord(ReviewModel):
    """One package folder's `prompts.json` (data-model section 7, **PromptsRecord**)."""

    prompts_version: Literal[1]
    system: str
    """`ReviewRun.system`, byte for byte."""
    user_messages: list[str]
    """Every `role: user` message of `ReviewRun.messages`, in order: the opening message, then
    one per answer turn as sent."""


def write_prompts_record(run: ReviewRun, folder: Path) -> None:
    """Write what `run` has sent so far to `folder / PROMPTS_FILE`, through the one atomic writer.

    Before the first turn no user message is in the history yet (`ReviewRun.start` sends
    `opening_message`, and `_ask` appends it), so the record then holds the opening message the
    first turn will send. UTF-8 bytes with `\\n` line endings and a final newline.
    """
    sent = [message["content"] for message in run.messages if message.get("role") == "user"]
    record = PromptsRecord(
        prompts_version=PROMPTS_VERSION,
        system=run.system,
        user_messages=sent if sent else [run.opening_message],
    )
    atomic.write_atomic(
        Path(folder) / PROMPTS_FILE, (record.model_dump_json(indent=2) + "\n").encode("utf-8")
    )


def read_prompts_record(folder: Path) -> PromptsRecord | None:
    """The record in `folder`, or `None` when it holds none (a folder written before the record).

    A file that is not JSON or does not validate raises its `ValueError` (pydantic's
    `ValidationError` is one) to the caller, which names it.
    """
    try:
        raw = (Path(folder) / PROMPTS_FILE).read_bytes()
    except FileNotFoundError:
        return None
    return PromptsRecord.model_validate_json(raw)
