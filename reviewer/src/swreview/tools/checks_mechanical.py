"""The mechanical checks of feature 010, and the one hook that runs them before the model.

`contracts/code-first.md` is normative. Every check here takes no argument a model chooses:
the joints come from the geometry, the masses and the properties from the package, so each
tool is a pure function of what was extracted and runs in the code-first pass - the pre-run
under lever 5 or lever 11 today, feature 008's pane default later - at no model round.

**`CODE_FIRST_CHECKS` is the only hook into the pre-run** (research R2.20). It names the
argument-free check tools in the order the pre-run calls them; `prerun.planned_calls` reads
it and plans `(name, {})` for each one the run did not withhold, after the interference
groups and before `check_standards`. A check that needed its own pre-run branch, or its own
memory of having run, would be a second copy of what feature 008 owns. The tuple grows with
the stories: `check_joints` (US2), then `check_mass_material` (US6) and `check_hygiene` (US7).

**Each tool is a thin wrapper** over a plain function of the package (`build_joint_map` and
the checks that run on it), usable from a test or a script with no session, and returns
counts rather than a payload the model has to page through (`contracts/code-first.md`
section 3). A second call records again, exactly as a second `check_rms_part` does; answering
repeats is feature 008's re-call guard, in one place.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import Any

import trimesh

from swreview.checks.fastener import HeadSweep
from swreview.checks.fastener_identity import (
    EnvelopeOf,
    RecognisedFastener,
    fastener_group,
    joint_map_with_fasteners,
    run_fastener_checks,
)
from swreview.checks.joint_alignment import JointResult, run_joint_checks
from swreview.checks.joints import (
    Candidate,
    Joint,
    JointMap,
    JointMapGap,
    fold_by_pattern,
    folded_result,
    joint_label,
    pattern_group,
)
from swreview.checks.mass import DocumentResult, run_mass_checks
from swreview.checks.result import CheckResult
from swreview.checks.tool_access import recess_group, run_head_fit, sweep_head
from swreview.report.session import CoverageBucket, CoverageItem, CoverageScope
from swreview.tools.context import ToolContext, current_context
from swreview.tools.measure import load_body_mesh
from swreview.tools.query import ToolResult
from swreview.tools.recording import record_result

__all__ = [
    "CODE_FIRST_CHECKS",
    "JOINT_MAP_CHECK",
    "BodyMeshes",
    "JointAnalysis",
    "check_joints",
    "check_mass_material",
    "joint_analysis",
    "record_joint_map",
]

CODE_FIRST_CHECKS: tuple[str, ...] = ("check_joints",)
"""The argument-free check tools the pre-run calls, in order. Each must be in
`registry.check_tools()` and take no parameter; `test_code_first_registration.py` holds it
to both."""

JOINT_MAP_CHECK = "joint.map"
"""The coverage check the joint map is recorded under. Not a checklist item id, so no row
of the map closes `holes.alignment` or `fasteners`; the findings on the joints do, by prefix
(`contracts/joint-map.md` section 7)."""


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _pattern_item(joints: list[Joint], configuration: str) -> CoverageItem:
    components = sorted({cid for joint in joints for cid in joint.component_ids})
    pairs = sorted(
        {pair for joint in joints for pair in combinations(sorted(joint.component_ids), 2)}
    )
    kind = joints[0].kind
    return CoverageItem(
        check=JOINT_MAP_CHECK,
        scope=CoverageScope(
            component_ids=components,
            pairs=[list(pair) for pair in pairs],
            configuration=configuration,
        ),
        reason=(
            f"{_plural(len(joints), f'{kind} joint')}: "
            + ", ".join(joint_label(joint) for joint in joints)
        ),
        error=None,
    )


def _candidate_item(candidate: Candidate, configuration: str) -> CoverageItem:
    values = candidate.values
    a, b = candidate.members
    return CoverageItem(
        check=JOINT_MAP_CHECK,
        scope=CoverageScope(
            component_ids=sorted(set(candidate.component_ids)),
            pairs=[sorted(candidate.component_ids)],
            configuration=configuration,
        ),
        reason=(
            f"{a} and {b} are not a joint: {candidate.reason} (angle {values['angle_deg']!r} "
            f"deg, offset {values['offset_mm']!r} mm, radius sum {values['radius_sum_mm']!r} "
            f"mm, gap {values['gap_mm']!r} mm); listed for the engineer"
        ),
        error=None,
    )


def _gap_item(gap: JointMapGap) -> CoverageItem:
    return CoverageItem(
        check=JOINT_MAP_CHECK,
        scope=CoverageScope(component_ids=[gap.component_id] if gap.component_id else []),
        reason=gap.reason,
        error=None,
    )


def _unplaced_item(fastener: RecognisedFastener) -> CoverageItem:
    return CoverageItem(
        check=JOINT_MAP_CHECK,
        scope=CoverageScope(component_ids=[fastener.component_id]),
        reason=f"{fastener.designation} was not placed: {fastener.unplaced_reason}",
        error=None,
    )


def record_joint_map(context: ToolContext, joint_map: JointMap) -> Counter[CoverageBucket]:
    """Write the map as coverage (`contracts/joint-map.md` section 7); return what was written.

    One `checked` item per pattern group, one `skipped` item per candidate, per gap - the
    package-level "no hole was extracted" and "the hole phase did not run" among them - and
    per recognised fastener no rule placed.
    """
    configuration = context.ir.design.active_configuration
    written: Counter[CoverageBucket] = Counter()

    def record(bucket: CoverageBucket, item: CoverageItem) -> None:
        context.record_coverage(bucket, item)
        written[bucket] += 1

    by_id = {joint.id: joint for joint in joint_map.joints}
    for joint_ids in joint_map.pattern_groups().values():
        record("checked", _pattern_item([by_id[joint_id] for joint_id in joint_ids], configuration))
    for candidate in joint_map.candidates:
        record("skipped", _candidate_item(candidate, configuration))
    for gap in joint_map.gaps:
        record("skipped", _gap_item(gap))
    for fastener in joint_map.unplaced:
        record("skipped", _unplaced_item(fastener))
    return written


# --- what every joint check reads, once per context -------------------------------------------


@dataclass(frozen=True)
class JointAnalysis:
    """The recognised fasteners and the joint map they are placed in."""

    recognised: tuple[RecognisedFastener, ...]
    joint_map: JointMap


def joint_analysis(context: ToolContext) -> JointAnalysis:
    """The context's joint analysis, built on first use and kept on the context (T049), so
    `check_joints` and the interference tool's thread-model rule read one map, built once."""
    if context.joint_analysis is None:
        recognised, joint_map = joint_map_with_fasteners(context.ir)
        context.joint_analysis = JointAnalysis(recognised=recognised, joint_map=joint_map)
    analysis: JointAnalysis = context.joint_analysis
    return analysis


class BodyMeshes:
    """The package's body meshes by component, each loaded at most once per tool call.

    The tool layer's half of "pure but for the mesh load": the checks take a `mesh_of`
    callable and never open a file. A component whose bodies are absent or unloadable
    reads as `None` and its reason is kept, so a check can name it rather than skip it.
    """

    def __init__(self, context: ToolContext) -> None:
        self._context = context
        self._meshes: dict[str, trimesh.Trimesh | None] = {}
        self.reasons: dict[str, str] = {}

    def mesh_of(self, component_id: str) -> trimesh.Trimesh | None:
        if component_id not in self._meshes:
            bodies = [body for body in self._context.ir.bodies if body.component_id == component_id]
            loaded = []
            for body in bodies:
                mesh, reason = load_body_mesh(self._context, body)
                if mesh is None:
                    self.reasons[component_id] = reason or f"{component_id} body {body.id}"
                    loaded = []
                    break
                loaded.append(mesh)
            if not bodies:
                self.reasons[component_id] = f"{component_id} has no exported body mesh"
            self._meshes[component_id] = trimesh.util.concatenate(loaded) if loaded else None
        return self._meshes[component_id]


def _head_sweeper(
    context: ToolContext, meshes: BodyMeshes
) -> tuple[EnvelopeOf | None, str]:
    """What sweeps each placed screw's head, or `None` and why no sweep can be made.

    Every body the package holds is swept, the screw's own excluded. With lever 10a's lazy
    meshes nothing is fetched here - the code-first pass makes no bridge call - and every
    part component whose body was never fetched is named, never assumed clear
    (`contracts/tool-access.md` section 3). A package with no body mesh at all is one
    skipped item for every joint rather than an unresolved finding each.
    """
    package = context.ir
    lazy = context.extraction.meshes == "lazy"
    if not package.bodies:
        reason = "the package holds no body mesh"
        if lazy:
            reason += " (extracted with lazy meshes; check_joints fetches none)"
        return None, reason
    with_bodies = sorted({body.component_id for body in package.bodies})
    parts = {item.document_id for item in package.documents if item.kind == "part"}
    unfetched_parts = [
        component.id
        for component in package.components
        if lazy
        and component.suppression == "resolved"
        and component.document_id in parts
        and component.id not in with_bodies
    ]

    def sweep(joint: Joint) -> HeadSweep:
        assert joint.fastener is not None
        screw = joint.fastener.component_id
        return sweep_head(
            joint,
            package,
            screw_mesh=meshes.mesh_of(screw),
            others=[(cid, meshes.mesh_of(cid)) for cid in with_bodies if cid != screw],
            unfetched=[cid for cid in unfetched_parts if cid != screw],
        )

    return sweep, ""


def _record_folded(
    context: ToolContext,
    results: Sequence[JointResult],
    group_of: Callable[[Joint], str] = pattern_group,
) -> ToolResult | None:
    """Record `results` one finding per folded group; the error result if one is refused."""
    pairs = [(item.joint, item.result) for item in results]
    for joints, result in fold_by_pattern(pairs, group_of):
        recorded = record_result(
            context,
            folded_result(joints, result),
            component_ids=sorted({cid for joint in joints for cid in joint.component_ids}),
            tool_result_ids=[context.current_step_id],
        )
        if "error" in recorded:
            return recorded
    return None


def _record_identity(context: ToolContext, results: Sequence[CheckResult]) -> ToolResult | None:
    for result in results:
        recorded = record_result(
            context,
            result,
            component_ids=[str(item) for item in result.inputs],
            tool_result_ids=[context.current_step_id],
        )
        if "error" in recorded:
            return recorded
    return None


def check_joints() -> ToolResult:
    """Find every joint of the assembly from its geometry, and check how each lines up.

    Notes:
        Takes no argument. A joint is two or more parts whose holes - or a hole and a screw
        or pin face - share an axis: parallel, overlapping in projection and touching along
        it. Each pattern of joints is recorded as checked coverage; a pair that misses by a
        little is listed for the engineer, never reported, and every hole or face the map
        could not use is skipped coverage saying why. Each joint's offset is then checked
        against the clearance its fastener leaves, with the position budget as a callout,
        and a pattern of identical results is one finding naming every joint.
    """
    context = current_context()
    session = context.require_session()
    findings_before = len(session.findings)

    analysis = joint_analysis(context)
    joint_map = analysis.joint_map
    written = record_joint_map(context, joint_map)
    checks = run_joint_checks(context.ir, joint_map)
    refused = _record_folded(context, checks.results)
    if refused is not None:
        return refused

    meshes = BodyMeshes(context)
    envelope_of, no_sweep = _head_sweeper(context, meshes)
    fasteners = run_fastener_checks(
        context.ir,
        joint_map,
        analysis.recognised,
        mesh_of=meshes.mesh_of,
        envelope_of=envelope_of,
        no_sweep_reason=no_sweep,
    )
    refused = (
        _record_folded(context, fasteners.results, fastener_group)
        or _record_folded(context, run_head_fit(context.ir, joint_map), recess_group)
        or _record_identity(context, fasteners.identity)
    )
    if refused is not None:
        return refused
    _record_coverage(context, written, "skipped", (*checks.skipped, *fasteners.skipped))

    findings = session.findings[findings_before:]
    return _summary(
        findings=[finding.id for finding in findings],
        statuses=Counter(finding.status for finding in findings),
        written=written,
        extra={
            "joints": {
                "total": len(joint_map.joints),
                "by_kind": dict(Counter(joint.kind for joint in joint_map.joints)),
            },
            "pattern_groups": len(joint_map.pattern_groups()),
            "candidates": len(joint_map.candidates),
            "recognised_fasteners": len(analysis.recognised),
            "unplaced_fasteners": len(joint_map.unplaced),
        },
    )


def _record_documents(
    context: ToolContext, results: Sequence[DocumentResult]
) -> ToolResult | None:
    """Record document-scope results, each bound to its instances or, for the root, to its
    document; the error result if one is refused."""
    for item in results:
        recorded = record_result(
            context,
            item.result,
            component_ids=list(item.component_ids),
            document_ids=list(item.document_ids),
            tool_result_ids=[context.current_step_id],
        )
        if "error" in recorded:
            return recorded
    return None


def _record_coverage(
    context: ToolContext,
    written: Counter[CoverageBucket],
    bucket: CoverageBucket,
    items: Sequence[CoverageItem],
) -> None:
    for item in items:
        context.record_coverage(bucket, item)
        written[bucket] += 1


def check_mass_material() -> ToolResult:
    """Check every part has a material or a deliberate mass override, that its density fits
    its material, and flag assembly mass overrides.

    Notes:
        Takes no argument. Parts that pass the material rule are counted; unread parts and
        bodies are counted too, never assumed.
    """
    context = current_context()
    session = context.require_session()
    findings_before = len(session.findings)
    checks = run_mass_checks(context.ir)
    written: Counter[CoverageBucket] = Counter()
    refused = _record_documents(context, checks.findings)
    if refused is not None:
        return refused
    _record_coverage(context, written, "checked", checks.checked)
    _record_coverage(context, written, "skipped", checks.skipped)
    findings = session.findings[findings_before:]
    return _summary(
        findings=[finding.id for finding in findings],
        statuses=Counter(finding.status for finding in findings),
        written=written,
        extra={"documents": checks.documents},
    )


def _summary(
    *,
    findings: list[str],
    statuses: Counter[str],
    written: Counter[CoverageBucket],
    extra: dict[str, Any],
) -> ToolResult:
    """The counts every tool here returns (`contracts/code-first.md` section 3)."""
    return {
        "status": "recorded",
        "findings": len(findings),
        "by_status": dict(statuses),
        "finding_ids": findings,
        "coverage": {
            "checked": written["checked"],
            "skipped": written["skipped"],
            "unresolved": written["unresolved"],
        },
        **extra,
    }
