"""The cost is reported honestly - the User Story 5 acceptance (feature 008 T093, SC-009).

Written after the code it accepts and passing with no further production code: a scripted
review whose provider reports cached input writes a session, a report and steps that state new
(uncached) and cached input as two numbers and name the largest results; a provider that sends
no cached count gets "Cache split not reported" instead; and on the big fixture replayed with
the pane defaults, every step's recorded size is the replay's own count of that call's full
result - one tokenizer, one serialization.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swreview.agent.providers import ProviderName, TokenUsage, tool_result_text
from swreview.agent.providers.fake import (
    FakeProvider,
    ScriptedRound,
    ScriptedToolCall,
    ScriptedTurn,
)
from swreview.agent.runner import start_review
from swreview.agent.settings import pane_defaults
from swreview.benchmark.recording import read_recording
from swreview.benchmark.replay import ReplayPasses, replay_passes
from swreview.ir.loader import load_package, save_package
from swreview.report.markdown import render_report
from swreview.report.session import ReviewSession, load_session
from swreview.tokens import count_tokens
from swreview.tools.registry import TOOL_RESULTS_DIR_NAME
from tests.support.prerun import prerun_package

pytestmark = pytest.mark.usefixtures("vocabulary")

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_PROFILE = REPO_ROOT / "config" / "standards.example.yaml"
BIG = REPO_ROOT / "reviewer" / "tests" / "fixtures" / "replay" / "big-assembly"

CALLS = (
    ScriptedToolCall("check_rms_part", {"document_id": None}),
    ScriptedToolCall("list_components", {"parent_id": None, "include_suppressed": True}),
)


def round_usage(input_tokens: int, cached: int | None) -> TokenUsage:
    return TokenUsage(
        input_tokens=input_tokens,
        cached_input_tokens=cached,
        cache_write_tokens=None,
        output_tokens=100,
        reasoning_tokens=0,
        tool_result_input_tokens=None,
        total_tokens=input_tokens + 100,
        latency_s=0.5,
    )


def scripted_review(tmp_path: Path, first: TokenUsage, closing: TokenUsage) -> Path:
    """One turn of two rounds - a round of two calls, then the answer - with this usage."""
    folder = tmp_path / "run"
    save_package(prerun_package(), folder)
    run = start_review(
        folder,
        folder,
        provider=FakeProvider(
            script=[
                ScriptedTurn(
                    text="Done.", rounds=(ScriptedRound(CALLS, usage=first),), usage=closing
                )
            ],
            model="fake-scripted",
            clock=lambda: 0.0,
        ),
    )
    try:
        run.start()
    finally:
        run.close()
    return folder


def report_of(folder: Path) -> tuple[ReviewSession, str]:
    session = load_session(folder / "session.json")
    return session, render_report(session, load_package(folder).package)


def test_a_provider_reporting_cached_input_gets_both_numbers_and_the_largest_results(
    tmp_path: Path,
) -> None:
    folder = scripted_review(tmp_path, round_usage(10_000, 9_000), round_usage(2_000, 1_200))

    session, report = report_of(folder)

    assert session.usage is not None
    assert session.usage.totals.input_tokens == 12_000
    assert session.usage.totals.cached_input_tokens == 10_200
    assert session.usage.totals.uncached_input_tokens == 1_800
    assert "- Cached input tokens: 10200" in report
    assert "- Uncached input tokens: 1800" in report
    assert "Cache split not reported" not in report
    assert "## Largest tool results" in report
    assert [step.tool for step in session.steps] == [call.name for call in CALLS]
    for step in session.steps:
        assert step.result_bytes is not None and step.result_bytes > 0
        assert step.result_tokens is not None and step.result_tokens > 0
    written = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    assert all({"result_bytes", "result_tokens"} <= set(step) for step in written["steps"])


def test_a_provider_without_a_cached_count_says_the_split_was_not_reported(
    tmp_path: Path,
) -> None:
    folder = scripted_review(tmp_path, round_usage(10_000, None), round_usage(2_000, None))

    session, report = report_of(folder)

    assert session.usage is not None
    assert session.usage.totals.cached_input_tokens is None
    assert "- Cache split not reported: the provider sent no cached-input count" in report
    assert "- Cached input tokens: not reported" in report


@pytest.fixture(scope="module")
def big_pane_passes(tmp_path_factory: pytest.TempPathFactory) -> tuple[ReplayPasses, Path]:
    """The big fixture replayed with the pane defaults, the folders the passes wrote kept."""
    scratch = tmp_path_factory.mktemp("honest-cost")
    recording = read_recording(BIG)
    pane = pane_defaults(ProviderName(recording.provider))
    passes = replay_passes(
        recording,
        scratch,
        requested=(pane.efficiency, pane.model_view),
        standards_profile=EXAMPLE_PROFILE,
    )
    return passes, scratch


def test_every_replayed_step_carries_the_replays_own_count_of_its_result(
    big_pane_passes: tuple[ReplayPasses, Path],
) -> None:
    """One tokenizer, one serialization: the size a step records is what the replay counts."""
    passes, _ = big_pane_passes
    session = passes.second.session
    played = [call for r in passes.second.rounds for call in r.calls]

    assert played
    for call in played:
        step = session.steps[call.step]
        assert step.result_tokens == count_tokens(call.text), (call.step, call.tool)
        assert step.result_bytes == len(call.text.encode("utf-8")), (call.step, call.tool)


def test_every_step_of_the_requested_pass_is_sized_from_its_stored_result(
    big_pane_passes: tuple[ReplayPasses, Path],
) -> None:
    """The pre-run's steps too, which the model never called: each size is its full result."""
    passes, scratch = big_pane_passes
    session = passes.second.session
    folder = scratch / "requested" / TOOL_RESULTS_DIR_NAME

    assert passes.second.setup_steps > 0
    for step in session.steps:
        stored = json.loads((folder / f"step-{step.index}.json").read_text(encoding="utf-8"))
        text = tool_result_text(stored["payload"])
        assert step.result_tokens == count_tokens(text), (step.index, step.tool)
        assert step.result_bytes == len(text.encode("utf-8")), (step.index, step.tool)
