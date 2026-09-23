"""The two product sites that build the Gemini adapter build it (feature 002, FR-015).

`cli.provider_factory` (the review, and through `chat.server.build_provider` the pane) and
`remodel.runner.build_provider` both passed `redact=` to `GeminiProvider`, whose constructor
takes `secrets=`: every Gemini review and remodel raised `TypeError` before its first request.
The chat-server tests replace the factory with a scripted one, so nothing exercised these
lines. Here `genai.Client` is replaced by a stub that records its arguments and the socket is
closed, so each test builds the real adapter without a network or a key.
"""

from __future__ import annotations

import socket
from typing import Any

import pytest
from google import genai
from pydantic import SecretStr

from swreview.agent.providers import ProviderName
from swreview.agent.providers.gemini_provider import GeminiProvider
from swreview.agent.settings import ProviderSettings, pane_efficiency
from swreview.chat.server import build_provider as pane_build_provider
from swreview.cli import provider_factory
from swreview.remodel import runner as remodel_runner

KEY = "gemini-test-key-not-real"
MODEL = "gemini-2.5-pro"


class _StubClient:
    """Stands in for `genai.Client`: keeps its keyword arguments and nothing else."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


def _refuse(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("a test tried to reach the network")


@pytest.fixture(autouse=True)
def _no_network_and_a_stub_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(genai, "Client", _StubClient)


def _gemini_settings() -> ProviderSettings:
    return ProviderSettings(
        provider=ProviderName.GEMINI, model=MODEL, api_key=SecretStr(KEY), key_source="env"
    )


def _assert_built(adapter: object) -> None:
    assert isinstance(adapter, GeminiProvider)
    assert isinstance(adapter._client, _StubClient)
    assert adapter._client.kwargs["api_key"] == KEY
    # The key is among what the adapter masks in any message it reports (FR-015).
    assert KEY in adapter._secrets


def test_the_review_factory_builds_the_gemini_adapter() -> None:
    _assert_built(provider_factory(_gemini_settings()))


def test_the_review_factory_builds_it_with_the_pane_levers_too() -> None:
    settings = _gemini_settings()
    _assert_built(provider_factory(settings, pane_efficiency(settings.provider)))


def test_the_pane_builds_the_gemini_adapter() -> None:
    _assert_built(pane_build_provider(_gemini_settings()))


def test_the_remodel_runner_builds_the_gemini_adapter() -> None:
    _assert_built(remodel_runner.build_provider(_gemini_settings()))
