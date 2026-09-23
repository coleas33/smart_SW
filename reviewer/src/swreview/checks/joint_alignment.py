"""Joint alignment: every joint's offset against its clearance, and the stack-up (feature 010).

`contracts/alignment.md` is normative. Two checks run on every joint the joint map finds,
with no argument a model chooses:

- **`hole.nominal_alignment`** (FR-007, FR-008). At nominal sizes the axis offset a joint
  allows is the sum over its clearance holes of `(H - F) / 2`; a tapped hole centres the
  screw on its thread and adds nothing. That is ASME Y14.5's fixed-fastener relation for a
  screw into a tapped hole and the floating one for a pin or bolt through clearance holes
  (research R2.6). An offset beyond the sum is demonstrated with both numbers; a fastener
  that cannot pass a hole at all is a negative term, demonstrated too (R2.4). The allowed
  offset doubled is the position budget, reported as the callout the drawing should carry.
- **`hole.position_stack`** (FR-010). The worst case over the richest model whose
  contributors all have a tolerance from some source: size and position, or size only with
  every unresolved position named as an excluded effect, or unresolved naming what is
  missing (R2.7). A demonstrated finding fails at every permitted size; a pass holds at
  every one; anything between is suspected. No tolerance is ever assumed: every limit comes
  through a `ToleranceLookup`, and `checks/result.limits_mm` is its only reader.

The sizes (research R2.5): a hole's is its Hole Wizard diameter when the package has one,
else its bore measured from the faces, labelled; the fastener's is, in order, the measured
diameter of a pin face in a pin joint, the tapped hole's thread, or the size the clearance
hole was made for. A recognised screw (US4) will come first.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

from swreview import units
from swreview.checks.fastener import parse_thread
from swreview.checks.joints import HoleInstance, Joint, JointMap, native_size, plain_diameter_mm
from swreview.checks.result import (
    ROUNDING_ASSUMPTION,
    CheckResult,
    limits_mm,
    permitted_radial_offset_mm,
    round_length,
    unresolved,
)
from swreview.checks.tolerances import (
    SOURCE_LABELS,
    SOURCE_ORDER,
    NoSources,
    ResolvedTolerance,
    ToleranceLookup,
    ToleranceSubject,
    UnresolvedTolerance,
)
from swreview.findings import Calculation, Severity
from swreview.ir.models import EvidencePackage, Quantity
from swreview.report.session import CoverageItem, CoverageScope

__all__ = [
    "CHECK_NOMINAL",
    "CHECK_STACK",
    "ClearanceTerm",
    "FastenerSize",
    "JointChecks",
    "JointResult",
    "check_nominal_alignment",
    "check_position_stack",
    "fastener_size",
    "run_joint_checks",
    "tolerance_subjects",
]

CHECK_NOMINAL = "hole.nominal_alignment"
CHECK_STACK = "hole.position_stack"
FUNCTION_NOMINAL = "swreview.checks.joint_alignment.check_nominal_alignment"
FUNCTION_STACK = "swreview.checks.joint_alignment.check_position_stack"
FUNCTION_VERSION = "1"

Fixture = Literal["fixed", "floating"]

REQUIREMENT_NOMINAL = (
    "the members of a joint line up within the clearance its fastener leaves: half of each "
    "clearance hole's diameter less the fastener's, summed over the joint (the fixed- and "
    "floating-fastener relations of ASME Y14.5 at nominal size)"
)
REQUIREMENT_STACK = (
    "the members of a joint line up within the clearance its fastener leaves at every size "
    "and position its tolerances permit (worst case)"
)
NO_CLEARANCE_LIMIT = (
    "the joint has no clearance: the fit is line to line and any position error prevents assembly"
)
NOMINAL_EXCLUDED = [
    "size tolerances of the holes and the fastener (hole.position_stack covers them when "
    "tolerances are read)",
    "position tolerances of the holes",
    "form error of the hole walls and clearance in the thread",
]
STACK_EXCLUDED = [
    "form error of the hole walls and clearance in the thread",
    "statistical (RSS) combination: the stack is worst case",
]


# --- sizes -------------------------------------------------------------------------------


@dataclass(frozen=True)
class FastenerSize:
    """`F`: the fastener or pin a joint takes, and where the number came from."""

    mm: float
    source: str
    threaded: bool
    """A thread's nominal major diameter is the fastener at maximum material and needs no
    tolerance (the fixed-fastener convention); a pin's measured or drawn size does."""
    component_id: str | None = None
    face_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClearanceTerm:
    """One clearance hole's share of the joint's allowed offset: `(H - F) / 2`."""

    instance_id: str
    hole_id: str
    h_mm: float
    h_source: str
    f_mm: float
    f_source: str
    term_mm: float


def fastener_size(joint: Joint, package: EvidencePackage) -> FastenerSize | None:
    """`F` by research R2.5's precedence, or `None` when nothing in the package states it.

    A recognised screw placed in the joint comes first - its thread's nominal major
    diameter, the fastener at maximum material - unless its shank or its names contradict
    that size, when the next source speaks instead.
    """
    del package  # the recognised fastener is read from the joint, not the package
    placed = joint.fastener
    if placed is not None and placed.size_trusted and placed.fastener.thread_designation:
        nominal = parse_thread(placed.fastener.thread_designation).nominal_diameter
        if nominal is not None:
            return FastenerSize(
                mm=round_length(units.as_mm(nominal)),
                source=(
                    f"the thread of the recognised screw {placed.component_id} "
                    f"({placed.fastener.thread_designation})"
                ),
                threaded=True,
                component_id=placed.component_id,
            )
    if joint.kind == "pin" and joint.cylinders:
        member = joint.cylinders[0]
        return FastenerSize(
            mm=member.diameter_mm,
            source=f"the measured diameter of pin face {member.face_id} on {member.component_id}",
            threaded=False,
            component_id=member.component_id,
            face_ids=(member.face_id,),
        )
    for instance in joint.instances:
        designation = instance.hole.thread_designation
        if instance.is_tapped and designation:
            nominal = parse_thread(designation).nominal_diameter
            if nominal is not None:
                return FastenerSize(
                    mm=round_length(units.as_mm(nominal)),
                    source=f"the thread of the tapped hole {instance.hole_id} ({designation})",
                    threaded=True,
                )
    for instance in joint.instances:
        size = instance.hole.size
        if not instance.is_clearance or size is None:
            continue
        plain = plain_diameter_mm(size)
        thread = parse_thread(size).nominal_diameter
        if plain is not None:
            mm, threaded = plain, False
        elif thread is not None:
            mm, threaded = units.as_mm(thread), True
        else:
            continue
        return FastenerSize(
            mm=round_length(mm),
            source=(
                f"the fastener size the Hole Wizard hole {instance.hole_id} was made for ({size})"
            ),
            threaded=threaded,
        )
    return None


def _hole_size(instance: HoleInstance) -> tuple[float, str]:
    source = (
        "the Hole Wizard diameter"
        if instance.size_source == "hole_wizard"
        else "derived from the cylinder face"
    )
    return instance.size_mm, source


def _term_key(instance: HoleInstance, joint: Joint) -> str:
    """The hole id, or the instance id when the joint holds two instances of one hole."""
    same = [item for item in joint.instances if item.hole_id == instance.hole_id]
    return instance.hole_id if len(same) == 1 else instance.id


def _mm(value: float) -> Quantity:
    return Quantity(value=round_length(value), unit="mm")


def _number(value: float) -> str:
    return repr(round_length(value))


def _roles(joint: Joint) -> tuple[list[HoleInstance], list[HoleInstance]]:
    clearance = [item for item in joint.instances if item.is_clearance]
    unknown = [item for item in joint.instances if not item.is_clearance and not item.is_tapped]
    return clearance, unknown


def _unknown_role(check: str, instances: Sequence[HoleInstance], requirement: str) -> CheckResult:
    names = ", ".join(item.hole_id for item in instances)
    return unresolved(
        check,
        f"the role of {names} (its hole type is unknown), so its clearance",
        [item.id for item in instances],
        requirement=requirement,
        recommended_action=(
            f"Record the hole type of {names} in the model's Hole Wizard feature so the joint "
            "can be judged."
        ),
    )


def _no_fastener(check: str, joint: Joint, requirement: str) -> CheckResult:
    return unresolved(
        check,
        "the fastener size of the joint (no pin face, tapped thread or Hole Wizard size states it)",
        [item.id for item in joint.instances],
        requirement=requirement,
        recommended_action=(
            "Model the fastener or pin, or size its holes with Hole Wizard, so the joint's "
            "clearance can be computed."
        ),
    )


# --- hole.nominal_alignment --------------------------------------------------------------


def _callout(fixture: Fixture, terms: Sequence[ClearanceTerm], joint: Joint, allowed: float) -> str:
    if fixture == "fixed":
        tapped = ", ".join(
            dict.fromkeys(item.hole_id for item in joint.instances if item.is_tapped)
        )
        holes = ", ".join(dict.fromkeys(term.hole_id for term in terms))
        return (
            f"position ⌀{_number(2 * allowed)} total at nominal size, to be shared between "
            f"{holes} and the tapped {tapped} (fixed-fastener rule)"
        )
    zones = [(term.hole_id, round_length(term.h_mm - term.f_mm)) for term in terms]
    if len({zone for _, zone in zones}) == 1:
        holes = ", ".join(hole for hole, _ in zones)
        return (
            f"position ⌀{_number(zones[0][1])} at nominal size on each of {holes} "
            "(floating-fastener rule)"
        )
    first, *rest = zones
    parts = [f"⌀{_number(first[1])} at nominal size on {first[0]}"]
    parts.extend(f"⌀{_number(zone)} on {hole}" for hole, zone in rest)
    return f"position {', '.join(parts)} (floating-fastener rule)"


def check_nominal_alignment(
    joint: Joint, package: EvidencePackage, lookup: ToleranceLookup | None = None
) -> CheckResult | None:
    """`hole.nominal_alignment` for one joint, or `None` when it has no clearance hole.

    A joint of a screw face in a lone tapped hole has nothing to line up: the thread centres
    the screw and no other hole locates it, so there is no clearance to compare with. The
    tool records that as one coverage row rather than a verdict.

    `lookup`, when it resolves every size, adds the maximum-material zone to the callout
    (`contracts/alignment.md` section 2); it never changes the verdict.
    """
    clearance, unknown = _roles(joint)
    if not clearance and not unknown:
        return None
    if unknown:
        return _unknown_role(CHECK_NOMINAL, unknown, REQUIREMENT_NOMINAL)
    fastener = fastener_size(joint, package)
    if fastener is None:
        return _no_fastener(CHECK_NOMINAL, joint, REQUIREMENT_NOMINAL)

    terms = []
    inputs: dict[str, Quantity | str] = {"F": _mm(fastener.mm), "F_source": fastener.source}
    for instance in clearance:
        h_mm, h_source = _hole_size(instance)
        key = _term_key(instance, joint)
        inputs[f"H_{key}"] = _mm(h_mm)
        inputs[f"H_{key}_source"] = h_source
        diameter = native_size(instance.hole)
        if instance.size_source == "hole_wizard" and diameter is not None and diameter.unit != "mm":
            inputs[f"H_{key}_as_read"] = diameter
        terms.append(
            ClearanceTerm(
                instance_id=instance.id,
                hole_id=key,
                h_mm=h_mm,
                h_source=h_source,
                f_mm=fastener.mm,
                f_source=fastener.source,
                term_mm=round_length((h_mm - fastener.mm) / 2.0),
            )
        )

    fixture: Fixture = "fixed" if any(item.is_tapped for item in joint.instances) else "floating"
    allowed = round_length(sum(term.term_mm for term in terms))
    offset = joint.offset_mm
    callout = _callout(fixture, terms, joint, allowed)
    mmc = _maximum_material_zone(joint, package, fastener, clearance, lookup)
    if mmc is not None:
        callout = f"{callout}; ⌀{_number(mmc)} at maximum material"
    result: dict[str, Quantity | bool | str | float] = {
        "offset_mm": offset,
        "allowed_offset_mm": allowed,
        "fixture": fixture,
        "position_budget_mm": round_length(2 * allowed),
        "callout": callout,
        "fastener_mm": fastener.mm,
        "terms": "; ".join(
            f"{term.hole_id}: ({_number(term.h_mm)} - {_number(term.f_mm)}) / 2 = "
            f"{_number(term.term_mm)}"
            for term in terms
        ),
    }
    result.update({f"term_{term.hole_id}_mm": term.term_mm for term in terms})
    calculation = Calculation(
        model=CHECK_NOMINAL,
        inputs=inputs,  # type: ignore[arg-type]
        assumptions=[
            "sizes are nominal: each clearance hole at its drawn or measured size and the "
            "fastener at its nominal size, which for a thread is its maximum material size",
            "a tapped hole centres the screw on its thread and contributes no clearance",
            "the offset is the largest lateral distance of a member axis from the reference "
            "axis, measured on the reference axis's own line",
            ROUNDING_ASSUMPTION,
        ],
        excluded_effects=list(NOMINAL_EXCLUDED),
        result=result,
        units_out="mm",
        function=FUNCTION_NOMINAL,
        function_version=FUNCTION_VERSION,
    )

    blocked = [term for term in terms if term.term_mm < 0.0]
    if blocked:
        term = blocked[0]
        status, severity = "demonstrated", "high"
        observed = (
            f"A {_number(fastener.mm)} mm fastener cannot pass {term.hole_id} "
            f"({_number(term.h_mm)} mm): the hole is smaller than the fastener it must take"
        )
        action = (
            f"Enlarge {term.hole_id} or use the fastener it was made for; a "
            f"{_number(fastener.mm)} mm fastener cannot pass it."
        )
    elif offset > allowed:
        status, severity = "demonstrated", "high"
        observed = (
            f"The member axes are {_number(offset)} mm apart where the joint's clearance "
            f"allows {_number(allowed)} mm ({fixture} fastener)"
        )
        action = (
            "Bring the holes onto a common axis or open the clearance, and put the position "
            f"budget on the drawing: {callout}."
        )
    else:
        status, severity = "checked_within_scope", "info"
        observed = (
            f"The member axes are {_number(offset)} mm apart, within the {_number(allowed)} mm "
            f"the joint's clearance allows ({fixture} fastener)"
        )
        action = f"Carry the position budget on the drawing: {callout}."

    limits = [
        f"{CHECK_NOMINAL} compared nominal sizes only; {NOMINAL_EXCLUDED[0]} and "
        f"{NOMINAL_EXCLUDED[1]} were not included"
    ]
    if status == "checked_within_scope" and allowed == 0.0:
        limits.append(NO_CLEARANCE_LIMIT)
    return CheckResult(
        check=CHECK_NOMINAL,
        status=status,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        observed=observed,
        requirement=REQUIREMENT_NOMINAL,
        inputs=[item.id for item in joint.instances],
        calculation=calculation,
        coverage_limits=limits,
        recommended_action=action,
    )


# --- hole.position_stack -----------------------------------------------------------------


def _document_of(package: EvidencePackage, component_id: str | None) -> str | None:
    if component_id is None:
        return None
    component = next((item for item in package.components if item.id == component_id), None)
    return None if component is None else component.document_id


def _size_subjects(
    joint: Joint,
    package: EvidencePackage,
    fastener: FastenerSize | None,
    clearance: Sequence[HoleInstance],
) -> list[ToleranceSubject]:
    subjects = [
        ToleranceSubject(
            kind="hole_size",
            nominal_mm=instance.size_mm,
            document_id=_document_of(package, instance.component_id),
            face_ids=instance.face_ids,
            instance_id=instance.id,
            component_id=instance.component_id,
        )
        for instance in clearance
    ]
    if fastener is not None and not fastener.threaded:
        subjects.append(
            ToleranceSubject(
                kind="pin_size",
                nominal_mm=fastener.mm,
                document_id=_document_of(package, fastener.component_id),
                face_ids=fastener.face_ids,
                component_id=fastener.component_id,
            )
        )
    return subjects


def _position_subject(instance: HoleInstance, package: EvidencePackage) -> ToleranceSubject:
    return ToleranceSubject(
        kind="hole_position",
        nominal_mm=instance.size_mm,
        document_id=_document_of(package, instance.component_id),
        face_ids=instance.face_ids,
        instance_id=instance.id,
        component_id=instance.component_id,
    )


def tolerance_subjects(joint: Joint, package: EvidencePackage) -> list[ToleranceSubject]:
    """Every subject `hole.position_stack` asks its lookup about for `joint`: each clearance
    hole's size, the pin's when the fastener is known and is not threaded, then every
    instance's position. Feature 011's drawing brief lists them with what each resolves to,
    so the brief and the stack-up cannot name different subjects (011 FR-042)."""
    clearance, _ = _roles(joint)
    sizes = _size_subjects(joint, package, fastener_size(joint, package), clearance)
    return [*sizes, *(_position_subject(instance, package) for instance in joint.instances)]


def _maximum_material_zone(
    joint: Joint,
    package: EvidencePackage,
    fastener: FastenerSize,
    clearance: Sequence[HoleInstance],
    lookup: ToleranceLookup | None,
) -> float | None:
    """`H_min - F_max` summed as a zone, when every size resolves; `None` otherwise."""
    if lookup is None or not clearance:
        return None
    resolved = [
        lookup.resolve(subject) for subject in _size_subjects(joint, package, fastener, clearance)
    ]
    if any(isinstance(item, UnresolvedTolerance) for item in resolved):
        return None
    f_max = fastener.mm
    holes = []
    for item in resolved:
        assert isinstance(item, ResolvedTolerance)
        limits = limits_mm(item.dimension)
        if item.subject.kind == "pin_size":
            f_max = limits.max_mm
        else:
            holes.append(limits.min_mm)
    return round_length(sum(h_min - f_max for h_min in holes))


def check_position_stack(
    joint: Joint, package: EvidencePackage, lookup: ToleranceLookup
) -> CheckResult | None:
    """`hole.position_stack` for one joint, or `None` when it has no clearance hole.

    The model is the richest whose contributors all resolve (research R2.7): with every
    size and every position, `size_and_position`; with every size and a position missing,
    `size_only`, each missing position named in `excluded_effects`; with a size missing,
    unresolved, naming it and every source searched.
    """
    clearance, unknown = _roles(joint)
    if not clearance and not unknown:
        return None
    if unknown:
        return _unknown_role(CHECK_STACK, unknown, REQUIREMENT_STACK)
    fastener = fastener_size(joint, package)
    if fastener is None:
        return _no_fastener(CHECK_STACK, joint, REQUIREMENT_STACK)

    sizes = [
        (subject, lookup.resolve(subject))
        for subject in _size_subjects(joint, package, fastener, clearance)
    ]
    missing = [answer for _, answer in sizes if isinstance(answer, UnresolvedTolerance)]
    if missing:
        first = missing[0]
        result = unresolved(
            CHECK_STACK,
            f"a tolerance for {first.subject.label}",
            [item.id for item in joint.instances],
            requirement=REQUIREMENT_STACK,
            recommended_action=(
                f"Tolerance {first.subject.label} on the drawing or in the model, or declare "
                "the general tolerance in the standards profile, and re-run the review."
            ),
        )
        return _with_limits(
            result,
            [f"{answer.subject.label}: searched {answer.searched_text()}" for answer in missing],
        )

    positions = [
        (instance, lookup.resolve(_position_subject(instance, package)))
        for instance in joint.instances
    ]
    open_positions = [answer for _, answer in positions if isinstance(answer, UnresolvedTolerance)]
    model = "size_only" if open_positions else "size_and_position"
    zone = 0.0
    if not open_positions:
        zone = round_length(
            sum(
                permitted_radial_offset_mm(units.as_mm(answer.dimension.nominal))
                for _, answer in positions
                if isinstance(answer, ResolvedTolerance)
            )
        )

    inputs: dict[str, Quantity | str] = {}
    f_min = f_max = fastener.mm
    holes: list[tuple[str, float, float]] = []
    limits_text: list[str] = []
    for subject, answer in sizes:
        assert isinstance(answer, ResolvedTolerance)
        limits = limits_mm(answer.dimension)
        label = subject.instance_id or "fastener"
        inputs[f"{label}_min"] = _mm(limits.min_mm)
        inputs[f"{label}_max"] = _mm(limits.max_mm)
        inputs[f"{label}_source"] = f"{SOURCE_LABELS[answer.source_kind]}: {answer.cited}"
        if answer.conflict:
            limits_text.append(answer.conflict)
        if subject.kind == "pin_size":
            f_min, f_max = limits.min_mm, limits.max_mm
        else:
            holes.append((subject.instance_id or "", limits.min_mm, limits.max_mm))
    for instance, answer in positions:
        if isinstance(answer, ResolvedTolerance):
            inputs[f"{instance.id}_position_zone"] = answer.dimension.nominal  # type: ignore[assignment]
            inputs[f"{instance.id}_position_source"] = (
                f"{SOURCE_LABELS[answer.source_kind]}: {answer.cited}"
            )
            if answer.conflict:
                limits_text.append(answer.conflict)
    inputs["F_source"] = fastener.source

    c_min = round_length(sum((h_min - f_max) / 2.0 for _, h_min, _ in holes))
    c_max = round_length(sum((h_max - f_min) / 2.0 for _, _, h_max in holes))
    offset = joint.offset_mm
    excluded = list(STACK_EXCLUDED)
    excluded.extend(
        f"{answer.subject.label} (no tolerance: searched {answer.searched_text()})"
        for answer in open_positions
    )
    status: str
    severity: Severity
    if round_length(max(0.0, offset - zone)) > c_max:
        status, severity = "demonstrated", "high"
        observed = (
            f"The member axes are {_number(offset)} mm apart and even the largest clearance "
            f"the tolerances permit allows {_number(c_max)} mm ({model.replace('_', ' ')})"
        )
        action = "Bring the holes onto a common axis or open the clearance and its tolerances."
    elif round_length(offset + zone) <= c_min:
        status, severity = "checked_within_scope", "info"
        observed = (
            f"The member axes are {_number(offset)} mm apart, within the {_number(c_min)} mm "
            f"the smallest permitted clearance allows ({model.replace('_', ' ')})"
        )
        action = ""
    else:
        status, severity = "suspected", "medium"
        observed = (
            f"The member axes are {_number(offset)} mm apart: passes at some sizes within "
            f"tolerance and fails at others (clearance {_number(c_min)} to {_number(c_max)} mm, "
            f"{model.replace('_', ' ')})"
        )
        action = "Tighten the tolerances or open the clearance so every permitted size assembles."

    calculation = Calculation(
        model=CHECK_STACK,
        inputs=inputs,  # type: ignore[arg-type]
        assumptions=[
            "worst case: every contributor at the limit that hurts",
            "a thread's nominal major diameter is the fastener at maximum material and needs "
            "no tolerance (fixed-fastener convention)",
            "a position zone permits half its value as axis offset",
            ROUNDING_ASSUMPTION,
        ],
        excluded_effects=excluded,
        result={
            "model": model,
            "offset_mm": offset,
            "position_half_zones_mm": zone,
            "clearance_min_mm": c_min,
            "clearance_max_mm": c_max,
            "fastener_min_mm": round_length(f_min),
            "fastener_max_mm": round_length(f_max),
        },
        units_out="mm",
        function=FUNCTION_STACK,
        function_version=FUNCTION_VERSION,
    )
    limits = [f"{CHECK_STACK} is a worst-case stack over the {model.replace('_', ' ')} model"]
    limits.extend(limits_text)
    return CheckResult(
        check=CHECK_STACK,
        status=status,  # type: ignore[arg-type]
        severity=severity,
        observed=observed,
        requirement=REQUIREMENT_STACK,
        inputs=[item.id for item in joint.instances],
        calculation=calculation,
        coverage_limits=limits,
        recommended_action=action,
    )


def _with_limits(result: CheckResult, extra: Sequence[str]) -> CheckResult:
    return replace(result, coverage_limits=[*result.coverage_limits, *extra])


# --- every joint ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JointResult:
    """One check's verdict on one joint."""

    joint: Joint
    result: CheckResult


@dataclass(frozen=True)
class JointChecks:
    """What the joint checks found, and what they recorded as not evaluated."""

    results: tuple[JointResult, ...]
    skipped: tuple[CoverageItem, ...]


def _skipped(check: str, joints: Sequence[Joint], reason: str) -> CoverageItem:
    return CoverageItem(
        check=check,
        scope=CoverageScope(
            component_ids=sorted({cid for joint in joints for cid in joint.component_ids})
        ),
        reason=reason,
        error=None,
    )


def run_joint_checks(
    package: EvidencePackage, joint_map: JointMap, lookup: ToleranceLookup | None = None
) -> JointChecks:
    """Both checks over every joint, as plain values (`contracts/code-first.md` section 6).

    `lookup` defaults to `NoSources` until feature 010 US8's resolver exists. When the
    lookup holds no source at all, the stack is **one** skipped coverage item for every
    joint rather than an unresolved finding per joint (`contracts/alignment.md` section 4).
    A joint with no clearance hole is named once in a skipped item per check.
    """
    lookup = lookup or NoSources()
    results: list[JointResult] = []
    not_applicable: list[Joint] = []
    single: list[Joint] = []
    stacks = lookup.holds_any_source()
    for joint in joint_map.joints:
        nominal = check_nominal_alignment(joint, package, lookup if stacks else None)
        if nominal is None:
            not_applicable.append(joint)
            continue
        if len(joint.instances) + len(joint.cylinders) < 2:
            # A lone clearance instance and a screw placed by its origin: no second measured
            # axis, and the origin is on the hole's axis by construction (the placement rule),
            # so any verdict would be vacuous.
            single.append(joint)
            continue
        results.append(JointResult(joint, nominal))
        if stacks:
            stack = check_position_stack(joint, package, lookup)
            if stack is not None:
                results.append(JointResult(joint, stack))

    skipped: list[CoverageItem] = []
    if not_applicable:
        names = ", ".join(joint.id for joint in not_applicable)
        reason = (
            f"no clearance hole to line up in {names}: a tapped hole centres its screw on the "
            "thread and no other hole locates it"
        )
        skipped.append(_skipped(CHECK_NOMINAL, not_applicable, reason))
        if stacks:
            skipped.append(_skipped(CHECK_STACK, not_applicable, reason))
    if single:
        names = ", ".join(joint.id for joint in single)
        reason = (
            f"one measured member only in {names}: a screw placed by its origin in a clearance "
            "hole gives no second axis to line up, and the part it threads into has no "
            "extracted hole"
        )
        skipped.append(_skipped(CHECK_NOMINAL, single, reason))
        if stacks:
            skipped.append(_skipped(CHECK_STACK, single, reason))
    if not stacks and joint_map.joints:
        searched = ", ".join(SOURCE_LABELS[source] for source in SOURCE_ORDER)
        skipped.append(
            _skipped(
                CHECK_STACK,
                joint_map.joints,
                f"no tolerance source is read for this package; searched: {searched}",
            )
        )
    return JointChecks(results=tuple(results), skipped=tuple(skipped))
