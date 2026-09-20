"""One re-model run, phase by phase (T117): plan, judge, apply, verify.

The four phases of `plan.md` are four functions here, and `run_remodel` is the composition
the host calls. Nothing in this module decides anything about a part: the planner, the
executor and the gate each own their decision and this module's whole job is the order they
run in, the state the run is recorded at, and the one turn a model gets in the middle.

| Phase | What it does | Who decides |
|---|---|---|
| A `plan_run` | `plan_reorganize` over the copy's dump, filed as revision 1 | the planner, purely |
| B `judge` | one bounded turn over the five proposal tools, then revision 2 | the model proposes |
| C `apply_changes` | every planned change, in the plan's order, to completion | the executor |
| D `verify` | the three checks, the save or the discard, the report | a pure gate |

Five things about phase B are worth stating here, because each of them is a decision
somebody would otherwise have to infer from the code:

**It is one turn, not a conversation.** A rejected proposal comes back inside the same turn
as an error result the model may act on, which is what `contracts/tools.md` means by "a
rejection is a result": the correction loop is the tool loop, and a second turn would be a
second opening message with nothing new to say.

**It never re-opens the order.** A group the model decides is recorded on the target and in
the deviations and is printed in the report; it does **not** re-run the ranking, the order,
the pins, the folders or the moves. That is the owner decision in its own words - the model
proposes into the plan and never orders, moves, rolls back or issues a verdict - and a
re-plan triggered by a model's answer would be the model deciding the order at one remove.
So revision 2 is revision 1 plus what was accepted: descriptions, globals, the groups the
model decided, its deviations, its rejections, and the C2, C5 and C6 changes that carry the
accepted proposals out.

**It is skippable, and its absence is written down.** A plan with no judgement slots - no
blank description, no ambiguous fillet, no unclassified feature, no parameter a global could
be justified by - never constructs a provider at all, and neither does a run given no
provider settings. Every other way the phase can contribute less than a finished turn is
written down as a `PlanCoverage` row under `JUDGEMENT_ITEM`, in its own words: it ran and
proposed nothing, it was skipped, a provider could not be built, it failed, it failed after
N proposals, or it was cut short at the step budget or the provider's output ceiling. An
empty list would read as "nobody looked", and the wrong sentence is worse (Principle VI).

**It survives its model, twice.** Neither constructing the adapter nor running the turn can
end the run: both are caught, reported on the stream and recorded on the plan, and phases C
and D go on. Nothing about a re-model depends on a model having answered, and a run that
threw away a good deterministic plan because a key was unset or a model timed out would be
the wrong failure (FR-045).

**It cannot reach a document.** The judgement context carries no bridge, so no bridge tool
is registered for the turn, and none of the five tools it does get names a document, a path
or a run folder. The `RemodelClient` this module holds is never passed to phase B.

This is also the **one place a remodel run constructs a provider** (`contracts/tools.md`,
"Providers"): `build_provider` asks the registry for the adapter, OpenAI by default and
Gemini as the only alternative. Every other module of `remodel/` is deterministic and a
test asserts none of them reaches the registry.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from swreview.agent import providers
from swreview.agent.events import (
    DEFAULT_MAX_STEPS,
    EVENTS_FILE_NAME,
    EventListener,
    EventSink,
    UsageLedger,
    emit_error,
    emit_turn_failed,
    no_redaction,
    utc_now,
)
from swreview.agent.providers import (
    AgentProvider,
    EffortLevel,
    EventCallback,
    ProviderName,
)
from swreview.agent.runner import SESSION_FILE_NAME
from swreview.agent.settings import (
    DEFAULT_EFFORT,
    DEFAULT_PROVIDER,
    ProviderSettings,
    output_ceiling,
)
from swreview.agent.settings import redact as redact_secrets
from swreview.bridge.remodel_client import RemodelClient
from swreview.checks.rms_types import load_table
from swreview.ir.loader import LoadedPackage
from swreview.ir.models import EvidencePackage, Feature
from swreview.remodel.apply import (
    ApplyResult,
    EquationStepError,
    Verification,
    apply_changes,
    equation_changes,
    open_log,
    verify,
)
from swreview.remodel.artifacts import GradedRun, grade_remodel_run
from swreview.remodel.geometry import GeometryReading
from swreview.remodel.intent import description_gaps, global_candidates
from swreview.remodel.plan import (
    ChangeSubject,
    DescriptionProposal,
    GlobalProposal,
    PlanCoverage,
    PlannedChange,
    PlanTarget,
    RemodelPlan,
    SourceAttestation,
    plan_path,
    plan_reorganize,
    record_state,
    require_runnable_plan,
)
from swreview.remodel.scope import ScopeSignals
from swreview.remodel.tolerances import IDENTITY, Tolerances, require_stage_1
from swreview.remodel.units import DocumentUnitError
from swreview.report.session import (
    ProviderInfo,
    ReviewSession,
    cut_short_reason,
    save_session,
)
from swreview.tools.context import ToolContext, build_context
from swreview.tools.registry import ToolDispatch, ToolRegistry
from swreview.tools.remodel_plan import RemodelToolContext

__all__ = [
    "DEFAULT_PROVIDER",
    "GLOBALS_ITEM",
    "GLOBALS_NOT_WRITTEN",
    "JUDGEMENT_CUT_SHORT",
    "JUDGEMENT_FAILED",
    "JUDGEMENT_FAILED_PARTIAL",
    "JUDGEMENT_ITEM",
    "JUDGEMENT_REGISTRY",
    "JUDGEMENT_SKIPPED",
    "JUDGEMENT_UNAVAILABLE",
    "NOTHING_PROPOSED",
    "OPENING_MESSAGE",
    "PACKAGE_AFTER_FAILED",
    "PACKAGE_AFTER_ITEM",
    "PROMPT_FILE",
    "RemodelRun",
    "build_provider",
    "describe_changes",
    "judge",
    "judgement_context",
    "judgement_slots",
    "judgement_tools",
    "plan_run",
    "revision_two",
    "run_remodel",
    "system_prompt",
]

PROMPT_FILE = Path(__file__).resolve().parents[1] / "agent" / "prompts" / "remodel_v1.md"
"""The judgement phase's system prompt, versioned beside the review's own (T119)."""

OPENING_MESSAGE = (
    "Read the plan with get_remodel_plan, then propose what needs judgement rather than "
    "arithmetic: a description for a feature that has none, a global for a value the "
    "package actually carries, a group for a fillet or for a feature the type table could "
    "not classify. Propose nothing you cannot ground in the plan or the package, and when "
    "there is nothing left worth proposing, say what you proposed and what you left alone."
)

JUDGEMENT_ITEM = "model judgement"
"""The `PlanCoverage.item` every "the judgement phase contributed nothing" row carries."""

NOTHING_PROPOSED = (
    "the judgement phase ran and proposed nothing that was accepted, so every group, name "
    "and order in this plan is the method's"
)

JUDGEMENT_SKIPPED = (
    "the judgement phase did not run: this plan offered nothing that needs judgement, or "
    "the run was given no provider, so no model saw this part"
)

JUDGEMENT_FAILED = (
    "the judgement phase ended in an error and proposed nothing; the deterministic phases "
    "ran unaffected: {error}"
)

JUDGEMENT_FAILED_PARTIAL = (
    "the judgement phase ended in an error after {count} accepted proposal(s), which this "
    "plan carries; the deterministic phases ran unaffected: {error}"
)
"""What a turn that proposed and *then* failed is recorded as.

`JUDGEMENT_FAILED` says the phase proposed nothing, and what was accepted before the
failure is carried into revision 2 either way - the tools wrote it as they accepted it -
so recording the empty sentence over a plan that holds two model descriptions would be the
plan lying about where they came from (FR-020, FR-056, Principle I)."""

JUDGEMENT_UNAVAILABLE = (
    "a model was asked for and could not be built, so no model saw this part; the "
    "deterministic phases ran unaffected: {error}"
)
"""What a run whose provider could not be *constructed* records instead of `JUDGEMENT_SKIPPED`.

Constructing the adapter reaches a vendor SDK - a key that is not set, a package that is
not installed, a base URL nobody can parse - and every one of those raises before there is
a turn to fail. `JUDGEMENT_SKIPPED` would say this plan offered nothing worth judging,
which is the opposite of what happened."""

JUDGEMENT_CUT_SHORT = "the judgement phase was cut short: {reason}"
"""What a turn that ended on `max_steps` or on the provider's output ceiling adds.

It is recorded *beside* whatever `_absence` decided rather than instead of it, because the
two are different facts: what the turn contributed, and whether it got to finish. A turn
cut off mid-proposal that had already had something accepted records no absence at all, so
without this row revision 2 would be indistinguishable from a turn that stopped because it
was done - the "an empty list reads as 'nobody looked'" failure in its other direction
(Principle VI)."""

GLOBALS_ITEM = "global variables"
"""The `PlanCoverage.item` of a global that was accepted and could not be written.

The planner writes its own row under this same item - how many readings could justify a
global, and that a v1 global drives nothing - and that is deliberate: the item names the
subject, and a reader looking up what this run did about globals wants both rows."""

GLOBALS_NOT_WRITTEN = (
    "{count} accepted global(s) are recorded in this plan and were not written into the "
    "copy: {reason}"
)

PACKAGE_AFTER_ITEM = "package-after.json"
"""The `PlanCoverage.item` of a run whose reading after the last change never arrived.

The item is the file, because that is the thing that is missing: the grades, the geometry
comparison and the gate all read it, and a reader looking up why this run has no grades
wants the row under the name of the artifact they went looking for."""

PACKAGE_AFTER_FAILED = (
    "the dump of the copy after the last change did not arrive, so this run was never "
    "verified and never saved; every change it applied is in changes.jsonl: {error}"
)
"""What a run whose `dump_after` raised records before it fails.

The dump is taken by the add-in, in process and on the application thread, and reaches the
run through a rendezvous that can time out; a failure there is an absence of a **reading**
and not of a change, and the sentence says which so that nobody reads a `failed` run as one
whose changes were rolled back."""

SLOT_DESCRIPTIONS = "descriptions"
SLOT_GLOBALS = "globals"
SLOT_FILLETS = "fillets"
SLOT_UNKNOWNS = "unknowns"

_FILLET_DEFAULT = "fillet_default_core"
"""The `Deviation.kind` the planner writes for a fillet it defaulted into `3-Core`; one of
those is a fillet the model may call cosmetic instead (`plan.md` point 14)."""

_NEEDS_JUDGEMENT = "needs_judgement"
"""The `PlanTarget.state` of a feature the type table could not place."""


# --- phase A: the plan ---------------------------------------------------------------


def plan_run(
    run_dir: Path | str,
    package: EvidencePackage,
    *,
    document_id: str | None = None,
    signals: ScopeSignals | None = None,
    probe_id: str | None = None,
    now: datetime | None = None,
) -> RemodelPlan:
    """Plan the reorganize stage and file it as `plan.json` revision 1.

    The arguments are `plan_reorganize`'s, unchanged and undocumented again here: this adds
    the file and nothing else, so a plan read back off disk is exactly what the pure planner
    returned.

    The write is not `record_state`, and cannot be: `planned` is entered from nothing
    (`plan.py::ENTERED_FROM`), because a run that entered it twice would be two runs in one
    folder. Every transition after this one goes through `record_state`.
    """
    plan = plan_reorganize(
        package, document_id=document_id, signals=signals, probe_id=probe_id, now=now
    )
    target = plan_path(run_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return plan


# --- phase B: the one turn a model gets ------------------------------------------------


def build_provider(settings: ProviderSettings) -> AgentProvider:
    """The adapter the judgement phase talks to. **The one construction site of this run.**

    `providers.get` is the registry, and it is the whole of the provider policy: it answers
    for `openai` (the default), `gemini` and `fake`, and raises `UnknownProviderError` for
    every other string, so there is no name a remodel run could be given that reaches a
    fourth vendor.

    The scripted adapter is deliberately not built here. It plays a script, a script belongs
    to whoever wrote it, and a default script invented in the product would make a test pass
    for the fixture's reasons; callers that want it inject their own factory.

    Raises:
        ValueError: `settings` names the scripted provider.
        UnknownProviderError: the registry does not answer for that name.
    """
    adapter = providers.get(settings.provider)
    if settings.provider is ProviderName.FAKE:
        raise ValueError(
            "the scripted provider plays a script, and a remodel run has none to give it; "
            "pass provider_factory= with the script this run should play"
        )
    if settings.provider is ProviderName.GEMINI:
        from google import genai

        return adapter(
            client=genai.Client(**settings.client_kwargs()),
            model=settings.model,
            redact=lambda text: redact_secrets(text, settings.secrets),
            max_output_tokens=output_ceiling(settings.provider, settings.model),
        )
    return adapter(model=settings.model, **settings.client_kwargs())


def system_prompt() -> str:
    """`remodel_v1.md`, read from disk. The prompt is guidance; the tools are the control."""
    return PROMPT_FILE.read_text(encoding="utf-8")


def judgement_slots(plan: RemodelPlan, package: EvidencePackage) -> tuple[str, ...]:
    """What this plan has for a model to judge, by the tool that would answer it.

    Empty means no provider is constructed at all, which is what makes "stage 1's apply loop
    runs with no model in it" a property of the run rather than a claim about it (SC-009).
    Each membership test is the admissibility rule the matching tool enforces, asked of the
    same module the tool asks - `intent.py` for the two proposals, the plan's own targets and
    deviations for the two decisions - so a slot can never disagree with the tool that fills
    it.
    """
    table = load_table()
    rows = _rows(plan, package)
    slots: list[str] = []
    if any(gap.proposable for gap in description_gaps(rows, table)):
        slots.append(SLOT_DESCRIPTIONS)
    if global_candidates(rows, table):
        slots.append(SLOT_GLOBALS)
    if any(item.kind == _FILLET_DEFAULT for item in plan.deviations):
        slots.append(SLOT_FILLETS)
    if any(item.state == _NEEDS_JUDGEMENT for item in plan.targets):
        slots.append(SLOT_UNKNOWNS)
    return tuple(slots)


def judgement_context(
    *,
    plan: RemodelPlan,
    package: EvidencePackage,
    provider: str,
    model: str,
    document_length_unit: str | None = None,
    base_dir: Path | str = ".",
    emit: EventCallback | None = None,
) -> tuple[ToolContext, RemodelToolContext]:
    """The context the five proposal tools read and write, and the plan object behind it.

    Both, because the caller needs both and neither can be recovered from the other without
    a cast: `ToolContext.remodel` is `Any` by design, so that the tool layer does not import
    the re-modeler. `tools/remodel_plan._judgement()` hands back the same pair for the same
    reason.

    **No bridge**, so `ToolRegistry` registers no bridge tool for this turn and there is no
    call on the surface that could reach a document. No exception store either: a waiver is
    about a rule's verdict and this phase reaches no verdict.
    """
    context = build_context(
        LoadedPackage(package=package, base_dir=Path(base_dir)),
        model=model,
        emit=emit,
    )
    remodel = RemodelToolContext(
        plan=plan,
        provider=provider,
        model=model,
        document_length_unit=document_length_unit,
    )
    context.remodel = remodel
    return context, remodel


JUDGEMENT_REGISTRY = ToolRegistry(functions=())
"""The judgement phase's whole tool surface: the five proposal tools and nothing else.

`ToolRegistry` adds them because `context.remodel` is set, which is the registration
condition of `contracts/tools.md`; the curated **review** list is dropped because none of it
belongs to this turn. That is Principle II in its own words - "the model's whole surface is
four `propose_*` tools plus one read-back" - and it is also the reason the phase cannot name
a document: every review query tool takes a `document_id` and this turn is offered none of
them. What the model may read is the plan, through `get_remodel_plan`.
"""


def judgement_tools(context: ToolContext) -> ToolDispatch:
    """The five proposal tools, bound to `context` and recorded into its session."""
    return JUDGEMENT_REGISTRY.dispatch(context)


def judge(
    *,
    run_dir: Path | str,
    plan: RemodelPlan,
    package: EvidencePackage,
    provider: AgentProvider | None,
    sink: EventSink,
    document_length_unit: str | None = None,
    which_configs: int | None = None,
    effort: EffortLevel = DEFAULT_EFFORT,
    max_steps: int = DEFAULT_MAX_STEPS,
    no_provider_reason: str = JUDGEMENT_SKIPPED,
    redact: Callable[[str], str] = no_redaction,
    now: Callable[[], datetime] = utc_now,
) -> RemodelPlan:
    """Run the judgement turn and write revision 2 of the plan. Returns it, in `applying`.

    `provider` of `None` skips the turn: the run goes `planned -> applying` and revision 2 is
    revision 1 plus the coverage row that says the phase contributed nothing (data-model
    section 11). With a provider the run passes through `judging`, which is on disk for as
    long as the turn lasts.

    A provider that raises is **reported and survived**: the error and `turn.ended` reach the
    stream, the session is written, the absence is recorded on the plan, and the
    deterministic phases carry on. Nothing about a re-model depends on a model having
    answered, and a run that threw away a good plan because a model timed out would be the
    wrong failure.

    Args:
        run_dir: The run folder; `plan.json`, `events.jsonl` and `session.json` live here.
        plan: Revision 1, as phase A wrote it.
        package: `package-before.json`, the dump of the copy at open.
        provider: The adapter, already constructed, or `None` to skip the phase.
        sink: The run's event stream. The one stamper of `seq` and `at` and the only writer
            of `events.jsonl`, shared with the review run (`agent/events.py`).
        document_length_unit: `remodel.open`'s reading of the copy (FR-027). `None` refuses
            every global rather than seeding a literal from an assumed metre.
        which_configs: `swInConfigurationOpts_e` as `remodel.open` recorded it. `None`
            blocks every equation add, because a global written into one configuration of
            several is invisible in the others.
        effort: What the engineer asked for; the adapter maps it or fails fast.
        max_steps: Tool calls this turn may make.
        no_provider_reason: The sentence recorded when `provider` is `None`. It defaults to
            "nothing here needed judging, or nobody offered a provider", and the one caller
            that knows better - a run whose provider could not be constructed - says so
            instead, because those are not the same absence.
        redact: Masks the run's key out of provider error text before it is written.
        now: The clock every stamp of this phase comes from.
    """
    folder = Path(run_dir)
    if provider is None:
        return _revision_two(
            folder,
            plan,
            None,
            package=package,
            which_configs=which_configs,
            document_length_unit=document_length_unit,
            absence=no_provider_reason,
            now=now,
        )

    plan = record_state(folder, plan, "judging", at=now())
    context, remodel = judgement_context(
        plan=plan,
        package=package,
        provider=str(provider.name),
        model=provider.model,
        document_length_unit=document_length_unit,
        base_dir=folder,
        emit=sink.emit,
    )
    session = context.session
    if session is None:  # pragma: no cover - build_context always makes one
        raise ValueError("build_context returned a context without a session to record in")
    effort_mapping = provider.effort_mapping(effort)
    session.provider_info = ProviderInfo(
        provider=str(provider.name),
        model=provider.model,
        effort_mapping=effort_mapping,
        key_source="none",
    )
    ledger = UsageLedger()
    sink.add_listener(ledger)
    sink.emit(
        "session.started",
        {
            "session_id": str(session.session_id),
            "package_id": str(session.package_id),
            "provider": str(provider.name),
            "model": provider.model,
            "effort_mapping": effort_mapping.model_dump(mode="json"),
        },
    )

    failure: str | None = None
    cut_short: str | None = None
    try:
        result = provider.run(
            system=system_prompt(),
            messages=[{"role": "user", "content": OPENING_MESSAGE}],
            tools=judgement_tools(context),
            effort=effort,
            max_steps=max_steps,
            on_event=sink.emit,
        )
    except Exception as exc:
        # The redaction, the error's shape on the stream and the `turn.ended` that closes
        # the turn are the review run's too, and are shared with it (T106). What is this
        # run's own is what happens next: it does not re-raise.
        failure = emit_turn_failed(sink, exc, redact)
    else:
        # Both ends that are not a normal stop are recorded, because a turn cut off at the
        # step budget or at the provider's output ceiling is not a turn that had nothing
        # more to say. `cut_short_reason` is the review run's reading of the same reason.
        cut_short = cut_short_reason(result.reason, max_steps)
        sink.emit("turn.ended", {"reason": result.reason})

    _close_session(folder, session, sink, ledger, now=now)
    return _revision_two(
        folder,
        plan,
        remodel,
        package=package,
        which_configs=which_configs,
        document_length_unit=document_length_unit,
        absence=_absence(remodel, failure),
        cut_short=None if cut_short is None else JUDGEMENT_CUT_SHORT.format(reason=cut_short),
        now=now,
    )


def _absence(remodel: RemodelToolContext, failure: str | None) -> str | None:
    """The sentence the plan records about what the turn contributed, or `None`.

    `None` only when the turn both succeeded and had something accepted: what was accepted
    is its own record, and a row beside it would say the phase contributed nothing about a
    plan that carries what it contributed.
    """
    accepted = len(remodel.descriptions) + len(remodel.globals) + len(remodel.targets)
    if failure is not None:
        if accepted:
            return JUDGEMENT_FAILED_PARTIAL.format(count=accepted, error=failure)
        return JUDGEMENT_FAILED.format(error=failure)
    if accepted:
        return None
    return NOTHING_PROPOSED


def _close_session(
    run_dir: Path,
    session: ReviewSession,
    sink: EventSink,
    ledger: UsageLedger,
    *,
    now: Callable[[], datetime],
) -> Path:
    """End the session, write `session.json`, and say so on the stream.

    Not `finalize_session`: that rebuilds a review's checklist coverage, its open evidence
    requests and its findings, none of which a remodel run has. What is shared is the shape
    of the file and the summing rule for what the turn cost, and both are used here.
    """
    session.ended_at = now()
    session.usage = ledger.usage()
    path = save_session(session, run_dir / SESSION_FILE_NAME)
    body: dict[str, Any] = {
        "ended_at": session.ended_at.isoformat(),
        # Required by `chat-events.schema.json`, which is authoritative for a remodel run's
        # stream as much as for a review's (data-model.md section 10). A remodel run records
        # no engineer minutes, so what it carries is the zeroed record `new_session` made.
        "timing": session.timing.model_dump(mode="json"),
    }
    if session.usage is not None:
        body["usage"] = session.usage.model_dump(mode="json")
    sink.emit("session.ended", body)
    return path


# --- revision 2 --------------------------------------------------------------------------


def describe_changes(
    descriptions: Sequence[DescriptionProposal],
    rows: Sequence[Feature],
    *,
    first_seq: int = 1,
) -> tuple[PlannedChange, ...]:
    """C2: one `describe` per accepted description proposal, in the order they were made.

    `params` mirrors `remodel.describe`'s payload exactly, so the executor hands this object
    to the client and composes no second idea of the operation. A proposal whose feature is
    not in the tree is a defect in the tool that accepted it, not a condition of the part, so
    it raises rather than being dropped.
    """
    by_id = {row.id: row for row in rows}
    changes: list[PlannedChange] = []
    for offset, proposal in enumerate(descriptions):
        row = by_id.get(proposal.feature_id)
        if row is None:
            raise ValueError(
                f"the plan describes {proposal.feature_id}, which this document's tree does "
                "not carry; a description proposal is validated against the tree before it "
                "is accepted, so a plan that reaches here with one is a plan nobody can apply"
            )
        changes.append(
            PlannedChange(
                seq=first_seq + offset,
                kind="describe",
                subject_kind="feature",
                subject=ChangeSubject(
                    feature_id=row.id, name=row.name, persist_ref=row.persist_ref
                ),
                params={"persist_ref": row.persist_ref, "text": proposal.text},
                expect={"rebuild_errors_delta": 0},
            )
        )
    return tuple(changes)


def revision_two(
    plan: RemodelPlan,
    remodel: RemodelToolContext | None,
    *,
    package: EvidencePackage,
    which_configs: int | None = None,
    document_length_unit: str | None = None,
    absence: str | None = None,
    cut_short: str | None = None,
) -> RemodelPlan:
    """Revision 1 plus what the judgement phase accepted. Pure: no file, no clock.

    The change list keeps the planner's own order and gains two runs: the descriptions
    between the renames and the reorders (C2), and the equations at the end (C5 then C6).
    Nothing is re-sorted, because the planner's list is already in the fixed order of
    `data-model.md` section 1.11 and re-sorting it would be this module having a second
    opinion about an order it does not own.

    `absence` is the sentence recorded as one `PlanCoverage` row when the phase contributed
    nothing - it ran and proposed nothing, it was skipped, or it failed. `None` records
    nothing, because the accepted proposals are themselves the record.

    `cut_short` is the second row, and a second fact: the turn did not get to finish. It is
    recorded beside `absence` rather than instead of it, since a turn cut off after a
    proposal was accepted records no absence at all.
    """
    rows = _rows(plan, package)
    descriptions = (*plan.descriptions, *(remodel.descriptions if remodel else ()))
    globals_ = (*plan.globals, *(remodel.globals if remodel else ()))
    renames = [change for change in plan.changes if change.kind == "rename"]
    rest = [change for change in plan.changes if change.kind != "rename"]
    described = describe_changes(descriptions, rows)
    equations, unwritable = _equation_changes(
        globals_, document_length_unit=document_length_unit, which_configs=which_configs
    )
    changes = tuple(
        change.model_copy(update={"seq": seq})
        for seq, change in enumerate((*renames, *described, *rest, *equations), start=1)
    )
    coverage = [*plan.coverage]
    if absence is not None:
        coverage.append(PlanCoverage(item=JUDGEMENT_ITEM, reason=absence, feature_ids=()))
    if cut_short is not None:
        coverage.append(PlanCoverage(item=JUDGEMENT_ITEM, reason=cut_short, feature_ids=()))
    if unwritable is not None:
        coverage.append(PlanCoverage(item=GLOBALS_ITEM, reason=unwritable, feature_ids=()))
    # Re-validated rather than `model_copy`d: revision 2 has to pass the plan's own rules -
    # the seq numbers start at 1 with no holes and the change list is in the fixed order -
    # and `model_copy` skips every one of them. The field values go across as the objects
    # they already are, because the model is strict and a dumped `Move` is not a `Move`.
    return RemodelPlan(
        **{
            **dict(plan),
            "plan_revision": 2,
            "targets": _merged_targets(plan, remodel),
            "descriptions": descriptions,
            "globals": globals_,
            "deviations": (*plan.deviations, *(remodel.deviations if remodel else ())),
            "rejected_proposals": (
                *plan.rejected_proposals,
                *(remodel.rejected_proposals if remodel else ()),
            ),
            "changes": changes,
            "coverage": tuple(coverage),
        }
    )


def _equation_changes(
    globals_: Sequence[GlobalProposal],
    *,
    document_length_unit: str | None,
    which_configs: int | None,
) -> tuple[tuple[PlannedChange, ...], str | None]:
    """C5 and C6, or no equation change and the reason there is none.

    The executor refuses to compose an equation it cannot seed honestly: a configuration
    scope nobody read, a document unit nobody read, an evidence row that no longer agrees
    with the metres behind it. Every one of those is a refusal of **the change**, not of the
    run: the plan, the reorder and the folders are unaffected and throwing them away because
    a global could not be seeded would lose good work for an unrelated reason. So the globals
    stay on the plan as the accepted proposals they are, no `equation.add` is composed, and
    the reason is recorded as coverage so the report says they were not written and why.
    """
    if not globals_:
        return (), None
    try:
        return (
            equation_changes(
                repairs=(),
                globals_=globals_,
                document_length_unit=document_length_unit,
                which_configs=which_configs,
            ),
            None,
        )
    except (EquationStepError, DocumentUnitError) as exc:
        return (), GLOBALS_NOT_WRITTEN.format(count=len(globals_), reason=exc)


def _revision_two(
    run_dir: Path,
    plan: RemodelPlan,
    remodel: RemodelToolContext | None,
    *,
    package: EvidencePackage,
    which_configs: int | None,
    document_length_unit: str | None,
    absence: str | None,
    now: Callable[[], datetime],
    cut_short: str | None = None,
) -> RemodelPlan:
    """Compose revision 2 and move the run to `applying`, which writes it to disk."""
    revised = revision_two(
        plan,
        remodel,
        package=package,
        which_configs=which_configs,
        document_length_unit=document_length_unit,
        absence=absence,
        cut_short=cut_short,
    )
    return record_state(run_dir, revised, "applying", at=now())


def _merged_targets(
    plan: RemodelPlan, remodel: RemodelToolContext | None
) -> tuple[PlanTarget, ...]:
    """The partition with the model's decisions **in place of** the planner's, not beside.

    Two targets for one feature is not a partition, and the plan is a partition of the tree
    by construction (`data-model.md` section 1.1). This is the same rule
    `get_remodel_plan("targets")` reads back, so what the model saw is what the plan carries.
    """
    if remodel is None:
        return plan.targets
    decided = {item.feature_id: item for item in remodel.targets}
    return tuple(decided.get(item.feature_id, item) for item in plan.targets)


def _rows(plan: RemodelPlan, package: EvidencePackage) -> list[Feature]:
    """The tree of the one document this plan is about, in package order."""
    return [row for row in package.features if row.document_id == plan.document_id]


# --- phases C and D, and the run they compose ---------------------------------------------


@dataclass(frozen=True)
class RemodelRun:
    """What one run did, phase by phase, and where each phase left its artifacts."""

    run_dir: Path
    plan: RemodelPlan
    """The plan as the last phase left it: revision 2, in its terminal state."""

    judged: bool
    """Whether a model saw this part at all. `False` is recorded on the plan too."""

    slots: tuple[str, ...]
    applied: ApplyResult
    graded: GradedRun
    verification: Verification

    @property
    def events_path(self) -> Path:
        return self.run_dir / EVENTS_FILE_NAME

    @property
    def session_path(self) -> Path:
        return self.run_dir / SESSION_FILE_NAME


def run_remodel(
    *,
    run_dir: Path | str,
    client: RemodelClient,
    plan: RemodelPlan,
    package: EvidencePackage,
    dump_after: Callable[[], EvidencePackage],
    baseline: int,
    before: GeometryReading,
    attestation: SourceAttestation,
    settings: ProviderSettings | None = None,
    provider_factory: Callable[[ProviderSettings], AgentProvider] = build_provider,
    document_length_unit: str | None = None,
    which_configs: int | None = None,
    tolerances: Tolerances = IDENTITY,
    effort: EffortLevel = DEFAULT_EFFORT,
    max_steps: int = DEFAULT_MAX_STEPS,
    run_root: Path | str | None = None,
    callbacks: Iterable[EventListener] = (),
    stop_requested: Callable[[], bool] = lambda: False,
    redact: Callable[[str], str] = no_redaction,
    now: Callable[[], datetime] = utc_now,
) -> RemodelRun:
    """Phases B to D of one run, to completion, and the report at the end of them.

    B to D and not A to D, because the host plans before it starts: `remodel.plan` copies,
    opens, dumps and calls `plan_run`, answers the pane with the plan summary, and only
    `remodel.start` runs this. The run then goes to completion and asks nobody anything;
    there is no approval parameter in this signature and none below it (FR-045).

    Args:
        run_dir: The run folder every artifact of this run is written into.
        client: The `remodel.*` bridge. **Phase B never receives it.**
        plan: Revision 1, from `plan_run`, with the copy and the source recorded on it.
        package: `package-before.json`, the dump of the copy at open.
        dump_after: Takes the `ModelCheck` dump of the copy after the last change. A
            callable and not a package, because it is a reading of the document as the apply
            phase leaves it and cannot be taken before that phase runs.
        baseline: The run's rebuild-error count, read at open before any change.
        before: The `copy_at_open` geometry reading. The source is never opened for the
            comparison in any mode (FR-037); this reading stands for it.
        attestation: The source attestation as `remodel.open` recorded it. Phase D re-checks
            it and writes the completed record.
        settings: Which provider the judgement phase would use. `None` skips the phase.
        provider_factory: Builds the adapter from those settings, and defaults to
            `build_provider`, the one construction site. Injected by tests so no unit test
            needs a key or a network.
        document_length_unit: `remodel.open`'s reading of the copy (FR-027).
        which_configs: `swInConfigurationOpts_e` as `remodel.open` recorded it.
        tolerances: The profile the gate decides under. `IDENTITY`, and it must be
            calibrated before it may decide a run (FR-036).
        effort: What the engineer asked of the model.
        max_steps: Tool calls the judgement turn may make.
        run_root: The run root an earlier run's waivers may be carried forward from.
        callbacks: Live listeners on the event stream.
        stop_requested: The engineer's stop flag, handed straight to `apply_changes`, which
            reads it between changes and finalizes the run as `truncated` (`remodel.stop`).
            Phases B and D never read it: a turn is one turn and the gate is what makes a
            partial run safe to look at, so there is nothing in either worth cutting short.
        redact: Masks the run's key out of provider error text.
        now: The clock every stamp of this run comes from.

    Raises:
        Exception: whatever `dump_after` raised, after this run has been finalized as
            `failed` with the change log intact and the reason recorded on the plan. The
            dump is taken out of process by the add-in, so it can time out or fail outright;
            a run that let that leave `plan.json` saying `applying` would leave a run folder
            nobody could read the state of. The exception itself is re-raised rather than
            swallowed, because whether to tell the engineer "the run failed" or to retry is
            the caller's decision and not this module's.
    """
    # These are pure, local checks. They must precede provider construction, bridge calls,
    # mutation and the after-dump rendezvous, even when a caller bypasses the HTTP route's
    # state check.
    require_runnable_plan(plan)
    require_stage_1(tolerances)
    folder = Path(run_dir)
    slots = judgement_slots(plan, package)
    sink = EventSink(folder / EVENTS_FILE_NAME, listeners=callbacks, clock=now)
    provider: AgentProvider | None = None
    no_provider_reason = JUDGEMENT_SKIPPED
    if settings is not None and slots:
        try:
            provider = provider_factory(settings)
        except Exception as exc:
            # Constructing the adapter reaches a vendor SDK, and a key that is not set, a
            # package that is not installed or a base URL nobody can parse all raise here,
            # before there is a turn to fail. A run that threw away a good deterministic
            # plan because a model could not be built would be the wrong failure, exactly
            # as one that threw it away because a model timed out would be: the failure is
            # reported, the absence is recorded, and phases C and D run (FR-045).
            no_provider_reason = JUDGEMENT_UNAVAILABLE.format(
                error=emit_error(sink, exc, redact)
            )
    plan = judge(
        run_dir=folder,
        plan=plan,
        package=package,
        provider=provider,
        sink=sink,
        document_length_unit=document_length_unit,
        which_configs=which_configs,
        effort=effort,
        max_steps=max_steps,
        no_provider_reason=no_provider_reason,
        redact=redact,
        now=now,
    )

    log = open_log(folder)
    applied = apply_changes(
        client=client,
        log=log,
        changes=plan.changes,
        target_path=str(plan.copy_path),
        baseline=baseline,
        limits=plan.limits,
        stop_requested=stop_requested,
        now=now,
    )
    try:
        after = dump_after()
    except Exception as exc:
        _package_after_failed(folder, plan, exc, sink=sink, redact=redact, now=now)
        raise
    graded = grade_remodel_run(
        folder,
        before=package,
        after=after,
        source_design_id=attestation.source_design_id,
        run_root=run_root,
        document_id=plan.document_id,
    )
    verification = verify(
        client=client,
        log=log,
        run_dir=folder,
        plan=plan,
        applied=applied,
        before=before,
        tolerances=tolerances,
        graded=graded,
        attestation=attestation,
        now=now,
    )
    return RemodelRun(
        run_dir=folder,
        plan=verification.plan,
        judged=provider is not None,
        slots=slots,
        applied=applied,
        graded=graded,
        verification=verification,
    )


def _package_after_failed(
    run_dir: Path,
    plan: RemodelPlan,
    exc: BaseException,
    *,
    sink: EventSink,
    redact: Callable[[str], str],
    now: Callable[[], datetime],
) -> None:
    """Finalize a run whose after-dump never arrived: report it, record it, fail it.

    The three steps are the ones every other failure of this run takes, in the same order
    and through the same functions - the error goes on the event stream, the reason goes on
    the plan as one `PlanCoverage` row, and the state goes to `failed` - because a reader
    asking why a run ended should not have to know which phase ended it. `changes.jsonl` is
    not touched: the changes were applied, and the reading taken after them is what is
    missing.
    """
    message = emit_error(sink, exc, redact)
    coverage = (
        *plan.coverage,
        PlanCoverage(
            item=PACKAGE_AFTER_ITEM,
            reason=PACKAGE_AFTER_FAILED.format(error=message),
            feature_ids=(),
        ),
    )
    record_state(
        run_dir,
        RemodelPlan(**{**dict(plan), "coverage": coverage}),
        "failed",
        at=now(),
    )
