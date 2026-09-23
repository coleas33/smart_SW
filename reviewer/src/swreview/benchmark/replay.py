"""Playing recorded rounds through the current code (feature 008, `contracts/replay.md`).

`play_review` is the one driver the replay and the test support share. It turns a list of
`TurnPlan`s - each turn's rounds of tool calls, the way a recording grouped them - into
`FakeProvider` `ScriptedRound`s, runs them through `start_review` exactly as a review runs
(the same dispatch, the same session, the same events), and hands back every round with the
results the model would have been sent with it:

- `PlayedRound.visible` is every tool result in the history that round's request carries: the
  results of the turns already committed to the conversation, then the results of this turn's
  earlier rounds. A turn that was stopped is not committed - the runner keeps no history for a
  turn that did not return - so its results are visible only inside it, exactly as they were.
- `PlayedRound.prior_rounds` counts the model's answers already in that history, which is
  what the output tokens riding in the request are counted over.
- `PlayedCall` carries each call's full `ToolCallResult`, so a caller can size it with
  `tool_result_text` and compare it with a recorded summary.

The driver makes no network call and needs no key and no SOLIDWORKS unless its caller hands
`start_review` a bridge factory.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from swreview.agent.providers import (
    FRAMING_TOKENS,
    ProviderTool,
    TokenUsage,
    ToolCallResult,
    ToolSet,
    TurnEndReason,
    summarize_result,
    tool_result_text,
)
from swreview.agent.providers.fake import (
    FakeProvider,
    ScriptedRound,
    ScriptedToolCall,
    ScriptedTurn,
)
from swreview.agent.runner import ReviewRun, start_review
from swreview.benchmark.recording import RecordedCall, RecordedRound, Recording
from swreview.ir.loader import PACKAGE_FILE_NAME
from swreview.report.session import ReviewSession
from swreview.tokens import count_tokens

__all__ = [
    "EMPTY_EXPLANATIONS",
    "FOLLOW_UP_PLACEHOLDER",
    "PlayedCall",
    "PlayedReview",
    "PlayedRound",
    "TurnKind",
    "TurnPlan",
    "estimated_sizes",
    "play_review",
    "turn_plans",
]

TurnKind = Literal["opening", "follow_up", "answer"]

EMPTY_EXPLANATIONS = '{"explanations": []}'
"""What a scripted presentation request answers: a valid, empty batch (the fallback applies)."""

FOLLOW_UP_PLACEHOLDER = "(the engineer's follow-up question; the event log does not record it)"
"""What a replayed follow-up turn says. Its size is taken from the recorded growth, not from
these words, which no event records."""


@dataclass(frozen=True)
class TurnPlan:
    """One turn to play: its rounds of calls, how it was opened and how it ends.

    `kind` says how the turn begins: `opening` is the review's first turn, `follow_up` an
    engineer's question (`user_text`), `answer` an answered evidence request (`answers`, one
    `(request_id, answer)` pair). `rounds` are the model's rounds that asked for calls, in
    order; the turn's closing round answers with `text`. `stop_at_last_call` stops the turn
    as the pane's Stop does - at the next tool boundary - so its last call is started and never
    finished, and the turn ends `stopped` without a closing round.
    """

    rounds: tuple[tuple[ScriptedToolCall, ...], ...] = ()
    kind: TurnKind = "opening"
    user_text: str = ""
    answers: tuple[tuple[str, str], ...] = ()
    text: str = ""
    end_reason: TurnEndReason = "end"
    stop_at_last_call: bool = False

    def __post_init__(self) -> None:
        if any(not calls for calls in self.rounds):
            raise ValueError("every scripted round asks for at least one call")
        if self.kind == "answer" and len(self.answers) != 1:
            raise ValueError("an answer turn resumes on exactly one answered evidence request")
        if self.kind != "answer" and self.answers:
            raise ValueError("only an answer turn carries answers")
        if self.stop_at_last_call and not self.rounds:
            raise ValueError("a turn stopped at its last call needs a call to stop at")

    @property
    def calls(self) -> int:
        return sum(len(calls) for calls in self.rounds)


@dataclass(frozen=True)
class PlayedCall:
    """One call the scripted model made, with the full result the dispatch returned."""

    index: int
    """Its position among the model's calls across the whole review, from 0."""
    step: int
    """The `InvestigationStep` it recorded."""
    tool: str
    arguments: dict[str, Any]
    result: ToolCallResult

    @property
    def text(self) -> str:
        """What the model reads of it: the one serialization."""
        return tool_result_text(self.result.payload)

    @property
    def summary(self) -> str:
        return summarize_result(self.result.payload)

    @property
    def status(self) -> Literal["ok", "error"]:
        return "error" if self.result.is_error else "ok"


@dataclass(frozen=True)
class PlayedRound:
    """One model round as played: what it was sent with, and what it asked for."""

    turn: int
    index: int
    """Its place among the turn's rounds; `len(plan.rounds)` is the closing round."""
    prior_rounds: int
    """The model's answers already in the history this round's request carries."""
    visible: tuple[PlayedCall, ...]
    calls: tuple[PlayedCall, ...]


@dataclass
class PlayedReview:
    """What a played script produced: the session, and every round with its history."""

    session: ReviewSession
    rounds: list[PlayedRound] = field(default_factory=list)
    setup_steps: int = 0
    """Steps setup wrote before the first model round (lever 5's pre-run)."""


class _Stop(BaseException):
    """Raised at a tool boundary to stop a turn, as the pane's `TurnStopped` is.

    A `BaseException`, like `TurnStopped`: the runner turns an `Exception` out of a turn into a
    failed turn, and a stopped one is not a failure.
    """


class _RecordingTools:
    """The run's `ToolSet`, recording every result in order and stopping where it is told to."""

    def __init__(self, tools: ToolSet, run: ReviewRun) -> None:
        self.tools = tools
        self.run = run
        self.played: list[PlayedCall] = []
        self.stop_at: int | None = None

    def __iter__(self) -> Iterator[ProviderTool]:
        return iter(self.tools)

    def __len__(self) -> int:
        return len(self.tools)

    def call(self, name: str, arguments: Mapping[str, Any], call_id: str = "") -> ToolCallResult:
        index = len(self.played)
        if self.stop_at is not None and index == self.stop_at:
            raise _Stop(f"stopped before {name!r}")
        step = len(self.run.session.steps)
        result = self.tools.call(name, arguments, call_id)
        self.played.append(
            PlayedCall(index=index, step=step, tool=name, arguments=dict(arguments), result=result)
        )
        return result


def _scripted(
    turn_index: int, plan: TurnPlan, usages: Mapping[tuple[int, int], TokenUsage | None]
) -> ScriptedTurn:
    return ScriptedTurn(
        text=plan.text,
        rounds=tuple(
            ScriptedRound(tuple(calls), usage=usages.get((turn_index, index)))
            for index, calls in enumerate(plan.rounds)
        ),
        usage=usages.get((turn_index, len(plan.rounds))),
        end_reason=plan.end_reason,
    )


def play_review(
    package_dir: Path | str,
    run_dir: Path | str,
    turns: Sequence[TurnPlan],
    *,
    usages: Mapping[tuple[int, int], TokenUsage | None] | None = None,
    presentation: TokenUsage | None = None,
    model: str = "fake-scripted",
    **start_review_kwargs: Any,
) -> PlayedReview:
    """Play `turns` through `start_review` in `run_dir` and return every round as played.

    `run_dir` receives a copy of `package_dir/package.json` and is reviewed in place, the
    way the pane reviews its run folder. `usages` gives each round's usage by `(turn,
    round)` (the closing round is `len(plan.rounds)`); a round with none reports none.
    `presentation`, when given, turns the presentation request on and is what it costs.
    """
    if "explain_findings" in start_review_kwargs:
        raise TypeError("the presentation request is turned on by `presentation`, not directly")
    run_path = Path(run_dir)
    run_path.mkdir(parents=True, exist_ok=True)
    source = Path(package_dir) / PACKAGE_FILE_NAME
    if source.resolve() != (run_path / PACKAGE_FILE_NAME).resolve():
        shutil.copyfile(source, run_path / PACKAGE_FILE_NAME)
    usage_of = usages or {}
    provider = FakeProvider(
        script=[_scripted(index, plan, usage_of) for index, plan in enumerate(turns)],
        explanation_script=(
            (ScriptedTurn(text=EMPTY_EXPLANATIONS, usage=presentation),)
            if presentation is not None
            else ()
        ),
        model=model,
        clock=lambda: 0.0,
    )
    run = start_review(
        run_path,
        run_path,
        provider=provider,
        explain_findings=presentation is not None,
        **start_review_kwargs,
    )
    try:
        return _play(run, turns)
    finally:
        run.close()


def _play(run: ReviewRun, turns: Sequence[TurnPlan]) -> PlayedReview:
    tools = _RecordingTools(run.tools, run)
    run.tools = tools
    played = PlayedReview(session=run.session, setup_steps=len(run.session.steps))
    committed: list[PlayedCall] = []
    committed_rounds = 0
    for turn_index, plan in enumerate(turns):
        start = len(tools.played)
        tools.stop_at = start + plan.calls - 1 if plan.stop_at_last_call else None
        stopped = _drive(run, plan)
        dispatched = tools.played[start:]
        rounds = _rounds_of(turn_index, plan, committed, committed_rounds, dispatched, stopped)
        played.rounds.extend(rounds)
        if not stopped:
            committed.extend(dispatched)
            committed_rounds += len(rounds)
    played.session = run.session
    return played


def _drive(run: ReviewRun, plan: TurnPlan) -> bool:
    """Run one turn the way its plan opens it; `True` when it was stopped at a tool boundary."""
    try:
        if plan.kind == "opening":
            run.start()
        elif plan.kind == "follow_up":
            run.continue_session(plan.user_text)
        else:
            [(request_id, answer)] = plan.answers
            run.answer_evidence(request_id, answer)
    except _Stop:
        # What the pane's `_end_stopped` does when `TurnStopped` reaches it.
        run.sink.emit("turn.ended", {"reason": "stopped"})
        run.finalize()
        return True
    return False


def turn_plans(
    recording: Recording,
    *,
    arguments: Callable[[RecordedCall], Mapping[str, Any]] | None = None,
    text: str = "",
    follow_up_text: str = FOLLOW_UP_PLACEHOLDER,
) -> list[TurnPlan]:
    """The recorded turns as plans to play: every recorded call, in its recorded round.

    `arguments` rewrites a call's arguments (the fixture generator scrambles the model's
    prose); by default they are played as recorded. A turn's rounds that asked for calls
    become its rounds and its last main round, which asked for none, its closing round;
    presentation rounds are not played (they are carried). A dangling call is already gone
    (the reader drops it), so a stopped turn is played as far as the recording got.
    """
    rewrite = arguments if arguments is not None else (lambda call: call.arguments)
    plans: list[TurnPlan] = []
    for turn in recording.turns:
        main = turn.main_rounds
        with_calls = [r for r in main if r.calls]
        if any(not r.calls for r in main[:-1]):
            raise ValueError(
                f"turn {turn.index} of {recording.run_dir} has a round with no call before its "
                "last round; no adapter records that shape, so it cannot be replayed"
            )
        plans.append(
            TurnPlan(
                rounds=tuple(
                    tuple(ScriptedToolCall(call.tool, dict(rewrite(call))) for call in r.calls)
                    for r in with_calls
                ),
                kind=turn.kind,
                user_text=follow_up_text if turn.kind == "follow_up" else "",
                answers=turn.answers,
                text=text,
                end_reason=turn.end_reason if turn.end_reason != "open" else "end",
            )
        )
    return plans


def estimated_sizes(
    recording: Recording,
    recorded_round: RecordedRound,
    known: Mapping[int, int],
) -> dict[int, tuple[int, bool]]:
    """The size, in tokens, of each call of a round not in `known`, from the recorded growth.

    `known` maps a step to the size of a call whose result the current code reproduces. What
    is left of the round's growth - the next main round's input, minus this round's input and
    output, minus every known call with its framing, minus the framing of each unknown one -
    is shared equally among the unknown calls (the remainder to the first). When the growth is
    not observable, or what is left is negative, each unknown call is sized at the tokens of
    its recorded 200-character summary and flagged as a lower bound (`contracts/replay.md`
    section 4, rule 3).
    """
    unknown = [call for call in recorded_round.calls if call.step not in known]
    if not unknown:
        return {}
    growth = recording.growth_after(recorded_round)
    rest = None
    if growth is not None:
        spent = sum(
            known[call.step] + FRAMING_TOKENS for call in recorded_round.calls if call.step in known
        )
        rest = growth - spent - FRAMING_TOKENS * len(unknown)
    if rest is None or rest < 0:
        return {call.step: (count_tokens(call.summary), True) for call in unknown}
    share, remainder = divmod(rest, len(unknown))
    return {
        call.step: (share + (1 if position < remainder else 0), False)
        for position, call in enumerate(unknown)
    }


def _rounds_of(
    turn_index: int,
    plan: TurnPlan,
    committed: Sequence[PlayedCall],
    committed_rounds: int,
    dispatched: Sequence[PlayedCall],
    stopped: bool,
) -> list[PlayedRound]:
    """Split one turn's dispatched calls back into the rounds its plan grouped them in.

    A round is played when the budget reached it; the closing round is played when every
    call ran and the turn was not stopped.
    """
    rounds: list[PlayedRound] = []
    visible = list(committed)
    offset = 0
    for index, calls in enumerate(plan.rounds):
        if offset >= len(dispatched) and not (stopped and offset == len(dispatched)):
            return rounds
        mine = tuple(dispatched[offset : offset + len(calls)])
        rounds.append(
            PlayedRound(
                turn=turn_index,
                index=index,
                prior_rounds=committed_rounds + index,
                visible=tuple(visible),
                calls=mine,
            )
        )
        visible.extend(mine)
        offset += len(calls)
        if len(mine) < len(calls):
            return rounds
    if not stopped:
        rounds.append(
            PlayedRound(
                turn=turn_index,
                index=len(plan.rounds),
                prior_rounds=committed_rounds + len(plan.rounds),
                visible=tuple(visible),
                calls=(),
            )
        )
    return rounds
