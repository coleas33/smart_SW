"""Fastener joint checks: bottoming, thread engagement, thread match, head clearance (T088).

One entry point, `check_fastener_joint`, returns one `CheckResult` per check, so a joint
that bottoms is still reported when its engagement rule is unknown. Every length goes
through `swreview.units` and lands in `Calculation.inputs` twice - as read and in
millimetres - so a finding can cite both (FR-023, constitution Principle II).

The sign conventions, once:

    protrusion = screw length - clamped stack - washers     (how far past the joint face)
    margin     = usable thread depth - protrusion           (negative means bottoming)
    engagement = min(protrusion, usable thread depth)       (threads actually engaged)
    ratio      = engagement / nominal thread diameter

`hole.thread_depth` is the *usable* thread depth and is never derived from `hole_depth`:
an unknown thread depth leaves both bottoming and engagement `unresolved`, because a
drill depth would clear joints a tapped depth would fail (constitution Principle I).

Joint kinds outside the pilot (`pin`, `nut`, `washer`, `other`) produce a single
`fastener.unsupported` result carrying `out_of_scope: <kind>`; the tool layer files that
in the `out_of_scope` coverage bucket, never as a pass (FR-024).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Literal

from swreview import units
from swreview.checks.engagement_rules import EngagementRules, MaterialRule, load_rules
from swreview.checks.result import (
    ROUNDING_ASSUMPTION,
    CheckResult,
    round_length,
    unresolved,
)
from swreview.findings import Calculation, Severity
from swreview.geometry.envelope import EnvelopeResult
from swreview.ir.models import Fastener, Hole, Quantity

__all__ = [
    "CHECK_BOTTOMING",
    "CHECK_ENGAGEMENT",
    "CHECK_HEAD_CLEARANCE",
    "CHECK_THREAD_MATCH",
    "CHECK_UNSUPPORTED",
    "EXCLUDED_EFFECTS",
    "FUNCTION_VERSION",
    "SUPPORTED_KINDS",
    "THROUGH_TAPPED_SOURCE",
    "ClampedLayer",
    "Placement",
    "ThreadSpec",
    "UsableThread",
    "check_fastener_joint",
    "check_placed_screw",
    "nominal_diameter",
    "parse_thread",
]

CHECK_BOTTOMING = "fastener.bottoming"
CHECK_ENGAGEMENT = "fastener.engagement"
CHECK_THREAD_MATCH = "fastener.thread_match"
CHECK_HEAD_CLEARANCE = "fastener.head_clearance"
CHECK_UNSUPPORTED = "fastener.unsupported"

FUNCTION = "swreview.checks.fastener.check_fastener_joint"
FUNCTION_VERSION = "1"

SUPPORTED_KINDS: tuple[str, ...] = ("screw", "bolt")
"""Joint kinds this check models. Everything else is reported out of scope (FR-024)."""

RATIO_EPS = 1e-9
"""A ratio exactly on the rule passes; only a real shortfall is a finding."""

DIAMETER_EPS_MM = 1e-6
"""Two nominal diameters closer than this are the same thread size."""

EXCLUDED_EFFECTS = [
    "thread form, class of fit, and the tolerance on the tapped depth",
    "preload, thread shear area and stripping strength",
    "chamfer, countersink and counterbore depth at the joint face",
    "gasket compression and joint settling",
]

_SEVERITY_BY_STATUS: dict[str, Severity] = {
    "unresolved": "medium",
    "checked_within_scope": "info",
}


@dataclass(frozen=True)
class ClampedLayer:
    """One component the screw clamps: what it is, how thick it is, what it is made of.

    `thickness is None` means the thickness could not be obtained; the checks that need
    the stack then stay unresolved and name this component.
    """

    component_id: str
    thickness: Quantity | None
    material: str | None = None


# --- thread designations ----------------------------------------------------------

ThreadSeries = Literal["metric", "unified"]

_WHITESPACE = re.compile(r"\s+")
_METRIC = re.compile(r"^M(\d+(?:\.\d+)?)(?:[X*](\d+(?:\.\d+)?))?(?:$|[^0-9.].*$)")
_NUMBER_SERIES = re.compile(r"^#(\d+)-(\d+)(?:$|[^0-9.].*$)")
_FRACTIONAL_INCH = re.compile(r"^(\d+)/(\d+)-(\d+)(?:$|[^0-9.].*$)")
_DECIMAL_INCH = re.compile(r"^(\d*\.\d+)-(\d+)(?:$|[^0-9.].*$)")

_MM_PER_INCH = 25.4
_NUMBER_SIZE_BASE_IN = 0.060
_NUMBER_SIZE_STEP_IN = 0.013
"""ASME number sizes: nominal diameter = 0.060 in + 0.013 in per size, so #10 is 0.190 in."""


@dataclass(frozen=True)
class ThreadSpec:
    """A thread designation parsed into the parts two threads are compared on."""

    text: str
    series: ThreadSeries | None
    nominal_diameter: Quantity | None
    pitch_mm: float | None
    normalized: str

    @property
    def recognized(self) -> bool:
        return self.series is not None


def _spec(
    text: str, series: ThreadSeries, diameter_mm: float, pitch_mm: float | None
) -> ThreadSpec:
    prefix = "M" if series == "metric" else "UN"
    pitch_part = "" if pitch_mm is None else f"X{round_length(pitch_mm):g}"
    return ThreadSpec(
        text=text,
        series=series,
        nominal_diameter=Quantity(value=round_length(diameter_mm), unit="mm"),
        pitch_mm=None if pitch_mm is None else round_length(pitch_mm),
        normalized=f"{prefix}{round_length(diameter_mm):g}{pitch_part}",
    )


def _tpi_to_pitch_mm(threads_per_inch: str) -> float:
    return _MM_PER_INCH / float(threads_per_inch)


def parse_thread(designation: str) -> ThreadSpec:
    """Parse `M6x1.0`, `1/4-20`, `#10-32` or `0.190-32` into a comparable `ThreadSpec`.

    Anything else comes back with `series=None` and no diameter: unrecognised, which the
    checks report as unresolved rather than guessing at a match. A designation with no
    pitch (`M6`) parses with `pitch_mm=None`; the comparison then uses diameter alone.
    """
    cleaned = _WHITESPACE.sub("", designation).upper()

    metric = _METRIC.match(cleaned)
    if metric is not None:
        pitch = metric.group(2)
        return _spec(
            designation, "metric", float(metric.group(1)), None if pitch is None else float(pitch)
        )

    number = _NUMBER_SERIES.match(cleaned)
    if number is not None:
        diameter_in = _NUMBER_SIZE_BASE_IN + _NUMBER_SIZE_STEP_IN * int(number.group(1))
        return _spec(
            designation,
            "unified",
            diameter_in * _MM_PER_INCH,
            _tpi_to_pitch_mm(number.group(2)),
        )

    fractional = _FRACTIONAL_INCH.match(cleaned)
    if fractional is not None:
        diameter_in = float(fractional.group(1)) / float(fractional.group(2))
        return _spec(
            designation,
            "unified",
            diameter_in * _MM_PER_INCH,
            _tpi_to_pitch_mm(fractional.group(3)),
        )

    decimal = _DECIMAL_INCH.match(cleaned)
    if decimal is not None:
        return _spec(
            designation,
            "unified",
            float(decimal.group(1)) * _MM_PER_INCH,
            _tpi_to_pitch_mm(decimal.group(2)),
        )

    return ThreadSpec(
        text=designation, series=None, nominal_diameter=None, pitch_mm=None, normalized=cleaned
    )


def nominal_diameter(designation: str) -> Quantity | None:
    """The nominal thread diameter in millimetres, or `None` if the designation is unread."""
    return parse_thread(designation).nominal_diameter


# --- the clamped stack -------------------------------------------------------------


CLAMPED_PROTRUSION = "protrusion = screw length - clamped stack - washers"
CLAMPED_POSE = "the screw is drawn fully home and square to the joint face"
PLACED_POSE = "the screw is where the assembly places it"


@dataclass
class _Stack:
    """What the bottoming and engagement checks share, computed once, in millimetres.

    `missing` holds noun phrases naming the values that could not be obtained; they are
    what the unresolved results report, so they read as "the length of fastener fst:1".

    `bottoming_derivation` and `engagement_derivation` say where the protrusion and the
    usable thread came from - the lines each rule function writes ahead of its own - and
    `pose` what is assumed about the screw's seat. A clamped stack derives its protrusion
    from a length and a list of layers; a placed screw measures it from the assembly
    (`check_placed_screw`), so the same four rule functions serve both.
    """

    length_mm: float | None = None
    clamped_mm: float | None = None
    washer_mm: float = 0.0
    thread_depth_mm: float | None = None
    protrusion_mm: float | None = None
    missing: list[str] = field(default_factory=list)
    inputs: dict[str, Quantity | str] = field(default_factory=dict)
    sources: list[Quantity | str] = field(default_factory=list)
    bottoming_derivation: list[str] = field(default_factory=lambda: [CLAMPED_PROTRUSION])
    engagement_derivation: list[str] = field(default_factory=list)
    pose: str = CLAMPED_POSE

    def missing_for(self, *keywords: str) -> list[str]:
        """The missing phrases that mention any of `keywords`, in table order."""
        return [phrase for phrase in self.missing if any(word in phrase for word in keywords)]


def _record(stack: _Stack, name: str, quantity: Quantity) -> float:
    """Convert one length to mm, keeping both the source and the converted value."""
    converted = units.convert(quantity, "mm")
    stack.inputs[name] = converted.source
    stack.inputs[f"{name}_mm"] = converted.converted
    stack.sources.append(converted.source)
    return converted.converted.value


def _build_stack(
    fastener: Fastener,
    hole: Hole,
    clamped: Sequence[ClampedLayer],
    washers: Sequence[Quantity],
) -> _Stack:
    stack = _Stack()
    stack.inputs["fastener_id"] = fastener.id
    stack.inputs["hole_id"] = hole.id

    if fastener.length is None:
        stack.missing.append(f"the length of fastener {fastener.id}")
    else:
        stack.length_mm = _record(stack, "fastener_length", fastener.length)

    if hole.thread_depth is None:
        stack.missing.append(f"the usable thread depth of hole {hole.id}")
    else:
        stack.thread_depth_mm = _record(stack, "usable_thread_depth", hole.thread_depth)

    if not clamped:
        stack.missing.append("the clamped stack (no clamped component was supplied)")
    else:
        total_mm: float | None = 0.0
        for index, layer in enumerate(clamped):
            if layer.thickness is None:
                stack.missing.append(f"the thickness of clamped component {layer.component_id}")
                total_mm = None
                continue
            thickness_mm = _record(stack, f"clamped_{index}_{layer.component_id}", layer.thickness)
            if total_mm is not None:
                total_mm += thickness_mm
        stack.clamped_mm = total_mm

    for index, washer in enumerate(washers):
        stack.washer_mm += _record(stack, f"washer_{index}", washer)

    if stack.length_mm is not None and stack.clamped_mm is not None:
        stack.protrusion_mm = round_length(stack.length_mm - stack.clamped_mm - stack.washer_mm)
    return stack


def _calculation(
    model: str,
    stack: _Stack,
    result: dict[str, Quantity | bool | str | float],
    assumptions: list[str],
    extra_inputs: dict[str, Quantity | str] | None = None,
) -> Calculation:
    return Calculation(
        model=model,
        inputs={**stack.inputs, **(extra_inputs or {})},
        assumptions=[*assumptions, ROUNDING_ASSUMPTION],
        excluded_effects=list(EXCLUDED_EFFECTS),
        result=result,
        units_out="mm",
        function=FUNCTION,
        function_version=FUNCTION_VERSION,
    )


def _limit(check: str, missing: Sequence[str]) -> str:
    """The coverage limit wording `swreview.checks.result.unresolved` produces."""
    return f"{check} not evaluated: {' and '.join(missing)} is unknown"


# --- the four checks ---------------------------------------------------------------

_BOTTOMING_REQUIREMENT = (
    "the screw must clamp the stack before its tip reaches the bottom of the usable "
    "thread: usable thread depth - protrusion >= 0"
)


def _bottoming(fastener: Fastener, hole: Hole, stack: _Stack) -> CheckResult:
    action = (
        f"Shorten {fastener.id}, deepen the tapped thread in {hole.id}, or add a washer, so "
        "the screw clamps the stack before it bottoms."
    )

    if hole.end_condition == "through":
        return CheckResult(
            check=CHECK_BOTTOMING,
            status="checked_within_scope",
            severity="info",
            observed=f"Hole {hole.id} is a through hole, so the screw cannot bottom in it.",
            requirement=_BOTTOMING_REQUIREMENT,
            inputs=list(stack.sources),
            calculation=_calculation(
                CHECK_BOTTOMING,
                stack,
                {"bottoming_possible": False, "end_condition": "through"},
                ["a through hole has no closed end for the screw tip to reach"],
            ),
            coverage_limits=[
                f"{CHECK_BOTTOMING} not applicable: hole {hole.id} is a through hole; what the "
                "screw protrudes into on the far side was not checked"
            ],
            recommended_action="",
        )

    if hole.end_condition != "blind":
        return unresolved(
            CHECK_BOTTOMING,
            f"the end condition of hole {hole.id}",
            stack.sources,
            requirement=_BOTTOMING_REQUIREMENT,
            recommended_action=f"Record whether {hole.id} is blind or through, then re-run.",
        )

    if stack.missing:
        return unresolved(
            CHECK_BOTTOMING,
            " and ".join(stack.missing),
            stack.sources,
            requirement=_BOTTOMING_REQUIREMENT,
            recommended_action="Supply the missing dimension, then re-run the check.",
        )

    assert stack.protrusion_mm is not None and stack.thread_depth_mm is not None
    margin_mm = round_length(stack.thread_depth_mm - stack.protrusion_mm)
    status = "demonstrated" if margin_mm < 0.0 else "checked_within_scope"
    return CheckResult(
        check=CHECK_BOTTOMING,
        status=status,
        severity=_SEVERITY_BY_STATUS.get(status, "high"),
        observed=(
            f"{fastener.id} protrudes {stack.protrusion_mm} mm into {hole.id}, which has "
            f"{stack.thread_depth_mm} mm of usable thread: margin {margin_mm} mm"
        ),
        requirement=_BOTTOMING_REQUIREMENT,
        inputs=list(stack.sources),
        calculation=_calculation(
            CHECK_BOTTOMING,
            stack,
            {
                "protrusion_mm": stack.protrusion_mm,
                "margin_mm": margin_mm,
                "bottoms": margin_mm < 0.0,
            },
            [
                *stack.bottoming_derivation,
                "margin = usable thread depth - protrusion",
                stack.pose,
            ],
        ),
        coverage_limits=[],
        recommended_action=action if status == "demonstrated" else "",
    )


def _engagement(
    fastener: Fastener,
    hole: Hole,
    stack: _Stack,
    hole_material: str | None,
    rule: MaterialRule,
) -> CheckResult:
    designation = hole.thread_designation or fastener.thread_designation
    diameter = None if designation is None else nominal_diameter(designation)

    extra_inputs: dict[str, Quantity | str] = {
        "hole_material": hole_material or "unknown",
        "material_class": rule.name,
        "engagement_rule_source": rule.source,
    }
    if diameter is not None:
        extra_inputs["nominal_diameter_mm"] = diameter

    requirement = (
        f"usable thread engagement must be at least {rule.min_engagement_ratio} x the nominal "
        f"thread diameter for material class {rule.name} ({rule.source})"
        if rule.min_engagement_ratio is not None
        else "usable thread engagement must meet the rule for the tapped material"
    )
    assumptions = [
        *stack.engagement_derivation,
        "engagement = min(protrusion, usable thread depth)",
        f"engagement rule for material class {rule.name}: {rule.source}",
    ]

    missing = stack.missing_for("length", "clamped", "usable thread depth", "protrusion")
    if designation is None or diameter is None:
        missing.append(f"the nominal thread diameter for designation {designation!r}")
    if rule.min_engagement_ratio is None:
        missing.append(
            f"the engagement rule for hole material {hole_material!r}, which matched no "
            "material class in engagement_rules.yaml"
        )

    calculation = None
    ratio = None
    engagement_mm = None
    if stack.protrusion_mm is not None and stack.thread_depth_mm is not None:
        engagement_mm = round_length(min(stack.protrusion_mm, stack.thread_depth_mm))
        result: dict[str, Quantity | bool | str | float] = {
            "protrusion_mm": stack.protrusion_mm,
            "engagement_mm": engagement_mm,
        }
        if diameter is not None:
            ratio = round_length(engagement_mm / diameter.value)
            result["ratio"] = ratio
        if rule.min_engagement_ratio is not None:
            result["required_ratio"] = rule.min_engagement_ratio
            result["meets_rule"] = ratio is not None and ratio >= rule.min_engagement_ratio
        calculation = _calculation(CHECK_ENGAGEMENT, stack, result, assumptions, extra_inputs)

    if missing:
        # Not `unresolved()`: the measured engagement is still worth reporting, and that
        # helper deliberately carries no calculation.
        return CheckResult(
            check=CHECK_ENGAGEMENT,
            status="unresolved",
            severity="medium",
            observed=f"{' and '.join(missing)} is unknown; the check did not run",
            requirement=requirement,
            inputs=list(stack.sources),
            calculation=calculation,
            coverage_limits=[_limit(CHECK_ENGAGEMENT, missing)],
            recommended_action="Supply the missing value, then re-run the check.",
        )

    assert ratio is not None and engagement_mm is not None
    assert rule.min_engagement_ratio is not None
    status = (
        "demonstrated" if ratio < rule.min_engagement_ratio - RATIO_EPS else "checked_within_scope"
    )
    return CheckResult(
        check=CHECK_ENGAGEMENT,
        status=status,
        severity=_SEVERITY_BY_STATUS.get(status, "high"),
        observed=(
            f"{fastener.id} engages {engagement_mm} mm of thread in {hole.id}: {ratio} x d "
            f"against the {rule.min_engagement_ratio} x d rule for {rule.name}"
        ),
        requirement=requirement,
        inputs=list(stack.sources),
        calculation=calculation,
        coverage_limits=[],
        recommended_action=(
            f"Lengthen {fastener.id} or deepen the thread in {hole.id} to reach "
            f"{rule.min_engagement_ratio} x d, or agree an exception for this joint."
            if status == "demonstrated"
            else ""
        ),
    )


_THREAD_REQUIREMENT = (
    "the fastener thread and the tapped hole thread must be the same series, nominal "
    "diameter and pitch"
)


def _thread_match(fastener: Fastener, hole: Hole, stack: _Stack) -> CheckResult:
    missing = []
    if fastener.thread_designation is None:
        missing.append(f"the thread designation of fastener {fastener.id}")
    if hole.thread_designation is None:
        missing.append(f"the thread designation of hole {hole.id}")
    if missing:
        return unresolved(
            CHECK_THREAD_MATCH,
            " and ".join(missing),
            stack.sources,
            requirement=_THREAD_REQUIREMENT,
            recommended_action="Record both thread designations, then re-run the check.",
        )

    screw = parse_thread(fastener.thread_designation)
    tapped = parse_thread(hole.thread_designation)
    observed = f"fastener {fastener.id} is {screw.text!r}; hole {hole.id} is {tapped.text!r}"

    unreadable = [spec.text for spec in (screw, tapped) if not spec.recognized]
    if unreadable:
        return unresolved(
            CHECK_THREAD_MATCH,
            f"the thread size in {' and '.join(repr(text) for text in unreadable)}",
            stack.sources,
            requirement=_THREAD_REQUIREMENT,
            recommended_action=(
                "Record the thread in a standard designation (M6x1.0, 1/4-20), then re-run."
            ),
        )

    assert screw.nominal_diameter is not None and tapped.nominal_diameter is not None
    mismatched = (
        screw.series != tapped.series
        or abs(screw.nominal_diameter.value - tapped.nominal_diameter.value) > DIAMETER_EPS_MM
        or (
            screw.pitch_mm is not None
            and tapped.pitch_mm is not None
            and abs(screw.pitch_mm - tapped.pitch_mm) > DIAMETER_EPS_MM
        )
    )
    pitch_compared = screw.pitch_mm is not None and tapped.pitch_mm is not None
    status = "demonstrated" if mismatched else "checked_within_scope"
    return CheckResult(
        check=CHECK_THREAD_MATCH,
        status=status,
        severity=_SEVERITY_BY_STATUS.get(status, "high"),
        observed=observed,
        requirement=_THREAD_REQUIREMENT,
        inputs=list(stack.sources),
        calculation=_calculation(
            CHECK_THREAD_MATCH,
            stack,
            {
                "fastener_thread": screw.normalized,
                "hole_thread": tapped.normalized,
                "matches": not mismatched,
                "pitch_compared": pitch_compared,
            },
            [
                "designations are compared on series, nominal diameter and pitch",
                "a pitch given on only one side is not treated as a mismatch",
            ],
            {"fastener_thread_as_read": screw.text, "hole_thread_as_read": tapped.text},
        ),
        coverage_limits=(
            []
            if pitch_compared
            else [
                f"{CHECK_THREAD_MATCH} compared nominal diameter only: a pitch was given on "
                "one side of the joint"
            ]
        ),
        recommended_action=(
            f"Change {fastener.id} or the tapped thread in {hole.id} so the two agree."
            if mismatched
            else ""
        ),
    )


_HEAD_REQUIREMENT = (
    "the driving tool envelope around the fastener head must be clear of other bodies"
)


def _head_clearance(
    fastener: Fastener, hole: Hole, stack: _Stack, envelope: EnvelopeResult | None
) -> CheckResult:
    if envelope is None:
        return unresolved(
            CHECK_HEAD_CLEARANCE,
            f"the tool envelope around the head of {fastener.id}",
            stack.sources,
            requirement=_HEAD_REQUIREMENT,
            recommended_action=(
                f"Export the body meshes near {fastener.id} and re-run the check with an "
                "envelope raycast."
            ),
        )

    blocking = ", ".join(
        f"{hit.component_id} at {round_length(hit.first_hit_distance_m * 1000.0)} mm"
        for hit in envelope.hits
    )
    result: dict[str, Quantity | bool | str | float] = {
        "clear": not envelope.hits,
        "blocking_components": blocking or "none",
    }
    if envelope.hits:
        result["first_hit_mm"] = round_length(
            min(hit.first_hit_distance_m for hit in envelope.hits) * 1000.0
        )
    calculation = _calculation(
        CHECK_HEAD_CLEARANCE,
        stack,
        result,
        [
            "a ring of rays on the tool envelope plus one on the axis, swept back from the "
            f"head plane of {fastener.id} along the fastener axis",
            "the envelope is a straight cylinder: a swing arc for a wrench is not modelled",
        ],
    )

    if envelope.hits:
        return CheckResult(
            check=CHECK_HEAD_CLEARANCE,
            status="demonstrated",
            severity="medium",
            observed=f"The tool envelope of {fastener.id} runs into {blocking}.",
            requirement=_HEAD_REQUIREMENT,
            inputs=list(stack.sources),
            calculation=calculation,
            coverage_limits=list(envelope.unresolved),
            recommended_action=(
                f"Move the obstructing body, change the head or drive of {fastener.id}, or "
                "relocate the joint."
            ),
        )
    if envelope.unresolved:
        return CheckResult(
            check=CHECK_HEAD_CLEARANCE,
            status="unresolved",
            severity="medium",
            observed=(
                f"The tool envelope of {fastener.id} was clear of the bodies that could be "
                "swept, but not every body could be tested."
            ),
            requirement=_HEAD_REQUIREMENT,
            inputs=list(stack.sources),
            calculation=calculation,
            coverage_limits=list(envelope.unresolved),
            recommended_action="Export the missing body meshes, then re-run the check.",
        )
    return CheckResult(
        check=CHECK_HEAD_CLEARANCE,
        status="checked_within_scope",
        severity="info",
        observed=f"The tool envelope of {fastener.id} is clear of every body that was swept.",
        requirement=_HEAD_REQUIREMENT,
        inputs=list(stack.sources),
        calculation=calculation,
        coverage_limits=[
            f"{CHECK_HEAD_CLEARANCE} swept only the bodies passed to the raycast, sampled on "
            "the envelope circle and the axis"
        ],
        recommended_action="",
    )


def _unsupported(fastener: Fastener) -> CheckResult:
    supported = " and ".join(SUPPORTED_KINDS)
    return CheckResult(
        check=CHECK_UNSUPPORTED,
        status="unresolved",
        severity="info",
        observed=(
            f"{fastener.id} is a {fastener.kind}; this phase models {supported} joints into a "
            "tapped hole only."
        ),
        requirement="joint kinds outside the pilot are reported out of scope, never as passed",
        inputs=[fastener.id],
        calculation=None,
        coverage_limits=[f"out_of_scope: {fastener.kind}"],
        recommended_action=f"Review the {fastener.kind} joint at {fastener.id} by hand.",
    )


def check_fastener_joint(
    fastener: Fastener,
    hole: Hole,
    clamped: Sequence[ClampedLayer],
    washers: Sequence[Quantity] = (),
    hole_material: str | None = None,
    rules: EngagementRules | None = None,
    envelope: EnvelopeResult | None = None,
) -> list[CheckResult]:
    """Check one screw-in-tapped-hole joint and return one result per check.

    `clamped` is the stack the screw pulls together, in order from the head; `washers` are
    the washer thicknesses under the head. `hole_material` selects the engagement rule from
    `engagement_rules.yaml`. `envelope` is the result of `geometry.envelope_raycast` around
    the head; without it head clearance stays unresolved.

    Returns `fastener.bottoming`, `fastener.engagement`, `fastener.thread_match` and
    `fastener.head_clearance` for a supported joint kind, and a single
    `fastener.unsupported` result for any other kind.

    Raises `pint.DimensionalityError` when an angle is supplied where a length belongs.
    """
    if fastener.kind not in SUPPORTED_KINDS:
        return [_unsupported(fastener)]

    stack = _build_stack(fastener, hole, clamped, washers)
    rule = (rules or load_rules()).for_material(hole_material)
    return [
        _bottoming(fastener, hole, stack),
        _engagement(fastener, hole, stack, hole_material, rule),
        _thread_match(fastener, hole, stack),
        _head_clearance(fastener, hole, stack, envelope),
    ]


# --- the placed screw (feature 010 US4) ---------------------------------------------------

THROUGH_TAPPED_SOURCE = "derived: through-tapped length from the tapped face"
THIN_SHEET_SEVERITY: Severity = "low"
"""A through-tapped part thinner than the rule's length cannot meet it with any screw: the
owner's answer of 2026-09-23 makes that shortfall a finding at low severity, carrying the
sheet thickness (feature 010 research R5)."""


@dataclass(frozen=True)
class UsableThread:
    """How much thread a placed screw can engage, and where the number came from.

    A blind hole's is its Hole Wizard `thread_depth`; a through-tapped hole's is its tapped
    face's axial length, labelled derived. Never `hole_depth`, never a blind face's extent -
    the tap drill runs deeper than the thread (research R2.13).
    """

    length_mm: float
    source: str

    @property
    def is_through_tapped(self) -> bool:
        return self.source == THROUGH_TAPPED_SOURCE


@dataclass(frozen=True)
class Placement:
    """What the assembly says about one placed screw in its tapped hole (`contracts/
    fasteners.md` section 4): the protrusion - the tip's depth below the thread entry along
    the tapped axis - and the usable thread, each with where it came from, or the words
    naming why it could not be measured.

    Every phrase in `missing` names the protrusion or the usable thread depth, so the rule
    functions route it to the checks that need it.
    """

    protrusion_mm: float | None
    protrusion_source: str
    usable_thread: UsableThread | None
    missing: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.protrusion_mm is None and not any("protrusion" in item for item in self.missing):
            raise ValueError("a placement with no protrusion must say why in `missing`")
        if self.usable_thread is None and not any(
            "usable thread depth" in item for item in self.missing
        ):
            raise ValueError("a placement with no usable thread must say why in `missing`")

    def derivation(self) -> list[str]:
        """The lines every placed-screw result carries in place of the clamped-stack ones."""
        lines = [
            "protrusion = thread entry - screw tip, along the tapped axis "
            f"({self.protrusion_source})"
        ]
        if self.usable_thread is not None:
            lines.append(f"usable thread depth = {self.usable_thread.source}")
        return lines


def _placed_stack(fastener: Fastener, hole: Hole, placement: Placement) -> _Stack:
    stack = _Stack(
        bottoming_derivation=placement.derivation(),
        engagement_derivation=placement.derivation(),
        pose=PLACED_POSE,
    )
    stack.inputs["fastener_id"] = fastener.id
    stack.inputs["hole_id"] = hole.id
    stack.missing = list(placement.missing)
    if placement.protrusion_mm is not None:
        stack.protrusion_mm = round_length(placement.protrusion_mm)
        quantity = Quantity(value=stack.protrusion_mm, unit="mm")
        stack.inputs["protrusion_mm"] = quantity
        stack.sources.append(quantity)
    if placement.usable_thread is not None:
        stack.thread_depth_mm = round_length(placement.usable_thread.length_mm)
        quantity = Quantity(value=stack.thread_depth_mm, unit="mm")
        stack.inputs["usable_thread_depth_mm"] = quantity
        stack.inputs["usable_thread_source"] = placement.usable_thread.source
        stack.sources.append(quantity)
    return stack


def _thin_sheet(
    result: CheckResult, fastener: Fastener, hole: Hole, placement: Placement
) -> CheckResult:
    """A demonstrated shortfall in a through-tapped part thinner than the rule's length is
    `low` severity and says so, with the sheet thickness (owner answer 2026-09-23)."""
    usable = placement.usable_thread
    calculation = result.calculation
    if (
        result.status != "demonstrated"
        or usable is None
        or not usable.is_through_tapped
        or calculation is None
    ):
        return result
    ratio = calculation.result.get("required_ratio")
    designation = hole.thread_designation or fastener.thread_designation
    diameter = None if designation is None else nominal_diameter(designation)
    if not isinstance(ratio, float) or diameter is None:
        return result
    required_mm = round_length(ratio * diameter.value)
    if usable.length_mm >= required_mm:
        return result
    sheet = round_length(usable.length_mm)
    return replace(
        result,
        severity=THIN_SHEET_SEVERITY,
        observed=(
            f"{result.observed}; the tapped part is a {sheet} mm sheet, thinner than the "
            f"{required_mm} mm the rule needs, so no screw length can meet it"
        ),
        calculation=calculation.model_copy(
            update={
                "result": {
                    **calculation.result,
                    "sheet_thickness_mm": sheet,
                    "required_engagement_mm": required_mm,
                }
            }
        ),
        recommended_action=(
            f"Accept the thin-sheet engagement of {fastener.id} in {hole.id} deliberately, or "
            "use a thicker part, an insert or a nut."
        ),
    )


def check_placed_screw(
    fastener: Fastener,
    hole: Hole,
    placement: Placement,
    hole_material: str | None = None,
    rules: EngagementRules | None = None,
    envelope: EnvelopeResult | None = None,
) -> list[CheckResult]:
    """The four joint checks for a screw the assembly places in a tapped hole (FR-012, FR-013).

    Beside `check_fastener_joint`, not instead of it: that check takes a clamped stack a
    model names; this one reads the protrusion and the usable thread off the placed geometry
    (`placement`), so no clamped list and no bounding-box layer thickness is needed. The same
    `_bottoming`, `_engagement`, `_thread_match` and `_head_clearance` decide, each result
    carrying the placement's derivation instead of the clamped-stack formula; `hole_depth` is
    never read. A through-tapped part too thin for the rule makes the engagement shortfall
    low severity, with the sheet thickness.
    """
    if fastener.kind not in SUPPORTED_KINDS:
        return [_unsupported(fastener)]

    stack = _placed_stack(fastener, hole, placement)
    rule = (rules or load_rules()).for_material(hole_material)
    return [
        _bottoming(fastener, hole, stack),
        _thin_sheet(
            _engagement(fastener, hole, stack, hole_material, rule), fastener, hole, placement
        ),
        _thread_match(fastener, hole, stack),
        _head_clearance(fastener, hole, stack, envelope),
    ]
