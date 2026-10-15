"""The provider identity and effort rule of a review that has not been sent."""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from swreview.agent.providers import (
    ADAPTER_MODULES,
    EffortLevel,
    EffortMapping,
    EventCallback,
    ProviderName,
    ToolSet,
    TurnResult,
)

if TYPE_CHECKING:
    from swreview.agent.settings import ProviderSettings


class ProviderNotSent(RuntimeError):
    """No model request is permitted before the engineer chooses Send."""


class DeferredProvider:
    """Use the adapter's effort rule, with no key access or client construction.

    It exposes none of the optional provider configuration protocols. Importing the
    adapter's module for its rule is allowed; constructing its SDK client is not.
    """

    def __init__(self, name: ProviderName, model: str) -> None:
        self.name = name
        self.model = model
        self._step_index = 0

    @classmethod
    def for_settings(cls, settings: ProviderSettings) -> DeferredProvider:
        return cls(settings.provider, settings.model)

    def effort_mapping(self, effort: EffortLevel) -> EffortMapping:
        module = importlib.import_module(ADAPTER_MODULES[self.name])
        return module.effort_mapping_for(self.model, effort)

    def start_steps_at(self, index: int) -> None:
        self._step_index = index

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
        raise ProviderNotSent("The review has not been sent to the model.")

    def for_presentation(self, max_output_tokens: int) -> DeferredProvider:
        raise ProviderNotSent("The review has not been sent to the model.")
