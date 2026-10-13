"""T015: one aware local clock for every model-status timestamp."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from swreview.agent import events, runner
from swreview.agent.providers import ProviderName
from swreview.agent.providers.deferred import DeferredProvider
from swreview.agent.providers.fake import FakeProvider
from swreview.agent.settings import (
    MODEL_VIEW_OFF,
    MODEL_VIEW_PANE,
    EfficiencySettings,
    ProviderSettings,
)
from tests.unit.test_session import build_session


def test_local_now_is_aware_and_is_the_machines_local_time_to_the_second() -> None:
    before = datetime.now(UTC).astimezone()
    actual = events.local_now()
    after = datetime.now(UTC).astimezone()
    assert actual.tzinfo is not None
    assert actual.utcoffset() == after.utcoffset()
    assert before.replace(microsecond=0) <= actual.replace(microsecond=0)
    assert actual.replace(microsecond=0) <= after.replace(microsecond=0)


class HookProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__(script=(), model="fake-1")
        self.calls: list[tuple[str, Any]] = []

    def use_model_view(self, view: Any) -> None:
        self.calls.append(("view", view))

    def use_prompt_cache(self, session_id: str) -> None:
        self.calls.append(("cache", session_id))

    def drop_prior_reasoning(self) -> None:
        self.calls.append(("drop", None))


@pytest.mark.parametrize("cache", [False, True])
@pytest.mark.parametrize("drop", [False, True])
@pytest.mark.parametrize("view", [MODEL_VIEW_OFF, MODEL_VIEW_PANE])
def test_configure_provider_calls_the_enabled_hooks_in_order(
    cache: bool, drop: bool, view: Any
) -> None:
    session = build_session(
        efficiency=EfficiencySettings(prompt_cache_key=cache, drop_prior_reasoning=drop),
        model_view=view,
    )
    provider = HookProvider()
    runner.configure_provider(provider, session)
    expected: list[tuple[str, Any]] = [("view", view)]
    if cache:
        expected.append(("cache", str(session.session_id)))
    if drop:
        expected.append(("drop", None))
    assert provider.calls == expected


@pytest.mark.parametrize("cache", [False, True])
@pytest.mark.parametrize("drop", [False, True])
def test_start_review_keeps_the_existing_provider_hook_calls(
    tmp_package_dir: Path, tmp_path: Path, cache: bool, drop: bool
) -> None:
    provider = HookProvider()
    run = runner.start_review(
        tmp_package_dir,
        tmp_path / "out",
        provider=provider,
        effort="high",
        efficiency=EfficiencySettings(prompt_cache_key=cache, drop_prior_reasoning=drop),
        model_view=MODEL_VIEW_PANE,
    )
    try:
        expected: list[tuple[str, Any]] = [("view", MODEL_VIEW_PANE)]
        if cache:
            expected.append(("cache", str(run.session.session_id)))
        if drop:
            expected.append(("drop", None))
        assert provider.calls == expected
    finally:
        run.close()


def test_configure_provider_calls_no_optional_hook_on_a_deferred_adapter() -> None:
    provider = DeferredProvider.for_settings(
        ProviderSettings(provider=ProviderName.FAKE, model="fake-1")
    )
    # Its three optional protocol members are deliberately absent. A call is a failure.
    runner.configure_provider(
        provider,
        build_session(
            efficiency=EfficiencySettings(prompt_cache_key=True, drop_prior_reasoning=True)
        ),
    )
