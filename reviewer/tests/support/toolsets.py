"""A `ToolSet` over hand-written tool stubs, for the three adapter test modules.

An adapter never resolves a tool name itself: it dispatches every call the model asks for
through the `agent.providers.ToolSet` the runner hands it, which is `tools/registry.py`'s
`ToolDispatch`. A test that handed an adapter a plain list would be testing a shape the
product never passes, so it wraps its stubs in the real dispatch instead - and the
unknown-name path an adapter no longer implements is then the production one.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
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


@dataclass
class Withholding:
    """A dispatch that still answers one tool it does not offer, as `prerun.PrerunGuard`
    answers a tool lever 13 withheld (feature 008 FR-030): not iterated, so no adapter
    encodes it, and callable, so a model that asks for it anyway gets its answer."""

    dispatch: ToolDispatch
    withheld: Any

    def __iter__(self) -> Iterator[Any]:
        return iter(self.dispatch)

    def __len__(self) -> int:
        return len(self.dispatch)

    def call(self, name: str, arguments: Mapping[str, Any], call_id: str = "") -> Any:
        if name == self.withheld.name:
            return self.withheld.call(arguments, call_id)
        return self.dispatch.call(name, arguments, call_id)


def withholding(tools: Sequence[Any], withheld: Any) -> Withholding:
    """`toolset(tools)`, answering `withheld` too without offering it."""
    return Withholding(toolset(tools), withheld)
