"""The scripted fake, recording review and presentation inputs before each turn.

The ordered log is a snapshot of what the runner passed, encoded by the OpenAI adapter's
own functions. Raw specs and the first message remain beside those bytes for Send's
request-prefix assertions. A presentation clone has independent fake state and shares the
same log, so its requests cannot disappear from a characterization of the whole review.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from swreview.agent.providers import (
    EffortLevel,
    EffortMapping,
    EventCallback,
    ProviderName,
    ProviderTool,
    ToolSet,
    TurnResult,
)
from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.agent.providers.openai_provider import _encode_history, tool_param


def encoded_tools(tools: Iterable[ProviderTool]) -> bytes:
    """The tool array exactly as the OpenAI adapter puts it on the wire.

    `tool_param` is the adapter's own encoder (`strictify` included), so a schema change
    that survives a round trip through the registry but changes one byte of JSON is
    caught here rather than by a cache miss on the wire.
    """
    return json.dumps([tool_param(tool) for tool in tools], ensure_ascii=False).encode("utf-8")


@dataclass(frozen=True)
class RecordedRequest:
    system: str
    encoded_tools: bytes
    encoded_history: tuple[bytes, ...]
    tool_specs: tuple[dict[str, Any], ...]
    first_message: dict[str, Any] | None
    presentation: bool


class RecordingProvider:
    """The scripted fake, keeping each input even when its turn raises.

    Delegation keeps the log unambiguously at the runner/provider boundary. The three
    original prefix-test views remain available, derived from the same ordered log.
    """

    name = ProviderName.FAKE

    def __init__(
        self,
        script: Sequence[ScriptedTurn],
        model: str = "fake-1",
        *,
        explanation_script: Sequence[ScriptedTurn] = (),
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        self.model = model
        self._inner = FakeProvider(
            script=script, model=model, explanation_script=explanation_script, clock=clock
        )
        self.log: list[RecordedRequest] = []
        self._presentation = False

    @property
    def systems(self) -> list[str]:
        return [entry.system for entry in self.log]

    @property
    def tool_arrays(self) -> list[bytes]:
        return [entry.encoded_tools for entry in self.log]

    @property
    def inputs(self) -> list[list[str]]:
        """Each turn's encoded input list, one JSON string per item, in order."""
        return [[item.decode("utf-8") for item in entry.encoded_history] for entry in self.log]

    def effort_mapping(self, effort: EffortLevel) -> EffortMapping:
        return self._inner.effort_mapping(effort)

    def start_steps_at(self, index: int) -> None:
        self._inner.start_steps_at(index)

    def for_presentation(self, max_output_tokens: int) -> RecordingProvider:
        provider = RecordingProvider((), model=self.model)
        provider._inner = self._inner.for_presentation(max_output_tokens)
        provider.log = self.log
        provider._presentation = True
        return provider

    def run(
        self,
        *,
        system: str,
        messages: Sequence[Mapping[str, Any]],
        tools: ToolSet,
        effort: EffortLevel,
        max_steps: int,
        on_event: EventCallback,
    ) -> TurnResult:
        self.log.append(
            RecordedRequest(
                system=system,
                encoded_tools=encoded_tools(tools),
                encoded_history=tuple(
                    json.dumps(item, ensure_ascii=False).encode("utf-8")
                    for item in _encode_history(messages)
                ),
                tool_specs=tuple(
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": deepcopy(tool.schema),
                    }
                    for tool in tools
                ),
                first_message=deepcopy(dict(messages[0])) if messages else None,
                presentation=self._presentation,
            )
        )
        return self._inner.run(
            system=system,
            messages=messages,
            tools=tools,
            effort=effort,
            max_steps=max_steps,
            on_event=on_event,
        )
