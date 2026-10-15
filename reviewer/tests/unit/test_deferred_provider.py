"""An unticked review knows its effort rule without reading a key or creating a client."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any, get_args

import pytest

from swreview.agent import providers
from swreview.agent.providers import EffortLevel, EffortMapping, ProviderName

CASES = [
    (ProviderName.OPENAI, model)
    for model in (
        "gpt-5.6", "gpt-5.6-sol", "gpt-5.5", "gpt-5.1", "gpt-5-mini",
        "o4-mini", "o3", "FICT-unknown-model",
    )
] + [
    (ProviderName.GEMINI, model)
    for model in (
        "gemini-3.5-flash", "gemini-2.5-pro", "gemini-2.5-flash",
        "gemini-2.5-flash-lite", "gemini-2.5-flash-lite-preview",
        "gemini-2.5-FICT-unknown", "FICT-unknown-model",
    )
] + [(ProviderName.FAKE, model) for model in ("fake-scripted", "FICT-unknown-model")]


def deferred_module() -> Any:
    return importlib.import_module("swreview.agent.providers.deferred")


def real_adapter(name: ProviderName, model: str) -> Any:
    adapter = providers.get(name)
    if name == ProviderName.FAKE:
        return adapter(script=(), model=model)
    if name == ProviderName.OPENAI:
        return adapter(client=object(), model=model)
    return adapter(client=object(), model=model, secrets=[])


@pytest.mark.parametrize("name,model", CASES)
@pytest.mark.parametrize("effort", get_args(EffortLevel))
def test_deferred_identity_mapping_and_refusals_match_the_real_adapter(
    name: ProviderName, model: str, effort: EffortLevel
) -> None:
    provider = deferred_module().DeferredProvider.for_settings(
        SimpleNamespace(provider=name, model=model)
    )
    real = real_adapter(name, model)
    assert (provider.name, provider.model) == (real.name, real.model)
    try:
        expected = real.effort_mapping(effort)
    except ValueError as error:
        with pytest.raises(type(error)) as refused:
            provider.effort_mapping(effort)
        assert str(refused.value) == str(error)
    else:
        assert provider.effort_mapping(effort) == expected
    provider.start_steps_at(21)


@pytest.mark.parametrize("name", list(ProviderName))
@pytest.mark.parametrize("effort", get_args(EffortLevel))
def test_no_sdk_client_or_key_is_used(name: ProviderName, effort: EffortLevel,
                                    monkeypatch: pytest.MonkeyPatch) -> None:
    import openai
    from google import genai

    def no_client(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("an unticked review tried to construct an SDK client")

    monkeypatch.setattr(openai, "OpenAI", no_client)
    monkeypatch.setattr(genai, "Client", no_client)

    class KeyTrap:
        provider = name
        model = {
            ProviderName.OPENAI: "gpt-5.6",
            ProviderName.GEMINI: "gemini-2.5-pro",
            ProviderName.FAKE: "fake-scripted",
        }[name]

        @property
        def api_key(self) -> Any:
            raise AssertionError("an unticked review read the provider key")

        @property
        def secrets(self) -> Any:
            raise AssertionError("an unticked review read key material")

    provider = deferred_module().DeferredProvider.for_settings(KeyTrap())
    assert provider.effort_mapping(effort).requested == effort


@pytest.mark.parametrize("name", list(ProviderName))
def test_deferred_cannot_run_or_make_a_presentation_provider_and_has_no_configuration_hooks(
    name: ProviderName,
) -> None:
    module = deferred_module()
    provider = module.DeferredProvider.for_settings(
        SimpleNamespace(provider=name, model="FICT-unknown-model")
    )
    with pytest.raises(module.ProviderNotSent):
        provider.run(system="Fictional", messages=[], tools=[], effort="high",
                     max_steps=1, on_event=lambda kind, body: None)
    with pytest.raises(module.ProviderNotSent):
        provider.for_presentation(1)
    assert not isinstance(provider, providers.ModelViewAware)
    assert not isinstance(provider, providers.PromptCacheAware)
    assert not isinstance(provider, providers.PriorReasoningAware)


@pytest.mark.parametrize("name", list(ProviderName))
def test_real_adapter_and_deferred_delegate_to_one_effort_rule(
    name: ProviderName, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = importlib.import_module(providers.ADAPTER_MODULES[name])
    expected = EffortMapping(requested="high", provider_param="FICT-effort", provider_value="FICT")
    calls: list[tuple[str, EffortLevel]] = []

    def mapping(model: str, effort: EffortLevel) -> EffortMapping:
        calls.append((model, effort))
        return expected

    monkeypatch.setattr(module, "effort_mapping_for", mapping)
    real = real_adapter(name, "FICT-delegation")
    assert real.effort_mapping("high") is expected
    provider = deferred_module().DeferredProvider.for_settings(
        SimpleNamespace(provider=name, model="FICT-delegation")
    )
    assert provider.effort_mapping("high") is expected
    assert calls == [("FICT-delegation", "high"), ("FICT-delegation", "high")]
