"""The cacheable prefix must not move within a session (T047, FR-042, lever 3).

Lever 3 on OpenAI is not "add caching": our prefix is already stable, so we are already
getting implicit hits we simply cannot see, and the lever names the cache and records the
diagnostics. That makes *this* file the real deliverable of the OpenAI half - it is the
regression test that fails the day some other change moves the prefix, which is the one
way the saving can be lost silently.

What "the prefix" is, concretely: everything a request puts ahead of the turn's own new
content - the `instructions` string (`system`) and the encoded tool array - plus the
history, which is an append-only prefix of the next request's history. Rounds 2..n of an
n-request turn should hit on everything rounds 1..n-1 sent.

**What would break the prefix**, ranked by how likely we are to do it to ourselves. Each
entry names the `PromptCacheDiagnosticsCacheMiss.reason` it would be recorded as
(`openai/types/responses/response.py:202-212`), which is the authoritative list:

1. **Lever 4 (`tool_tiers`) changing the tool list mid-session** (`tools_changed`). The
   most likely of the five, and designed out rather than tested away: OQ-3 restricts
   lever 4 to the package-decidable tiers, so the list is decided once from the package
   and never narrowed again part-way through. `test_the_encoded_tool_array_is_byte_
   identical_at_every_round` is what fails if a later build makes it per-turn.
2. **Lever 2 (`trim_tool_descriptions`) toggled mid-session** - safe **only** because the
   flag is read once at `start_review` and carried on `ReviewRun`; a build that re-read
   `EfficiencySettings` per turn would rewrite every description in the middle of a
   session and miss on `tools_changed`.
3. **Anything per-turn put into `system`** (`input_changed`): a coverage digest, the open
   checklist items, a timestamp, the count of findings so far. This is the worst of the
   five because it invalidates the prefix for **the whole session** rather than once, and
   it is exactly why lever 5's pre-run digest goes into the first *user* message instead
   of into the system prompt. `test_the_system_prompt_is_byte_identical_at_every_round`
   is its guard.
4. **Effort changed mid-session** (`reasoning_effort_changed`). The pane refuses a
   settings save *during* a turn but not *between* turns, so this one is reachable today
   by an engineer with the settings dialog open. Not asserted here - `effort` is a
   request field the runner holds, not prompt content - but recorded because the
   diagnostics will name it and a reader should not have to guess where it came from.
5. **Lever 8's two models** (`model_changed`): two models mean two prefixes and two
   caches, which is one reason lever 8 is deferred.

`parallel_tool_calls` is a request field, not prompt content, and does not appear in the
miss enum, so flipping it should not break the prefix (UNVERIFIED, probe L5, T070).

No network and no key: the turns are played through the scripted fake, and the encoding
asserted is the OpenAI adapter's own `tool_param`, which is what actually goes on the
wire.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from swreview.agent import runner
from swreview.agent.providers import (
    EffortLevel,
    EffortMapping,
    EventCallback,
    ProviderName,
    ProviderTool,
    TurnResult,
)
from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.providers.openai_provider import _encode_history, tool_param
from tests.unit.test_runner_provider import (
    COVERAGE_ARGUMENTS,
    DRAWING_FINDING_ARGUMENTS,
    EVIDENCE_ARGUMENTS,
)

MODEL = "fake-1"
EFFORT: EffortLevel = "high"


# --- the prefix, as bytes --------------------------------------------------------------


def encoded_tools(tools: Iterable[ProviderTool]) -> bytes:
    """The tool array exactly as the OpenAI adapter puts it on the wire.

    `tool_param` is the adapter's own encoder (`strictify` included), so a schema change
    that survives a round trip through the registry but changes one byte of JSON is
    caught here rather than by a cache miss on the wire.
    """
    return json.dumps([tool_param(tool) for tool in tools], ensure_ascii=False).encode("utf-8")


def prefix_digest(system: str, tools: Iterable[ProviderTool]) -> str:
    """One sha256 over everything a request puts ahead of its new content.

    Shared with the child process below, which is why it is a module-level function and
    not an inline expression: the two processes must hash the same bytes the same way or
    the comparison proves nothing.
    """
    digest = hashlib.sha256()
    digest.update(system.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(encoded_tools(tools))
    return digest.hexdigest()


# --- the harness -------------------------------------------------------------------------


class RecordingProvider:
    """The scripted fake, keeping what each turn was handed.

    It delegates rather than subclasses so that what is recorded is unambiguously what
    the runner passed in, and it records before the turn runs, so a turn that raises has
    still contributed its prefix.
    """

    name = ProviderName.FAKE

    def __init__(self, script: Sequence[ScriptedTurn], model: str = MODEL) -> None:
        self.model = model
        self._inner = FakeProvider(script=script, model=model)
        self.systems: list[str] = []
        self.tool_arrays: list[bytes] = []
        self.inputs: list[list[str]] = []
        """Each turn's encoded `input` list, one JSON string per item, in order."""

    def effort_mapping(self, effort: EffortLevel) -> EffortMapping:
        return self._inner.effort_mapping(effort)

    def run(
        self,
        *,
        system: str,
        messages: Sequence[Mapping[str, Any]],
        tools: Any,
        effort: EffortLevel,
        max_steps: int,
        on_event: EventCallback,
    ) -> TurnResult:
        self.systems.append(system)
        self.tool_arrays.append(encoded_tools(tools))
        self.inputs.append(
            [json.dumps(item, ensure_ascii=False) for item in _encode_history(messages)]
        )
        return self._inner.run(
            system=system,
            messages=messages,
            tools=tools,
            effort=effort,
            max_steps=max_steps,
            on_event=on_event,
        )


def call(name: str, **arguments: Any) -> ScriptedToolCall:
    return ScriptedToolCall(name=name, arguments=arguments)


SCRIPT: tuple[ScriptedTurn, ...] = (
    ScriptedTurn(
        text="I checked the fastener joints on the cover.",
        tool_calls=(call("record_coverage", **COVERAGE_ARGUMENTS),),
    ),
    ScriptedTurn(
        text="I need the usable thread depth before I can finish.",
        tool_calls=(call("request_evidence", **EVIDENCE_ARGUMENTS),),
    ),
    ScriptedTurn(
        text="With the depth in hand, the callout is incomplete.",
        tool_calls=(call("record_drawing_finding", **DRAWING_FINDING_ARGUMENTS, status="issue"),),
    ),
    ScriptedTurn(text="Nothing further."),
)
"""Four turns of the shapes a session really takes: a tool call, an evidence request, an
answered request that resumes the review, and a plain follow-up."""


@pytest.fixture
def played(
    tmp_package_dir: Path, tmp_path: Path
) -> Callable[[], tuple[runner.ReviewRun, RecordingProvider]]:
    """A session with all four turns played, and the provider that saw them."""

    def play() -> tuple[runner.ReviewRun, RecordingProvider]:
        provider = RecordingProvider(SCRIPT)
        run = runner.start_review(
            tmp_package_dir, tmp_path / "out", provider=provider, effort=EFFORT
        )
        run.start()
        run.continue_session("Is the thread depth called out?")
        request_id = run.session.evidence_requests[0].id
        run.answer_evidence(request_id, "The usable depth is 8 mm.")
        run.continue_session("Anything else?")
        return run, provider

    return play


# --- the regression tests ---------------------------------------------------------------


def test_the_system_prompt_is_byte_identical_at_every_round(
    played: Callable[[], tuple[runner.ReviewRun, RecordingProvider]],
) -> None:
    """Point 3 above: anything per-turn in `system` invalidates the whole session."""
    run, provider = played()
    try:
        assert len(provider.systems) == 4
        assert len(set(provider.systems)) == 1
        assert provider.systems[0] == run.system
    finally:
        run.close()


def test_the_encoded_tool_array_is_byte_identical_at_every_round(
    played: Callable[[], tuple[runner.ReviewRun, RecordingProvider]],
) -> None:
    """Points 1 and 2 above: the tool list is decided once, not per turn."""
    run, provider = played()
    try:
        assert len(provider.tool_arrays) == 4
        assert len(set(provider.tool_arrays)) == 1
        assert provider.tool_arrays[0]
    finally:
        run.close()


def test_each_turn_extends_the_previous_history_rather_than_rewriting_it(
    played: Callable[[], tuple[runner.ReviewRun, RecordingProvider]],
) -> None:
    """The history is append-only, so every earlier item is still cacheable.

    Includes the case the research note calls out by name: `answer_evidence` mutates
    `session.findings` and never `self.messages`, so the answered turn extends the
    history exactly as a follow-up does.
    """
    run, provider = played()
    try:
        for earlier, later in zip(provider.inputs, provider.inputs[1:], strict=False):
            assert len(later) > len(earlier), "a turn added nothing; the script is wrong"
            assert later[: len(earlier)] == earlier
    finally:
        run.close()


CHILD_PROGRAM = """
import sys

from swreview.agent import runner
from swreview.agent.providers.fake import FakeProvider
from tests.unit.test_prefix_stability import prefix_digest

run = runner.start_review(sys.argv[1], sys.argv[2], provider=FakeProvider(script=(), model="f"))
try:
    sys.stdout.write(prefix_digest(run.system, run.tools))
finally:
    run.close()
"""
"""What a second process makes of the same package: the same prefix, or a bug.

It goes through `start_review` rather than rebuilding the prompt by hand, so it exercises
the production path - the checklist, the package summary and the tool registry - and not
a test's imitation of it.
"""


@pytest.mark.parametrize("seed", ["0", "12345"])
def test_the_prefix_is_identical_in_another_process_with_a_different_hash_seed(
    tmp_package_dir: Path, tmp_path: Path, seed: str
) -> None:
    """A restart must resume onto the same prefix, whatever `PYTHONHASHSEED` it gets.

    The pane restarts the backend on a settings save and resumes the same run folder, so
    a prefix that depended on set or dict iteration order would hit before the restart
    and miss after it - the same failure `prompt_cache_key` being process-local would
    cause, and just as invisible. Two seeds because one proves only that this process
    agrees with itself.
    """
    provider = FakeProvider(script=(), model=MODEL)
    run = runner.start_review(tmp_package_dir, tmp_path / "parent", provider=provider)
    try:
        here = prefix_digest(run.system, run.tools)
    finally:
        run.close()

    completed = subprocess.run(  # noqa: S603 - the command is this test's own
        [sys.executable, "-c", CHILD_PROGRAM, str(tmp_package_dir), str(tmp_path / seed)],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(Path(__file__).resolve().parents[2]),
        env={**os.environ, "PYTHONHASHSEED": seed},
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == here
