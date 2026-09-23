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

import json
import re
import shutil
import tempfile
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
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
from swreview.agent.settings import EfficiencySettings
from swreview.benchmark.recording import (
    UNCOMMITTED_ENDS,
    RecordedCall,
    RecordedRound,
    Recording,
    read_recording,
)
from swreview.checks.interference import CHECK as INTERFERENCE_CHECK
from swreview.findings import Finding, SubjectKey, finding_subject_key
from swreview.ir.loader import PACKAGE_FILE_NAME
from swreview.prerun import ALREADY_RUN
from swreview.report.session import Contact, ReviewSession
from swreview.tokens import TOKENIZER_NAME, count_tokens, encoding
from swreview.tools.registry import (
    BRIDGE_TOOL_FUNCTIONS,
    COMPACT_QUERY_TOOL_FUNCTIONS,
    REMODEL_TOOL_FUNCTIONS,
    TOOL_FUNCTIONS,
    standards_tools,
)

__all__ = [
    "EMPTY_EXPLANATIONS",
    "FOLLOW_UP_PLACEHOLDER",
    "CallClass",
    "PlayedCall",
    "PlayedReview",
    "PlayedRound",
    "ReclassifiedFinding",
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
    for turn_index, plan in enumerate(turns):
        start = len(tools.played)
        tools.stop_at = start + plan.calls - 1 if plan.stop_at_last_call else None
        stopped = _drive(run, plan)
        dispatched = tools.played[start:]
        rounds = _rounds_of(turn_index, plan, committed, committed_rounds, dispatched, stopped)
        played.rounds.extend(rounds)
        if not stopped and plan.end_reason not in UNCOMMITTED_ENDS:
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


# --- the replay: two passes, classes, accounting, findings (contracts/replay.md §3 to §7) ------

CallClass = Literal["reproduced", "changed", "estimated", "carried", "answered_from_checks"]
"""How a recorded call was priced. `answered_from_checks` (User Story 2): the requested pass
ran checks first and its re-call guard answered the call from the pre-run. User Story 3 adds
`stored`; `carried` is a presentation round, which has no calls of its own."""

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
    model_view: dict[str, Any] | None = None
    """What the model read of each result; recorded from User Story 3 on, off until then."""


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
    regrouped: None = None
    """The labelled regrouped estimate; User Story 4 fills it."""
    findings: ReplayFindings


def replay(
    run_dir: Path | str,
    *,
    requested: EfficiencySettings,
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
class ReplayPasses:
    """The two played passes of one recording: as recorded (A) and as requested (B)."""

    recording: Recording
    as_recorded: EfficiencySettings
    requested: EfficiencySettings
    first: PlayedReview
    second: PlayedReview
    with_profile: bool


def replay_passes(
    recording: Recording,
    scratch: Path | str,
    *,
    requested: EfficiencySettings,
    standards_profile: Path | str | None = None,
) -> ReplayPasses:
    """Play pass A and pass B of `recording` into `scratch/as-recorded` and `scratch/requested`.

    The folders are the caller's: `replay_recording` hands a temporary one and lets it go;
    an acceptance test keeps it to read what the requested pass wrote. Nothing is written
    anywhere else, and never into the recording's own folder.
    """
    recorded_settings = recording.session.efficiency or EfficiencySettings()
    plans = turn_plans(recording)
    options: dict[str, Any] = {"standards_profile": standards_profile}
    first = play_review(
        recording.run_dir,
        Path(scratch) / "as-recorded",
        plans,
        model=recording.session.model,
        efficiency=recorded_settings,
        **options,
    )
    second = play_review(
        recording.run_dir,
        Path(scratch) / "requested",
        plans,
        model=recording.session.model,
        efficiency=requested,
        **options,
    )
    return ReplayPasses(
        recording=recording,
        as_recorded=recorded_settings,
        requested=requested,
        first=first,
        second=second,
        with_profile=standards_profile is not None,
    )


def replay_recording(
    recording: Recording,
    *,
    requested: EfficiencySettings,
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
    sizes_first, lower = _sizes(recording, first, classes)
    sizes_second = _requested_sizes(first, second, classes, sizes_first, answered)
    rounds = _rounds(
        recording,
        classes,
        first,
        second,
        sizes_first,
        sizes_second,
        lower,
        answered,
        prefix_difference=count_tokens(second.prefix) - count_tokens(first.prefix),
    )
    return ReplayReport(
        run_dir=str(recording.run_dir),
        provider=recording.provider,
        tokenizer=TOKENIZER_NAME,
        comparison="shape" if recording.provider == "gemini" else "exact",
        framing_tokens=FRAMING_TOKENS,
        settings=ReplaySettings(
            as_recorded=PassSettings(efficiency=passes.as_recorded),
            requested=PassSettings(efficiency=passes.requested),
        ),
        rounds=rounds,
        totals=_totals(rounds),
        findings=_findings(recording, classes, second, answered),
    )


@dataclass(frozen=True)
class _Classified:
    """One recorded call, its counterpart in pass A (by position), and its class."""

    index: int
    recorded: RecordedCall
    played: PlayedCall | None
    class_: CallClass
    reason: str | None


def _classify(recording: Recording, first: PlayedReview, with_profile: bool) -> list[_Classified]:
    """Class every recorded call from pass A (contracts/replay.md section 3)."""
    played = [call for played_round in first.rounds for call in played_round.calls]
    classified: list[_Classified] = []
    index = 0
    for turn in recording.turns:
        estimated_at: int | None = None
        for recorded_round in turn.rounds:
            for call in recorded_round.calls:
                counterpart = played[index] if index < len(played) else None
                class_, reason = _class_of(call, counterpart, estimated_at, with_profile)
                if class_ == "estimated" and estimated_at is None:
                    estimated_at = call.step
                classified.append(_Classified(index, call, counterpart, class_, reason))
                index += 1
    return classified


def _class_of(
    recorded: RecordedCall,
    played: PlayedCall | None,
    estimated_at: int | None,
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
    if estimated_at is not None:
        return "estimated", (
            f"its result differs from the recording after the estimated call at step "
            f"{estimated_at}, whose effect a replay cannot reproduce"
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


def _sizes(
    recording: Recording, first: PlayedReview, classes: Sequence[_Classified]
) -> tuple[dict[int, int], set[int]]:
    """Pass A's size of every call, by index, and the indices sized as a lower bound."""
    sizes: dict[int, int] = {}
    for item in classes:
        if item.class_ != "estimated" and item.played is not None:
            sizes[item.index] = count_tokens(item.played.text)
    by_step = {item.recorded.step: item for item in classes}
    lower: set[int] = set()
    for turn in recording.turns:
        for recorded_round in turn.rounds:
            known = {
                call.step: sizes[by_step[call.step].index]
                for call in recorded_round.calls
                if by_step[call.step].index in sizes
            }
            for step, (size, bound) in estimated_sizes(recording, recorded_round, known).items():
                sizes[by_step[step].index] = size
                if bound:
                    lower.add(by_step[step].index)
    return sizes, lower


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


def _requested_sizes(
    first: PlayedReview,
    second: PlayedReview,
    classes: Sequence[_Classified],
    sizes_first: Mapping[int, int],
    answered: Mapping[int, str],
) -> dict[int, int]:
    """Pass B's size of every call: the current code's result, or pass A's estimate.

    A call the guard answered is sized at the guard's answer whatever its pass-A class: the
    answer is what the requested pass really sends, even behind an estimated call.
    """
    played = {call.index: call for r in second.rounds for call in r.calls}
    sizes = dict(sizes_first)
    for item in classes:
        if (item.class_ != "estimated" or item.index in answered) and item.index in played:
            sizes[item.index] = count_tokens(played[item.index].text)
    return sizes


def _rounds(
    recording: Recording,
    classes: Sequence[_Classified],
    first: PlayedReview,
    second: PlayedReview,
    sizes_first: Mapping[int, int],
    sizes_second: Mapping[int, int],
    lower: set[int],
    answered: Mapping[int, str],
    *,
    prefix_difference: int,
) -> list[ReplayRound]:
    """Price every recorded round in both passes (contracts/replay.md section 4)."""
    base = recording.turns[0].main_rounds[0].usage.input_tokens or 0
    by_step = {item.recorded.step: item for item in classes}
    played_first = {(r.turn, r.index): r for r in first.rounds}
    played_second = {(r.turn, r.index): r for r in second.rounds}
    rounds: list[ReplayRound] = []
    committed_outputs = 0
    words = 0
    words_unknown = False
    for turn in recording.turns:
        if turn.index > 0:
            words += turn.user_tokens or 0
            words_unknown = words_unknown or turn.user_tokens is None
        outputs = committed_outputs
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
            fixed = base + outputs + words
            a, b = played_first.get(key), played_second.get(key)
            as_recorded = (
                fixed + sum(sizes_first[c.index] + FRAMING_TOKENS for c in a.visible)
                if a is not None
                else recorded_input
            )
            requested_input = (
                fixed
                + prefix_difference
                + sum(sizes_second[c.index] + FRAMING_TOKENS for c in b.visible)
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
                    or (words_unknown and turn.index > 0),
                    calls=calls,
                )
            )
            outputs += recorded_round.usage.output_tokens or 0
        if turn.end_reason not in UNCOMMITTED_ENDS:
            committed_outputs = outputs
    return rounds


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
            and step_class.class_ == "estimated"
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


def render_replay_lines(report: ReplayReport) -> list[str]:
    """The human output, in the order `contracts/replay.md` section 7 gives."""
    lines = [
        f"replay of {report.run_dir}",
        f"provider {report.provider}; tokens counted with {report.tokenizer}; "
        f"{report.comparison} comparison; {report.framing_tokens} framing tokens per result",
        f"as recorded: {_levers(report.settings.as_recorded)}",
        f"requested: {_levers(report.settings.requested)}",
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
