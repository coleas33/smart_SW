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
from itertools import combinations
from typing import TYPE_CHECKING, Any

from swreview.checks.fastener import HeadSweep
from swreview.checks.fastener_identity import (
    EnvelopeOf,
    RecognisedFastener,
    fastener_group,
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
from swreview.checks.mass import SUMMARY_CHECK as MASS_SUMMARY
from swreview.checks.mass import run_mass_checks
from swreview.checks.result import CheckResult, DocumentResult
from swreview.checks.tolerances import ResolverLookup
from swreview.checks.tool_access import recess_group, run_head_fit, sweep_head
from swreview.report.names import plural
from swreview.report.session import CoverageBucket, CoverageItem, CoverageScope
from swreview.tools.context import ToolContext, current_context
from swreview.tools.joint_context import BodyMeshes, joint_analysis
from swreview.tools.query import ToolResult
from swreview.tools.recording import record_result

if TYPE_CHECKING:  # the standards package reaches the runner; only the type is needed here
    from swreview.checks.hygiene import HygieneChecks
    from swreview.checks.mass import MassChecks
    from swreview.checks.standards.profile import StandardsProfile

__all__ = [
    "CODE_FIRST_CHECKS",
    "JOINT_MAP_CHECK",
    "check_hygiene",
    "check_joints",
    "check_mass_material",
    "record_joint_map",
]

CODE_FIRST_CHECKS: tuple[str, ...] = ("check_joints", "check_mass_material", "check_hygiene")
"""The argument-free check tools the pre-run calls, in order. Each must be in
`registry.check_tools()` and take no parameter; `test_code_first_registration.py` holds it
to both."""

SUMMARY_BUCKETS: tuple[CoverageBucket, ...] = ("checked", "skipped", "failed")
"""The buckets the mass and hygiene families' summary row can be in (T108, amended
2026-09-23). It is one row that moves between them, which `replace_coverage` - same check,
same bucket - cannot express on its own, so the others are cleared first."""

JOINT_MAP_CHECK = "joint.map"
"""The coverage check the joint map is recorded under. Not a checklist item id, so no row
of the map closes `holes.alignment` or `fasteners`; the findings on the joints do, by prefix
(`contracts/joint-map.md` section 7)."""


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
            f"{plural(len(joints), f'{kind} joint')}: "
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


def _attached_profile(context: ToolContext) -> StandardsProfile | None:
    """The profile of the standards run attached to the review, or `None`: the joint and
    hygiene checks read it, and never load one themselves.

    Imported here, as prerun and the registry import every standards module: a module under
    `checks/standards/` reaches `checks/rules/` and the runner, which import the pre-run,
    which imports this module (`prerun._deferred` says it once).
    """
    from swreview.tools.standards_checks import standards_run

    run = standards_run(context)
    return None if run is None else run.profile


def _head_sweeper(context: ToolContext, meshes: BodyMeshes) -> tuple[EnvelopeOf | None, str]:
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
    """Find every joint from the geometry and check it: alignment, stack-up, fastener
    identity, thread, engagement, bottoming, tool access and head fit.

    Notes:
        Takes no argument. A near miss is listed, never reported; what the map could not use
        is skipped coverage saying why.
    """
    context = current_context()
    session = context.require_session()
    findings_before = len(session.findings)

    analysis = joint_analysis(context)
    joint_map = analysis.joint_map
    written = record_joint_map(context, joint_map)
    lookup = ResolverLookup(context.ir, _attached_profile(context))
    checks = run_joint_checks(context.ir, joint_map, lookup)
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


def _record_documents(context: ToolContext, results: Sequence[DocumentResult]) -> ToolResult | None:
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


def _summary_bucket(
    written: Counter[CoverageBucket], findings: int, error: str | None
) -> CoverageBucket:
    """Where the family's summary row goes (T108, amended 2026-09-23).

    `failed` when a finding was refused, whatever the call recorded before it; `checked`
    only when the call wrote a `checked` per-check row or recorded a finding; `skipped`
    otherwise - a run that checked nothing (no standards profile, every part lightweight)
    must not read "checked" on the Review summary's goal line.
    """
    if error is not None:
        return "failed"
    if written["checked"] or findings:
        return "checked"
    return "skipped"


def _record_summary(
    context: ToolContext,
    check: str,
    written: Counter[CoverageBucket],
    *,
    documents: int,
    findings: int,
    error: str | None,
) -> None:
    """The family's one summary row, under its checklist item's id (feature 010 T108).

    The checklist matches coverage by id, never by prefix, and every other row these tools
    write is per check, so without this row a run with no finding would leave the item open
    (research R2.25). Its bucket is `_summary_bucket`'s, its reason what the call wrote and
    found, whatever the bucket, and its `error` the refusal of a `failed` call. One row
    across `SUMMARY_BUCKETS`, so a repeated call leaves one wherever the last call put it.
    It is not counted in `written`: the result's counts stay the per-check rows.
    """
    bucket = _summary_bucket(written, findings, error)
    coverage = context.require_session().coverage
    for other in SUMMARY_BUCKETS:
        if other != bucket:
            items = getattr(coverage, other)
            items[:] = [item for item in items if item.check != check]
    context.replace_coverage(
        check,
        bucket,
        CoverageItem(
            check=check,
            scope=CoverageScope(configuration=context.ir.design.active_configuration),
            reason=(
                f"{written['checked']} checked, {written['skipped']} skipped coverage item(s) "
                f"over {documents} document(s); {findings} finding(s)"
            ),
            error=error,
        ),
    )


def _record_family(
    context: ToolContext,
    check: str,
    checks: MassChecks | HygieneChecks,
    extra: dict[str, Any],
) -> ToolResult:
    """Record one family's run - its findings, its per-check rows, its summary row under
    `check` - and return the tool's counts, or the refusal of a finding.

    A refused finding stops the call before its per-check rows are written, as every check
    tool stops at one; the summary row is still written, `failed`, so the item's row and the
    goal line say a check failed rather than keep what an earlier call wrote. `failed` closes
    no checklist item, and finalization adds no close-out row beside the item's own `failed`
    row, so the saved session says the same (`runner.finalize_session`).
    """
    session = context.require_session()
    findings_before = len(session.findings)
    written: Counter[CoverageBucket] = Counter()
    refused = _record_documents(context, checks.findings)
    if refused is None:
        _record_coverage(context, written, "checked", checks.checked)
        _record_coverage(context, written, "skipped", checks.skipped)
    findings = session.findings[findings_before:]
    _record_summary(
        context,
        check,
        written,
        documents=checks.documents,
        findings=len(findings),
        error=None if refused is None else str(refused["error"]),
    )
    if refused is not None:
        return refused
    return _summary(
        findings=[finding.id for finding in findings],
        statuses=Counter(finding.status for finding in findings),
        written=written,
        extra={"documents": checks.documents, **extra},
    )


def check_mass_material() -> ToolResult:
    """Check every part has a material or a deliberate mass override, that its density fits
    the material, and flag assembly mass overrides.

    Notes:
        Takes no argument. Unread parts and bodies are counted, never assumed.
    """
    context = current_context()
    return _record_family(context, MASS_SUMMARY, run_mass_checks(context.ir), {})


def check_hygiene() -> ToolResult:
    """Check part numbers against file names, duplicate descriptions and part numbers,
    revisions, and suppressed or lightweight components.

    Notes:
        Takes no argument. Property names come from the attached standards profile; without
        one those checks are skipped.
    """
    # Deferred for the reason `_attached_profile` gives: hygiene reads a standards module.
    from swreview.checks.hygiene import SUMMARY_CHECK as HYGIENE_SUMMARY
    from swreview.checks.hygiene import run_hygiene_checks

    context = current_context()
    profile = _attached_profile(context)
    return _record_family(
        context,
        HYGIENE_SUMMARY,
        run_hygiene_checks(context.ir, profile),
        {"profile": "absent" if profile is None else "attached"},
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
