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
from time import perf_counter
from typing import Any

from swreview.agent.providers import ToolCallRequest, call_tool
from swreview.agent.settings import EfficiencySettings
from swreview.findings import Finding
from swreview.geometry.axis import axis_distance
from swreview.ir.models import EvidencePackage
from swreview.report.session import CoverageItem, CoverageScope
from swreview.tools.checks_interference import groups_of
from swreview.tools.context import ToolContext
from swreview.tools.registry import ToolDispatch

__all__ = [
    "DIGEST_HEADER",
    "EVALUATED_HEADER",
    "INTERFERENCE_TOOL",
    "NOT_EVALUATED_HEADER",
    "PRERUN_CHECK_PREFIX",
    "PRERUN_TOOLS",
    "RMS_PRERUN_TOOLS",
    "NotEvaluated",
    "PrerunCall",
    "PrerunResult",
    "coaxial_hole_pairs",
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
    """
    withheld = {tool.name for tool in tools.withheld}
    planned: list[tuple[str, dict[str, Any]]] = [
        (name, {}) for name in RMS_PRERUN_TOOLS if name not in withheld
    ]
    if INTERFERENCE_TOOL not in withheld:
        keys = dict.fromkeys(group.group_key for group in groups_of(context.ir))
        planned.extend((INTERFERENCE_TOOL, {"group_key": key}) for key in keys)
    return tuple(planned)


def not_evaluated_families(
    package: EvidencePackage, withheld: Sequence[tuple[str, str]]
) -> tuple[NotEvaluated, ...]:
    """Every line of the "NOT evaluated" block, counted against `package`.

    Four families are here on every run, because no enumerator can decide their scope, and
    two more appear conditionally: a pre-run tool a tier withheld, which carries the tier's
    own sentence rather than a second one written here (contracts/levers.md, levers 4 and
    5), and interference when the package reports none, so "no group was checked" is a
    statement about the package rather than a silence.

    Args:
        package: The package under review; every count comes off it.
        withheld: `(tool name, reason)` for each pre-run tool this run did not offer.
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
    return tuple(families)


def prerun_checks(
    context: ToolContext, tools: ToolDispatch, *, efficiency: EfficiencySettings
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
        efficiency: This run's levers. Only `prerun_checks` is read.

    Returns:
        What was run and what was not, so the caller can render the digest, or `None` when
        the lever is off and there is no digest to render.
    """
    if not efficiency.prerun_checks:
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
                error=str(result.payload["error"]) if result.is_error else None,
            )
        )

    withheld_prerun_tools = [
        (tool.name, tool.reason) for tool in tools.withheld if tool.name in PRERUN_TOOLS
    ]
    families = not_evaluated_families(context.ir, withheld_prerun_tools)
    for family in families:
        context.record_coverage("skipped", family.coverage_item())
    return PrerunResult(calls=tuple(calls), not_evaluated=families)
