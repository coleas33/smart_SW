"""T023: the replay delegates to the runner's one request-prefix renderer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from swreview import tokens
from swreview.agent import runner
from swreview.agent.providers import ProviderName
from swreview.agent.providers.fake import FakeProvider
from swreview.agent.runner import request_prefix
from swreview.agent.settings import EfficiencySettings
from swreview.benchmark import replay
from swreview.benchmark.recording import read_recording
from swreview.tokens import TokenizerUnavailable, count_tokens
from tests.support.recording_provider import RecordingProvider
from tests.support.recordings import RECORDING_NAMES, recording_folder
from tests.support.replay import ALL_OFF
from tests.unit.test_runner_send import waiting_cache_run


def test_the_runner_names_the_request_prefix() -> None:
    assert callable(runner.request_prefix)


def test_the_replay_passes_the_real_runs_prefix_inputs_to_the_shared_renderer(
    tmp_package_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = runner.start_review(
        tmp_package_dir,
        tmp_path / "out",
        provider=FakeProvider(script=(), model="fake-1"),
        effort="high",
    )
    calls: list[tuple[Any, ...]] = []

    def shared(*args: Any) -> str:
        calls.append(args)
        return "FICT-shared-renderer"

    monkeypatch.setattr(runner, "request_prefix", shared)
    try:
        assert replay._prefix(run) == "FICT-shared-renderer"
        assert calls == [(run.system, run.tools, run.opening_message)]
    finally:
        run.close()


@pytest.mark.usefixtures("vocabulary")
@pytest.mark.parametrize("provider_name", list(ProviderName))
def test_send_cache_estimates_the_actual_prefix_and_marks_only_gemini_approximate(
    tmp_path: Path, provider_name: ProviderName
) -> None:
    with waiting_cache_run(tmp_path, provider_name=provider_name) as run:
        expected = count_tokens(request_prefix(run.system, run.tools, run.opening_message))
        assert expected > 0

        run.build_send_cache()

        assert run._send_cache is not None
        assert run._send_cache.estimate.model_dump() == {
            "input_tokens": expected,
            "encoding": "o200k_base",
            "approximate": provider_name == ProviderName.GEMINI,
        }
        assert run.first_request_estimate() == expected
        assert isinstance(run.provider, RecordingProvider)
        assert run.provider.log == []


@pytest.mark.usefixtures("vocabulary")
def test_the_estimate_counts_the_offered_tools_after_lever_thirteen_withheld_checks(
    tmp_path: Path,
) -> None:
    with waiting_cache_run(tmp_path) as run:
        assert run._prerun is not None
        assert run._dispatch is not None
        withheld = set(run._prerun.withheld)
        offered = {tool.name for tool in run.tools}
        registered = {tool.name for tool in run._dispatch}
        assert withheld
        assert offered == registered - withheld
        expected = count_tokens(request_prefix(run.system, run.tools, run.opening_message))
        full_array_count = count_tokens(
            request_prefix(run.system, run._dispatch, run.opening_message)
        )
        assert expected < full_array_count

        run.build_send_cache()

        assert run._send_cache is not None
        assert run._send_cache.estimate.input_tokens == expected


@pytest.mark.parametrize("provider_name", [ProviderName.FAKE, ProviderName.GEMINI])
def test_a_missing_vocabulary_leaves_input_tokens_unknown_never_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider_name: ProviderName
) -> None:
    with waiting_cache_run(tmp_path, provider_name=provider_name) as run:

        def unavailable() -> Any:
            raise TokenizerUnavailable("the vocabulary is absent")

        # Patch the loader itself after setup: a warm process cache must not turn this
        # missing-vocabulary case into a number, and setup's step sizes are independent.
        monkeypatch.setattr(tokens, "encoding", unavailable)

        assert run.first_request_estimate() is None
        run.build_send_cache()

        assert run._send_cache is not None
        assert run._send_cache.estimate.input_tokens is None
        assert run._send_cache.estimate.encoding == "o200k_base"
        assert run._send_cache.estimate.approximate == (provider_name == ProviderName.GEMINI)
        assert isinstance(run.provider, RecordingProvider)
        assert run.provider.log == []


def test_an_unexpected_tokenizer_failure_propagates_and_does_not_publish_a_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with waiting_cache_run(tmp_path) as run:

        def failed() -> Any:
            raise RuntimeError("the tokenizer failed unexpectedly")

        monkeypatch.setattr(tokens, "encoding", failed)

        with pytest.raises(RuntimeError, match="the tokenizer failed unexpectedly"):
            run.build_send_cache()

        assert run._send_cache is None


@pytest.mark.usefixtures("vocabulary")
def test_two_different_prepared_prefixes_have_different_independent_numeric_counts(
    tmp_path: Path,
) -> None:
    prefixes: list[str] = []
    counts: list[int] = []
    for name, efficiency in (("checks-first", None), ("all-tools", EfficiencySettings())):
        with waiting_cache_run(tmp_path / name, efficiency=efficiency) as run:
            # Serialize the actual offered request fields independently of request_prefix,
            # first_request_estimate and build_send_cache. T008 separately pins the move.
            prefix = run.system + json.dumps([
                {"name": tool.name, "description": tool.description, "parameters": tool.schema}
                for tool in run.tools
            ]) + run.opening_message
            expected = count_tokens(prefix)
            assert expected > 0
            run.build_send_cache()
            assert run._send_cache is not None
            assert run._send_cache.opening == run.opening_message
            assert run._send_cache.estimate.input_tokens == expected
            prefixes.append(prefix)
            counts.append(expected)
    assert prefixes[0] != prefixes[1]
    assert counts[0] != counts[1]


@pytest.mark.usefixtures("vocabulary")
def test_the_estimate_bounds_each_recordings_billed_first_round(tmp_path: Path) -> None:
    """SC-006 measures the actual owner recordings, never fixture token totals.

    The first as-recorded pass rebuilds the offered tools and opening through the shared
    request-prefix renderer. Output is only the percentage gap, never a design name,
    a recording folder or either request size. Missing owner inputs use the recording
    mapping helper's existing skip reason, just as the replay's acceptance tests do.
    """
    checked = False
    outside: list[float] = []
    for index, name in enumerate(RECORDING_NAMES):
        recording = read_recording(recording_folder(name))
        if recording.provider != ProviderName.OPENAI.value:
            continue
        checked = True
        first_round = recording.turns[0].main_rounds[0]
        billed = first_round.usage.input_tokens
        if billed is None or billed <= 0:
            pytest.fail("the recorded first model round has no positive billed input")
        passes = replay.replay_passes(recording, tmp_path / str(index), requested=ALL_OFF)
        estimated = count_tokens(passes.first.prefix)
        gap = (estimated / billed - 1) * 100
        print(f"{gap:+.1f}%")
        # A normal assert would put both private sizes into pytest's rewritten failure.
        # Keep the exact acceptance bounds while reporting only their percentage gap.
        if estimated < billed or estimated > billed * 1.35:
            outside.append(gap)
    if not checked:
        pytest.skip("the owner's mapped recordings contain no OpenAI review")
    if outside:
        percentages = ", ".join(f"{gap:+.1f}%" for gap in outside)
        pytest.fail(f"first-request gaps outside 0% to +35%: {percentages}")
