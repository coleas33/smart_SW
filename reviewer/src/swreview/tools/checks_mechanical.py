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
from itertools import combinations
from typing import Any

from swreview.checks.joint_alignment import run_joint_checks
from swreview.checks.joints import (
    Candidate,
    Joint,
    JointMap,
    JointMapGap,
    build_joint_map,
    fold_by_pattern,
    folded_result,
    joint_label,
)
from swreview.report.session import CoverageBucket, CoverageItem, CoverageScope
from swreview.tools.context import ToolContext, current_context
from swreview.tools.query import ToolResult
from swreview.tools.recording import record_result

__all__ = ["CODE_FIRST_CHECKS", "JOINT_MAP_CHECK", "check_joints", "record_joint_map"]

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


def record_joint_map(context: ToolContext, joint_map: JointMap) -> Counter[CoverageBucket]:
    """Write the map as coverage (`contracts/joint-map.md` section 7); return what was written.

    One `checked` item per pattern group, one `skipped` item per candidate and per gap -
    the package-level "no hole was extracted" and "the hole phase did not run" among them.
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
    return written


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

    joint_map = build_joint_map(context.ir)
    written = record_joint_map(context, joint_map)
    checks = run_joint_checks(context.ir, joint_map)
    for joints, result in fold_by_pattern([(item.joint, item.result) for item in checks.results]):
        recorded = record_result(
            context,
            folded_result(joints, result),
            component_ids=sorted({cid for joint in joints for cid in joint.component_ids}),
            tool_result_ids=[context.current_step_id],
        )
        if "error" in recorded:
            return recorded
    for item in checks.skipped:
        context.record_coverage("skipped", item)
        written["skipped"] += 1

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
            "unplaced_fasteners": len(joint_map.unplaced),
        },
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
