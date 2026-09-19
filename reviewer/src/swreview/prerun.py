"""Running the deterministic checks that enumerate themselves, before the first turn.

Lever 5 (`EfficiencySettings.prerun_checks`, default off and staying off). A model-driven
review spends a round trip asking for each check whose scope is already decided by the
package: three RMS calls that take no argument worth choosing, and one call per
interference group SOLIDWORKS already grouped. Those round trips buy nothing - the answer
does not depend on anything the model knows - so this module makes them before the first
turn and tells the model what it found.

**The pre-run calls the same tool functions through the same `ToolDispatch`**, which is
the property the whole lever rests on. Every pre-run check therefore produces a real
`InvestigationStep`, real findings through `ToolContext.record_finding`, real coverage and
real `tool.started` / `tool.finished` events: the pane shows the pre-run happening, the
report is structurally indistinguishable from a model-driven run, and
`Finding.tool_result_ids` still points at a real step. A pre-run that reached past the
dispatch into `run_part_checks` would have to synthesize all four, and the report would
start lying about provenance.

**Only the four checks that already enumerate themselves.** RMS part rules, RMS equations
and RMS assembly rules each have a runner that takes no selection, and
`checks_interference.groups_of` enumerates every group. The other four checks do not: a
fastener joint needs the clamped stack, which is model-chosen and whose enumerator is a
separately specified increment (OQ-4); `check_hole_alignment` without a tolerance
`SourceRef` is `unresolved` *by design*, so pre-running every coaxial pair would
manufacture verdictless findings and degrade the report; and fit and axial stack need
drawing dimensions someone has to identify as bore, shaft or link. All four are counted
into the digest instead of being run.

**The digest is prose over a coverage item, never prose instead of one.** Each "NOT
evaluated" line is one `NotEvaluated`, which writes a `skipped` coverage item and renders a
digest line from the same sentence, so an engineer reading `report.md` and a model reading
the first user message are reading the same claim. That block exists because the digest's
own risk is that the model reads "these checks are done" as "the review is done";
generating it from the coverage machinery is what keeps the two renderings from drifting
(FR-010, RK-6).

The digest itself is prepended to the **first user message** by `agent/runner.py`, never to
the system prompt: the system prompt is the cacheable prefix and the digest is per package,
so a digest in `system` would invalidate that prefix for the whole session
(contracts/levers.md, lever 3).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from swreview.agent.providers import ToolCallRequest, ToolCallResult, call_tool
from swreview.agent.settings import EfficiencySettings
from swreview.findings import Finding
from swreview.geometry.axis import axis_distance
from swreview.ir.models import EvidencePackage
from swreview.report.attention import Ranking, coverage_line, load_policy, start_here_lines
from swreview.report.session import CoverageItem, CoverageScope
from swreview.tools.checks_interference import groups_of
from swreview.tools.context import ToolContext
from swreview.tools.registry import ToolDispatch

__all__ = [
    "DIGEST_HEADER",
    "EVALUATED_HEADER",
    "GATE_BLIND_SPOT_HEADER",
    "GATE_INSTRUCTION",
    "GATE_JUDGEMENT_HEADER",
    "GATE_NONE",
    "GATE_NOT_REACHED_HEADER",
    "GATE_START_HERE_HEADER",
    "INTERFERENCE_TOOL",
    "NOT_EVALUATED_HEADER",
    "PRERUN_CHECK_PREFIX",
    "PRERUN_TOOLS",
    "RMS_PRERUN_TOOLS",
    "STANDARDS_FAMILY_NAME",
    "STANDARDS_NOT_DUMPED",
    "STANDARDS_NO_PROFILE",
    "STANDARDS_UNGRADABLE_ROOT",
    "STANDARDS_UNREADABLE",
    "UNNAMED_ERROR",
    "NotEvaluated",
    "PrerunCall",
    "PrerunResult",
    "attach_standards",
    "coaxial_hole_pairs",
    "gate_brief",
    "not_evaluated_families",
    "planned_calls",
    "prerun_checks",
]

RMS_PRERUN_TOOLS: tuple[str, ...] = (
    "check_rms_part",
    "check_rms_equations",
    "check_rms_assembly",
)
"""The three RMS tools whose scope is the package, in the order the pre-run calls them.

None takes an argument the pre-run has to choose: `check_rms_part` and
`check_rms_equations` grade every part document when `document_id` is omitted, and
`check_rms_assembly` has no argument at all.
"""

INTERFERENCE_TOOL = "check_interference_group"
"""The fourth: one call per group `groups_of` enumerates."""

PRERUN_TOOLS: tuple[str, ...] = (*RMS_PRERUN_TOOLS, INTERFERENCE_TOOL)

PRERUN_CHECK_PREFIX = "coverage.prerun."
"""What every coverage item the digest writes is checked against.

Deliberately not a checklist item id: `Checklist.bucket_of` closes an item out on a
coverage entry whose `check` *equals* the item id, so writing "fastener joints were not
evaluated" against `fasteners` would close the very item that sentence is asking the model
to work on. The prefix mirrors `runner.PROFILE_CHECK`, which says the same kind of thing
about the dump profile.
"""

DIGEST_HEADER = (
    "Deterministic checks ran before this turn, through the same tools you have. Their "
    "findings, coverage and investigation steps are already in this session, so do not "
    "run them again; `get_review_checklist` shows where each checklist item now stands."
)

EVALUATED_HEADER = "Evaluated:"
NOT_EVALUATED_HEADER = "NOT evaluated, and why:"
NOTHING_EVALUATED = "  nothing: no pre-run check was available this run."

UNNAMED_ERROR = "the tool reported a failure without naming it"
"""What a failed call's line says when its envelope carries no `error` key.

Every tool of feature 001 puts one there, and `check_standards` - which the pre-run reaches
only with lever 11 on - is the first envelope this module has been handed that it did not
write the contract for. An unguarded read would turn one tool's shape into a `KeyError` in
*setup*, which is the one place a review cannot recover from (research R2.11).
"""

GATE_START_HERE_HEADER = "Start here:"
GATE_JUDGEMENT_HEADER = "Needs your judgement:"
GATE_NOT_REACHED_HEADER = "Not reached in this run:"
GATE_BLIND_SPOT_HEADER = "Not visible to any rule:"
"""The four headers the gate's brief adds, in the order `contracts/gate.md` section 3
lists them. Plain lines rather than Markdown headings: the brief is a chat message and the
report is a document, and only the report has a table of contents to be in."""

GATE_NONE = "  none"
"""What a list with nothing in it says. Never an omitted header: a brief that dropped
"Needs your judgement" when nothing did would read as a brief that forgot to ask."""

GATE_INSTRUCTION = (
    "These verdicts are computed from checked code. Do not re-derive them; spend your "
    "rounds on what was not reached."
)
"""The last line, verbatim (FR-029). The whole gate rests on it: a model handed five ranked
verdicts and no instruction may spend its rounds confirming them, which is the expensive
failure this lever is measured against."""

STANDARDS_FAMILY_NAME = "standards"
"""The family the standards half is counted under: `coverage.prerun.standards`, and the
label every line below is rendered behind by `NotEvaluated.line()`."""

STANDARDS_NO_PROFILE = "no profile was configured for this review"
STANDARDS_UNREADABLE = "the profile at {path} could not be loaded: {error}"
STANDARDS_NOT_DUMPED = (
    "the package was not dumped with the standards profile (missing phases: {phases})"
)
STANDARDS_UNGRADABLE_ROOT = "the root document cannot be graded, so no document was: {error}"
"""Why a review carries no standards grading (`contracts/gate.md` section 2).

Four rather than the table's three: the root a traversal cannot grade is named in research
R2.11 as a failure of the same path, and giving it the "unreadable profile" line would say
the profile was the problem when it was not. Each renders as the contract's line through
`NotEvaluated.line()`, whose label is `STANDARDS_FAMILY_NAME` - "standards: no profile was
configured for this review".

**Every one of them is a line and none of them is a refusal.** `run_standards_check` refuses
a package whose phases did not run, because a release gate that graded an extract which
never read the evidence would report a clean result on unread data. A review has fifteen
other things to do and must not be lost to that, so the same condition is reported here and
the review starts (FR-027).
"""


def _plural(count: int, noun: str) -> str:
    """`1 fastener`, `0 fasteners`. One spelling rule for every count in the digest."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def coaxial_hole_pairs(package: EvidencePackage) -> int:
    """How many hole pairs in two different components share an axis as modelled.

    The candidate pairs for `hole.coaxiality`, counted rather than checked. "Shares an
    axis" is `AxisRelation.relation == "coincident"` - the criterion `geometry/axis.py`
    already applies, with its own tolerances - rather than a coaxiality rule invented here,
    and the pair must cross two components because the checklist item is coaxiality *across
    mating parts*.

    Quadratic in the number of holes on purpose: it runs once per review over a list the
    extractor already loaded, and an index keyed on a rounded axis would be a second
    coaxiality rule to keep in step with the first.
    """
    holes = package.holes
    pairs = 0
    for index, first in enumerate(holes):
        for second in holes[index + 1 :]:
            if first.component_id == second.component_id:
                continue
            try:
                relation = axis_distance(first.axis, second.axis)
            except ValueError:
                # A zero-length direction is a missing input, not a pair: unknown stays
                # unknown and the hole is simply not counted as a candidate.
                continue
            if relation.relation == "coincident":
                pairs += 1
    return pairs


@dataclass(frozen=True)
class NotEvaluated:
    """One check family the pre-run did not evaluate, said once and rendered twice.

    `coverage_item()` is what the report reads and `line()` is what the model reads, and
    both come out of this one object, so the two cannot drift apart.
    """

    check: str
    """The coverage `check` this is written against: `PRERUN_CHECK_PREFIX` plus a family."""

    label: str
    """What the digest calls the family, in engineer's words rather than as a check id."""

    reason: str
    """The counts and the why, in one sentence. The coverage item's reason verbatim."""

    def coverage_item(self) -> CoverageItem:
        return CoverageItem(
            check=self.check, scope=CoverageScope(), reason=self.reason, error=None
        )

    def line(self) -> str:
        return f"  {self.label}: {self.reason}"


@dataclass(frozen=True)
class PrerunCall:
    """One call the pre-run made, and what the session holds because of it."""

    tool: str
    arguments: Mapping[str, Any]
    step_index: int
    findings: tuple[Finding, ...]
    error: str | None

    @property
    def label(self) -> str:
        arguments = ", ".join(f"{name}={value!r}" for name, value in self.arguments.items())
        return f"{self.tool}({arguments})"

    def line(self) -> str:
        if self.error is not None:
            return f"  {self.label} -> error: {self.error}"
        found = "no findings" if not self.findings else _plural(len(self.findings), "finding")
        return f"  {self.label} -> ok, {found}"


@dataclass(frozen=True)
class PrerunResult:
    """What the pre-run did, in the order it did it, and the digest rendered from it."""

    calls: tuple[PrerunCall, ...]
    not_evaluated: tuple[NotEvaluated, ...]

    @property
    def findings(self) -> tuple[Finding, ...]:
        return tuple(finding for call in self.calls for finding in call.findings)

    def digest(self) -> str:
        """The text prepended to the first user message.

        Counts per check with every finding named by id, then the "NOT evaluated" block.
        Nothing here is counted independently of the session: the findings are the objects
        the tools recorded, so a digest that disagrees with `session.json` is not a thing
        this can produce.
        """
        lines = [DIGEST_HEADER, "", EVALUATED_HEADER]
        lines.extend([call.line() for call in self.calls] or [NOTHING_EVALUATED])
        lines.append(f"Findings recorded: {len(self.findings)}")
        lines.extend(self._finding_lines())
        if self.not_evaluated:
            lines.extend(["", NOT_EVALUATED_HEADER])
            lines.extend(family.line() for family in self.not_evaluated)
        return "\n".join(lines)

    def _finding_lines(self) -> list[str]:
        """One line per check and status, in the order the findings were recorded."""
        grouped: dict[tuple[str, str], list[str]] = {}
        for finding in self.findings:
            grouped.setdefault((finding.check, finding.status), []).append(finding.id)
        return [
            f"  {check} - {len(ids)} {status}: {', '.join(ids)}"
            for (check, status), ids in grouped.items()
        ]


def gate_brief(prerun: PrerunResult, ranking: Ranking) -> str:
    """The procedural gate's first user message (`contracts/gate.md` section 3, FR-029).

    Six parts, in order: lever 5's digest byte-identical, the ranked rows, the rows only the
    engineer can settle, what the run did not reach, what no rule can see, and the
    instruction. Everything but the two lists this function owns is rendered by somebody
    else - `attention.start_here_lines` and `attention.coverage_line`, the same two functions
    `report/markdown.py` calls - so the ids the model reads and the ids the engineer reads
    are one list by construction rather than by two renderers agreeing (FR-031).

    **The caps are the renderers' own.** `start_here_lines` amplifies `ranking.top_n` rows
    and `coverage_line` prints `MAX_NOT_CLOSED` close-out sentences; what falls past either
    is still counted, by the not-amplified line and by the bucket counts above the bullets.
    Nothing is dropped silently here, because nothing is dropped here at all.

    Args:
        prerun: What the pre-run ran and what it counted. Part 1 is its digest and part 5
            is one sentence per family it counted.
        ranking: The session the pre-run just wrote, ranked. The caller ranks it, because
            the report's caller ranks the same session the same way and a second `rank()`
            inside here would be a second place the policy is applied.

    Returns:
        The brief, ending with the instruction. The opening instruction is appended by the
        caller, exactly as it is to the digest, because `OPENING_MESSAGE` lives in
        `agent/runner.py` and this module is imported *by* it.
    """
    policy = load_policy()
    parts: tuple[list[str], ...] = (
        [prerun.digest()],
        [GATE_START_HERE_HEADER, *start_here_lines(ranking)],
        [GATE_JUDGEMENT_HEADER, *_judgement_lines(ranking)],
        [GATE_NOT_REACHED_HEADER, *coverage_line(ranking)],
        [GATE_BLIND_SPOT_HEADER, *_blind_spot_lines(prerun, policy.blind_spots)],
        [GATE_INSTRUCTION],
    )
    return "\n\n".join("\n".join(part) for part in parts)


def _judgement_lines(ranking: Ranking) -> list[str]:
    """Part 3: the rows key 2 placed, which no tool this product has can settle.

    The title rather than the reason, because the reason of a needs-judgement row *is*
    "needs your judgement" - the row is already in "Start here" saying that, and what this
    list adds is what each judgement is about.
    """
    rows = [row for row in ranking.rows if not row.key.judgement]
    return [f"  {row.finding_id} `{row.check}` - {row.title}" for row in rows] or [GATE_NONE]


def _blind_spot_lines(prerun: PrerunResult, blind_spots: Mapping[str, str]) -> list[str]:
    """Part 5: one sentence per family the policy file names a blind spot for.

    Backed one-to-one: the families walked are exactly the `NotEvaluated`s the pre-run
    wrote as `coverage.prerun.<family>` skipped items, so every sentence the model reads is
    a claim the report carries too.

    A family the table has no sentence for is skipped rather than given a made-up one. The
    only ones today are the withheld pre-run tools (lever 4), whose family name is a *tool*
    name and whose sentence is the tier's own - already in the digest, and a statement about
    this run rather than about what no rule can ever see.
    """
    lines = [
        f"  {family.label}: {blind_spots[name]}"
        for family in prerun.not_evaluated
        if (name := family.check.removeprefix(PRERUN_CHECK_PREFIX)) in blind_spots
    ]
    return lines or [GATE_NONE]


def planned_calls(
    context: ToolContext, tools: ToolDispatch
) -> tuple[tuple[str, dict[str, Any]], ...]:
    """The calls the pre-run will make, by name and arguments, in order.

    Read by `prerun_checks` and by the test that asserts these are the same calls a model
    would otherwise have had to make. A tool this run withheld (lever 4) is not called
    here: calling it would write the tier's refusal against a request the model never made,
    and the tier's own sentence goes into the digest instead.

    A group key that appears in two configurations is called once. `check_interference_group`
    resolves the active configuration itself and refuses anything still ambiguous, so a
    second call would ask it the same question twice.

    `check_standards` is planned last, and only when the context carries a standards run -
    the same attribute `ToolRegistry._offered` reads to decide whether to register the tool
    at all (research R2.11). Asking the context rather than taking a parameter is what keeps
    the plan and the tool array from being two answers to one question: a plan that named a
    tool the dispatch never offered would call something that is not there.
    """
    # Deferred: see `_deferred` below.
    from swreview.checks.standards.registry import CHECK_TOOL
    from swreview.tools.standards_checks import standards_run

    withheld = {tool.name for tool in tools.withheld}
    planned: list[tuple[str, dict[str, Any]]] = [
        (name, {}) for name in RMS_PRERUN_TOOLS if name not in withheld
    ]
    if INTERFERENCE_TOOL not in withheld:
        keys = dict.fromkeys(group.group_key for group in groups_of(context.ir))
        planned.extend((INTERFERENCE_TOOL, {"group_key": key}) for key in keys)
    if CHECK_TOOL not in withheld and standards_run(context) is not None:
        planned.append((CHECK_TOOL, {}))
    return tuple(planned)


def _deferred() -> None:
    """Why every import of a standards module in this file is made inside a function.

    `checks/rules/run.py` imports `agent/runner.py`, which imports this module, and every
    module under `checks/standards/` reaches `checks/rules/` - so importing any of them at
    the top of this file closes the cycle at interpreter start.
    `ToolRegistry.standards_tools` defers its own import of the tool for the same reason and
    says so; by the time a review calls anything here, every module is loaded.

    A function rather than a comment repeated four times, so there is one place to correct
    if the cycle is ever broken and the imports can come up to the top.
    """


def attach_standards(
    context: ToolContext, profile_path: Path | str | None
) -> NotEvaluated | None:
    """Attach a standards run to `context`, or say why this review has no grading (FR-027).

    Called by `start_review` **between** `build_context` and the dispatch, because
    `ToolRegistry._offered` registers `check_standards` only when the context already
    carries a run, and the tool array never changes again once the dispatch is built
    (research R2.11, and lever 3's prefix guarantee).

    Args:
        context: The run being set up. The run is attached to it, and its package is what
            the graded set and the phase rows are read from.
        profile_path: The standards profile this design is graded against, or `None` when
            the review was started without one.

    Returns:
        `None` when the run is attached and the checks will run, or the one `NotEvaluated`
        the pre-run counts and the brief prints. **Never raises**: every refusal the
        standards machinery can make is turned into a line here, because a review that
        cannot grade the release checklist is still a review (`contracts/gate.md` section 2).
    """
    # Deferred: see `_deferred` above.
    from swreview.checks.standards.profile import ProfileError, load_profile
    from swreview.checks.standards.run import missing_standards_phases
    from swreview.checks.standards.traversal import UngradableRootError, graded_documents
    from swreview.tools.standards_checks import StandardsRun, attach_standards_run

    if profile_path is None:
        return _standards_gap(STANDARDS_NO_PROFILE)
    try:
        profile = load_profile(profile_path)
    except ProfileError as error:
        return _standards_gap(STANDARDS_UNREADABLE.format(path=profile_path, error=error))

    missing = missing_standards_phases(context.ir)
    if missing:
        return _standards_gap(STANDARDS_NOT_DUMPED.format(phases=", ".join(missing)))
    try:
        documents = graded_documents(context.ir, profile)
    except UngradableRootError as error:
        return _standards_gap(STANDARDS_UNGRADABLE_ROOT.format(error=error))

    attach_standards_run(context, StandardsRun(profile=profile, documents=documents))
    return None


def _standards_gap(reason: str) -> NotEvaluated:
    """One `NotEvaluated` for the standards family, whichever of the four reasons it is."""
    return NotEvaluated(
        check=f"{PRERUN_CHECK_PREFIX}{STANDARDS_FAMILY_NAME}",
        label=STANDARDS_FAMILY_NAME,
        reason=reason,
    )


def not_evaluated_families(
    package: EvidencePackage,
    withheld: Sequence[tuple[str, str]],
    standards: NotEvaluated | None = None,
) -> tuple[NotEvaluated, ...]:
    """Every line of the "NOT evaluated" block, counted against `package`.

    Four families are here on every run, because no enumerator can decide their scope, and
    three more appear conditionally: a pre-run tool a tier withheld, which carries the
    tier's own sentence rather than a second one written here (contracts/levers.md, levers 4
    and 5); interference when the package reports none, so "no group was checked" is a
    statement about the package rather than a silence; and the standards family when
    `attach_standards` could not attach a run.

    Args:
        package: The package under review; every count comes off it.
        withheld: `(tool name, reason)` for each pre-run tool this run did not offer.
        standards: What `attach_standards` returned, or `None` when the standards run is
            attached and the checks will run - which is also what a review that never asked
            for one passes, because a family nobody asked about is not a gap this block
            reports (FR-030: lever 5's digest is unchanged by lever 11 existing).
    """
    families = [
        NotEvaluated(check=f"{PRERUN_CHECK_PREFIX}{name}", label=name, reason=reason)
        for name, reason in withheld
    ]
    if not groups_of(package):
        families.append(
            NotEvaluated(
                check=f"{PRERUN_CHECK_PREFIX}interference",
                label="interference",
                reason=(
                    "the package reports no interference, so no group was checked. That is "
                    "what SOLIDWORKS detected, not a claim that detection was run over "
                    "every configuration."
                ),
            )
        )
    families.extend(
        [
            NotEvaluated(
                check=f"{PRERUN_CHECK_PREFIX}fastener_joint",
                label="fastener joints",
                reason=(
                    f"{_plural(len(package.fasteners), 'fastener')} in the package; no "
                    "joint was evaluated. Which components a screw clamps is not derivable "
                    "from the package, so name the fastener, the hole and the clamped "
                    "stack yourself with `check_fastener_joint`."
                ),
            ),
            NotEvaluated(
                check=f"{PRERUN_CHECK_PREFIX}hole_alignment",
                label="hole alignment",
                reason=(
                    f"{_plural(coaxial_hole_pairs(package), 'coaxial hole pair')} across "
                    f"two components, out of {_plural(len(package.holes), 'hole')}; none "
                    "was evaluated. `check_hole_alignment` without the drawing tolerance "
                    "that governs the pair is `unresolved` by design, and the package binds "
                    "no tolerance to a hole, so identify it and call the check."
                ),
            ),
            NotEvaluated(
                check=f"{PRERUN_CHECK_PREFIX}fit",
                label="fit",
                reason=(
                    "no interface was evaluated: `check_fit` needs two drawing dimensions "
                    "identified as the bore and the shaft of one interface, which nothing in "
                    "the package says."
                ),
            ),
            NotEvaluated(
                check=f"{PRERUN_CHECK_PREFIX}axial_stack",
                label="axial stack",
                reason=(
                    "no stack was evaluated: `check_axial_stack` needs an ordered list of "
                    "dimensions with signs and the gap they set, which nothing in the "
                    "package says."
                ),
            ),
        ]
    )
    if standards is not None:
        families.append(standards)
    return tuple(families)


def prerun_checks(
    context: ToolContext,
    tools: ToolDispatch,
    *,
    efficiency: EfficiencySettings,
    standards: NotEvaluated | None = None,
) -> PrerunResult | None:
    """Run the self-enumerating checks into `context`'s session, or `None` with the flag off.

    The one writer, called where the review starts, beside `record_partial_evidence` and
    `carry_over_findings`, so the command line and the pane get the same answer and two
    places do not decide what a pre-run means.

    With the flag off nothing is called and nothing is written, which is what makes the off
    arm of the A/B indistinguishable from a build without the lever. With it on, a check
    that fails is a failed call like any other - `ToolDispatch.call` never raises, the
    recording sink writes the `failed` coverage item, and the next check still runs -
    because a pre-run that could end a review would be a new way to lose one.

    Args:
        context: The run being set up; its session, package and event stream are what the
            calls write to.
        tools: The dispatch this session will hand the provider. The same object, not a
            second one built for the pre-run: the steps, findings and events have to be the
            ones a model-driven call would have produced.
        efficiency: This run's levers. Only `prerun_checks` and `procedural_gate` are read.
        standards: What `attach_standards` returned, so the family it could not grade is
            counted and printed beside the four the pre-run never grades. `None` when the
            run is attached, and when the review never asked for one.

    Returns:
        What was run and what was not, so the caller can render the digest or the brief, or
        `None` when both levers are off and there is nothing to render.
    """
    if not (efficiency.prerun_checks or efficiency.procedural_gate):
        return None

    session = context.require_session()
    calls: list[PrerunCall] = []
    for name, arguments in planned_calls(context, tools):
        before = len(session.findings)
        step_index = len(session.steps)
        result = call_tool(
            request=ToolCallRequest(
                call_id=f"prerun_{len(calls) + 1}", name=name, arguments=arguments
            ),
            tools=tools,
            on_event=context.emit_event,
            step_index=step_index,
            clock=perf_counter,
        )
        calls.append(
            PrerunCall(
                tool=name,
                arguments=dict(arguments),
                step_index=step_index,
                findings=tuple(session.findings[before:]),
                error=_error_of(result),
            )
        )

    withheld_prerun_tools = [
        (tool.name, tool.reason) for tool in tools.withheld if tool.name in PRERUN_TOOLS
    ]
    families = not_evaluated_families(context.ir, withheld_prerun_tools, standards)
    for family in families:
        context.record_coverage("skipped", family.coverage_item())
    return PrerunResult(calls=tuple(calls), not_evaluated=families)


def _error_of(result: ToolCallResult) -> str | None:
    """What a call's line says about its failure, or `None` for a call that succeeded.

    `ToolCallResult.payload` is a plain dict and the `error` key is a convention every tool
    of feature 001 keeps; `call_tool` reads it with `.get` for that reason. The pre-run read
    it by subscript until lever 11 widened the set of tools it dispatches, and a `KeyError`
    here would be raised inside `start_review`, which is the one place a review has no way
    to recover from (research R2.11).
    """
    if not result.is_error:
        return None
    return str(result.payload.get("error", UNNAMED_ERROR))
