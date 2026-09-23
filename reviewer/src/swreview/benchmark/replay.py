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
- `PlayedRound.history` is that history as the adapters' neutral messages: the engineer's
  messages, one assistant message per round with the calls it asked for, each result as the
  model reads it (`model_payload`), and a committed turn's closing answer. It is what the
  replay prunes with the adapters' own `prune_history` (feature 008 User Story 3).
- `PlayedCall` carries each call's full `ToolCallResult`, so a caller can size it with
  `tool_result_text` and compare it with a recorded summary.

The driver makes no network call and needs no key and no SOLIDWORKS unless its caller hands
`start_review` a bridge factory.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from swreview.agent.providers import (
    FRAMING_TOKENS,
    ProviderTool,
    TokenUsage,
    ToolCallResult,
    ToolSet,
    TurnEndReason,
    model_payload,
    summarize_result,
    tool_result_text,
)
from swreview.agent.providers.fake import (
    FakeProvider,
    ScriptedRound,
    ScriptedToolCall,
    ScriptedTurn,
)
from swreview.agent.providers.pruning import prunable, prune_history, result_stub
from swreview.agent.runner import ReviewRun, answers_message, start_review
from swreview.agent.settings import (
    MODEL_VIEW_OFF,
    EfficiencySettings,
    ModelViewSettings,
    checks_first,
)
from swreview.benchmark.recording import (
    UNCOMMITTED_ENDS,
    RecordedCall,
    RecordedRound,
    RecordedTurn,
    Recording,
    read_recording,
)
from swreview.checks.interference import CHECK as INTERFERENCE_CHECK
from swreview.findings import Finding, SubjectKey, finding_subject_key
from swreview.ir.loader import PACKAGE_FILE_NAME
from swreview.prerun import ALREADY_RUN
from swreview.report.session import Contact, ReviewSession
from swreview.tokens import TOKENIZER_NAME, count_tokens, encoding
from swreview.tools.model_view import model_view as view_of
from swreview.tools.registry import (
    BRIDGE_TOOL_FUNCTIONS,
    COMPACT_QUERY_TOOL_FUNCTIONS,
    REMODEL_TOOL_FUNCTIONS,
    TOOL_FUNCTIONS,
    TOOL_RESULTS_DIR_NAME,
    standards_tools,
)

__all__ = [
    "EMPTY_EXPLANATIONS",
    "FOLLOW_UP_PLACEHOLDER",
    "REGROUPED_ASSUMPTION",
    "CallClass",
    "PlayedCall",
    "PlayedReview",
    "PlayedRound",
    "ReclassifiedFinding",
    "RegroupRule",
    "Regrouped",
    "RegroupedPass",
    "RegroupedRound",
    "ReplayCall",
    "ReplayFinding",
    "ReplayFindings",
    "ReplayPasses",
    "ReplayReport",
    "ReplayRound",
    "ReplayTotals",
    "TurnKind",
    "TurnPlan",
    "estimated_sizes",
    "play_review",
    "render_replay_lines",
    "replay",
    "replay_passes",
    "replay_recording",
    "report_of",
    "request_messages",
    "subject_of",
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
    engineer's question (`user_text`), `answer` the engineer's answers to evidence requests
    (`answers`, one `(request_id, answer)` pair each, sent together when there are several).
    `rounds` are the model's rounds that asked for calls, in order; the turn's closing round
    answers with `text`. `stop_at_last_call` stops the turn as the pane's Stop does - at the
    next tool boundary - so its last call is started and never finished, and the turn ends
    `stopped` without a closing round.
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
        if self.kind == "answer" and not self.answers:
            raise ValueError("an answer turn resumes on at least one answered evidence request")
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
    history: tuple[dict[str, Any], ...]
    """The neutral messages this round's request carries, before any pruning: its tool
    messages are `visible`, in order (`contracts/replay.md` section 4, rule 4)."""


@dataclass
class PlayedReview:
    """What a played script produced: the session, and every round with its history."""

    session: ReviewSession
    rounds: list[PlayedRound] = field(default_factory=list)
    setup_steps: int = 0
    """Steps setup wrote before the first model round (lever 5's pre-run)."""
    prefix: str = ""
    """The system prompt, the tool schemas and the opening message, as `_prefix` renders them."""
    opening: str = ""
    """The first user message the review opened on: the checks-first digest, when it ran."""


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


def _prefix(run: ReviewRun) -> str:
    """What every request of the run starts with: the system prompt, the tools, the opening.

    Serialized the same way for every pass, so the difference between two passes is the
    difference their settings make; the provider's own rendering of the schemas is not seen
    here, which is why the replay calibrates the prefix to the recorded first round.
    """
    tools = [
        {"name": tool.name, "description": tool.description, "parameters": tool.schema}
        for tool in run.tools
    ]
    return run.system + json.dumps(tools) + run.opening_message


def _play(run: ReviewRun, turns: Sequence[TurnPlan]) -> PlayedReview:
    played = PlayedReview(
        session=run.session,
        setup_steps=len(run.session.steps),
        prefix=_prefix(run),
        opening=run.opening_message,
    )
    tools = _RecordingTools(run.tools, run)
    run.tools = tools
    committed: list[PlayedCall] = []
    committed_rounds = 0
    history: list[dict[str, Any]] = []
    for turn_index, plan in enumerate(turns):
        start = len(tools.played)
        tools.stop_at = start + plan.calls - 1 if plan.stop_at_last_call else None
        stopped = _drive(run, plan)
        dispatched = tools.played[start:]
        # The runner appends the engineer's message before the turn runs and keeps it
        # whether or not the turn returns; only a returned turn adds its rounds.
        history.append(_user_message(run, plan))
        rounds = _rounds_of(
            turn_index, plan, committed, committed_rounds, dispatched, stopped, history
        )
        played.rounds.extend(rounds)
        if not stopped and plan.end_reason not in UNCOMMITTED_ENDS:
            committed.extend(dispatched)
            committed_rounds += len(rounds)
            history.extend(m for r in rounds if r.calls for m in _round_messages(r.calls))
            if plan.end_reason != "max_steps":
                history.append({"role": "assistant", "content": plan.text})
    played.session = run.session
    return played


def _user_message(run: ReviewRun, plan: TurnPlan) -> dict[str, Any]:
    """The engineer's message the runner appends before the turn, in the runner's words."""
    if plan.kind == "opening":
        text = run.opening_message
    elif plan.kind == "follow_up":
        text = plan.user_text
    else:
        text = answers_message(plan.answers)
    return {"role": "user", "content": text}


def _round_messages(calls: Sequence[PlayedCall]) -> list[dict[str, Any]]:
    """One round in the neutral history: the assistant message asking for its calls, then
    one tool message per call carrying what the model reads of it - the fake's shape, which
    is every adapter's (`providers/fake.py`, `openai_provider._append_assistant`)."""
    return [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"call_id": c.result.call_id, "name": c.tool, "arguments": dict(c.arguments)}
                for c in calls
            ],
        },
        *(
            {
                "role": "tool",
                "call_id": c.result.call_id,
                "name": c.tool,
                "content": model_payload(c.result),
                "is_error": c.result.is_error,
            }
            for c in calls
        ),
    ]


def _drive(run: ReviewRun, plan: TurnPlan) -> bool:
    """Run one turn the way its plan opens it; `True` when it was stopped at a tool boundary.

    Answers sent together resume one turn through `answer_evidence_batch`, and a single one
    through `answer_evidence`, as the pane's two routes do (`contracts/replay.md` section 2).
    """
    try:
        if plan.kind == "opening":
            run.start()
        elif plan.kind == "follow_up":
            run.continue_session(plan.user_text)
        elif len(plan.answers) == 1:
            [(request_id, answer)] = plan.answers
            run.answer_evidence(request_id, answer)
        else:
            run.answer_evidence_batch(plan.answers)
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
    history: Sequence[dict[str, Any]],
) -> list[PlayedRound]:
    """Split one turn's dispatched calls back into the rounds its plan grouped them in.

    A round is played when the budget reached it; the closing round is played when every
    call ran and the turn was not stopped. `history` is what the turn's first request
    carries: the committed history and the engineer's message.
    """
    rounds: list[PlayedRound] = []
    visible = list(committed)
    messages = list(history)
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
                history=tuple(messages),
            )
        )
        visible.extend(mine)
        messages.extend(_round_messages(mine) if mine else ())
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
                history=tuple(messages),
            )
        )
    return rounds


# --- the replay: two passes, classes, accounting, findings (contracts/replay.md §3 to §7) ------

CallClass = Literal[
    "reproduced", "changed", "estimated", "stored", "carried", "answered_from_checks"
]
"""How a recorded call was priced. `answered_from_checks` (User Story 2): the requested pass
ran checks first and its re-call guard answered the call from the pre-run. `stored` (User
Story 3): the call would be estimated, but the run folder keeps its full result. `carried` is
a presentation round, which has no calls of its own."""

BRIDGE_TOOLS = frozenset(function.__name__ for function in BRIDGE_TOOL_FUNCTIONS)
STANDARDS_TOOLS = frozenset(function.__name__ for function in standards_tools())
KNOWN_TOOLS = frozenset(
    function.__name__
    for function in (
        *TOOL_FUNCTIONS,
        *BRIDGE_TOOL_FUNCTIONS,
        *REMODEL_TOOL_FUNCTIONS,
        *COMPACT_QUERY_TOOL_FUNCTIONS,
        *standards_tools(),
    )
)
"""Every tool the current code can offer in some run; a recorded name outside it is retired."""


class ReplayModel(BaseModel):
    """The replay report's parts: strict, and serialized under their contract names."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ReplayCall(ReplayModel):
    step: int
    tool: str
    class_: CallClass = Field(alias="class")
    reason: str | None = None
    """A sentence for every class but `reproduced`."""


class ReplayRound(ReplayModel):
    turn: int
    round: int
    kind: Literal["main", "presentation"]
    recorded_input: int
    as_recorded_input: int
    requested_input: int
    estimated: bool
    lower_bound: bool
    calls: list[ReplayCall]


class ReplayTotals(ReplayModel):
    recorded: int
    as_recorded: int
    requested: int
    difference: int
    """`requested - recorded`."""
    estimated_rounds: int
    lower_bound_rounds: int
    carried_rounds: int


class PassSettings(ReplayModel):
    efficiency: EfficiencySettings
    model_view: ModelViewSettings
    """What the model read of each result: the recording's own (off when it records none)
    for pass A, the requested one for pass B."""


class ReplaySettings(ReplayModel):
    as_recorded: PassSettings
    requested: PassSettings


class ReplayFinding(ReplayModel):
    check: str
    subject: str
    """The printable form of `finding_subject_key` without the check (`subject_of`)."""


class NotReplayableFinding(ReplayFinding):
    step: int | None
    reason: str


class ReclassifiedFinding(ReplayFinding):
    """A recorded finding the requested pass judged a contact (feature 010 T095)."""

    step: int | None
    group_key: str
    contact_id: str
    """The requested pass's contact whose group key and configuration matched."""


class ReplayFindings(ReplayModel):
    recorded: int
    replayed: int
    lost: list[ReplayFinding]
    added: list[ReplayFinding]
    not_replayable: list[NotReplayableFinding]
    reclassified: list[ReclassifiedFinding] = Field(default_factory=list)
    """Recorded `interference.static` findings whose group key and configuration equal a
    contact the requested pass recorded: touching groups, contacts by design since feature
    010 (its `contracts/contacts.md` section 6). Neither lost nor not replayable."""


RegroupRule = Literal["R", "M"]
"""Rule R drops the recorded calls the requested pass answered from its checks; rule M merges
consecutive rounds of one turn that call one tool (`contracts/replay.md` section 6)."""

REGROUPED_ASSUMPTION = (
    "the model does not repeat a check the digest reported, and batches consecutive calls "
    "to one tool"
)
"""What the regrouped estimate assumes, printed beside it (research R2.43)."""


class Regrouped(ReplayModel):
    """The labelled regrouped estimate (User Story 4, data-model section 2).

    Pass B's script with rule R and rule M applied, played through the current code and
    priced by the strict figure's own accounting; SC-003 is gated on `total`.
    """

    assumption: str
    rules: list[RegroupRule]
    """The rules whose condition the requested settings meet, in the order they apply."""
    rounds: int
    """The rounds the estimate prices: the regrouped main rounds and every carried round."""
    total: int


class ReplayReport(ReplayModel):
    """One recorded review re-priced by the current code (data-model section 2)."""

    run_dir: str
    provider: str
    tokenizer: str
    comparison: Literal["exact", "shape"]
    framing_tokens: int
    settings: ReplaySettings
    rounds: list[ReplayRound]
    totals: ReplayTotals
    regrouped: Regrouped | None = None
    """The labelled regrouped estimate; `None` when neither rule applies."""
    findings: ReplayFindings


Requested = tuple[EfficiencySettings, ModelViewSettings]
"""What pass B runs with: its levers and its model view, as `cli._review_settings` resolves
them."""


def replay(
    run_dir: Path | str,
    *,
    requested: Requested,
    standards_profile: Path | str | None = None,
) -> ReplayReport:
    """Replay the review in `run_dir` as recorded and with `requested`, and compare both.

    No key, no network, no SOLIDWORKS: both passes play the recorded rounds through
    `start_review` with the scripted provider, in a temporary folder holding a copy of the
    package, and nothing is written into `run_dir`. Refuses a folder that is not a review
    (`RecordingRefused`) and a machine without the vocabulary (`TokenizerUnavailable`).
    """
    return replay_recording(
        read_recording(run_dir), requested=requested, standards_profile=standards_profile
    )


@dataclass(frozen=True)
class RegroupedRound:
    """One round of the regrouped script that asks for calls."""

    sources: tuple[RecordedRound, ...]
    """The recorded main rounds it stands for: one, or a run rule M merged."""
    calls: tuple[int, ...]
    """The recorded calls it keeps, by their index among the model's calls, in recorded order."""


@dataclass(frozen=True)
class RegroupedPass:
    """Pass B's script regrouped by rules R and M, and that script as played."""

    rules: tuple[RegroupRule, ...]
    turns: tuple[tuple[RegroupedRound, ...], ...]
    """Each recorded turn's regrouped rounds that ask for calls, in order."""
    played: PlayedReview


@dataclass(frozen=True)
class ReplayPasses:
    """The played passes of one recording: as recorded (A), as requested (B), and B regrouped."""

    recording: Recording
    as_recorded: EfficiencySettings
    as_recorded_view: ModelViewSettings
    requested: EfficiencySettings
    requested_view: ModelViewSettings
    first: PlayedReview
    second: PlayedReview
    with_profile: bool
    regrouped: RegroupedPass | None = None
    """`None` when neither regrouping rule applies to the requested settings."""


def replay_passes(
    recording: Recording,
    scratch: Path | str,
    *,
    requested: Requested,
    standards_profile: Path | str | None = None,
) -> ReplayPasses:
    """Play pass A and pass B of `recording` into `scratch/as-recorded` and `scratch/requested`.

    Pass A runs with the recording's own levers and model view (a session written before
    either records none, which is off); pass B with `requested`. When a regrouping rule
    applies to `requested`, pass B's script regrouped by it is played too, into
    `scratch/regrouped` (User Story 4). The folders are the caller's: `replay_recording`
    hands a temporary one and lets it go; an acceptance test keeps it to read what the
    requested pass wrote. Nothing is written anywhere else, and never into the recording's
    own folder.
    """
    requested_settings, requested_view = requested
    recorded_settings = recording.session.efficiency or EfficiencySettings()
    recorded_view = recording.session.model_view or MODEL_VIEW_OFF
    plans = turn_plans(recording)
    options: dict[str, Any] = {"standards_profile": standards_profile}
    first = play_review(
        recording.run_dir,
        Path(scratch) / "as-recorded",
        plans,
        model=recording.session.model,
        efficiency=recorded_settings,
        model_view=recorded_view,
        **options,
    )
    second = play_review(
        recording.run_dir,
        Path(scratch) / "requested",
        plans,
        model=recording.session.model,
        efficiency=requested_settings,
        model_view=requested_view,
        **options,
    )
    with_profile = standards_profile is not None
    rules = _regroup_rules(requested_settings)
    regrouped: RegroupedPass | None = None
    if rules:
        classes = _classify(recording, first, with_profile)
        turns = _regroup(
            recording,
            classes,
            _answered_from_checks(classes, second),
            drop_answered="R" in rules,
            merge="M" in rules,
        )
        regrouped = RegroupedPass(
            rules=rules,
            turns=turns,
            played=play_review(
                recording.run_dir,
                Path(scratch) / "regrouped",
                _regrouped_plans(plans, turns, len(classes)),
                model=recording.session.model,
                efficiency=requested_settings,
                model_view=requested_view,
                **options,
            ),
        )
    return ReplayPasses(
        recording=recording,
        as_recorded=recorded_settings,
        as_recorded_view=recorded_view,
        requested=requested_settings,
        requested_view=requested_view,
        first=first,
        second=second,
        with_profile=with_profile,
        regrouped=regrouped,
    )


def replay_recording(
    recording: Recording,
    *,
    requested: Requested,
    standards_profile: Path | str | None = None,
) -> ReplayReport:
    """`replay` over a recording already read."""
    encoding()  # a replay that cannot count has nothing to report: refuse before running
    with tempfile.TemporaryDirectory(prefix="swreview-replay-") as scratch:
        passes = replay_passes(
            recording, scratch, requested=requested, standards_profile=standards_profile
        )
    return report_of(passes)


def report_of(passes: ReplayPasses) -> ReplayReport:
    """Price and compare two played passes (`contracts/replay.md` sections 3 to 5)."""
    recording, first, second = passes.recording, passes.first, passes.second
    classes = _classify(recording, first, passes.with_profile)
    answered = _answered_from_checks(classes, second)
    pricing_first, lower = _as_recorded_pricing(recording, classes, passes.as_recorded_view)
    pricing_second = _requested_pricing(pricing_first, answered, passes.requested_view)
    prefix_difference = count_tokens(second.prefix) - count_tokens(first.prefix)
    rounds = _rounds(
        recording,
        classes,
        first,
        second,
        pricing_first,
        pricing_second,
        lower,
        answered,
        prefix_difference=prefix_difference,
    )
    return ReplayReport(
        run_dir=str(recording.run_dir),
        provider=recording.provider,
        tokenizer=TOKENIZER_NAME,
        comparison="shape" if recording.provider == "gemini" else "exact",
        framing_tokens=FRAMING_TOKENS,
        settings=ReplaySettings(
            as_recorded=PassSettings(
                efficiency=passes.as_recorded, model_view=passes.as_recorded_view
            ),
            requested=PassSettings(efficiency=passes.requested, model_view=passes.requested_view),
        ),
        rounds=rounds,
        totals=_totals(rounds),
        regrouped=_regrouped_estimate(
            recording, passes.regrouped, pricing_second, prefix_difference=prefix_difference
        ),
        findings=_findings(recording, classes, second, answered),
    )


@dataclass(frozen=True)
class _Stored:
    """A call's full result as the recorded review stored it (`tool-results/step-<n>.json`)."""

    payload: dict[str, Any]
    is_error: bool


@dataclass(frozen=True)
class _Classified:
    """One recorded call, its counterpart in pass A (by position), and its class."""

    index: int
    recorded: RecordedCall
    played: PlayedCall | None
    class_: CallClass
    reason: str | None
    stored: _Stored | None = None
    """The stored result a `stored` call is sized from."""


def _classify(recording: Recording, first: PlayedReview, with_profile: bool) -> list[_Classified]:
    """Class every recorded call from pass A (contracts/replay.md section 3).

    A call that would be estimated is `stored` instead when the run folder keeps its full
    result. Either way the replay could not run it, so a later divergence in the turn is
    still put down to it.
    """
    played = [call for played_round in first.rounds for call in played_round.calls]
    classified: list[_Classified] = []
    index = 0
    for turn in recording.turns:
        unreproduced_at: int | None = None
        for recorded_round in turn.rounds:
            for call in recorded_round.calls:
                counterpart = played[index] if index < len(played) else None
                class_, reason = _class_of(call, counterpart, unreproduced_at, with_profile)
                stored = _stored_result(recording, call) if class_ == "estimated" else None
                if stored is not None:
                    class_ = "stored"
                    reason = (
                        f"{reason}; sized from its stored result "
                        f"{TOOL_RESULTS_DIR_NAME}/step-{call.step}.json"
                    )
                if class_ in ("estimated", "stored") and unreproduced_at is None:
                    unreproduced_at = call.step
                classified.append(_Classified(index, call, counterpart, class_, reason, stored))
                index += 1
    return classified


def _stored_result(recording: Recording, call: RecordedCall) -> _Stored | None:
    """The call's stored full result, when the recorded review wrote one for this call.

    Taken only when the file names this recording's session, this step, this tool and these
    arguments, and carries a payload: a stale file from an earlier review in a reused
    folder, or one a hand edit broke, is not this call's result and is ignored, leaving the
    call estimated.
    """
    path = recording.run_dir / TOOL_RESULTS_DIR_NAME / f"step-{call.step}.json"
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(envelope, dict):
        return None
    payload = envelope.get("payload")
    if (
        envelope.get("session_id") != str(recording.session.session_id)
        or envelope.get("step") != call.step
        or envelope.get("tool") != call.tool
        or envelope.get("arguments") != call.arguments
        or not isinstance(payload, dict)
    ):
        return None
    return _Stored(payload=payload, is_error=envelope.get("status") == "error")


def _class_of(
    recorded: RecordedCall,
    played: PlayedCall | None,
    unreproduced_at: int | None,
    with_profile: bool,
) -> tuple[CallClass, str | None]:
    if recorded.tool not in KNOWN_TOOLS:
        return "estimated", f"{recorded.tool} is not known to the current code"
    if recorded.tool in BRIDGE_TOOLS:
        return "estimated", (
            f"{recorded.tool} needs the live SOLIDWORKS bridge, which a replay does not have"
        )
    if recorded.tool in STANDARDS_TOOLS and not with_profile:
        return "estimated", (
            f"{recorded.tool} needs a standards profile, and none was given (--standards-profile)"
        )
    if played is None:
        return "estimated", "the replay stopped before this call"
    if played.status != recorded.status:
        return "estimated", (
            f"the recording returned {recorded.status} and the current code returns "
            f"{played.status}: {played.summary}"
        )
    if same_summary(recorded.summary, played.summary):
        return "reproduced", None
    if unreproduced_at is not None:
        return "estimated", (
            f"its result differs from the recording after the estimated call at step "
            f"{unreproduced_at}, whose effect a replay cannot reproduce"
        )
    return "changed", "the current code's result differs from the recorded one"


_SESSION_IDS = re.compile(r"\b(F|ER)-[0-9]{3,}\b")
_TRUNCATION = "…"


def same_summary(recorded: str, replayed: str) -> bool:
    """Whether two 200-character trace lines report the same result.

    Finding and evidence-request ids are compared as ids, not as numbers: a replay that cannot
    run a recorded check skips that check's findings, so every later finding is numbered lower
    than it was recorded and a summary that differs only by its ids is the same result. When a
    line was cut at its length limit, the two are compared as far as both go.
    """

    def normalized(summary: str) -> tuple[str, bool]:
        cut = summary.endswith(_TRUNCATION)
        text = summary[: -len(_TRUNCATION)] if cut else summary
        return _SESSION_IDS.sub(r"\1-#", text), cut

    left, left_cut = normalized(recorded)
    right, right_cut = normalized(replayed)
    if left_cut or right_cut:
        shared = min(len(left), len(right))
        return left[:shared] == right[:shared]
    return left == right


@dataclass(frozen=True)
class _Estimate:
    """A result the replay could not run: its estimated size, and whether it was an error."""

    tokens: int
    is_error: bool


@dataclass(frozen=True)
class _Pricing:
    """How one pass prices the results its requests carry (contracts/replay.md section 4).

    Every result is read from the pass's own played history, except the ones listed here.
    A `stored` entry's content is its stored result as the pass's settings show it, pruned
    like any other result. An `estimates` entry has no content: it is sized at its estimate
    - the recorded growth, the full payload as recorded, whatever the view - until the
    adapters' rule makes it a stub, and then at the part of its stub the replay can know
    (its tool and arguments, without the counts and ids its payload would add).
    """

    view: ModelViewSettings
    estimates: Mapping[int, _Estimate]
    stored: Mapping[int, _Stored]


def request_messages(
    history: Sequence[Mapping[str, Any]], view: ModelViewSettings
) -> list[dict[str, Any]]:
    """The messages a request built from `history` carries under `view`: the adapters' rule.

    Pruned by the adapters' own `prune_history` when the view prunes, pointing stubs at
    `get_finding` only when slimming offers it, exactly as `openai_provider._visible` and
    the Gemini adapter's `_contents` do; unchanged otherwise.
    """
    if not view.history_pruning:
        return [dict(message) for message in history]
    return prune_history(
        history, view.prune_after_rounds, finding_detail=view.payload_slimming
    )


def _shown(tool: str, stored: _Stored, view: ModelViewSettings) -> dict[str, Any]:
    """A stored result as the model would read it under `view`: the tool's view when slimming."""
    return view_of(tool, stored.payload) if view.payload_slimming else stored.payload


def _read_tokens(content: Mapping[str, Any], view: ModelViewSettings) -> int:
    """`T` of one result as the model reads it: the one serialization, compact when slimming."""
    return count_tokens(tool_result_text(content, compact=view.payload_slimming))


def _results_tokens(
    played: PlayedRound, pricing: _Pricing, cache: dict[tuple[int, bool], int]
) -> int:
    """Σ over the tool messages one round's request carries of their tokens and framing.

    The round's neutral history with each stored result put in its place and each estimated
    one given its recorded status, passed through `request_messages`; an estimated result
    becomes a stub where the adapters' rule (`prunable`) says so and its stub is smaller
    than its estimate. `cache` holds each call's count in full and as a stub, which is all a
    result can be (a stub is a function of the result alone).
    """
    history = list(played.history)
    positions = [i for i, message in enumerate(history) if message.get("role") == "tool"]
    if len(positions) != len(played.visible):
        raise AssertionError(
            f"round {played.index} of turn {played.turn} carries {len(positions)} tool "
            f"messages for {len(played.visible)} visible results"
        )
    view = pricing.view
    for position, call in zip(positions, played.visible, strict=True):
        stored = pricing.stored.get(call.index)
        estimate = pricing.estimates.get(call.index)
        if stored is not None:
            history[position] = {
                **history[position],
                "content": _shown(call.tool, stored, view),
                "is_error": stored.is_error,
            }
        elif estimate is not None:
            history[position] = {**history[position], "is_error": estimate.is_error}
    sent = request_messages(history, view)
    old = prunable(history, view.prune_after_rounds) if view.history_pruning else {}
    total = 0
    for position, call in zip(positions, played.visible, strict=True):
        estimate = pricing.estimates.get(call.index)
        if estimate is not None:
            stub = None
            if position in old:
                stub = _read_tokens(
                    result_stub(
                        call.tool, old[position], {}, finding_detail=view.payload_slimming
                    ),
                    view,
                )
            total += (estimate.tokens if stub is None else min(stub, estimate.tokens))
            total += FRAMING_TOKENS
            continue
        content = sent[position]["content"]
        key = (call.index, content is not history[position]["content"])
        if key not in cache:
            cache[key] = _read_tokens(content, view)
        total += cache[key] + FRAMING_TOKENS
    return total


def _as_recorded_pricing(
    recording: Recording, classes: Sequence[_Classified], view: ModelViewSettings
) -> tuple[_Pricing, set[int]]:
    """Pass A's pricing, and the indices whose estimate is a lower bound.

    A call's size as the next request reads it - in full, since no result is pruned in the
    request right after it - is what the recorded growth is shared out against.
    """
    known: dict[int, int] = {}
    stored: dict[int, _Stored] = {}
    for item in classes:
        if item.stored is not None:
            stored[item.index] = item.stored
            known[item.index] = _read_tokens(_shown(item.recorded.tool, item.stored, view), view)
        elif item.class_ != "estimated" and item.played is not None:
            known[item.index] = _read_tokens(model_payload(item.played.result), view)
    by_step = {item.recorded.step: item for item in classes}
    estimates: dict[int, _Estimate] = {}
    lower: set[int] = set()
    for turn in recording.turns:
        for recorded_round in turn.rounds:
            sized = {
                call.step: known[by_step[call.step].index]
                for call in recorded_round.calls
                if by_step[call.step].index in known
            }
            for step, (size, bound) in estimated_sizes(recording, recorded_round, sized).items():
                item = by_step[step]
                estimates[item.index] = _Estimate(size, item.recorded.status == "error")
                if bound:
                    lower.add(item.index)
    return _Pricing(view=view, estimates=estimates, stored=stored), lower


def _answered_from_checks(
    classes: Sequence[_Classified], second: PlayedReview
) -> dict[int, str]:
    """The recorded calls pass B's re-call guard answered, by index, each with its reason.

    Recognised by the guard's own answer (`prerun.ALREADY_RUN`), never by the tool's name:
    a call the guard lets through - another group, a component subset, a call whose pre-run
    attempt failed - keeps its pass-A class (`contracts/replay.md` section 3).
    """
    played = {call.index: call for r in second.rounds for call in r.calls}
    answered: dict[int, str] = {}
    for item in classes:
        call = played.get(item.index)
        if call is None or call.result.payload.get("status") != ALREADY_RUN:
            continue
        answered[item.index] = (
            f"the pre-run ran this call at step {call.result.payload.get('ran_at_step')}"
        )
    return answered


def _requested_pricing(
    first: _Pricing, answered: Mapping[int, str], view: ModelViewSettings
) -> _Pricing:
    """Pass B's pricing: the current code's result, pass A's estimate, or the stored result.

    A call the guard answered is read from the guard's answer whatever its pass-A class: the
    answer is what the requested pass really sends, even behind an estimated call. A stored
    result is shown as pass B's settings show it.
    """
    return _Pricing(
        view=view,
        estimates={
            index: size for index, size in first.estimates.items() if index not in answered
        },
        stored={index: item for index, item in first.stored.items() if index not in answered},
    )


def _rounds(
    recording: Recording,
    classes: Sequence[_Classified],
    first: PlayedReview,
    second: PlayedReview,
    pricing_first: _Pricing,
    pricing_second: _Pricing,
    lower: set[int],
    answered: Mapping[int, str],
    *,
    prefix_difference: int,
) -> list[ReplayRound]:
    """Price every recorded round in both passes (contracts/replay.md section 4)."""
    by_step = {item.recorded.step: item for item in classes}
    played_first = {(r.turn, r.index): r for r in first.rounds}
    played_second = {(r.turn, r.index): r for r in second.rounds}
    cache_first: dict[tuple[int, bool], int] = {}
    cache_second: dict[tuple[int, bool], int] = {}
    rounds: list[ReplayRound] = []
    conversation = _Conversation.of(recording)
    for turn in recording.turns:
        conversation.begin(turn)
        for recorded_round in turn.rounds:
            recorded_input = recorded_round.usage.input_tokens or 0
            items = [by_step[call.step] for call in recorded_round.calls]
            calls = [
                ReplayCall(
                    step=i.recorded.step,
                    tool=i.recorded.tool,
                    class_="answered_from_checks" if i.index in answered else i.class_,
                    reason=answered.get(i.index, i.reason),
                )
                for i in items
            ]
            if recorded_round.kind == "presentation":
                rounds.append(
                    ReplayRound(
                        turn=turn.index,
                        round=recorded_round.index,
                        kind="presentation",
                        recorded_input=recorded_input,
                        as_recorded_input=recorded_input,
                        requested_input=recorded_input,
                        estimated=False,
                        lower_bound=False,
                        calls=calls,
                    )
                )
                continue
            key = (turn.index, recorded_round.index)
            fixed = conversation.fixed
            a, b = played_first.get(key), played_second.get(key)
            as_recorded = (
                fixed + _results_tokens(a, pricing_first, cache_first)
                if a is not None
                else recorded_input
            )
            requested_input = (
                fixed + prefix_difference + _results_tokens(b, pricing_second, cache_second)
                if b is not None
                else recorded_input
            )
            rounds.append(
                ReplayRound(
                    turn=turn.index,
                    round=recorded_round.index,
                    kind="main",
                    recorded_input=recorded_input,
                    as_recorded_input=as_recorded,
                    requested_input=requested_input,
                    estimated=any(i.class_ == "estimated" for i in items),
                    lower_bound=any(i.index in lower for i in items)
                    or (conversation.words_unknown and turn.index > 0),
                    calls=calls,
                )
            )
            conversation.add_output(recorded_round.usage.output_tokens or 0)
        conversation.end(turn)
    return rounds


@dataclass
class _Conversation:
    """The part of each request that is not a tool result, walking the recorded turns.

    `R0`, the recorded outputs of the model's earlier main rounds, and the engineer's words
    (`contracts/replay.md` section 4, terms 1 to 3): a round sees the outputs of the turns
    committed before its own and of its own turn's earlier rounds; a stopped or failed turn
    leaves none of its outputs behind for the next (rule 7). The strict figure and the
    regrouped estimate walk it the same way, so the two can differ only by their rounds.
    """

    base: int
    words: int = 0
    words_unknown: bool = False
    """A later turn's words were not observable, so they count as zero (rule 7)."""
    outputs: int = 0
    committed_outputs: int = 0

    @classmethod
    def of(cls, recording: Recording) -> _Conversation:
        return cls(base=recording.turns[0].main_rounds[0].usage.input_tokens or 0)

    def begin(self, turn: RecordedTurn) -> None:
        if turn.index > 0:
            self.words += turn.user_tokens or 0
            self.words_unknown = self.words_unknown or turn.user_tokens is None
        self.outputs = self.committed_outputs

    @property
    def fixed(self) -> int:
        return self.base + self.outputs + self.words

    def add_output(self, tokens: int) -> None:
        self.outputs += tokens

    def end(self, turn: RecordedTurn) -> None:
        if turn.end_reason not in UNCOMMITTED_ENDS:
            self.committed_outputs = self.outputs


# --- the regrouped estimate (User Story 4, contracts/replay.md section 6) ----------------------


def _regroup_rules(requested: EfficiencySettings) -> tuple[RegroupRule, ...]:
    """The regrouping rules whose condition `requested` meets: R with checks first, M with
    parallel tool calls."""
    rules: list[RegroupRule] = []
    if checks_first(requested):
        rules.append("R")
    if requested.parallel_tool_calls:
        rules.append("M")
    return tuple(rules)


def _regroup(
    recording: Recording,
    classes: Sequence[_Classified],
    answered: Mapping[int, str],
    *,
    drop_answered: bool,
    merge: bool,
) -> tuple[tuple[RegroupedRound, ...], ...]:
    """Each recorded turn's rounds with calls, regrouped by rule R and then rule M.

    Rule R (`drop_answered`) drops every call the requested pass's guard answered from the
    pre-run; a round left with no call disappears. Rule M (`merge`) then merges each run of
    consecutive rounds of one turn whose calls all name one tool into one round holding
    those calls in recorded order - never a call the replay could not run (estimated or
    stored in pass A), and never across a turn. Consecutive means after rule R: two rounds
    of one tool that a dropped check separated are merged, because the model the estimate
    assumes never made the call between them. The closing round of a turn asks for no call
    and is kept as it is by the pricing.
    """
    by_step = {item.recorded.step: item for item in classes}
    by_index = {item.index: item for item in classes}
    turns: list[tuple[RegroupedRound, ...]] = []
    for turn in recording.turns:
        rounds: list[RegroupedRound] = []
        for recorded_round in turn.main_rounds:
            calls = tuple(
                by_step[call.step].index
                for call in recorded_round.calls
                if not (drop_answered and by_step[call.step].index in answered)
            )
            if not calls:
                continue
            here = RegroupedRound(sources=(recorded_round,), calls=calls)
            if merge and rounds and _one_batch((*rounds[-1].calls, *calls), by_index):
                earlier = rounds[-1]
                rounds[-1] = RegroupedRound(
                    sources=earlier.sources + here.sources, calls=earlier.calls + here.calls
                )
            else:
                rounds.append(here)
        turns.append(tuple(rounds))
    return tuple(turns)


def _one_batch(calls: Sequence[int], by_index: Mapping[int, _Classified]) -> bool:
    """Rule M's condition: every call names one tool, and the replay ran each of them."""
    items = [by_index[index] for index in calls]
    return len({item.recorded.tool for item in items}) == 1 and all(
        item.class_ not in ("estimated", "stored") for item in items
    )


def _regrouped_plans(
    plans: Sequence[TurnPlan], turns: Sequence[Sequence[RegroupedRound]], calls: int
) -> list[TurnPlan]:
    """The recorded plans with each turn's rounds replaced by its regrouped rounds."""
    scripted = [call for plan in plans for round_calls in plan.rounds for call in round_calls]
    if len(scripted) != calls:
        raise AssertionError(
            f"the plans script {len(scripted)} calls where the recording classes {calls}"
        )
    return [
        replace(plan, rounds=tuple(tuple(scripted[i] for i in r.calls) for r in rounds))
        for plan, rounds in zip(plans, turns, strict=True)
    ]


def _regrouped_estimate(
    recording: Recording,
    regrouped: RegroupedPass | None,
    requested: _Pricing,
    *,
    prefix_difference: int,
) -> Regrouped | None:
    """Price the regrouped script as the strict figure prices pass B (section 4).

    Each regrouped round's output is its recorded rounds' outputs together; a round rule R
    emptied is gone with its output, because the model never answered it. A call the replay
    could not run keeps pass B's pricing, under its new position in the script. The closing
    round and every carried presentation round are priced as the strict figure prices them.
    """
    if regrouped is None:
        return None
    kept = [index for rounds in regrouped.turns for r in rounds for index in r.calls]
    pricing = _Pricing(
        view=requested.view,
        estimates={
            position: requested.estimates[index]
            for position, index in enumerate(kept)
            if index in requested.estimates
        },
        stored={
            position: requested.stored[index]
            for position, index in enumerate(kept)
            if index in requested.stored
        },
    )
    played = {(r.turn, r.index): r for r in regrouped.played.rounds}
    cache: dict[tuple[int, bool], int] = {}
    conversation = _Conversation.of(recording)
    total = count = 0
    for turn, rounds in zip(recording.turns, regrouped.turns, strict=True):
        conversation.begin(turn)
        main = turn.main_rounds
        priced = [r.sources for r in rounds]
        if main and not main[-1].calls:
            priced.append((main[-1],))
        for position, sources in enumerate(priced):
            round_ = played.get((turn.index, position))
            total += (
                conversation.fixed
                + prefix_difference
                + _results_tokens(round_, pricing, cache)
                if round_ is not None
                else sources[0].usage.input_tokens or 0
            )
            conversation.add_output(sum(s.usage.output_tokens or 0 for s in sources))
        carried = [r for r in turn.rounds if r.kind == "presentation"]
        total += sum(r.usage.input_tokens or 0 for r in carried)
        count += len(priced) + len(carried)
        conversation.end(turn)
    return Regrouped(
        assumption=REGROUPED_ASSUMPTION, rules=list(regrouped.rules), rounds=count, total=total
    )


def _totals(rounds: Sequence[ReplayRound]) -> ReplayTotals:
    recorded = sum(r.recorded_input for r in rounds)
    requested = sum(r.requested_input for r in rounds)
    return ReplayTotals(
        recorded=recorded,
        as_recorded=sum(r.as_recorded_input for r in rounds),
        requested=requested,
        difference=requested - recorded,
        estimated_rounds=sum(1 for r in rounds if r.estimated),
        lower_bound_rounds=sum(1 for r in rounds if r.lower_bound),
        carried_rounds=sum(1 for r in rounds if r.kind == "presentation"),
    )


def subject_of(key: SubjectKey) -> str:
    """A finding's subject key, without its check, as one line a person can read."""
    _, components, locations, inputs, configuration = key
    parts: list[str] = []
    if components:
        parts.append("components " + ", ".join(components))
    for document_id, sheet, view, annotation, page in locations:
        where = [document_id] + [
            f"{label} {value}"
            for label, value in (
                ("sheet", sheet),
                ("view", view),
                ("annotation", annotation),
                ("page", page),
            )
            if value is not None
        ]
        parts.append("at " + " ".join(str(item) for item in where))
    if inputs:
        parts.append("inputs " + ", ".join(inputs))
    parts.append(f"configuration {configuration}")
    return "; ".join(parts)


def _judged_group(finding: Finding) -> tuple[str, str] | None:
    """`(group key, configuration)` of a recorded interference finding, or `None`.

    The group key is read from the recorded calculation's inputs, where the interference
    check writes it; a finding of another check, or one that carries no group key, names no
    group and can never be matched to a contact.
    """
    if finding.check != INTERFERENCE_CHECK or finding.calculation is None:
        return None
    group_key = finding.calculation.inputs.get("group_key")
    if not isinstance(group_key, str):
        return None
    return group_key, finding.configuration


def _contacts_by_group(session: ReviewSession) -> dict[tuple[str, str], list[Contact]]:
    """The requested pass's contacts by `(group key, configuration)`, in the order recorded."""
    contacts: dict[tuple[str, str], list[Contact]] = {}
    for contact in session.contacts:
        contacts.setdefault((contact.group_key, contact.configuration), []).append(contact)
    return contacts


def _findings(
    recording: Recording,
    classes: Sequence[_Classified],
    second: PlayedReview,
    answered: Mapping[int, str],
) -> ReplayFindings:
    """Compare the recorded and requested findings as multisets (contracts/replay.md §5).

    A recorded interference finding whose group the requested pass judged a contact is
    reclassified first, whatever its step's class: the contact says what became of it, which
    is more than "not replayable" can. Each contact reclassifies one recorded finding, so the
    comparison stays a multiset. A finding of a step the requested pass answered from checks
    is compared against the whole requested session - the pre-run wrote it there - even
    when pass A had to estimate the step, and a missing one is lost.
    """
    by_step = {item.recorded.step: item for item in classes}
    unmatched_contacts = _contacts_by_group(second.session)
    reclassified: list[ReclassifiedFinding] = []
    not_replayable: list[NotReplayableFinding] = []
    replayable: Counter[SubjectKey] = Counter()
    recorded_all: Counter[SubjectKey] = Counter()
    for item in recording.findings:
        key = finding_subject_key(item.finding)
        recorded_all[key] += 1
        group = _judged_group(item.finding)
        if group is not None and unmatched_contacts.get(group):
            contact = unmatched_contacts[group].pop(0)
            reclassified.append(
                ReclassifiedFinding(
                    check=item.finding.check,
                    subject=subject_of(key),
                    step=item.step,
                    group_key=contact.group_key,
                    contact_id=contact.id,
                )
            )
            continue
        step_class = by_step.get(item.step) if item.step is not None else None
        if (
            step_class is not None
            and step_class.class_ in ("estimated", "stored")
            and step_class.index not in answered
        ):
            not_replayable.append(
                NotReplayableFinding(
                    check=item.finding.check,
                    subject=subject_of(key),
                    step=item.step,
                    reason=step_class.reason or "its step could not be replayed offline",
                )
            )
        else:
            replayable[key] += 1
    replayed = Counter(finding_subject_key(finding) for finding in second.session.findings)
    return ReplayFindings(
        recorded=len(recording.findings),
        replayed=len(second.session.findings),
        lost=_listed(replayable - replayed),
        added=_listed(replayed - recorded_all),
        not_replayable=not_replayable,
        reclassified=reclassified,
    )


def _listed(keys: Counter[SubjectKey]) -> list[ReplayFinding]:
    return [
        ReplayFinding(check=key[0], subject=subject_of(key))
        for key in sorted(keys.elements(), key=lambda key: (key[0], subject_of(key)))
    ]


def _levers(settings: PassSettings) -> str:
    on = [name for name, value in settings.efficiency.model_dump().items() if value is True]
    return ", ".join(on) if on else "every lever off"


def _model_view(settings: PassSettings) -> str:
    view = settings.model_view
    age = view.prune_after_rounds
    parts = (["payload slimming"] if view.payload_slimming else []) + (
        [f"history pruning after {age} round{'' if age == 1 else 's'}"]
        if view.history_pruning
        else []
    )
    return "model view " + (", ".join(parts) if parts else "off")


def render_replay_lines(report: ReplayReport) -> list[str]:
    """The human output, in the order `contracts/replay.md` section 7 gives."""
    lines = [
        f"replay of {report.run_dir}",
        f"provider {report.provider}; tokens counted with {report.tokenizer}; "
        f"{report.comparison} comparison; {report.framing_tokens} framing tokens per result",
        f"as recorded: {_levers(report.settings.as_recorded)}; "
        f"{_model_view(report.settings.as_recorded)}",
        f"requested: {_levers(report.settings.requested)}; "
        f"{_model_view(report.settings.requested)}",
        f"{'turn':>4} {'round':>5} {'recorded':>12} {'as recorded':>12} {'requested':>12}  flags",
    ]
    for r in report.rounds:
        flags = []
        if r.kind == "presentation":
            flags.append("carried")
        if r.estimated:
            flags.append("estimated")
        if r.lower_bound:
            flags.append("lower bound")
        if any(c.class_ == "changed" for c in r.calls):
            flags.append("changed")
        if any(c.class_ == "stored" for c in r.calls):
            flags.append("stored")
        if any(c.class_ == "answered_from_checks" for c in r.calls):
            flags.append("answered from checks")
        lines.append(
            f"{r.turn:>4} {r.round:>5} {r.recorded_input:>12,} {r.as_recorded_input:>12,} "
            f"{r.requested_input:>12,}  {', '.join(flags)}".rstrip()
        )
    totals = report.totals
    lines.append(
        f"totals: recorded {totals.recorded:,}; as recorded {totals.as_recorded:,}; "
        f"requested {totals.requested:,}; difference {totals.difference:+,}"
    )
    lines.append(
        f"rounds: {totals.estimated_rounds} estimated, {totals.lower_bound_rounds} lower bound, "
        f"{totals.carried_rounds} carried"
    )
    if report.regrouped is not None:
        regrouped = report.regrouped
        lines.append(
            f"regrouped estimate (rule {', '.join(regrouped.rules)}): {regrouped.total:,} over "
            f"{regrouped.rounds} rounds, assuming {regrouped.assumption}"
        )
    priced = [c for r in report.rounds for c in r.calls if c.class_ != "reproduced"]
    for call in priced:
        lines.append(f"  step {call.step} {call.tool}: {call.class_} - {call.reason}")
    findings = report.findings
    lines.append(
        f"findings: {findings.recorded} recorded, {findings.replayed} replayed, "
        f"{len(findings.lost)} lost, {len(findings.added)} added, "
        f"{len(findings.not_replayable)} not replayable offline, "
        f"{len(findings.reclassified)} reclassified as contacts"
    )
    lines += [f"  lost: {item.check} - {item.subject}" for item in findings.lost]
    lines += [f"  added: {item.check} - {item.subject}" for item in findings.added]
    lines += [
        f"  not replayable: {item.check} - {item.subject} (step {item.step}: {item.reason})"
        for item in findings.not_replayable
    ]
    lines += [
        f"  reclassified: {item.check} - {item.subject} (contact {item.contact_id})"
        for item in findings.reclassified
    ]
    return lines
