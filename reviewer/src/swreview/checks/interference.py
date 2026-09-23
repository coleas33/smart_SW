"""Static interference, grouped by pattern and honoring exceptions (T066).

SOLIDWORKS does the detection; this module does everything the report needs around it.
Four rules from US3 live here:

- **Grouping (FR-011).** A screw pattern that hits the same boss six times is one
  condition, not six findings. The extractor derives `group_key` from the pattern ids of
  the two components; when it could not, the fallback here is the sorted pair of
  `pattern_id`-or-`component_id`, which collapses the same repeat without inventing a
  relationship between unrelated pairs.
- **No overall pass while anything is unknown (FR-019).** A `truncated` or `failed` pair
  is `unresolved`, and `run_coverage` emits an unresolved coverage item for every one of
  them, so a session that contains a truncated pair cannot be summarized as a pass. An
  exception never clears a truncated pair: there is nothing to except yet.
- **Volumes are reported as measured (FR-018).** The stored unit is what the extractor
  verified on the workstation (research R12); the mm3 value the severity threshold used
  is recorded next to it rather than replacing it (constitution Principle II).
- **Selected positions are not a motion study (FR-020).** `mechanism_positions_coverage`
  writes the sentence the constitution requires, in one place, so no caller can soften it.

Severity is a volume threshold and nothing more: above 1 mm3 an overlap is real material
that has to be machined away, at or below it the overlap is often a modelling artifact
(a fillet, a coincident face, a rounded thread profile). It is not a judgment about
whether the interference matters - that needs the design intent, which is the engineer's.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from swreview import units
from swreview.checks.fastener import parse_thread
from swreview.checks.fastener_identity import MeshOf, screw_extent, tapped_span_mm
from swreview.checks.joints import Joint, JointMap
from swreview.checks.result import CheckResult, round_length, unresolved
from swreview.exceptions import ExceptionStore, ReviewException
from swreview.findings import Calculation, Severity
from swreview.ir.models import EvidencePackage, Interference, Volume
from swreview.report.session import CoverageItem, CoverageScope, ReviewSession

__all__ = [
    "CHECK",
    "CONTACT_VOLUME_MM3",
    "EXCLUDED_EFFECTS",
    "SEVERITY_VOLUME_MM3",
    "VOLUME_TO_MM3",
    "ContactKind",
    "ContactVerdict",
    "GroupOutcome",
    "InterferenceGroup",
    "check_interference_group",
    "classify_group",
    "group_interferences",
    "interference_outcomes",
    "mechanism_positions_coverage",
    "run_coverage",
    "volume_mm3",
]

CHECK = "interference.static"
FUNCTION = "swreview.checks.interference.check_interference_group"
FUNCTION_VERSION = "1"

VOLUME_TO_MM3: dict[str, float] = {"mm3": 1.0, "in3": 16387.064, "m3": 1e9}
"""Exact conversions to mm3. One cubic inch is 16387.064 mm3 by the definition of the
inch as 25.4 mm; `swreview.units` converts lengths only, so the factor lives here."""

SEVERITY_VOLUME_MM3 = 1.0
"""Above this the overlap is material; at or below it, often a modelling artifact."""

CONTACT_VOLUME_MM3 = 1e-6
"""At or below this every member of a group is two parts touching, not overlapping (feature
010 research R2.9). A thousandth of a cubic micrometre: below any material meaning, and
named because a float 0.0 from the host may arrive as a denormal."""

ContactKind = Literal["zero_volume", "possible_only", "thread_model"]

PLACES = 9

EXCLUDED_EFFECTS = [
    "motion: only the extracted position of each component was evaluated",
    "tolerance excursions: nominal modelled geometry only",
    "deflection under load",
    "thermal growth",
    "coatings, platings and surface treatments",
]

STATIC_SCOPE_LIMIT = (
    f"{CHECK} evaluated the components as modelled in one configuration; clearance "
    "across any motion path was not established"
)

_STATUS_RANK = {"computed": 0, "truncated": 1, "failed": 2}
_WORST_STATUS = {rank: status for status, rank in _STATUS_RANK.items()}

InterferenceStatus = Literal["computed", "truncated", "failed"]


@dataclass(frozen=True)
class InterferenceGroup:
    """One condition: every interfering pair that repeats the same geometry.

    `component_ids` is the sorted union of the members' component instances - the
    instance list FR-011 asks the report to carry - and `status` is the worst status of
    any member, so one truncated pair makes the whole group unresolved.
    """

    group_key: str
    interferences: list[Interference]
    component_ids: list[str]
    configuration: str
    status: InterferenceStatus

    @property
    def check(self) -> str:
        """Lets a group be handed straight to `ExceptionStore.accept`."""
        return CHECK

    @property
    def pairs(self) -> list[list[str]]:
        return [list(item.component_ids) for item in self.interferences]


def volume_mm3(volume: Volume) -> float:
    """`volume` in mm3, whatever unit the extractor verified it in."""
    factor = VOLUME_TO_MM3.get(volume.unit)
    if factor is None:  # pragma: no cover - the IR restricts the unit to three values
        raise ValueError(f"unknown volume unit {volume.unit!r}")
    return round(volume.value * factor, PLACES)


def _number(value: float) -> str:
    return repr(round(value, PLACES))


def _volume_text(volume: Volume) -> str:
    """The volume as stored, with the mm3 the threshold used when that differs."""
    as_reported = f"{_number(volume.value)} {volume.unit}"
    if volume.unit == "mm3":
        return as_reported
    return f"{as_reported} ({_number(volume_mm3(volume))} mm3)"


def _effective_key(package: EvidencePackage, item: Interference) -> str:
    """`group_key` from the extractor, or the sorted pattern-or-instance pair.

    The fallback groups two pairs together only when both sides are the same pattern (or
    the same instance): `cmp:0001|pat:screws` collapses every screw of that pattern
    against that bracket, and nothing else.
    """
    if item.group_key:
        return item.group_key
    by_id = {component.id: component for component in package.components}
    parts = []
    for component_id in item.component_ids:
        component = by_id.get(component_id)
        parts.append(
            component.pattern_id if component is not None and component.pattern_id else component_id
        )
    return "|".join(sorted(parts))


def group_interferences(package: EvidencePackage) -> list[InterferenceGroup]:
    """Every interference in `package`, collapsed into one group per repeated condition.

    Groups are keyed by configuration as well as `group_key`: the same pair interfering in
    two configurations is two conditions, and a report that merged them could not say
    which configuration it was talking about. Order follows first appearance in the
    package, so the output is deterministic for a golden fixture.
    """
    members: dict[tuple[str, str], list[Interference]] = {}
    for item in package.interferences:
        members.setdefault((item.configuration, _effective_key(package, item)), []).append(item)

    groups = []
    for (configuration, key), items in members.items():
        component_ids = sorted({cid for item in items for cid in item.component_ids})
        worst = _WORST_STATUS[max(_STATUS_RANK[item.status] for item in items)]
        groups.append(
            InterferenceGroup(
                group_key=key,
                interferences=list(items),
                component_ids=component_ids,
                configuration=configuration,
                status=worst,  # type: ignore[arg-type]
            )
        )
    return groups


def _pairs_text(items: Sequence[Interference]) -> str:
    return ", ".join(f"{item.component_ids[0]}+{item.component_ids[1]}" for item in items)


def _repeat_text(group: InterferenceGroup) -> str:
    if len(group.interferences) == 1:
        return ""
    return (
        f"; the same condition repeats across {len(group.interferences)} pairs "
        f"({_pairs_text(group.interferences)})"
    )


def _requirement(group: InterferenceGroup) -> str:
    settings = group.interferences[0].settings
    return (
        f"No unintended static interference between components in configuration "
        f"{group.configuration}; detection settings: coincident faces "
        f"{'as interference' if settings.treat_coincident_as_interference else 'ignored'}, "
        f"subassemblies "
        f"{'as components' if settings.treat_subassemblies_as_components else 'as a whole'}, "
        f"multibody {'included' if settings.include_multibody else 'excluded'}, hidden "
        f"bodies {'ignored' if settings.ignore_hidden else 'included'}, fasteners folder "
        f"{settings.fastener_folder_treatment}"
    )


def _calculation(group: InterferenceGroup) -> Calculation | None:
    """The volumes and the settings, or `None` when no member reported a volume."""
    measured = [item for item in group.interferences if item.volume is not None]
    if not measured:
        return None
    settings = group.interferences[0].settings
    inputs: dict[str, object] = {"group_key": group.group_key, "configuration": group.configuration}
    for item in measured:
        assert item.volume is not None
        inputs[f"{item.id}_pair"] = f"{item.component_ids[0]}+{item.component_ids[1]}"
        inputs[f"{item.id}_volume_as_reported"] = f"{_number(item.volume.value)} {item.volume.unit}"
        inputs[f"{item.id}_volume_mm3"] = f"{_number(volume_mm3(item.volume))} mm3"
    for name, value in settings.model_dump().items():
        inputs[name] = str(value)

    volumes = [volume_mm3(item.volume) for item in measured if item.volume is not None]
    return Calculation(
        model=CHECK,
        inputs=inputs,  # type: ignore[arg-type]
        assumptions=[
            "the overlap volumes are SOLIDWORKS' own, computed with the settings recorded "
            "here; this check converts and compares them but does not recompute them",
            "the volume unit is the one the extractor verified on the workstation "
            "(IInterference.Volume units are undocumented)",
            f"an overlap above {SEVERITY_VOLUME_MM3} mm3 is treated as material rather "
            "than a modelling artifact",
        ],
        excluded_effects=list(EXCLUDED_EFFECTS),
        result={
            "member_count": float(len(group.interferences)),
            "measured_count": float(len(measured)),
            "max_volume_mm3": max(volumes),
            "total_volume_mm3": round(sum(volumes), PLACES),
            "group_key": group.group_key,
        },
        units_out="mm3",
        function=FUNCTION,
        function_version=FUNCTION_VERSION,
    )


def _inputs(group: InterferenceGroup) -> list[str]:
    return [
        f"{item.id} {item.component_ids[0]}+{item.component_ids[1]} "
        f"{item.configuration} {item.status} "
        + (f"{_number(item.volume.value)} {item.volume.unit}" if item.volume else "no volume")
        for item in group.interferences
    ]


def _fastener_text(group: InterferenceGroup) -> str:
    if not any(item.is_fastener for item in group.interferences):
        return ""
    return "; SOLIDWORKS reported this pair in the fasteners folder"


def check_interference_group(
    group: InterferenceGroup,
    package: EvidencePackage,
    exceptions: ExceptionStore | None = None,
) -> CheckResult:
    """The verdict on one grouped interference condition.

    Order of decision, and why:

    1. a `truncated` or `failed` member makes the whole group `unresolved`. Nothing is
       known about those pairs, so neither a volume nor an exception can speak for them;
    2. an `active` exception bound to these components and this configuration makes the
       group `checked_within_scope`, with the exception id in the coverage limits so the
       report still shows the condition and who accepted it;
    3. a `needs_review` exception makes the group `suspected`: the accepted condition no
       longer matches the geometry it was accepted for, so it neither clears nor
       re-raises on its own (FR-013);
    4. a measured overlap volume is `demonstrated` - the overlap is a fact SOLIDWORKS
       computed, not an inference;
    5. a possible interference (coincident or touching faces, no volume) is `suspected`.
    """
    if group.status != "computed":
        return _unresolved_group(group)

    exception = (
        None
        if exceptions is None
        else exceptions.match(package, group.component_ids, group.configuration, CHECK)
    )
    if exception is not None and exception.status == "active":
        return _excepted(group, exception)
    if exception is not None:
        return _needs_review(group, exception)
    return _reported(group)


@dataclass(frozen=True)
class ContactVerdict:
    """A group that is two parts touching at nominal size, not an interference (R2.9).

    The session's `Contact` is built from this by the tool that judged the group, because
    only the session knows the contact's id and the step that judged it.
    """

    kind: ContactKind
    group_key: str
    configuration: str
    interference_ids: tuple[str, ...]
    component_ids: tuple[str, ...]
    volume_mm3: float | None
    """The largest member volume in mm3; `None` when no member reported one."""
    reason: str
    joint_id: str | None = None


@dataclass(frozen=True)
class GroupOutcome:
    """What one detected group is: exactly one of a finding and a contact."""

    finding: CheckResult | None
    contact: ContactVerdict | None


def _plural_pairs(count: int) -> str:
    return f"{count} pair" if count == 1 else f"{count} pairs"


def _contact(group: InterferenceGroup) -> ContactVerdict | None:
    """Rule 4: every member touches - a volume at or below `CONTACT_VOLUME_MM3`, or none
    with the possible-interference flag - or `None` when any member overlaps."""
    for item in group.interferences:
        if item.volume is None:
            if not item.is_possible:
                return None
        elif volume_mm3(item.volume) > CONTACT_VOLUME_MM3:
            return None

    measured = [item for item in group.interferences if item.volume is not None]
    pair = f"{group.component_ids[0]} and {', '.join(group.component_ids[1:])}"
    if measured:
        largest = max(measured, key=lambda item: volume_mm3(item.volume))  # type: ignore[arg-type]
        assert largest.volume is not None
        kind: ContactKind = "zero_volume"
        volume: float | None = volume_mm3(largest.volume)
        reported = _volume_text(largest.volume)
    else:
        kind, volume = "possible_only", None
        reported = "no overlap volume, only a possible interference"
    return ContactVerdict(
        kind=kind,
        group_key=group.group_key,
        configuration=group.configuration,
        interference_ids=tuple(item.id for item in group.interferences),
        component_ids=tuple(group.component_ids),
        volume_mm3=volume,
        reason=(
            f"{pair} touch at nominal in configuration {group.configuration}: SOLIDWORKS "
            f"reported {reported} ({_plural_pairs(len(group.interferences))}); this is a "
            "contact, not an interference."
        ),
    )


def _thread_bound(
    item: Interference,
    joint_map: JointMap,
    package: EvidencePackage,
    mesh_of: MeshOf | None,
) -> tuple[Joint, float] | None:
    """The screw joint `item` is the thread model of, and the annulus volume that bounds it:
    `pi/4 (d^2 - D^2) L` in mm3 (research R2.10). `None` when the pair is not one joint's
    screw and tapped part, or any of `d`, `D`, `L` is not known exactly."""
    pair = set(item.component_ids)
    for joint in joint_map.joints:
        placed, tapped = joint.fastener, joint.tapped_instance
        if placed is None or tapped is None or pair != {placed.component_id, tapped.component_id}:
            continue
        if not placed.size_trusted or not tapped.axis_aligned:
            return None
        designation = placed.fastener.thread_designation
        major = None if designation is None else parse_thread(designation).nominal_diameter
        mesh = None if mesh_of is None or placed.shank_face_id else mesh_of(placed.component_id)
        extent = screw_extent(joint, package, mesh)
        if major is None or extent is None:
            return None
        low, high = tapped_span_mm(joint)
        overlap = round_length(min(extent.high_mm, high) - max(extent.low_mm, low))
        d = units.as_mm(major)
        if overlap <= 0.0 or d <= tapped.bore_mm:
            return None
        return joint, round(math.pi / 4.0 * (d**2 - tapped.bore_mm**2) * overlap, PLACES)
    return None


def _thread_model(
    group: InterferenceGroup,
    joint_map: JointMap,
    package: EvidencePackage,
    mesh_of: MeshOf | None,
) -> ContactVerdict | None:
    """Rule 5: every member is a screw overlapping the part it threads into by no more than
    the annulus its modelled thread explains; `None` when any member is anything else."""
    bounds: list[tuple[Interference, Joint, float]] = []
    for item in group.interferences:
        if item.volume is None:
            return None
        found = _thread_bound(item, joint_map, package, mesh_of)
        if found is None or volume_mm3(item.volume) > found[1]:
            return None
        bounds.append((item, *found))

    item, joint, bound = max(
        bounds,
        key=lambda entry: volume_mm3(entry[0].volume),  # type: ignore[arg-type]
    )
    assert item.volume is not None
    pair = f"{group.component_ids[0]} and {', '.join(group.component_ids[1:])}"
    joints = ", ".join(dict.fromkeys(entry[1].id for entry in bounds))
    return ContactVerdict(
        kind="thread_model",
        group_key=group.group_key,
        configuration=group.configuration,
        interference_ids=tuple(entry.id for entry in group.interferences),
        component_ids=tuple(group.component_ids),
        volume_mm3=volume_mm3(item.volume),
        reason=(
            f"{pair} overlap in configuration {group.configuration} by "
            f"{_volume_text(item.volume)} ({_plural_pairs(len(group.interferences))}), within "
            f"the {_number(bound)} mm3 a thread modelled as a cylinder explains in joint "
            f"{joints}; this is a contact of the thread model, not an interference."
        ),
        joint_id=joint.id,
    )


def classify_group(
    group: InterferenceGroup,
    package: EvidencePackage,
    exceptions: ExceptionStore | None = None,
    joint_map: JointMap | None = None,
    mesh_of: MeshOf | None = None,
) -> GroupOutcome:
    """Whether one grouped condition is a finding or a contact (feature 010 `contracts/
    contacts.md` section 1), first rule that matches:

    1. an uncomputed member: the `unresolved` finding of today;
    2. an `active` exception: the excepted finding of today;
    3. a `needs_review` exception: the `suspected` finding of today;
    4. every member touching - no volume above `CONTACT_VOLUME_MM3`, or no volume and the
       possible flag - a **contact**, never a finding (owner decision 2026-09-23);
    5. with a `joint_map`, every member a screw overlapping the part it threads into by no
       more than `pi/4 (d^2 - D^2) L`, the annulus a thread modelled as a cylinder explains:
       a **thread-model contact** linked to the joint (research R2.10). `mesh_of` gives a
       screw with no extracted face its extent along the joint;
    6. otherwise the finding of today, a positive volume `demonstrated`.

    Rules 1 to 3 and 6 are `check_interference_group`'s verdicts unchanged, byte for byte.
    """
    if group.status == "computed":
        exception = (
            None
            if exceptions is None
            else exceptions.match(package, group.component_ids, group.configuration, CHECK)
        )
        if exception is None:
            contact = _contact(group)
            if contact is None and joint_map is not None:
                contact = _thread_model(group, joint_map, package, mesh_of)
            if contact is not None:
                return GroupOutcome(finding=None, contact=contact)
    return GroupOutcome(
        finding=check_interference_group(group, package, exceptions), contact=None
    )


def _unresolved_group(group: InterferenceGroup) -> CheckResult:
    unknown = [item for item in group.interferences if item.status != "computed"]
    errors = sorted({item.error for item in unknown if item.error})
    detail = f": {'; '.join(errors)}" if errors else ""
    return unresolved(
        CHECK,
        f"the interference result for {_pairs_text(unknown)} in configuration "
        f"{group.configuration} (detection reported "
        f"{', '.join(sorted({item.status for item in unknown}))}{detail})",
        _inputs(group),
        requirement=_requirement(group),
        recommended_action=(
            "Re-run interference detection for these pairs without truncation (raise or "
            "remove the pair limit, resolve the components) and re-check; do not report "
            "the assembly as clear while they are unknown."
        ),
    )


def _excepted(group: InterferenceGroup, exception: ReviewException) -> CheckResult:
    base = _reported(group)
    return CheckResult(
        check=CHECK,
        status="checked_within_scope",
        severity="info",
        observed=(
            f"{base.observed}. This condition is excepted by {exception.id}, accepted by "
            f"{exception.accepted_by} on {exception.accepted_at} for this geometry and "
            f"configuration: {exception.note}"
        ),
        requirement=_requirement(group),
        inputs=_inputs(group),
        calculation=base.calculation,
        coverage_limits=[f"exception:{exception.id}", STATIC_SCOPE_LIMIT],
        recommended_action=(
            f"None while the geometry is unchanged. Re-review {exception.id} if these "
            "components or this configuration change."
        ),
    )


def _needs_review(group: InterferenceGroup, exception: ReviewException) -> CheckResult:
    base = _reported(group)
    return CheckResult(
        check=CHECK,
        status="suspected",
        severity=base.severity,
        observed=(
            f"{base.observed}. Exception {exception.id} was accepted for this condition "
            "but the geometry or configuration it was bound to has changed, so it does "
            "not clear this finding"
        ),
        requirement=_requirement(group),
        inputs=_inputs(group),
        calculation=base.calculation,
        coverage_limits=[
            f"exception_needs_review:{exception.id}",
            STATIC_SCOPE_LIMIT,
        ],
        recommended_action=(
            f"Re-review exception {exception.id}: confirm the changed condition is still "
            "intended and re-accept it, or retire it and address the interference."
        ),
    )


def _reported(group: InterferenceGroup) -> CheckResult:
    """The verdict from the detection results alone, before any exception is applied."""
    measured = [item for item in group.interferences if item.volume is not None]
    pair = f"{group.component_ids[0]} and {', '.join(group.component_ids[1:])}"

    if measured:
        volumes = [volume_mm3(item.volume) for item in measured if item.volume is not None]
        worst = max(volumes)
        severity: Severity = "high" if worst > SEVERITY_VOLUME_MM3 else "medium"
        largest = max(measured, key=lambda item: volume_mm3(item.volume))  # type: ignore[arg-type]
        assert largest.volume is not None
        observed = (
            f"Static interference between {pair} in configuration {group.configuration}: "
            f"largest overlap volume {_volume_text(largest.volume)}"
            f"{_fastener_text(group)}{_repeat_text(group)}"
        )
        status = "demonstrated"
        action = (
            "Confirm whether this overlap is intended. If it is (a press fit, a thread "
            "modelled as a cylinder), accept an exception bound to this geometry and "
            "configuration; otherwise revise the parts or their mates."
        )
    else:
        severity = "medium"
        status = "suspected"
        observed = (
            f"Possible interference between {pair} in configuration {group.configuration}: "
            "SOLIDWORKS reported the faces as coincident or touching and gave no overlap "
            f"volume{_fastener_text(group)}{_repeat_text(group)}"
        )
        action = (
            "Decide whether the contact is intended. Re-run detection with coincident "
            "faces treated as interference to obtain a volume, or inspect the pair in "
            "SOLIDWORKS."
        )

    return CheckResult(
        check=CHECK,
        status=status,  # type: ignore[arg-type]
        severity=severity,
        observed=observed,
        requirement=_requirement(group),
        inputs=_inputs(group),
        calculation=_calculation(group),
        coverage_limits=[STATIC_SCOPE_LIMIT],
        recommended_action=action,
    )


def interference_outcomes(
    session: ReviewSession, package: EvidencePackage | None
) -> dict[str, int]:
    """The one count of every detected group and what became of it (feature 010
    `contracts/contacts.md` section 5).

    `groups` is every group the package reports when it is given - which equals
    `findings + contacts` once every group has been judged, the acceptance tests' check of
    FR-001 - and what this session judged when it is not. `unresolved` and `excepted` are
    subsets of `findings`.
    """
    findings = [finding for finding in session.findings if finding.check == CHECK]
    judged = len(findings) + len(session.contacts)
    return {
        "groups": judged if package is None else len(group_interferences(package)),
        "findings": len(findings),
        "contacts": len(session.contacts),
        "unresolved": sum(1 for finding in findings if finding.status == "unresolved"),
        "excepted": sum(
            1
            for finding in findings
            if finding.exception_id is not None and finding.status == "checked_within_scope"
        ),
    }


def run_coverage(
    package: EvidencePackage, interferences: Sequence[Interference] | None = None
) -> list[CoverageItem]:
    """One unresolved coverage item per truncated or failed pair.

    These belong in `Coverage.unresolved`. Their presence is what stops a run from being
    summarized as a pass while any pair went uncomputed (FR-019): the report says which
    pairs, in which configuration, and why.

    `interferences` narrows the sweep to a subset - one group's members, when a check tool
    has just judged that group - and defaults to every interference in the package.
    """
    return [
        CoverageItem(
            check=CHECK,
            scope=CoverageScope(
                component_ids=list(item.component_ids),
                pairs=[list(item.component_ids)],
                configuration=item.configuration,
            ),
            reason=(
                f"interference detection {item.status} for "
                f"{item.component_ids[0]}+{item.component_ids[1]} in configuration "
                f"{item.configuration}; the pair was not evaluated"
            ),
            error=item.error,
        )
        for item in (package.interferences if interferences is None else interferences)
        if item.status != "computed"
    ]


def mechanism_positions_coverage(positions: Sequence[str]) -> CoverageItem:
    """The sentence the constitution requires when a mechanism is checked at positions.

    Checking selected positions of a mechanism does not establish clearance across its
    motion path, and the report must say so (Principle VI, FR-020). An empty position
    list raises: a coverage item claiming nothing was checked is not a coverage item.
    """
    if not positions:
        raise ValueError("a mechanism coverage item needs at least one position checked")
    return CoverageItem(
        check=CHECK,
        scope=CoverageScope(positions=list(positions)),
        reason=(
            f"positions checked: {', '.join(positions)}; clearance across the full "
            "motion path was not established"
        ),
        error=None,
    )
