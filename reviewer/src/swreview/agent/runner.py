"""The agent loop: one review of one evidence package, start to saved session.

The loop belongs to this module. A provider adapter (`agent/providers`) runs exactly one
turn - streaming text, dispatching tool calls, mapping its own errors - and hands back a
`TurnResult`; everything around that turn is here, because none of it is provider
business:

- the system prompt: the versioned commitments in `prompts/system_v1.md`, the mandatory
  checklist rendered as text, and the package census, so the model starts oriented;
- a **per-turn** step budget. `max_steps` bounds the tool calls of one turn, not of the
  session (data-model section 3, rule 4): a resumed turn never no-ops because an earlier
  turn spent the budget. The cumulative count is kept separately, on the run;
- the event stream: one `EventSink` stamps `seq` and `at`, appends every event to
  `events.jsonl` and fans it out to listeners, so the pane, the CLI and the file all see
  the same ordered stream (`contracts/chat-events.schema.json`). The sink, its usage
  ledger, the step-budget default, the redactor hand-off and how a turn that raised is
  reported live in `agent/events.py` because the re-modeler's own loop shares them; they
  are imported here and re-exported, so every caller that predates the move still reads
  them off this module. The sentence a turn cut short is closed out with is shared the same
  way, from `report/session.py`, beside the predicate that reads it back;
- multi-turn. `ReviewRun.continue_session` appends an engineer turn and runs it, even on a
  session that already ended, and `ReviewRun.answer_evidence` answers an open request and
  resumes. A check re-run after its request is answered replaces the earlier verdict
  rather than adding a second one (rule 3);
- finalization: every evidence request still open and every checklist item still open
  becomes `unresolved` coverage before the session is written (FR-010, FR-019).
  `finalize_session` **rebuilds** what it wrote last time instead of appending to it, so
  finalizing twice is finalizing once (rule 1), and it runs on the failure path too, so
  `ended_at` is never left null (rule 5, FR-008);
- the two US3 hooks on the context: the `exceptions.json` beside the package, loaded when
  it is there, and the live SOLIDWORKS bridge when the run asked for one. Both are wired
  here and nowhere else, so the tools only ever see them through `ToolContext`.

`provider` is injected rather than built, so the whole loop is testable without a network
call or an API key: `providers.fake.FakeProvider` plays a script. `bridge_factory` is
injectable for the same reason: `--bridge` needs a workstation, a unit test does not.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from swreview.agent.checklist import FINDING_BUCKET, Checklist, load_checklist
from swreview.agent.events import (
    DEFAULT_MAX_STEPS,
    EVENTS_FILE_NAME,
    EventListener,
    EventSink,
    UsageLedger,
    emit_turn_failed,
    no_redaction,
    utc_now,
)
from swreview.agent.package_brief import package_brief
from swreview.agent.providers import (
    AgentProvider,
    EffortLevel,
    PromptCacheAware,
    ProviderTool,
    ToolCallResult,
    ToolSet,
    TurnResult,
)
from swreview.agent.providers.schema import ToolSpec
from swreview.agent.settings import EfficiencySettings, ExtractionSettings, checks_first
from swreview.bridge.client import DEFAULT_PIPE_NAME, BridgeClient
from swreview.carry_over import carry_over_findings, stamp_carry_over_keys
from swreview.checks.rms.registry import RMS_FAMILY
from swreview.exceptions import EXCEPTIONS_FILE_NAME, ExceptionStore
from swreview.findings import Finding
from swreview.ir.loader import LoadedPackage, load_package
from swreview.ir.models import EvidencePackage
from swreview.prerun import PrerunResult, attach_standards, gate_brief, prerun_checks
from swreview.report.attention import rank
from swreview.report.attention_record import write_attention_record
from swreview.report.explanations import (
    explanation_signature,
    fill_fallbacks,
    generate_explanations,
)
from swreview.report.session import (
    CLOSEOUT_CHECK,
    CoverageItem,
    CoverageScope,
    EvidenceRequest,
    KeySource,
    ProviderInfo,
    ReviewSession,
    cut_short_reason,
    save_session,
)
from swreview.tools.context import ToolContext, build_context
from swreview.tools.query import package_summary
from swreview.tools.registry import ToolRegistry

SYSTEM_PROMPT_FILE = Path(__file__).parent / "prompts" / "system_v1.md"
SESSION_FILE_NAME = "session.json"

EVIDENCE_CHECK = "coverage.evidence_request"
PROFILE_CHECK = "coverage.extractor_profile"

REDUCED_PROFILE_SKIPPED = (
    "the evidence was written by the {profile!r} dump profile: the {phases} phases were "
    "never run, so {arrays} are empty because nothing read them - not because this design "
    "has none. Extract full evidence and review again to cover anything that depends on "
    "them (FR-022)."
)
"""Why a reduced package cannot answer the checks that read the phases it skipped.

One template for every reduced profile, not one sentence per profile name (FR-037): the
profile is the package's own, and so are the phases, so a third reduced profile needs no
edit here. With `model_check`'s four skipped phases substituted in, it renders feature 003's
sentence byte for byte, which four unedited test modules read.
"""

GEOMETRY_PHASES: tuple[str, ...] = ("hole", "fastener", "face", "body")
"""The four phases **every** reduced profile switches off (`DumpProfile`).

The floor, and only the floor: a package that recorded no phase rows at all - written before
schema 1.3.0, or by a build that timed nothing - is still a reduced package, and saying
nothing about what it skipped is the silence this coverage item exists to break. A package
that does record its phases is read instead of this.
"""

STANDARDS_EVIDENCE_PHASES: tuple[str, ...] = ("cutlist", "drawing")
"""The phases a dump runs only when it was asked for standards evidence.

They are the reason this is not simply "every skipped row". A real package records a row for
**every** phase the extractor knows, skipped ones included (`PackageWriter.PhaseLog.Rows()`),
so a `model_check` dump reports these two as skipped exactly as it reports the geometry four -
and naming them would rewrite feature 003's sentence on every package the workstation writes,
which FR-037 forbids. A dump that ran neither of them was never asked for standards evidence,
so what it does not carry is not evidence its profile withheld; a dump that ran one and
skipped the other **was** asked, and the half it did not get - a standards dump of a part,
which has no drawing - is exactly what the sentence exists to name.

Phases, not profile names (FR-037): a third reduced profile is read the same way, by what its
package's rows say it ran, and needs no entry anywhere.
"""

FULL_PROFILE_ONLY_PHASES: tuple[str, ...] = ("tolerance",)
"""The phases only a `full` dump runs and no reduced-profile check reads.

`tolerance` (schema 1.5.0, feature 010) reads the part documents' dimension tolerances and
GTols for the joint checks, and every reduced profile skips it with the geometry phases
(`PackageWriter`). What a review of a reduced package misses because of it is already named
by the `hole` phase the sentence names - the joint checks read nothing without holes - so
naming it as well would tell the engineer nothing new and would add a word to feature 003's
sentence on every real package the workstation writes, which FR-037 forbids.

Dropped from the answer always, where the standards-evidence phases are dropped only when the
package ran neither: a phase that ran is never reported skipped anyway, so the condition
would say nothing for a single phase.
"""

PHASE_WORDS: dict[str, tuple[str, str]] = {
    "cutlist": ("cut list", "cut lists"),
    "drawing": ("drawing", "drawings"),
    "hole": ("hole", "holes"),
    "fastener": ("fastener", "fasteners"),
    "face": ("face", "faces"),
    "body": ("body or mesh", "bodies"),
}
"""How a phase is named in the sentence, and what its evidence is called there.

`body` is the pair that has to be written down: the phase writes bodies *or* meshes and the
array is `bodies`, and the two halves of the sentence therefore differ. Every other phase a
reduced profile can skip is here for the same reason - so the sentence reads as English
rather than as a field name - with an unnamed phase falling back to its own name.
"""

OPENING_MESSAGE = (
    "Review the evidence package described in the system prompt. Work through the "
    "checklist, gather evidence with the query tools before you judge anything, and "
    "close out every checklist item with a finding or a coverage entry. When you are "
    "done, summarize what you found and what is still unresolved."
)

ANSWER_MESSAGE = (
    "Evidence request {request_id} is answered: {answer}\n\n"
    "Re-run the check you named in that request's `why` using this answer and record one "
    "verdict for it. Your earlier entry for that check is replaced, not duplicated. Then "
    "close out anything the answer unblocks."
)

TOOL_NOTES_HEADER = "## Tool notes"
"""The heading lever 2's moved paragraphs land under, named so a test can look for it."""

TOOL_NOTES_LEAD = (
    "Call notes for the tools below. Each tool's own description is its first paragraph; "
    "everything else it used to say is here, once, rather than on every tool of every "
    "request. Read a tool's notes before calling it for the first time."
)


def build_system_prompt(
    checklist: Checklist,
    package: EvidencePackage,
    tools: Iterable[ToolSpec] = (),
    *,
    efficiency: EfficiencySettings | None = None,
) -> str:
    """The versioned prompt, the checklist, the package census, and the tool notes.

    The last of those is lever 2's other half and is rendered **only** when
    `trim_tool_descriptions` is on: the paragraphs the tool descriptions no longer carry
    arrive here once per session instead of once per tool per request. With the flag off
    the prompt is byte for byte what feature 001 built, which is what lets one commit run
    both arms of the A/B (FR-039, SC-007).

    Args:
        checklist: The review checklist, rendered under its own heading.
        package: The package under review, rendered as the census.
        tools: The specs the adapter is about to be handed, in the order it gets them, so
            the notes follow the tool list rather than a second copy of it. Lever 4 will
            hand over fewer; the block must shrink with them.
        efficiency: The run's lever flags. `None` - every caller that predates the lever -
            is read as every lever off.
    """
    sections = [
        SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip(),
        "## Review checklist\n\n" + checklist.render(),
        "## This package\n\n```json\n" + json.dumps(package_summary(package), indent=2) + "\n```",
    ]
    if efficiency is not None and efficiency.trim_tool_descriptions:
        notes = tool_notes_block(tools)
        if notes:
            sections.append(notes)
    return "\n\n".join(sections)


def tool_notes_block(tools: Iterable[ToolSpec]) -> str:
    """The `## Tool notes` section, or `""` when no tool handed over has any notes.

    One heading per tool that has notes and nothing at all for a tool that does not: a
    heading over an empty block tells the model there was something it did not get.
    """
    entries = [f"### {spec.name}\n\n{spec.notes}" for spec in tools if spec.notes]
    if not entries:
        return ""
    return "\n\n".join([TOOL_NOTES_HEADER, TOOL_NOTES_LEAD, *entries])


def _unresolved(
    session: ReviewSession,
    check: str,
    reason: str,
    *,
    component_ids: Iterable[str] = (),
    document_ids: Iterable[str] = (),
) -> CoverageItem:
    """Append one `unresolved` coverage item and hand it back to whoever wrote it.

    The item is returned so a caller that may have to withdraw it later - finalization,
    which rebuilds its own items on every call - can identify exactly the ones it wrote.
    """
    item = CoverageItem(
        check=check,
        scope=CoverageScope(
            component_ids=list(component_ids),
            document_ids=list(document_ids),
        ),
        reason=reason,
        error=None,
    )
    session.coverage.unresolved.append(item)
    return item


def record_partial_evidence(session: ReviewSession, package: EvidencePackage) -> None:
    """Record what the dump profile never extracted, before the first turn (FR-022, FR-037).

    A reduced package carries some of the phases and not others: a `model_check` package
    carries documents, mates, features and equations, and a `standards` one adds cut lists
    and, for a drawing root, drawings. Reviewed as if it were a full extract, either reads
    as a design with no holes, no fasteners and no geometry - the one reading of a partial
    package that is worse than no reading at all - so the review says up front which phases
    were skipped, in the same coverage the report already renders rather than in a new
    channel nobody reads.

    **Any** reduced profile, and the phases from the **package's own rows** (FR-037). The
    guard used to be `profile != "model_check"`, which a `standards` package passes, so it
    would have been reviewed as full evidence; and the phases used to be a literal four,
    which is right for one profile and wrong for the next. A profile name is not a list of
    phases, and the package already records which of its phases never ran.

    Written here rather than on the `POST /sessions` route (T084) so the command line
    gets it too: `swreview review` over a check folder is the same partial evidence, and
    two places deciding what a profile means would be two answers to one question.

    A `full` package is untouched, which is why every feature 001 and 002 golden is
    byte-identical after this.
    """
    if package.extractor.profile == "full":
        return

    skipped = _skipped_phases(package)
    session.coverage.skipped.append(
        CoverageItem(
            check=PROFILE_CHECK,
            scope=CoverageScope(),
            reason=REDUCED_PROFILE_SKIPPED.format(
                profile=package.extractor.profile,
                phases=_sentence([PHASE_WORDS.get(name, (name, name))[0] for name in skipped]),
                arrays=_sentence(
                    [PHASE_WORDS.get(name, (name, name + "s"))[1] for name in skipped]
                ),
            ),
            error=None,
        )
    )


def _skipped_phases(package: EvidencePackage) -> list[str]:
    """Which phases this package records as never having run, in the order it ran them.

    `skipped` and not `failed`: a failed phase threw, was recorded as a gap and the dump
    carried on, so its evidence is missing for a reason the gaps already name
    (`DumpPhase.status`). Only `skipped` means the profile or the options switched it off.

    The standards-evidence phases are dropped from the answer unless the package ran one of
    them, because every dump records a row for every phase and a `model_check` package
    therefore reports them skipped alongside the geometry four; see
    `STANDARDS_EVIDENCE_PHASES` for why that is not this sentence's business. The full-only
    phases are dropped always; see `FULL_PROFILE_ONLY_PHASES`.
    """
    recorded = [
        phase.name
        for phase in package.extractor.phases
        if phase.status == "skipped" and phase.name not in FULL_PROFILE_ONLY_PHASES
    ]
    ran = {phase.name for phase in package.extractor.phases if phase.status != "skipped"}
    if ran.isdisjoint(STANDARDS_EVIDENCE_PHASES):
        recorded = [name for name in recorded if name not in STANDARDS_EVIDENCE_PHASES]
    return recorded or list(GEOMETRY_PHASES)


def _sentence(words: Sequence[str]) -> str:
    """`a`, `a and b`, `a, b and c`: the list as it is read out loud."""
    if len(words) < 2:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def load_exceptions(loaded: LoadedPackage) -> ExceptionStore | None:
    """The `exceptions.json` beside `package.json`, or `None` when there is none.

    Absent is the normal case and means "no condition has been accepted for this design";
    the check tools then report every condition they find. A file that is there but
    unreadable raises rather than being skipped: an exception the reviewer silently
    dropped would re-raise something an engineer already accepted (FR-013).
    """
    path = loaded.base_dir / EXCEPTIONS_FILE_NAME
    if not path.is_file():
        return None
    return ExceptionStore(path).load()


def open_evidence_requests(session: ReviewSession) -> list[EvidenceRequest]:
    """The requests still waiting for an engineer's answer.

    One enumeration with two readers: finalization, which turns each of them into
    `unresolved` coverage, and lever 7's `coverage_complete`, for which a single open
    request means the review is not finished. Copied rather than shared, the two would
    part company the first time `status` grew a third value.
    """
    return [request for request in session.evidence_requests if request.status == "open"]


def finalize_session(
    context: ToolContext,
    started: datetime,
    *,
    written: list[CoverageItem] | None = None,
) -> ReviewSession:
    """Close out the session: open requests, open checklist items, timing, end time.

    Called whether the turn ended normally, ran out of steps, was truncated, or blew up:
    a session is never written with an item that quietly went nowhere, and `ended_at` is
    never left null (data-model section 3, rule 5).

    Args:
        context: The run's tool context; its `session` is the one being closed out.
        started: When the session started, for the unattended-runtime timing.
        written: The items a previous finalization of this same session appended. They
            are withdrawn by identity before the new ones are computed, and the list is
            updated in place, which is what makes a second finalization produce the same
            coverage rather than a duplicate of it (rule 1). Items *anything else* wrote -
            a `mark_coverage` call, a truncated or cut-short turn - are never touched.
            Pass the same list on every call; omitting it finalizes as a one-shot.
    """
    review = context.session
    previous = written if written is not None else []
    review.coverage.unresolved[:] = [
        item for item in review.coverage.unresolved if all(item is not stale for stale in previous)
    ]
    previous.clear()

    for request in open_evidence_requests(review):
        previous.append(
            _unresolved(
                review,
                EVIDENCE_CHECK,
                f"{request.id} is still open: {request.what}",
                component_ids=[
                    entity_id
                    for entity_id in request.entity_ids
                    if context.component(entity_id) is not None
                ],
            )
        )
    for item in context.checklist.open_items(review):
        previous.append(
            _unresolved(
                review,
                item.id,
                f"{item.title}: the review ended without a finding or a coverage entry for it",
            )
        )

    stamp_carry_over_keys(
        review,
        context.ir,
        efficiency=review.efficiency if review.efficiency is not None else EfficiencySettings(),
    )

    ended = datetime.now(UTC)
    review.ended_at = ended
    review.timing = review.timing.replace(
        unattended_runtime_minutes=(ended - started).total_seconds() / 60.0
    )
    return review


# --- lever 7: the coverage-driven stop ---------------------------------------------------


STOP_CLOSING_BUCKETS: frozenset[str] = frozenset({FINDING_BUCKET, "checked"})
"""The only two ways an item is closed **for the purpose of stopping early** (OQ-5)."""

COVERAGE_STOP_KEY = "coverage_stop"
"""Where the sentence below rides on the tool result that closed the last item."""

COVERAGE_STOP_SENTENCE = (
    "Coverage is complete: every checklist item is closed by a finding or by a checked "
    "coverage entry, and no evidence request is open. The tools are withdrawn for the "
    "rest of this turn - write your closing summary now."
)
"""What the model is told alongside the last call's result, so the withdrawal is not a
silent one: it reads the sentence and writes its summary rather than trying a call that
the request will not permit."""


def coverage_complete(checklist: Checklist, session: ReviewSession) -> bool:
    """Has this review actually finished? Lever 7's stop predicate (FR-070, FR-071).

    True when no evidence request is open and every checklist item is closed **by a
    finding or by a `checked` coverage entry**. Both halves read exactly the state
    finalization reads - `open_evidence_requests` is literally the same function - because
    finalization's whole job is to enumerate these two sets, and a second enumeration
    would drift.

    **The bucket rule is deliberately stricter than `Checklist.open_items`, and the two
    must not be merged.** `bucket_of` searches `("checked", "skipped", "unresolved",
    "out_of_scope")`, and for *finalizing* that is right: an item closed any way is
    closed, and the report says in which bucket. For *stopping early* it is not - a review
    that skipped six of nine items has not finished, it has given up - and lever 7 acts on
    the answer by taking the tools away, so a loose predicate would freeze the give-up in
    place and pay it back as a short, cheap run in the results table (RK-7). The strict
    rule makes the lever fire less often and save less, which is the correct trade.
    """
    if open_evidence_requests(session):
        return False
    return all(
        checklist.bucket_of(item, session) in STOP_CLOSING_BUCKETS for item in checklist.items
    )


class CoverageStopTools:
    """The run's `ToolSet` with one question asked after each call: is the review finished?

    Lever 7, and built only when `EfficiencySettings.coverage_stop` is on - with the flag
    off the adapter is handed the `ToolDispatch` itself and nothing anywhere behaves
    differently (FR-039). The tool boundary is the only seam inside a turn, because
    `provider.run` does not return until the model stops, which is the same seam
    `chat/server.py`'s `StoppableTools` uses for the Stop button.

    **It answers the call instead of raising, and that difference is the design.**
    `StoppableTools` raises out of `call`, which leaves the triggering `function_call`
    with no `function_call_output`; Stop gets away with that because the engineer
    abandoned the turn, and coverage completion does not - a history missing an output is
    rejected on the next request (`openai_provider.py` module docstring), so the session
    could never be continued or have an evidence request answered, which is precisely what
    `continue_session` and `answer_evidence` exist to do. So the call is answered, the
    answer carries `COVERAGE_STOP_SENTENCE` saying why it is the last one, and the adapter
    withdraws the tools for the **next** round through `providers.tools_withdrawn`.

    The latch is per **turn**: `reopen()` is called at the top of every turn, because an
    answered evidence request or a follow-up question arrives at a session whose checklist
    is already closed, and a latch that outlived the turn would hand the engineer a model
    that can no longer look anything up - `continue_session` broken in a quieter way than
    raising would break it.
    """

    def __init__(self, tools: ToolSet, checklist: Checklist, session: ReviewSession) -> None:
        self.tools = tools
        self.checklist = checklist
        self.session = session
        self._withdrawn = False

    def __iter__(self) -> Iterator[ProviderTool]:
        return iter(self.tools)

    def __len__(self) -> int:
        return len(self.tools)

    def tools_withdrawn(self) -> bool:
        """`providers.WithdrawableTools`: may the next round of this turn call a tool?"""
        return self._withdrawn

    def reopen(self) -> None:
        """Put the tools back on the wire for a new turn. See the class docstring."""
        self._withdrawn = False

    def call(self, name: str, arguments: Mapping[str, Any], call_id: str = "") -> ToolCallResult:
        """Dispatch the call, then ask whether it was the one that finished the review.

        Asked after the call and never before it, because the call that closes the last
        checklist item is the one whose result the model is owed.
        """
        result = self.tools.call(name, arguments, call_id)
        if self._withdrawn or not coverage_complete(self.checklist, self.session):
            return result
        self._withdrawn = True
        # The sentence is this lever's annotation on the result, not the tool's own
        # output, so the `InvestigationStep` the tool layer already recorded keeps saying
        # what the tool returned. What the model was handed is on the stream, in this
        # call's `tool.finished`, and in the session history the next request echoes.
        return result.model_copy(
            update={"payload": {**result.payload, COVERAGE_STOP_KEY: COVERAGE_STOP_SENTENCE}}
        )


# --- one verdict per check --------------------------------------------------------------


def _verdict_key(finding: Finding) -> tuple[Any, ...]:
    """What makes two findings two verdicts on the *same* thing rather than two findings.

    A check, the component instances it judged, the drawing places it read, and the
    configuration it judged them in. Two drawing findings on different sheets, or the same
    check on different components, have different keys and both stand.
    """
    return (
        finding.check,
        tuple(finding.component_ids),
        tuple(
            (
                location.document_id,
                location.sheet,
                location.view,
                location.annotation,
                location.page,
            )
            for location in finding.drawing_locations
        ),
        finding.configuration,
    )


def _reconcile_reruns(session: ReviewSession, before: int) -> list[Finding]:
    """Fold a re-run check's new finding onto the one it re-judges (rule 3).

    `before` is how many findings the session held when the answer went in; everything
    after it came out of the resumed turn. A new finding whose verdict key matches an
    earlier one takes that finding's id and replaces it in place, so the report shows one
    verdict per check in its original position instead of two contradictory ones. A new
    finding that matches nothing is simply a new finding.

    Only findings from a turn that an answered evidence request started are reconciled:
    inside one ordinary turn, two calls to the same check are the model's own doing and
    are left exactly as it recorded them.

    Returns the folded findings in their final form. The tool layer already announced each
    of them under the id it was allocated, so the caller re-announces it under the id it
    was folded onto: the stream's last word on a finding id is then the verdict
    `session.json` holds.
    """
    previous = list(session.findings[:before])
    added = list(session.findings[before:])
    by_key = {_verdict_key(finding): index for index, finding in enumerate(previous)}
    kept: list[Finding] = []
    folded: list[Finding] = []
    for finding in added:
        index = by_key.get(_verdict_key(finding))
        if index is None:
            kept.append(finding)
            continue
        previous[index] = finding.model_copy(update={"id": previous[index].id})
        folded.append(previous[index])
    session.findings[:] = [*previous, *kept]
    return folded


# --- one review in flight ----------------------------------------------------------------


class ReviewRun:
    """One review: the session, the provider, the message history and the event stream.

    Built by `start_review`, played by `start`, and kept alive afterwards so the engineer
    can send a follow-up (`continue_session`) or answer an evidence request
    (`answer_evidence`). Every one of those runs a turn and finalizes, so `session.json`
    on disk is current after each of them.
    """

    def __init__(
        self,
        *,
        context: ToolContext,
        provider: AgentProvider,
        tools: ToolSet,
        system: str,
        sink: EventSink,
        out_dir: Path,
        effort: EffortLevel,
        max_steps: int,
        efficiency: EfficiencySettings | None = None,
        opening_message: str = OPENING_MESSAGE,
        bridge: Any | None = None,
        redact: Callable[[str], str] = no_redaction,
    ) -> None:
        self.context = context
        self.provider = provider
        self.tools = tools
        self.system = system
        self.opening_message = opening_message
        """What `start()` says first: `OPENING_MESSAGE`, with lever 5's digest or lever 11's
        brief above it (`_opening_message`).

        A per-package digest belongs here and not in `system`, which is the cacheable
        prefix: anything per-package put into the system prompt invalidates that prefix for
        the whole session (contracts/levers.md, lever 3). The gate's brief carries the
        session's ranked findings, which is even more per-package than the digest, so the
        same rule puts it in the same place (FR-029).
        """
        self.sink = sink
        self.out_dir = Path(out_dir)
        self.effort = effort
        self.max_steps = max_steps
        self.efficiency = efficiency if efficiency is not None else EfficiencySettings()
        """Which efficiency levers this run has on; every one of them off by default."""
        self.redact = redact
        """Applied to provider error text before it is written to `events.jsonl`."""
        self.messages: list[dict[str, Any]] = []
        self.total_steps = 0
        """Tool calls across every turn of this session. `max_steps` bounds one turn."""
        self.turns = 0
        self.started = context.session.started_at
        self._bridge = bridge
        self._finalized: list[CoverageItem] = []
        self._coverage_stop = tools if isinstance(tools, CoverageStopTools) else None
        """Lever 7's wrapper when this run has it, `None` when it does not.

        Held by identity, once, rather than asked for with `isinstance` per turn: the pane
        replaces `run.tools` with its own Stop wrapper after construction
        (`chat/server.py`), and a per-turn check on `self.tools` would then stop finding
        the one object that has to be reopened.
        """
        self.usage_ledger = UsageLedger()
        """What this session has cost so far, accumulated off the stream.

        Registered on the sink here rather than passed in, so every `ReviewRun` has one
        and there is no construction site that can forget it. It is attached before the
        first turn runs, so no round can arrive before it is listening.
        """
        sink.add_listener(self.usage_ledger)
        self._explanation_allowed = False
        self._pending_turn_end: str | None = None
        self.check_presentation_cancelled: Callable[[], None] = lambda: None

    @property
    def session(self) -> ReviewSession:
        session = self.context.session
        if session is None:  # pragma: no cover - build_context always makes one
            raise ValueError("a review run needs a tool context with a review session")
        return session

    @property
    def session_path(self) -> Path:
        return self.out_dir / SESSION_FILE_NAME

    @property
    def events_path(self) -> Path:
        return self.out_dir / EVENTS_FILE_NAME

    # --- turns --------------------------------------------------------------------

    def start(self) -> ReviewSession:
        """Play the opening turn.

        `session.started` is already on the stream: `start_review` emits it, because setup
        itself writes events - `record_partial_evidence` writes coverage, lever 11a writes
        carried findings, and lever 5's pre-run writes whole tool calls - and
        `session.started` is the first line of every `events.jsonl`.
        """
        return self._say(self.opening_message)

    def continue_session(self, text: str) -> ReviewSession:
        """Append an engineer turn and run it.

        Accepted on a session whose previous turn already ended: the review goes back to
        running and is finalized again afterwards (FR-006, US1 scenarios 4 and 5).
        """
        return self._say(text)

    def answer_evidence(self, request_id: str, answer: str) -> ReviewSession:
        """Answer an open evidence request and resume the review on the answer.

        The request stops being open, so finalization no longer reports it as unresolved
        (rule 2), and a check the resumed turn re-runs replaces its earlier verdict rather
        than adding a second one (rule 3).
        """
        request = next(
            (item for item in self.session.evidence_requests if item.id == request_id), None
        )
        if request is None:
            known = [item.id for item in self.session.evidence_requests]
            raise ValueError(f"no evidence request {request_id!r} in this session; open: {known}")
        if request.status != "open":
            raise ValueError(f"evidence request {request_id} is already answered")

        request.status = "answered"
        request.answer = answer
        request.answered_at = utc_now()
        self.sink.emit("evidence.answered", {"request_id": request_id, "answer": answer})

        before = len(self.session.findings)
        self._ask(ANSWER_MESSAGE.format(request_id=request_id, answer=answer))
        for finding in _reconcile_reruns(self.session, before):
            self.sink.emit("finding", finding.model_dump(mode="json"))
        return self.finalize()

    def finalize(self) -> ReviewSession:
        """Close the session out, write `session.json` and `attention.json`, and say so.

        The record is written here, from the finalized session, rather than beside
        whichever caller renders `report.md`: `finalize` runs on the failure path too
        (`_run_turn`), and a run that ended badly is exactly the one an engineer needs the
        ranking of. It writes only what `rank` derives from the session just saved, so the
        folder never holds a record naming a session it no longer has (research R2.7).
        """
        session = self.session
        ranking = rank(session)
        if session.explanations_enabled and ranking.rows and ranking.empty_reason is None:
            signature = explanation_signature(session, self.context.ir)
            if signature != session.finding_explanation_fingerprint:
                session.finding_explanations.clear()
                generated: dict[str, str] = {}
                if self._explanation_allowed:
                    offset = self.usage_ledger.current_round_count

                    def presentation_usage(event_type: str, body: dict[str, Any]) -> None:
                        self.sink.emit(
                            event_type, {**body, "round_index": offset + body.get("round_index", 0)}
                        )

                    generated = generate_explanations(
                        self.provider,
                        ranking.rows[: ranking.top_n],
                        effort="low",
                        on_usage=presentation_usage,
                        session=session,
                        package=self.context.ir,
                        check_cancelled=self.check_presentation_cancelled,
                    )
                    # One attempt per evidence fingerprint. A stopped/failed review that
                    # never attempted presentation may try on a later successful turn.
                    session.finding_explanation_fingerprint = signature
                session.finding_explanations.update(generated)
            fill_fallbacks(session, ranking.rows[: ranking.top_n])
        elif not ranking.rows or ranking.empty_reason is not None:
            session.finding_explanations.clear()
            session.finding_explanation_fingerprint = None

        # The closing request belongs to the same engineering turn. End that turn after
        # its usage, and measure runtime after it, so neither cost nor waiting disappears.
        if self._pending_turn_end is not None:
            reason = self._pending_turn_end
            self._pending_turn_end = None
            self.sink.emit("turn.ended", {"reason": reason})
        session = finalize_session(self.context, self.started, written=self._finalized)
        ranking = rank(session)
        # Before `save_session`, and recomputed from the whole ledger on every call, the
        # same rule finalization itself follows: finalizing twice is finalizing once.
        session.usage = self.usage_ledger.usage()
        save_session(session, self.session_path)
        write_attention_record(self.out_dir, ranking, session.session_id)
        ended_at = session.ended_at
        body: dict[str, Any] = {
            "ended_at": ended_at.isoformat() if ended_at is not None else None,
            "timing": session.timing.model_dump(mode="json"),
        }
        if session.usage is not None:
            # Optional in the contract, so a run with nothing to report says nothing. It
            # is here at all so the pane does not have to own a second summing rule.
            body["usage"] = session.usage.model_dump(mode="json")
        self.sink.emit("session.ended", body)
        return session

    def close(self) -> None:
        """Release what the run holds open. Only the live bridge needs it today."""
        if self._bridge is not None:
            self._bridge.close()
            self._bridge = None

    def cancel_presentation(self) -> None:
        """An external failure/Stop already closed the turn; finalization must be local."""
        self._explanation_allowed = False
        self._pending_turn_end = None

    # --- internals ----------------------------------------------------------------

    def _ask(self, text: str) -> TurnResult:
        """Append an engineer turn and run it. The caller decides when to finalize."""
        self.messages.append({"role": "user", "content": text})
        return self._run_turn()

    def _say(self, text: str) -> ReviewSession:
        self._ask(text)
        return self.finalize()

    def _run_turn(self) -> TurnResult:
        """One provider turn, its budget, and how it ended.

        A turn that fails is still an ended session: the error is reported, the turn is
        closed out, the session is finalized and written, and only then does the exception
        travel on to the caller, who decides whether to retry (FR-008, FR-028).
        """
        self.turns += 1
        self.session.ended_at = None
        self._explanation_allowed = False
        self._pending_turn_end = None
        if self._coverage_stop is not None:
            # Lever 7: the withdrawal lasts one turn. A follow-up question, or an answered
            # evidence request, arrives at a session whose checklist is already closed and
            # must still be able to look things up (`CoverageStopTools`).
            self._coverage_stop.reopen()
        try:
            result = self.provider.run(
                system=self.system,
                messages=self.messages,
                tools=self.tools,
                effort=self.effort,
                max_steps=self.max_steps,
                on_event=self.sink.emit,
            )
        except Exception as exc:
            # The redaction, the `error_body` shape and the `turn.ended` that closes the
            # turn are `agent/events.py`'s, shared with the re-model run (004 T106); what
            # is this run's own is what follows - finalize, then re-raise.
            self._explanation_allowed = False
            emit_turn_failed(self.sink, exc, self.redact)
            self.finalize()
            raise

        self.messages = [dict(message) for message in result.messages]
        self._explanation_allowed = result.reason == "end"
        self.total_steps += result.steps
        cut_short = cut_short_reason(result.reason, self.max_steps)
        if cut_short is not None:
            self._closeout(cut_short)
        if self.session.explanations_enabled:
            self._pending_turn_end = result.reason
        else:
            self.sink.emit("turn.ended", {"reason": result.reason})
        return result

    def _closeout(self, reason: str) -> None:
        """Record why this turn stopped short, and say so on the stream.

        The items *finalization* writes are not announced this way: it rebuilds them on
        every call (rule 1), so announcing each rebuild would put the same item on the
        stream once per turn. `session.ended` and `session.json` carry the closing
        coverage; a `coverage` event means something was just decided.
        """
        item = _unresolved(self.session, CLOSEOUT_CHECK, reason)
        self.sink.emit("coverage", {"bucket": "unresolved", "item": item.model_dump(mode="json")})


# --- entry points ---------------------------------------------------------------------


def start_review(
    package_dir: Path | str,
    out_dir: Path | str,
    *,
    provider: AgentProvider,
    model: str | None = None,
    effort: EffortLevel = "high",
    key_source: KeySource = "none",
    retry_of: str | UUID | None = None,
    max_steps: int = DEFAULT_MAX_STEPS,
    efficiency: EfficiencySettings | None = None,
    previous_session: Path | str | None = None,
    standards_profile: Path | str | None = None,
    fail_tool: Iterable[str] = (),
    bridge: bool = False,
    pipe_name: str = DEFAULT_PIPE_NAME,
    bridge_secret: str | None = None,
    bridge_factory: Callable[[str, str | None], Any] | None = None,
    callbacks: Iterable[EventListener] = (),
    redact: Callable[[str], str] = no_redaction,
    explain_findings: bool = False,
) -> ReviewRun:
    """Prepare a review of `package_dir` writing into `out_dir`; play it with `start()`.

    Nothing is sent to the provider here. The package is loaded, the tools are bound, the
    session records who is about to run it, and the event file is prepared - so a caller
    that wants the turns one at a time (the pane) and a caller that wants the whole review
    (`run_review`) share every line of setup.

    Args:
        package_dir: Directory holding `package.json`.
        out_dir: Directory `session.json` and `events.jsonl` are written to.
        provider: The adapter that runs each turn. Constructed by the caller, so no
            provider SDK is imported by a run that does not use one.
        model: Model id; the provider's own model when omitted. Never defaulted to a
            literal here - `agent/settings.py` owns the per-provider default (FR-026).
        effort: What the engineer asked for. The adapter maps it or fails fast; the
            mapping it chose is recorded on the session and in `session.started`.
        key_source: Where the provider's key came from, for the session record. `none`
            means the run needed no key, which is the truth for the scripted provider.
        explain_findings: Opt into one bounded presentation request for the top findings
            after a successful turn. The pane enables it; offline/check callers stay local.
        retry_of: The failed session this run replaces (FR-028), or None.
        max_steps: Tool-call budget for **one turn**. Hitting it is unresolved coverage,
            not a finish.
        efficiency: Which efficiency levers this run has on (feature 005). One object for
            all ten flags, recorded whole on the session so the run can be attributed to
            a configuration afterwards; `None` means every lever off, which is what is
            recorded.
        previous_session: The `session.json` of an earlier review of this design, for
            lever 11a to carry unchanged `rms.*` verdicts from. Read only when
            `efficiency.carry_over_rms` is on; a path that is not there raises, because a
            run that silently carried nothing would be an off arm wearing an on label.
        standards_profile: The standards profile this design is graded against, so the
            sixteen release checks run inside the review (FR-027). `None` - the default,
            and every caller that predates lever 11 - attaches no standards run, and
            `check_standards` is then not registered at all. A profile that cannot be
            used, or a package that was not dumped with the standards phases, is a
            not-evaluated line and never a refusal: see `prerun.attach_standards`.
        fail_tool: Tool names forced to fail; the `--fail-tool` test hook. An unknown
            name raises.
        bridge: Open the live SOLIDWORKS bridge and add the three bridge tools (US3).
            Needs `SwReview.Extractor.Console.exe serve` running on this workstation.
        pipe_name: Named pipe the bridge listens on.
        bridge_secret: The per-launch secret the in-process tool service requires on every
            request (contracts/README.md). `None` for the console host, which asks for
            none; the pane passes the review-session secret from `POST /sessions`.
        bridge_factory: Builds the bridge client from the pipe name and the secret - the
            session's whole `bridge` config - and defaults to
            `swreview.bridge.client.BridgeClient`, which takes them in that order. It is
            injectable for tests and for the `--fail-bridge` hook.
        callbacks: Live listeners on the event stream, called after each event is
            written. The pane's SSE fan-out is one; a test collecting events is another.
        redact: Masks the run's API key out of provider error text before it is written
            to `events.jsonl` (FR-015). The caller that resolved the key builds it;
            `no_redaction` is the default because a run may legitimately have no key.
    """
    loaded = load_package(package_dir)
    checklist = load_checklist()
    chosen_model = model if model is not None else provider.model
    effort_mapping = provider.effort_mapping(effort)

    bridge_client = None
    if bridge:
        factory = bridge_factory if bridge_factory is not None else BridgeClient
        bridge_client = factory(pipe_name, bridge_secret)
    out = Path(out_dir)
    try:
        # Before the context, which needs `emit`: what a tool writes is on the stream from
        # the first tool call, not from the end of the turn (FR-013).
        sink = EventSink(out / EVENTS_FILE_NAME, listeners=callbacks)
        context = build_context(
            loaded,
            model=chosen_model,
            checklist=checklist,
            exceptions=load_exceptions(loaded),
            bridge=bridge_client,
            emit=sink.emit,
        )
        session = context.session
        if session is None:  # pragma: no cover - build_context always makes one
            raise ValueError("build_context returned a context without a review session")
        session.provider_info = ProviderInfo(
            provider=str(provider.name),
            model=chosen_model,
            effort_mapping=effort_mapping,
            key_source=key_source,
        )
        session.retry_of = UUID(str(retry_of)) if retry_of is not None else None
        session.efficiency = efficiency if efficiency is not None else EfficiencySettings()
        if checks_first(session.efficiency):
            # Feature 008: a review that runs its checks first shows the modelling-practice
            # findings as one folded group. A plain session value, set once here, so the
            # ranking and the report read it without importing a setting (research R2.21).
            session.folded_families = [RMS_FAMILY.name]
        session.explanations_enabled = explain_findings
        # Lever 10a, read here rather than in the tool: `extraction` is a statement about
        # where this run's evidence comes from, and the one place the lever is turned into
        # that statement is `ExtractionSettings.for_efficiency`.
        context.extraction = ExtractionSettings.for_efficiency(session.efficiency)
        if session.efficiency.prompt_cache_key and isinstance(provider, PromptCacheAware):
            # Lever 3, read **once**, here: a flag re-read per turn could change the
            # request mid-session, and the cache key is the one thing that must not move
            # while the session lasts. The session id rather than anything this process
            # made up, because the pane restarts the backend on a settings save and
            # resumes this same run folder (contracts/levers.md, lever 3).
            provider.use_prompt_cache(str(session.session_id))
        # The stream opens before anything is written to it. Everything below this line
        # emits - partial evidence writes coverage, lever 11a writes carried findings, and
        # lever 5's pre-run writes a tool call, two findings and coverage of its own - and
        # `session.started` first is the one ordering rule `events.jsonl` has: the pane
        # opens a session on it and `benchmark/scorecard.py::seconds_to_first_finding`
        # counts no finding before it. It is emitted here rather than in `ReviewRun.start()`
        # for that reason, and a run with every lever off is unchanged by the move, because
        # setup wrote nothing between the two places.
        sink.emit(
            "session.started",
            {
                "session_id": str(session.session_id),
                "package_id": str(session.package_id),
                "provider": str(provider.name),
                "model": chosen_model,
                "effort_mapping": effort_mapping.model_dump(mode="json"),
            },
        )
        record_partial_evidence(session, loaded.package)
        carry_over_findings(
            context,
            previous_session=previous_session,
            efficiency=session.efficiency,
        )
        # Before the dispatch and after the context, which is the only window there is:
        # `ToolRegistry._offered` registers `check_standards` when the context carries a
        # standards run, and the tool array it builds never changes again for the life of
        # the session (research R2.11, and lever 3's prefix guarantee). What comes back is
        # `None` when the run is attached, and otherwise the one family the pre-run counts
        # instead - never an exception, because a review is not lost over one of sixteen.
        # Under checks first a review with no profile reports the family with its reason
        # (feature 008 US2 scenario 3), which supersedes 007 FR-030 for lever 5.
        standards_gap = (
            attach_standards(context, standards_profile)
            if standards_profile is not None or checks_first(session.efficiency)
            else None
        )
        tools = ToolRegistry().dispatch(context, fail_tool=fail_tool, efficiency=session.efficiency)
        # Lever 5, and the last thing setup does: the checks that enumerate themselves run
        # here, through the dispatch the provider is about to be handed, so their steps,
        # findings and events are the ones a model-driven call would have produced. `None`
        # with the flag off, and then nothing above is different either.
        prerun = prerun_checks(
            context,
            tools,
            efficiency=session.efficiency,
            standards=standards_gap,
            package_dir=loaded.base_dir,
            out_dir=out,
        )
        # A configured standards profile is review coverage even when the optional
        # pre-run/gate levers are off.  `prerun_checks` records this family when it runs;
        # keep the same CoverageItem on the ordinary path so a failed profile cannot
        # disappear from session.json and report.md.
        if standards_gap is not None and prerun is None:
            context.record_coverage("skipped", standards_gap.coverage_item())
        if session.steps:
            # Setup wrote steps - today only the pre-run does - so the adapter numbers its
            # own calls from there rather than from 0. `tool.started.step_index` identifies
            # an `InvestigationStep`, which is what the pane keys its tool cards on and what
            # `Finding.tool_result_ids` is joined to; a counter that restarted would point
            # the model's first call at the pre-run's card.
            provider.start_steps_at(len(session.steps))
        # Lever 7, and the last decision setup makes: after the pre-run, because the
        # pre-run is not a turn and has no next round to withdraw anything from. With the
        # flag off the adapter is handed the dispatch itself, so nothing in this module or
        # in either adapter takes a different path (FR-039).
        offered: ToolSet = tools
        if session.efficiency.coverage_stop:
            offered = CoverageStopTools(tools, checklist, session)
    except Exception:
        if bridge_client is not None:
            bridge_client.close()
        raise

    return ReviewRun(
        context=context,
        provider=provider,
        tools=offered,
        system=build_system_prompt(
            checklist,
            loaded.package,
            [tool.spec for tool in tools],
            efficiency=session.efficiency,
        ),
        sink=sink,
        out_dir=out,
        effort=effort,
        max_steps=max_steps,
        efficiency=session.efficiency,
        opening_message=_opening_message(
            prerun,
            session,
            loaded.package,
            standards_gap=standards_gap if standards_profile is not None else None,
        ),
        bridge=bridge_client,
        redact=redact,
    )


def _opening_message(
    prerun: PrerunResult | None,
    session: ReviewSession,
    package: EvidencePackage | None = None,
    *,
    standards_gap: Any | None = None,
) -> str:
    """The first user message: the opening instruction, and what the pre-run put above it.

    The one branch between lever 5 and lever 11, and it is **here** rather than inside
    `PrerunResult` so that `digest()` renders the same bytes whichever lever ran the
    pre-run (FR-030). With the gate on the brief replaces the digest as the body - the
    brief's own first part is that digest - and the opening instruction still closes the
    message, exactly as it does with lever 5 alone.

    The ranking is computed from the session the pre-run has just finished writing, which
    is the same `rank(session)` the report is rendered with at the end of the run: the
    ranked ids the model is handed and the ranked ids the engineer reads come off one
    function over one session (FR-031).
    """
    parts: list[str] = []
    if package is not None:
        parts.append(package_brief(package, standards_gap=standards_gap))
    if prerun is not None:
        gated = session.efficiency is not None and session.efficiency.procedural_gate
        parts.append(gate_brief(prerun, rank(session)) if gated else prerun.digest())
    parts.append(OPENING_MESSAGE)
    return "\n\n".join(parts)


def run_review(
    package_dir: Path | str,
    out_dir: Path | str,
    *,
    provider: AgentProvider,
    model: str | None = None,
    effort: EffortLevel = "high",
    **options: Any,
) -> ReviewSession:
    """Review the package in `package_dir` and write `session.json` into `out_dir`.

    The one-shot form: one opening turn, then finalize, then release the bridge. A caller
    that wants to keep talking to the session - the pane, which sends follow-ups and
    answers evidence requests - calls `start_review` and holds on to the `ReviewRun`.

    Args:
        package_dir: Directory holding `package.json`.
        out_dir: Directory `session.json` and `events.jsonl` are written to.
        provider: The adapter that runs the turn.
        model: Model id; the provider's own model when omitted.
        effort: What the engineer asked for; the adapter maps it or fails fast.
        options: The rest of `start_review`'s keyword arguments - `key_source`,
            `retry_of`, `max_steps`, `efficiency`, `previous_session`,
            `standards_profile`, `fail_tool`, `bridge`, `pipe_name`, `bridge_secret`,
            `bridge_factory`, `callbacks`, `redact` - documented there rather than
            restated here.
    """
    run = start_review(
        package_dir, out_dir, provider=provider, model=model, effort=effort, **options
    )
    try:
        return run.start()
    finally:
        run.close()
