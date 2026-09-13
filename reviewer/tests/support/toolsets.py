"""A `ToolSet` over hand-written tool stubs, for the three adapter test modules.

An adapter never resolves a tool name itself: it dispatches every call the model asks for
through the `agent.providers.ToolSet` the runner hands it, which is `tools/registry.py`'s
`ToolDispatch`. A test that handed an adapter a plain list would be testing a shape the
product never passes, so it wraps its stubs in the real dispatch instead - and the
unknown-name path an adapter no longer implements is then the production one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from swreview.tools.registry import ToolCallRecord, ToolDispatch


@dataclass
class RecordingList:
    """A `RecordingSink` that keeps what it was told, for a test to read back."""

    records: list[ToolCallRecord] = field(default_factory=list)

    def record(self, record: ToolCallRecord) -> None:
        self.records.append(record)


def toolset(tools: Sequence[Any]) -> ToolDispatch:
    """The stub tools of an adapter test, dispatched the way the product dispatches."""
    return ToolDispatch(tools=tuple(tools), sink=RecordingList())
