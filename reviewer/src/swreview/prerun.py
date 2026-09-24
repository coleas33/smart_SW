"""Running the deterministic checks that enumerate themselves, before the first turn.

Lever 5 (`EfficiencySettings.prerun_checks`), which feature 008 calls **checks first**: off in
the class and on the command line, the pane's default since 2026-09-22 (`agent/settings.py`
`pane_efficiency`). With SOLIDWORKS attached it also runs live interference detection first,
judges every group it found and writes the rows into the run folder's package; a model that
asks for one of these checks again is answered from the recorded result by `PrerunGuard`
(`contracts/checks-first.md`). A model-driven
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

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from swreview.agent.providers import ToolCallRequest, ToolCallResult, call_tool
from swreview.agent.settings import EfficiencySettings, checks_first
from swreview.checks.fastener_identity import joint_map_with_fasteners
from swreview.checks.interference import STATIC_SCOPE_LIMIT
from swreview.checks.joints import JointMap
from swreview.checks.rms.registry import RMS_FAMILY
from swreview.findings import Finding
from swreview.ir.loader import append_interference_run
from swreview.ir.models import EvidencePackage, Gap, Interference
from swreview.report.attention import (
    FAMILY_TITLES,
    Ranking,
    coverage_line,
    family_counts,
    family_of,
    load_policy,
    start_here_lines,
)
from swreview.report.session import Contact, CoverageItem, CoverageScope
from swreview.tools import checks_mechanical
from swreview.tools.checks_interference import groups_of
from swreview.tools.context import ToolContext
from swreview.tools.drawings import DRAWINGS_TOOL, drawing_evidence
from swreview.tools.model_view import check_digest, count_findings
from swreview.tools.registry import RecordedTool, ToolDispatch, record_call

__all__ = [
    "ALREADY_RUN",
    "DIGEST_HEADER",
    "DIGEST_ID_CAP",
    "EVALUATED_HEADER",
    "FAMILY_COUNTS_NOTE",
    "GATE_BLIND_SPOT_HEADER",
    "GATE_INSTRUCTION",
    "GATE_JUDGEMENT_HEADER",
    "GATE_NONE",
    "GATE_NOT_REACHED_HEADER",
    "GATE_START_HERE_HEADER",
    "INTERFERENCE_TOOL",
    "JOINTS_TOOL",
    "LIVE_INTERFERENCE_TOOL",
    "NOT_EVALUATED_HEADER",
    "PRERUN_CHECK_PREFIX",
    "PRERUN_INTERFERENCE_SETTINGS",
    "PRERUN_TOOLS",
    "REPEAT_NOTE",
    "RMS_PRERUN_TOOLS",
    "STANDARDS_FAMILY_NAME",
    "STANDARDS_NOT_DUMPED",
    "STANDARDS_NO_PROFILE",
    "STANDARDS_UNGRADABLE_ROOT",
    "STANDARDS_UNREADABLE",
    "UNNAMED_ERROR",
    "WITHHELD_LINE",
    "LiveOutcome",
    "NotEvaluated",
    "PrerunCall",
    "PrerunGuard",
    "PrerunResult",
    "answers_repeat",
    "attach_standards",
    "gate_brief",
    "not_evaluated_families",
    "planned_calls",
    "prerun_checks",
    "prerun_tools",
    "recorded_call",
    "repeat_key",
    "withheld_tools",
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

LIVE_INTERFERENCE_TOOL = "bridge_interference"
"""Checks first's live call (feature 008): once, the whole assembly, before everything else,
through the same dispatch the model uses, when SOLIDWORKS is attached."""

PRERUN_INTERFERENCE_SETTINGS: dict[str, Any] = {
    "treat_coincident_as_interference": True,
    "treat_subassemblies_as_components": True,
    "include_multibody": True,
    "ignore_hidden": False,
    "fastener_folder_treatment": "include",
}
"""The detection settings the live call states, all five: exactly what the model chose on
the recorded 830 run, so the pre-run reproduces its groups and keeps every recorded finding
reachable (research R2.17). Every row carries them, and the digest line prints them."""

LIVE_NO_BRIDGE = "no_bridge"
LIVE_NOT_ASSEMBLY = "not_assembly"
"""Why live detection was not attempted: no bridge (or no live tool), or a root it cannot
run on. `LiveOutcome.not_attempted` holds one of the two; each renders its own sentence."""

INTERFERENCE_NOT_REPORTED = (
    "the package reports no interference, so no group was checked. That is what SOLIDWORKS "
    "detected, not a claim that detection was run over every configuration."
)
INTERFERENCE_NOT_ATTACHED = (
    "SOLIDWORKS is not attached, so live detection did not run; the {groups} the package "
    "already holds {verb} judged"
)
INTERFERENCE_NEEDS_ASSEMBLY = (
    "live detection needs an assembly with two components or more; the root is {kind} with "
    "{components}"
)
INTERFERENCE_FAILED = "live detection failed: {error}; it was not evaluated"
INTERFERENCE_COLLIDED = (
    "{rows} dropped because their ids collide with rows of another configuration"
)
INTERFERENCE_NOT_WRITTEN = "the detected rows could not be written to package.json: {error}"
INTERFERENCE_CLEAN = "live detection over {configuration} found no interference ({settings})"
"""The interference family's sentences under checks first (`contracts/checks-first.md`
section 3): each is a coverage item's reason and a digest line, so the report and the model
read one claim. `INTERFERENCE_NOT_REPORTED` is the pre-008 sentence, unchanged."""

INTERFERENCE_ROWS_CHECK_FAMILY = "interference_rows"
"""The family a failed write of the detected rows is counted under:
`coverage.prerun.interference_rows`, unresolved, the findings still recorded."""

INTERFERENCE_CHECKLIST_ITEM = "interference"
"""The checklist item a clean live detection closes with a `checked` item."""


def prerun_tools() -> tuple[str, ...]:
    """Every tool the pre-run may call, read when asked: the four above, then feature 010's
    `CODE_FIRST_CHECKS`. A withheld one among them carries its tier's sentence into the
    digest (contracts/levers.md, levers 4 and 5)."""
    return (*RMS_PRERUN_TOOLS, INTERFERENCE_TOOL, *checks_mechanical.CODE_FIRST_CHECKS)


PRERUN_TOOLS: tuple[str, ...] = prerun_tools()

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

WITHHELD_LINE = (
    "Not offered to you this session, because checks first ran them to completion: {tools}."
)
"""The digest's line after `Evaluated:` when lever 13 took tools off the array (feature 008
FR-030, `contracts/checks-first.md` section 7): it names them, so a model that reads a tool
in the list above and misses it in its array knows why, and is told not to look for it."""

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


JOINTS_TOOL = "check_joints"
"""Feature 010's joint tool. When the pre-run plans it, the hole-alignment family states
what the joint map could not reach rather than counting candidate pairs (`contracts/
code-first.md` section 4); when a tier withholds it, the tier's own sentence says why."""


def _fastener_joint_family(joint_map: JointMap) -> NotEvaluated | None:
    """What the joint map could not reach for fasteners, or `None` when it reached them all.

    A recognised fastener no rule placed, and a placed screw whose tapped part has no
    extracted hole, are what the fastener checks could not judge (`contracts/code-first.md`
    section 4). A family with nothing to report renders no line.
    """
    unplaced = len(joint_map.unplaced)
    untapped = sum(
        1
        for joint in joint_map.joints
        if joint.fastener is not None and joint.tapped_instance is None
    )
    clauses = []
    if unplaced:
        clauses.append(
            f"{_plural(unplaced, 'recognised fastener')} {'was' if unplaced == 1 else 'were'} "
            "not placed in any joint"
        )
    if untapped:
        clauses.append(
            f"{_plural(untapped, 'placed screw')} {'enters' if untapped == 1 else 'enter'} a "
            "part whose tapped hole was not extracted"
        )
    if not clauses:
        return None
    return NotEvaluated(
        check=f"{PRERUN_CHECK_PREFIX}fastener_joint",
        label="fastener joints",
        reason=f"{'; '.join(clauses)}.",
    )


def _hole_alignment_family(package: EvidencePackage, joint_map: JointMap) -> NotEvaluated | None:
    """The holes the joint map could not use, or `None` when it missed nothing.

    A hole row with no cylinder face, or one on a component that was not read, yields no
    instance and so sits in no joint; those are what alignment could not judge. A family
    with nothing to report renders no line.
    """
    hole_ids = {hole.id for hole in package.holes}
    missed = [gap for gap in joint_map.gaps if gap.subject in hole_ids]
    if not missed:
        return None
    count = len(missed)
    return NotEvaluated(
        check=f"{PRERUN_CHECK_PREFIX}hole_alignment",
        label="hole alignment",
        reason=(
            f"{_plural(count, 'hole')} {'has' if count == 1 else 'have'} no cylinder face or "
            f"{'belongs' if count == 1 else 'belong'} to a component that was not read; "
            f"{'it is' if count == 1 else 'they are'} in no joint."
        ),
    )


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

    bucket: Literal["skipped", "unresolved"] = "skipped"
    """Where the coverage item is written. `skipped` for a family nobody ran; `unresolved`
    for work that ran and left something undecided - detected rows dropped for colliding
    ids, or rows that could not be written (feature 008)."""

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
    contacts: tuple[Contact, ...] = ()
    """What the call put on the session's contact list (feature 010): an interference group
    that is two parts touching is a contact, not a finding, and the line says so."""
    payload: Mapping[str, Any] | None = None
    """The call's full result, kept in memory so the re-call guard can answer a repeat with
    its digest (feature 008). Defaulted, so a direct constructor stays valid."""

    @property
    def label(self) -> str:
        arguments = ", ".join(f"{name}={value!r}" for name, value in self.arguments.items())
        return f"{self.tool}({arguments})"

    def line(self) -> str:
        if self.error is not None:
            return f"  {self.label} -> error: {self.error}"
        if self.tool == DRAWINGS_TOOL and self.payload is not None:
            return f"  {self.label} -> ok, {_drawing_counts(self.payload, self.findings)}"
        return f"  {self.label} -> ok, {_outcome_counts(self.findings, self.contacts)}"


def _drawing_counts(payload: Mapping[str, Any], findings: Sequence[Finding]) -> str:
    """`2 drawings, 3 candidates, 2 questions` - and the findings when there are any: what
    `check_drawings` recorded, read off its own payload (`contracts/questions.md` section 5)."""
    counts = [
        _plural(int(payload.get("drawings", 0)), "drawing"),
        _plural(int(payload.get("candidates", 0)), "candidate"),
        _plural(int(payload.get("questions", 0)), "question"),
    ]
    if findings:
        counts.append(_plural(len(findings), "finding"))
    return ", ".join(counts)


def _outcome_counts(findings: Sequence[Finding], contacts: Sequence[Contact]) -> str:
    """`2 findings, 1 contact`, or `no findings`: what a call, or a run of calls, recorded."""
    counts = [_plural(len(findings), "finding")] if findings else []
    if contacts:
        counts.append(_plural(len(contacts), "contact"))
    return ", ".join(counts) or "no findings"


def _settings_text(settings: Mapping[str, Any]) -> str:
    """`treat_coincident_as_interference=true, ...`: the five stated settings on one line."""
    return ", ".join(
        f"{name}={str(value).lower() if isinstance(value, bool) else value}"
        for name, value in settings.items()
    )


@dataclass(frozen=True)
class LiveOutcome:
    """What checks first's live interference detection did (feature 008, data-model section 8).

    Present on every checks-first pre-run: `not_attempted` says why the call was never made
    (`LIVE_NO_BRIDGE`, `LIVE_NOT_ASSEMBLY`), and otherwise `step_index` is the call's step
    and the rest is what it found, dropped and could not write. Every non-empty outcome is
    a coverage row and a digest line (`not_evaluated_families`); the re-call guard answers a
    repeat of the call from `groups`, `rows_added`, `configuration` and `settings`.
    """

    configuration: str
    settings: Mapping[str, Any]
    step_index: int | None = None
    not_attempted: str | None = None
    groups: int = 0
    """Distinct groups among the rows the call added: what the pre-run then judged."""
    rows_detected: int = 0
    rows_added: int = 0
    rows_collided: int = 0
    """Rows the call returned whose ids another configuration's rows already hold, which
    `bridge_interference` drops (research R2.16)."""
    error: str | None = None
    persist_error: str | None = None

    @property
    def succeeded(self) -> bool:
        """The call was made and answered; a failed write does not undo what it found."""
        return self.step_index is not None and self.error is None

    def line(self, call: PrerunCall) -> str:
        """The call's `Evaluated:` line: its error, a clean result, or rows in groups."""
        if not self.succeeded:
            return call.line()
        if self.rows_detected == 0:
            clean = INTERFERENCE_CLEAN.format(
                configuration=self.configuration, settings=_settings_text(self.settings)
            )
            return f"  interference: {clean}"
        return (
            f"  {LIVE_INTERFERENCE_TOOL}({self.configuration}) -> "
            f"{_plural(self.rows_added, 'row')} in {_plural(self.groups, 'group')} "
            f"({_settings_text(self.settings)})"
        )


DIGEST_ID_CAP = 20
"""How many finding ids one `(check, status)` line of the opening digest names.

The opening message sits in the fixed prefix of every request and is never pruned, so it
names at most twenty ids per line and counts the rest (`and 1480 more`); a tool digest,
which is pruned after two rounds, can afford its own larger caps (research R2.20)."""

COLLAPSED_ERRORS_NAMED = 3
"""How many failed calls a collapsed line names; the rest are counted."""

FAMILY_COUNTS_NOTE = "counts only - the findings are in the session and the report"
"""What a folded family's digest line ends with, so a model reading counts and no ids knows
the ids exist and where (FR-014)."""


@dataclass(frozen=True)
class PrerunResult:
    """What the pre-run did, in the order it did it, and the digest rendered from it."""

    calls: tuple[PrerunCall, ...]
    not_evaluated: tuple[NotEvaluated, ...]
    families: tuple[str, ...] = ()
    """The session's folded families when the pre-run ran (`["rms"]` under checks first):
    their findings are one counts line in the digest, never a list of ids."""
    live: LiveOutcome | None = None
    """What live interference detection did, or why it was not attempted (feature 008)."""
    withheld: tuple[str, ...] = ()
    """The tools lever 13 took off the array because this pre-run ran them to completion
    (`withheld_tools`), in pre-run order. Empty with the lever off; `PrerunGuard` leaves them
    out of what it hands the adapters, and the digest names them."""

    @property
    def findings(self) -> tuple[Finding, ...]:
        return tuple(finding for call in self.calls for finding in call.findings)

    def digest(self) -> str:
        """The text prepended to the first user message.

        Counts per check with the findings named by id - at most `DIGEST_ID_CAP` per line -
        and a folded family as one counts line, then the "NOT evaluated" block. Nothing here
        is counted independently of the session: the findings are the objects the tools
        recorded, so a digest that disagrees with `session.json` is not a thing this can
        produce.
        """
        lines = [DIGEST_HEADER, "", EVALUATED_HEADER]
        lines.extend(self._call_lines() or [NOTHING_EVALUATED])
        if self.withheld:
            lines.append(WITHHELD_LINE.format(tools=", ".join(self.withheld)))
        lines.append(f"Findings recorded: {len(self.findings)}")
        lines.extend(self._finding_lines())
        if self.not_evaluated:
            lines.extend(["", NOT_EVALUATED_HEADER])
            lines.extend(family.line() for family in self.not_evaluated)
        return "\n".join(lines)

    def _call_lines(self) -> list[str]:
        """One line per tool, in the order each was first called (research R2.20).

        A tool called once renders exactly `PrerunCall.line()`; a tool called several times
        - `check_interference_group` once per group - collapses to one line of counts, so
        a thousand groups are one line rather than a thousand. The live detection call
        renders its own line from `LiveOutcome` (`contracts/checks-first.md` section 3).
        """
        by_tool: dict[str, list[PrerunCall]] = {}
        for call in self.calls:
            by_tool.setdefault(call.tool, []).append(call)
        lines: list[str] = []
        for tool, calls in by_tool.items():
            if tool == LIVE_INTERFERENCE_TOOL and self.live is not None and len(calls) == 1:
                lines.append(self.live.line(calls[0]))
            elif len(calls) == 1:
                lines.append(calls[0].line())
            else:
                lines.append(_collapsed_line(tool, calls))
        return lines

    def _finding_lines(self) -> list[str]:
        """One line per folded family or per check and status, in recording order."""
        grouped: dict[tuple[str, str], list[Finding]] = {}
        for finding in self.findings:
            family = family_of(finding.check, self.families)
            key = ("", family) if family is not None else (finding.check, finding.status)
            grouped.setdefault(key, []).append(finding)
        lines: list[str] = []
        for (check, status), findings in grouped.items():
            if not check:
                lines.append(_family_line(status, findings))
                continue
            ids = [finding.id for finding in findings]
            more = len(ids) - DIGEST_ID_CAP
            named = ", ".join(ids[:DIGEST_ID_CAP]) + (f", and {more} more" if more > 0 else "")
            lines.append(f"  {check} - {len(ids)} {status}: {named}")
        return lines


def _collapsed_line(tool: str, calls: Sequence[PrerunCall]) -> str:
    """`check_interference_group x113 -> 113 ok, 113 findings`, errors counted and named."""
    failed = [call for call in calls if call.error is not None]
    parts = [f"{len(calls) - len(failed)} ok"]
    if failed:
        named = "; ".join(
            f"{call.label}: {call.error}" for call in failed[:COLLAPSED_ERRORS_NAMED]
        )
        rest = len(failed) - COLLAPSED_ERRORS_NAMED
        if rest > 0:
            named += f"; and {rest} more"
        parts.append(f"{_plural(len(failed), 'error')} ({named})")
    findings = [finding for call in calls for finding in call.findings]
    contacts = [contact for call in calls for contact in call.contacts]
    parts.append(_outcome_counts(findings, contacts))
    return f"  {tool} x{len(calls)} -> {', '.join(parts)}"


def _family_line(family: str, findings: Sequence[Finding]) -> str:
    """A folded family's one line: counts, never ids (FR-014).

    `modelling practice: 85 findings across 7 rules (51 demonstrated, 34 suspected); counts
    only - ...`, counted by `tools/model_view.count_findings` - the rule the re-call guard's
    counts-only answer uses - and worded by the ranking's own `family_counts`.
    """
    counts = count_findings((f.check, f.status, f.severity) for f in findings)
    statuses = ", ".join(f"{count} {status}" for status, count in counts.by_status.items())
    name = FAMILY_TITLES.get(family, family).lower()
    return (
        f"  {name}: {family_counts(counts.findings, counts.rules)} ({statuses}); "
        f"{FAMILY_COUNTS_NOTE}"
    )


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

    Feature 010's argument-free checks follow the interference groups, one `(name, {})` per
    name in `checks_mechanical.CODE_FIRST_CHECKS`, read at call time: that tuple is the one
    hook those checks have into the pre-run (feature 010 `contracts/code-first.md`).

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
    planned.extend(
        (name, {}) for name in checks_mechanical.CODE_FIRST_CHECKS if name not in withheld
    )
    # Feature 011: the drawing check, on the condition `ToolRegistry._offered` offers it on,
    # so the plan never names a tool the dispatch does not hold (`contracts/questions.md` 2).
    if DRAWINGS_TOOL not in withheld and drawing_evidence(context.ir):
        planned.append((DRAWINGS_TOOL, {}))
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
    *,
    live: LiveOutcome | None = None,
) -> tuple[NotEvaluated, ...]:
    """Every line of the "NOT evaluated" block, counted against `package`.

    Three families are here on every run, because no enumerator can decide their scope, and
    four more appear conditionally: a pre-run tool a tier withheld, which carries the
    tier's own sentence rather than a second one written here (contracts/levers.md, levers 4
    and 5); interference, whenever there is something to say about it (below); hole
    alignment when feature 010's `check_joints` runs and its joint map could not reach a
    hole - the joint map is what judges alignment now, so the line says what it missed, and
    a withheld `check_joints` speaks for itself; and the standards family when
    `attach_standards` could not attach a run.

    Args:
        package: The package under review; every count comes off it.
        withheld: `(tool name, reason)` for each pre-run tool this run did not offer.
        standards: What `attach_standards` returned, or `None` when the standards run is
            attached and the checks will run.
        live: What checks first's live detection did, or why it did not run (feature 008);
            `None` states nothing about detection and keeps the pre-008 rule - "no group
            was checked" when the package reports no interference.
    """
    families = [
        NotEvaluated(check=f"{PRERUN_CHECK_PREFIX}{name}", label=name, reason=reason)
        for name, reason in withheld
    ]
    families.extend(_interference_families(package, live))
    withheld_names = {name for name, _ in withheld}
    joints_run = (
        JOINTS_TOOL in checks_mechanical.CODE_FIRST_CHECKS and JOINTS_TOOL not in withheld_names
    )
    joint_map = joint_map_with_fasteners(package)[1] if joints_run else None
    if joint_map is None:
        families.append(
            NotEvaluated(
                check=f"{PRERUN_CHECK_PREFIX}fastener_joint",
                label="fastener joints",
                reason=(
                    f"{_plural(len(package.fasteners), 'fastener')} in the package; no "
                    "joint was evaluated. Which components a screw clamps is not derivable "
                    "from the package, so name the fastener, the hole and the clamped "
                    "stack yourself with `check_fastener_joint`."
                ),
            )
        )
    else:
        # Feature 010 T047: `check_joints` places the fasteners it recognises, so the line
        # states what the joint map could not reach rather than a count to judge by hand.
        fastener_joint = _fastener_joint_family(joint_map)
        if fastener_joint is not None:
            families.append(fastener_joint)
        hole_alignment = _hole_alignment_family(package, joint_map)
        if hole_alignment is not None:
            families.append(hole_alignment)
    families.extend(
        [
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


def _interference(
    reason: str, *, bucket: Literal["skipped", "unresolved"] = "skipped"
) -> NotEvaluated:
    return NotEvaluated(
        check=f"{PRERUN_CHECK_PREFIX}interference",
        label="interference",
        reason=reason,
        bucket=bucket,
    )


def _interference_families(
    package: EvidencePackage, live: LiveOutcome | None
) -> list[NotEvaluated]:
    """What the interference family says, from the package and the live outcome.

    `contracts/checks-first.md` section 3, one row per outcome: no bridge (the package's own
    groups were judged, or it reported none), a root live detection cannot run on, a failed
    call, rows dropped for colliding ids, rows that could not be written. A clean or
    successful detection says nothing here - its line is the call's own, and a clean one is
    also a `checked` item written by `prerun_checks`.
    """
    groups = groups_of(package)
    if live is None or live.not_attempted == LIVE_NO_BRIDGE:
        if not groups:
            return [_interference(INTERFERENCE_NOT_REPORTED)]
        if live is None:
            return []
        return [
            _interference(
                INTERFERENCE_NOT_ATTACHED.format(
                    groups=_plural(len(groups), "group"),
                    verb="was" if len(groups) == 1 else "were",
                )
            )
        ]
    if live.not_attempted == LIVE_NOT_ASSEMBLY:
        return [
            _interference(
                INTERFERENCE_NEEDS_ASSEMBLY.format(
                    kind=_root_kind(package),
                    components=_plural(len(package.components), "component"),
                )
            )
        ]
    families: list[NotEvaluated] = []
    if live.error is not None:
        families.append(_interference(INTERFERENCE_FAILED.format(error=live.error)))
    if live.rows_collided:
        rows = (
            "1 detected row was"
            if live.rows_collided == 1
            else f"{live.rows_collided} detected rows were"
        )
        families.append(
            _interference(INTERFERENCE_COLLIDED.format(rows=rows), bucket="unresolved")
        )
    if live.persist_error is not None:
        families.append(
            NotEvaluated(
                check=f"{PRERUN_CHECK_PREFIX}{INTERFERENCE_ROWS_CHECK_FAMILY}",
                label="interference",
                reason=INTERFERENCE_NOT_WRITTEN.format(error=live.persist_error),
                bucket="unresolved",
            )
        )
    return families


def _root_document(package: EvidencePackage) -> Any | None:
    root = package.design.root_assembly_document_id
    return next((d for d in package.documents if d.document_id == root), None)


def _root_kind(package: EvidencePackage) -> str:
    """`an assembly`, `a part`, `a drawing`, or what the package does not say."""
    document = _root_document(package)
    if document is None:
        return "a document the package does not carry"
    return f"{'an' if document.kind[0] in 'aeiou' else 'a'} {document.kind}"


def prerun_checks(
    context: ToolContext,
    tools: ToolDispatch,
    *,
    efficiency: EfficiencySettings,
    standards: NotEvaluated | None = None,
    package_dir: Path | None = None,
    out_dir: Path | None = None,
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
        package_dir: The folder the package was loaded from, whose `package.json` the live
            rows are merged from (feature 008, FR-009).
        out_dir: The run folder the merged `package.json` is written to - the package's own
            folder in the pane, `--out` on the command line, whose input is never written.

    Returns:
        What was run and what was not, so the caller can render the digest or the brief, or
        `None` when both levers are off and there is nothing to render.
    """
    if not checks_first(efficiency):
        return None

    session = context.require_session()
    calls: list[PrerunCall] = []
    live = _live_interference(context, tools, calls, package_dir=package_dir, out_dir=out_dir)
    for name, arguments in planned_calls(context, tools):
        calls.append(_prerun_call(context, tools, name, arguments, len(calls)))

    if live.succeeded and live.rows_detected == 0:
        context.record_coverage("checked", _clean_detection_item(live))
    withheld_prerun_tools = [
        (tool.name, tool.reason) for tool in tools.withheld if tool.name in prerun_tools()
    ]
    families = not_evaluated_families(context.ir, withheld_prerun_tools, standards, live=live)
    for family in families:
        context.record_coverage(family.bucket, family.coverage_item())
    return PrerunResult(
        calls=tuple(calls),
        not_evaluated=families,
        families=tuple(session.folded_families),
        live=live,
        withheld=(
            withheld_tools(context, tools, calls) if efficiency.withhold_prerun_tools else ()
        ),
    )


def withheld_tools(
    context: ToolContext, tools: ToolDispatch, calls: Sequence[PrerunCall]
) -> tuple[str, ...]:
    """The check tools lever 13 takes off the array: the ones this pre-run ran to completion.

    `contracts/checks-first.md` section 7, one clause per row (research R2.53). A call
    *completed* when it has no error and a `repeat_key`, so the re-call guard can answer
    any repeat of it; a tool is a candidate only when every one of its calls completed and
    it is on the wire now - a tool a tier withheld was never offered, and is not this
    lever's to claim. "Completed" is `answers_repeat`, the rule the guard's ledger is built
    by, so every withheld tool's calls are in the ledger by construction.

    - The three RMS tools leave together, and only when each ran package-wide (no
      `document_id`): one step of the system prompt and one checklist sentence name all
      three, and a partial set would leave a sentence naming a tool that is not there.
    - `check_interference_group` leaves when every group `groups_of` now enumerates had a
      completed call, no key is shared by two groups (the tool judges only the active
      configuration's), and live detection is not offered: with a bridge the model can
      detect again and add groups only this tool judges.
    - Each of feature 010's `CODE_FIRST_CHECKS` leaves on its own.
    - `check_standards` leaves when a standards run is attached and its call completed.

    `bridge_interference` and `get_finding` are never candidates. Returned in pre-run order.
    """
    # Deferred: see `_deferred` above.
    from swreview.checks.standards.registry import CHECK_TOOL
    from swreview.tools.standards_checks import standards_run

    offered = {tool.name for tool in tools}
    made: dict[str, list[PrerunCall]] = {}
    for call in calls:
        made.setdefault(call.tool, []).append(call)

    def completed(name: str) -> bool:
        calls = made.get(name, [])
        return name in offered and bool(calls) and all(answers_repeat(call) for call in calls)

    withheld: list[str] = []
    if all(
        completed(name) and not any(call.arguments.get("document_id") for call in made[name])
        for name in RMS_PRERUN_TOOLS
    ):
        withheld.extend(RMS_PRERUN_TOOLS)
    if (
        completed(INTERFERENCE_TOOL)
        and LIVE_INTERFERENCE_TOOL not in offered
        and _every_group_judged(context.ir, made[INTERFERENCE_TOOL])
    ):
        withheld.append(INTERFERENCE_TOOL)
    withheld.extend(name for name in checks_mechanical.CODE_FIRST_CHECKS if completed(name))
    if completed(DRAWINGS_TOOL):
        withheld.append(DRAWINGS_TOOL)
    if standards_run(context) is not None and completed(CHECK_TOOL):
        withheld.append(CHECK_TOOL)
    return tuple(withheld)


def _every_group_judged(package: EvidencePackage, calls: Sequence[PrerunCall]) -> bool:
    """Every group has a judged call for its key, and no key names two groups."""
    keys = [group.group_key for group in groups_of(package)]
    judged = {call.arguments.get("group_key") for call in calls}
    return len(keys) == len(set(keys)) and set(keys) <= judged


def _prerun_call(
    context: ToolContext,
    tools: ToolDispatch,
    name: str,
    arguments: Mapping[str, Any],
    number: int,
) -> PrerunCall:
    """One pre-run call: `recorded_call` under the pre-run's own call id."""
    return recorded_call(context, tools, name, arguments, call_id=f"prerun_{number + 1}")


def recorded_call(
    context: ToolContext,
    tools: ToolDispatch,
    name: str,
    arguments: Mapping[str, Any],
    *,
    call_id: str,
) -> PrerunCall:
    """One call through the dispatch, with the events around it, as the session recorded it.

    The pre-run's calls are made here, and so is the one call a review makes between turns
    outside it: feature 011's drawing check, restated over the package a confirmed read
    reloaded (`agent/runner.ReviewRun.answer_evidence_batch`). Either way the call is one real
    step - its events, its findings' `tool_result_ids` and its tool-results file all the
    session's - numbered from the session's own step count.
    """
    session = context.require_session()
    before = len(session.findings)
    contacts_before = len(session.contacts)
    step_index = len(session.steps)
    result = call_tool(
        request=ToolCallRequest(call_id=call_id, name=name, arguments=dict(arguments)),
        tools=tools,
        on_event=context.emit_event,
        step_index=step_index,
        clock=perf_counter,
    )
    return PrerunCall(
        tool=name,
        arguments=dict(arguments),
        step_index=step_index,
        findings=tuple(session.findings[before:]),
        error=_error_of(result),
        contacts=tuple(session.contacts[contacts_before:]),
        payload=result.payload,
    )


def _live_precondition(context: ToolContext, tools: ToolDispatch) -> str | None:
    """Why live detection cannot run here, or `None` when it can (research R2.16).

    It needs the bridge - and the live tool the dispatch registers with it - and a root
    assembly with two components or more: a part, or an assembly of one, has nothing to
    interfere with.
    """
    if context.bridge is None or tools.get(LIVE_INTERFERENCE_TOOL) is None:
        return LIVE_NO_BRIDGE
    root = _root_document(context.ir)
    if root is None or root.kind != "assembly" or len(context.ir.components) < 2:
        return LIVE_NOT_ASSEMBLY
    return None


def _live_interference(
    context: ToolContext,
    tools: ToolDispatch,
    calls: list[PrerunCall],
    *,
    package_dir: Path | None,
    out_dir: Path | None,
) -> LiveOutcome:
    """Checks first's first call: live detection once, its rows judged next, and written.

    The reviewed configuration's rows are removed from the in-memory package before the
    call - the host numbers rows from `int:0001` on every request and `bridge_interference`
    drops a row whose id the package already holds, so a Retry would otherwise judge stale
    rows (the rule `PackageAppender.Merge` applies on the console) - and put back exactly
    as they were when the call fails. On success the rows the call added are what
    `planned_calls` then judges, the host's gaps are kept once, and both are merged into
    `out_dir/package.json` (`ir/loader.append_interference_run`). Nothing here raises: a
    failed call is the dispatch's own failed item, and a failed write is an outcome.
    """
    package = context.ir
    configuration = package.design.active_configuration
    settings = dict(PRERUN_INTERFERENCE_SETTINGS)
    reason = _live_precondition(context, tools)
    if reason is not None:
        return LiveOutcome(configuration=configuration, settings=settings, not_attempted=reason)

    original = list(package.interferences)
    package.interferences[:] = [row for row in original if row.configuration != configuration]
    kept = {id(row) for row in package.interferences}
    gaps_before = len(package.gaps)
    call = _prerun_call(
        context,
        tools,
        LIVE_INTERFERENCE_TOOL,
        {"component_ids": [], "configuration": configuration, "settings": settings},
        len(calls),
    )
    calls.append(call)
    if call.error is not None:
        package.interferences[:] = original
        return LiveOutcome(
            configuration=configuration,
            settings=settings,
            step_index=call.step_index,
            error=call.error,
        )

    added = [row for row in package.interferences if id(row) not in kept]
    added_ids = {id(row) for row in added}
    detected = call.payload.get("interferences") if call.payload is not None else None
    rows_detected = len(detected) if isinstance(detected, list) else len(added)
    new_gaps = _keep_new_gaps_once(package, gaps_before)
    groups = {
        (group.configuration, group.group_key)
        for group in groups_of(package)
        if any(id(row) in added_ids for row in group.interferences)
    }
    return LiveOutcome(
        configuration=configuration,
        settings=settings,
        step_index=call.step_index,
        groups=len(groups),
        rows_detected=rows_detected,
        rows_added=len(added),
        rows_collided=max(0, rows_detected - len(added)),
        persist_error=_persist_rows(package_dir, out_dir, configuration, added, new_gaps),
    )


def _keep_new_gaps_once(package: EvidencePackage, gaps_before: int) -> list[Gap]:
    """The gaps the call appended, less any the package already held; returns those kept.

    `bridge_interference` appends every gap the host reports, so a Retry would hold the
    volume-unit caveat twice in memory while the written file holds it once. The in-memory
    package is made to agree with the file, because a re-render reads the file.
    """
    earlier = package.gaps[:gaps_before]
    kept: list[Gap] = []
    for gap in package.gaps[gaps_before:]:
        if gap not in earlier and gap not in kept:
            kept.append(gap)
    package.gaps[gaps_before:] = kept
    return kept


def _persist_rows(
    package_dir: Path | None,
    out_dir: Path | None,
    configuration: str,
    rows: Sequence[Interference],
    gaps: Sequence[Gap],
) -> str | None:
    """Write the live rows into the run folder's package; the error as a sentence, or `None`."""
    if package_dir is None or out_dir is None:
        return "no run folder was given to this pre-run, so the rows were not written"
    try:
        append_interference_run(package_dir, out_dir, configuration, rows, gaps)
    except (OSError, ValueError) as error:
        return f"{type(error).__name__}: {error}"
    return None


def _clean_detection_item(live: LiveOutcome) -> CoverageItem:
    """A clean live detection, closed as `checked` within its stated scope (research R2.20).

    A statement about what SOLIDWORKS computed in one configuration with five stated
    settings - never a pass beyond it, which is what `STATIC_SCOPE_LIMIT` says.
    """
    clean = INTERFERENCE_CLEAN.format(
        configuration=live.configuration, settings=_settings_text(live.settings)
    )
    return CoverageItem(
        check=INTERFERENCE_CHECKLIST_ITEM,
        scope=CoverageScope(configuration=live.configuration),
        reason=f"{clean}; {STATIC_SCOPE_LIMIT}",
        error=None,
    )


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


# --- the re-call guard (feature 008, `contracts/checks-first.md` section 5) -------------------

ALREADY_RUN = "already_run"
"""The status a guarded repeat answers with."""

REPEAT_NOTE = (
    "Checks first ran this call before your first turn; its findings are in the session. "
    "It was not run again."
)
"""What a guarded repeat says, so the model reads why it got an outcome and not a run."""


def repeat_key(tool: str, arguments: Mapping[str, Any]) -> tuple[Any, ...] | None:
    """What makes a model's call the same question a pre-run call already answered, or `None`.

    The contract's table: an RMS part or equations call is one question whatever its
    `document_id` - a narrowed call over a graded document would append a second finding
    per condition, which is exactly the duplicate FR-012 forbids; the assembly, standards
    and feature 010 argument-free checks take nothing; a group call is keyed by its group;
    and the live call only when it is the whole assembly, keyed by its configuration and its
    settings (as sorted JSON, so key order does not matter). A component subset, and every
    tool not named here, is not a repeat.
    """
    # Deferred: see `_deferred` above.
    from swreview.checks.standards.registry import CHECK_TOOL

    if tool in (
        *RMS_PRERUN_TOOLS,
        CHECK_TOOL,
        *checks_mechanical.CODE_FIRST_CHECKS,
        DRAWINGS_TOOL,
    ):
        return (tool,)
    if tool == INTERFERENCE_TOOL:
        group_key = arguments.get("group_key")
        return (tool, group_key) if isinstance(group_key, str) else None
    if tool == LIVE_INTERFERENCE_TOOL:
        if arguments.get("component_ids") != []:
            return None
        settings = json.dumps(arguments.get("settings"), sort_keys=True, default=str)
        return (tool, arguments.get("configuration"), settings)
    return None


def answers_repeat(call: PrerunCall) -> bool:
    """Whether the guard answers a repeat of this pre-run call: it completed, and has a key.

    The one rule behind both the guard's ledger and lever 13's "completed" (`withheld_tools`):
    a tool leaves the array only when every one of its calls is in the ledger, so a model that
    calls it anyway is answered `already_run`, never run twice (FR-012, FR-030).
    """
    return call.error is None and repeat_key(call.tool, call.arguments) is not None


class PrerunGuard:
    """The run's `ToolSet` with the pre-run's answers in front of it (research R2.19).

    Wrapped directly around the dispatch in `start_review` when a pre-run ran - innermost,
    so lever 7's `CoverageStopTools` and the pane's Stop wrapper see a guarded answer like
    any other result. Its ledger holds the pre-run's **successful** calls by `repeat_key`; a
    call that matches one is answered with the recorded outcome and recorded as one real
    step through `registry.record_call` - status ok, no coverage, no finding - so the step
    indices the adapters count stay the session's. Everything else goes to the dispatch.
    Registers no tool: iterating it is iterating the dispatch, less the tools lever 13
    withheld (`PrerunResult.withheld`, feature 008 FR-030). Those leave the array the
    adapters encode and nothing else: `call` still reaches the ledger - every one of their
    pre-run calls is in it, which is what made them withheld - and the dispatch behind it
    still holds them, so a model that calls one anyway is answered, never told it does not
    exist.
    """

    def __init__(
        self, tools: ToolDispatch, prerun: PrerunResult, *, folded: Sequence[str]
    ) -> None:
        self.tools = tools
        self.live = prerun.live
        self.folded = tuple(folded)
        self.withheld = frozenset(prerun.withheld)
        self._ledger: dict[tuple[Any, ...], PrerunCall] = {}
        for call in prerun.calls:
            if answers_repeat(call):
                key = repeat_key(call.tool, call.arguments)
                assert key is not None  # `answers_repeat` holds only for a call with a key
                self._ledger.setdefault(key, call)

    def __iter__(self) -> Iterator[RecordedTool]:
        """The array the adapters encode, and the one the prompt's tool notes describe."""
        return (tool for tool in self.tools if tool.name not in self.withheld)

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def answer_repeats_with(self, call: PrerunCall) -> None:
        """Answer every later repeat of `call`'s question from `call`, not from the pre-run.

        Feature 011: a confirmed drawing read reloads the package, and `check_drawings` is
        restated over it (`recorded_call`); the pre-run's outcome then describes a package the
        session no longer has, so a model that repeats the check is answered from the restated
        call. A call that did not complete leaves no ledger entry, and the next repeat runs.
        """
        key = repeat_key(call.tool, call.arguments)
        if key is None:
            return
        if answers_repeat(call):
            self._ledger[key] = call
        else:
            self._ledger.pop(key, None)

    def call(self, name: str, arguments: Mapping[str, Any], call_id: str = "") -> ToolCallResult:
        """The recorded outcome for a repeat, or the dispatch's own answer for anything else."""
        key = repeat_key(name, arguments) if isinstance(arguments, Mapping) else None
        recorded = self._ledger.get(key) if key is not None else None
        if recorded is None:
            # An unknown name's error lists this array, not the dispatch's: a tool lever 13
            # withheld is "not offered to you this session", and is never named as available.
            return self.tools.call(
                name, arguments, call_id, offered=[tool.name for tool in self]
            )
        payload = {
            "status": ALREADY_RUN,
            "ran_at_step": recorded.step_index,
            "note": REPEAT_NOTE,
            "outcome": self._outcome(recorded),
        }
        record_call(
            self.tools.sink,
            tool=name,
            arguments=arguments,
            payload=payload,
            elapsed_s=0.0,
            error=None,
        )
        return ToolCallResult(call_id=call_id, payload=payload, is_error=False)

    def _outcome(self, recorded: PrerunCall) -> dict[str, Any]:
        """The digest of the recorded result: counts only for a folded family (FR-014)."""
        if recorded.tool == LIVE_INTERFERENCE_TOOL and self.live is not None:
            return {
                "groups": self.live.groups,
                "rows": self.live.rows_added,
                "configuration": self.live.configuration,
                "settings": dict(self.live.settings),
            }
        counts_only = recorded.tool in RMS_PRERUN_TOOLS and RMS_FAMILY.name in self.folded
        return check_digest(recorded.payload or {}, counts_only=counts_only)
