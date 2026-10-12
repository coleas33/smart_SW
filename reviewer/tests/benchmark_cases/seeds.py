"""The seed kinds (feature 014 `generator.md` 3; `cases.md` 6.2 to 6.4; owner decision 16A).

`KINDS` is the registry every case spec's seeds are drawn from, each kind by its name. A kind
fixes what its seed is keyed as - an exact check (GN-9), the producer, the expected status - and
the evidence its package withholds so the model, not code, must find it; its planted and clean
forms change the design's records at the seed's places, never an id, so both key the same check
and references. The statuses are what each check can write: the fastener checks demonstrate a
joint that bottoms, under-engages or mismatches (`checks/fastener.py`), an offset beyond a drawn
zone is demonstrated and without one unresolved (`checks/hole_alignment.py:98-101, 130`).

**The fastener-family core kinds** (`thread_mismatch_unplaced`, `bottoming_unplaced`,
`engagement_unplaced`) plant one joint, a screw place and the hole its record names, through
`check_fastener_joint(fastener, hole, clamped)`; their screws stay on no extracted hole axis in
both forms (`joint_placement`), the fastener row still addressing them (GN-2), and their decoy is
the same call on a sibling screw's joint. Each form keeps the joint's other three rules passing,
so a correct review raises nothing but the planted one. **The hole-pair kinds**
(`coaxiality_drawn`, `coaxiality_undrawn`) move one hole of two empty holes of two parts off the
other's axis, through `check_hole_alignment(a, b[, tolerance])`, the tolerance drawn on the
assembly's ingested sheet only (`tolerance_source`); their decoys are another hole pair between
the same parts.

**`joint_absent` asks more of a design than empty holes.** At this commit the joint map pairs two
adjacent coaxial holes whether or not anything sits in them, and judges the pair's alignment with
the fastener size their Hole Wizard size names (`checks/joint_alignment.py` `fastener_size`): an
empty pair offset beyond that allowance is a code-produced demonstrated `hole.nominal_alignment`.
So the design keeps the joint map from pairing the two holes at all: their faces stand more than
the joint rules' 1 mm adjacency apart along the axis (`checks/joint_rules.yaml`
`adjacency_gap_mm`), which `check_hole_alignment`, reading the holes' axes, does not need.

**The fit, stack and drawing core kinds** draw limits and texts on ingested sheets only
(`drawing_only`; `tolerance_source`): a fit's bore and shaft and a stack's contributors and target
on the assembly's sheet, keyed by their dimensions, read through `check_fit` and
`check_axial_stack`; a tapped-hole callout on the part's own drawing, keyed to that document,
recorded with `record_drawing_finding`. **The anchor kinds** (`cases.md` 6.3 and 6.4) use the same
mechanism; the code-produced ones withhold nothing and have no correct call, since code finds
them, and the kinds with no clean form say so (`clean` is `None`), which row 6 reads.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import replace
from typing import TypeVar

from swreview.benchmark.answer_key_model import ExpectedStatus
from tests.benchmark_cases.spec import (
    At,
    ComponentPlace,
    ContactPlace,
    DimensionPlace,
    DocumentPlace,
    Form,
    HolePlace,
    Place,
    PlaceName,
    Places,
    ScrewPlace,
    SeedKind,
    ToolCall,
)
from tests.support.drawings import Limits

ENGAGEMENT_RATIO = 1.5
"""`checks/engagement_rules.yaml`'s rule for steel and aluminium, the materials every design's
tapped parts are cut from: usable engagement at least 1.5 x the thread's nominal diameter. Data
the generator may not import, stated here for the forms that set a joint's length."""

CLEAN_MARGIN_MM = 1.0
"""How far inside its tapped thread a clean joint's screw ends: it engages the thread less this
margin, so it neither bottoms nor falls short of the rule."""

BOTTOMING_OVERRUN_MM = 2.0
"""How far past the usable thread a bottoming screw reaches."""

AF2_OFFSET_MM = 0.750
"""AF-2's dowel offset (research §3; `generate_fixtures.py:444-445`)."""

COARSE_THREADS: tuple[tuple[str, str], ...] = (
    ("2", "0.4"),
    ("2.5", "0.45"),
    ("3", "0.5"),
    ("4", "0.7"),
    ("5", "0.8"),
    ("6", "1.0"),
    ("8", "1.25"),
    ("10", "1.5"),
    ("12", "1.75"),
)
"""ISO metric coarse threads, `(nominal diameter, pitch)` in mm, in size order: what "one size
below" steps along."""

_THREAD = re.compile(r"M(\d+(?:\.\d+)?)[xX-](\d+(?:\.\d+)?)")

RecordT = TypeVar("RecordT", bound=Place)
ScrewChange = Callable[[str, ScrewPlace, Places], dict[str, object]]
"""`(screw place name, its record, the records)` to the changes a form makes to the screw."""
Offset = Callable[[At, Places], float]


# --- records and threads ---------------------------------------------------------------------


def _record(places: Places, name: str, kind: type[RecordT]) -> RecordT:
    """The record of place `name`, which the spec checks hold to its role's kind."""
    record = places[name]
    if not isinstance(record, kind):
        raise ValueError(f"{name} is a {record.KIND} place, not a {kind.KIND} place")
    return record


def _thread_size(thread: str | None, where: str) -> tuple[str, str]:
    """`(nominal diameter, pitch)` of an ISO coarse thread written "M5x0.8" or "M5-0.8"."""
    match = None if thread is None else _THREAD.fullmatch(thread)
    sizes = [diameter for diameter, _ in COARSE_THREADS]
    if match is None or match.group(1) not in sizes:
        raise ValueError(f"{where} names thread {thread!r}, not an ISO coarse thread M<d>x<p>")
    return match.group(1), match.group(2)


def _one_size_below(thread: str | None, where: str) -> tuple[str, str]:
    """The ISO coarse thread one size below `thread`."""
    diameter, _ = _thread_size(thread, where)
    index = [size for size, _ in COARSE_THREADS].index(diameter)
    if index == 0:
        raise ValueError(f"{where} names {thread}, the smallest thread; nothing is one size below")
    return COARSE_THREADS[index - 1]


def _vendor(size: tuple[str, str]) -> str:
    """A thread in the vendor name's form `PackageBuilder.screw_document` takes, "M4-0.7"."""
    return f"M{size[0]}-{size[1]}"


def _hole_of(screw: ScrewPlace, places: Places) -> HolePlace:
    """The tapped hole a screw's record names."""
    return _record(places, screw.hole, HolePlace)


def _usable_thread(screw: ScrewPlace, name: str, places: Places) -> tuple[float, float]:
    """The joint's usable thread depth and nominal diameter, which a length form needs."""
    hole = _hole_of(screw, places)
    if hole.thread_depth_mm is None:
        raise ValueError(f"{name}'s hole {screw.hole} states no usable thread depth")
    diameter, _ = _thread_size(hole.thread, f"{name}'s hole {screw.hole}")
    return hole.thread_depth_mm, float(diameter)


def _clean_length(screw: ScrewPlace, name: str, places: Places) -> float:
    """A length whose reach past the clamped stack ends `CLEAN_MARGIN_MM` inside the usable
    thread and still engages the rule: no bottoming, no short engagement."""
    depth, diameter = _usable_thread(screw, name, places)
    reach = depth - CLEAN_MARGIN_MM
    if reach < ENGAGEMENT_RATIO * diameter:
        raise ValueError(
            f"{name}'s hole {screw.hole} has {depth:g} mm of usable thread, too little for a "
            f"clean joint that engages {ENGAGEMENT_RATIO:g} x {diameter:g} mm"
        )
    return round(screw.clamp_mm + reach, 3)


def _screw_form(words: str, change: ScrewChange) -> Form:
    """A form replacing the screw at the seed's `fastener` role by `change(name, screw,
    places)`'s changes, the screw left on no extracted hole axis (`joint_placement`)."""

    def apply(at: At, places: Places) -> dict[str, Place]:
        name = at["fastener"]
        screw = _record(places, name, ScrewPlace)
        return {name: replace(screw, seated=False, **change(name, screw, places))}

    return Form(words, apply)


def _joint(at: At, places: Places, role: str = "fastener") -> dict[str, PlaceName]:
    """The joint reference of the screw at `role`: the screw and its hole."""
    screw = _record(places, at[role], ScrewPlace)
    return {"fastener": PlaceName(at[role]), "hole": PlaceName(screw.hole)}


def _joint_call(name: str, places: Places) -> ToolCall:
    """`check_fastener_joint` on screw place `name`'s joint and clamped stack."""
    screw = _record(places, name, ScrewPlace)
    return ToolCall(
        "check_fastener_joint",
        {
            "fastener_id": PlaceName(name),
            "hole_id": PlaceName(screw.hole),
            "clamped_component_ids": [PlaceName(component) for component in screw.clamped],
        },
    )


JOINT_ROLES = {"fastener": "fastener", "sibling": "fastener"}
"""A planted joint's screw, and the sibling screw whose joint is its decoy."""


def _joint_kind(name: str, check: str, plant: Form, clean: Form) -> SeedKind:
    """A fastener-family core kind: model-produced, demonstrated, its screw unplaced."""
    return SeedKind(
        name=name,
        check=check,
        producer="model",
        expected_status="demonstrated",
        withheld=("joint_placement",),
        roles=JOINT_ROLES,
        plant=plant,
        clean=clean,
        references=lambda at, places: (_joint(at, places),),
        correct_calls=lambda at, places: (_joint_call(at["fastener"], places),),
        decoys=lambda at, places: (_joint_call(at["sibling"], places),),
    )


def _clean_screw(name: str, screw: ScrewPlace, places: Places) -> dict[str, object]:
    """The clean joint: the hole's thread, and a length ending inside it."""
    hole = _hole_of(screw, places)
    return {
        "thread": _vendor(_thread_size(hole.thread, f"{name}'s hole {screw.hole}")),
        "length_mm": _clean_length(screw, name, places),
    }


CLEAN_JOINT = _screw_form(
    "a screw of its tapped hole's thread, ending inside the usable thread", _clean_screw
)


def _thread_below(name: str, screw: ScrewPlace, places: Places) -> dict[str, object]:
    hole = _hole_of(screw, places)
    return {
        "thread": _vendor(_one_size_below(hole.thread, f"{name}'s hole {screw.hole}")),
        "length_mm": _clean_length(screw, name, places),
    }


def _overrun(name: str, screw: ScrewPlace, places: Places) -> dict[str, object]:
    depth, diameter = _usable_thread(screw, name, places)
    if depth < ENGAGEMENT_RATIO * diameter:
        raise ValueError(
            f"{name}'s hole {screw.hole} has {depth:g} mm of usable thread: a screw bottoming in "
            f"it would also engage less than {ENGAGEMENT_RATIO:g} x {diameter:g} mm"
        )
    clean = _clean_screw(name, screw, places)
    return {**clean, "length_mm": round(screw.clamp_mm + depth + BOTTOMING_OVERRUN_MM, 3)}


def _short(name: str, screw: ScrewPlace, places: Places) -> dict[str, object]:
    depth, diameter = _usable_thread(screw, name, places)
    if diameter > depth:
        raise ValueError(
            f"{name}'s hole {screw.hole} has {depth:g} mm of usable thread: a screw reaching "
            f"{diameter:g} mm would bottom as well as engage short"
        )
    clean = _clean_screw(name, screw, places)
    return {**clean, "length_mm": round(screw.clamp_mm + diameter, 3)}


THREAD_MISMATCH_UNPLACED = _joint_kind(
    "thread_mismatch_unplaced",
    "fastener.thread_match",
    plant=_screw_form(
        "a screw one thread size below its tapped hole's, on no extracted hole axis",
        _thread_below,
    ),
    clean=CLEAN_JOINT,
)
"""AF-1's shape (M4-0.7 into M5x0.8), its fastener row written, placed on no extracted axis."""

BOTTOMING_UNPLACED = _joint_kind(
    "bottoming_unplaced",
    "fastener.bottoming",
    plant=_screw_form(
        "a blind tapped hole whose usable thread depth is shorter than the screw's reach past "
        "its clamped stack, the screw on no extracted hole axis",
        _overrun,
    ),
    clean=CLEAN_JOINT,
)
"""The screw reaches `BOTTOMING_OVERRUN_MM` past the usable thread, which still engages the
rule, so only bottoming fails."""

ENGAGEMENT_UNPLACED = _joint_kind(
    "engagement_unplaced",
    "fastener.engagement",
    plant=_screw_form(
        "a screw that engages one diameter of thread, less than its rule's ratio, on no "
        "extracted hole axis",
        _short,
    ),
    clean=CLEAN_JOINT,
)
"""The screw reaches one nominal diameter past its stack: inside the thread, short of the rule."""


# --- hole pairs ------------------------------------------------------------------------------


def _offset(offset: Offset, words: str) -> Form:
    """A form moving hole `b` off hole `a`'s axis by `offset(at, places)` mm."""

    def apply(at: At, places: Places) -> dict[str, Place]:
        hole = _record(places, at["b"], HolePlace)
        return {at["b"]: replace(hole, offset_mm=offset(at, places))}

    return Form(words, apply)


def _zone(at: At, places: Places) -> float:
    """The drawn position tolerance's zone, which permits half of it as offset: planting the
    whole zone is twice what it permits (`checks/hole_alignment.py:121-130`)."""
    tolerance = _record(places, at["tolerance"], DimensionPlace)
    if tolerance.nominal_mm <= 0:
        raise ValueError(f"{at['tolerance']} draws a zone of {tolerance.nominal_mm:g} mm")
    return tolerance.nominal_mm


ALIGNED = _offset(lambda at, places: 0.0, "the two holes on one axis")


def _pair(at: At, places: Places) -> tuple[dict[str, list[PlaceName]], ...]:
    return ({"holes": [PlaceName(at["a"]), PlaceName(at["b"])]},)


def _alignment(a: str, b: str, tolerance: str | None = None) -> ToolCall:
    arguments: dict[str, object] = {"hole_id_a": PlaceName(a), "hole_id_b": PlaceName(b)}
    if tolerance is not None:
        arguments["tolerance"] = PlaceName(tolerance)
    return ToolCall("check_hole_alignment", arguments)


PAIR_ROLES = {"a": "hole", "b": "hole", "other_a": "hole", "other_b": "hole"}
"""A planted hole pair, and the other pair between the same parts its decoys call."""

COAXIALITY_DRAWN = SeedKind(
    name="coaxiality_drawn",
    check="hole.coaxiality",
    producer="model",
    expected_status="demonstrated",
    withheld=("joint_absent", "tolerance_source"),
    roles={**PAIR_ROLES, "tolerance": "dimension"},
    plant=_offset(
        _zone,
        "two empty holes of two parts meant to align, offset more than half the position "
        "tolerance drawn on the assembly's sheet",
    ),
    clean=ALIGNED,
    references=_pair,
    correct_calls=lambda at, places: (_alignment(at["a"], at["b"], at["tolerance"]),),
    decoys=lambda at, places: (
        _alignment(at["other_a"], at["other_b"], at["tolerance"]),
        _alignment(at["other_a"], at["other_b"]),
    ),
)

COAXIALITY_UNDRAWN = SeedKind(
    name="coaxiality_undrawn",
    check="hole.coaxiality",
    producer="model",
    expected_status="unresolved",
    withheld=("joint_absent",),
    roles=PAIR_ROLES,
    plant=_offset(
        lambda at, places: AF2_OFFSET_MM,
        "two empty dowel holes 0.750 mm apart, with no tolerance drawn",
    ),
    clean=ALIGNED,
    references=_pair,
    correct_calls=lambda at, places: (_alignment(at["a"], at["b"]),),
    decoys=lambda at, places: (_alignment(at["other_a"], at["other_b"]),),
    confirms_clean=False,
)
"""AF-2's 0.750 mm offset; with no tolerance the tool measures it and writes unresolved. It writes
unresolved on the aligned clean form too (`checks/hole_alignment.py:98-101`), so no call confirms
it: like a drawing kind's, a twin's condition of this kind carries no correct call, and still
catches a finding that contradicts it (owner decision 55A)."""


# --- fits ------------------------------------------------------------------------------------

FitLimits = tuple[Limits, Limits]
"""A fit's drawn limits: the bore's, then the shaft's."""

CLEARANCE: FitLimits = (("bilateral", 0.025, 0.0), ("bilateral", -0.009, -0.025))
"""Clear at both limits for any bore drawn at or above its shaft's nominal: 0.009 mm to 0.050 mm
at one nominal (`test_tools_checks_fit.py`'s 40 H7/g6 limits)."""

TRANSITION: FitLimits = (("bilateral", 0.010, 0.0), ("bilateral", 0.006, -0.004))
"""Straddling zero at one nominal: -0.006 mm to 0.014 mm diametral clearance."""

INTERFERENCE: FitLimits = (("bilateral", 0.010, 0.0), ("bilateral", 0.020, 0.014))
"""Wholly interfering at one nominal: -0.020 mm to -0.004 mm (R-3 variant A's limits)."""

BORE_UNDRAWN: FitLimits = (None, CLEARANCE[1])
"""The bore drawn with no tolerance, the shaft toleranced: unresolved naming the bore
(`checks/fit.py:97-100`)."""

UNDRAWN: FitLimits = (None, None)
"""Both drawn with no tolerance (R-3 variant B)."""


def _fit_form(words: str, limits: FitLimits, *, one_nominal: bool) -> Form:
    """A form drawing the seed's bore and shaft with `limits`, each text then read from its
    prefix, nominal and limits. `one_nominal`: the fit holds only when both are drawn at one
    nominal, which the design must give them."""
    bore_limits, shaft_limits = limits

    def apply(at: At, places: Places) -> dict[str, Place]:
        bore = _record(places, at["bore"], DimensionPlace)
        shaft = _record(places, at["shaft"], DimensionPlace)
        if bore.nominal_mm < shaft.nominal_mm or (
            one_nominal and bore.nominal_mm != shaft.nominal_mm
        ):
            raise ValueError(
                f"{at['bore']} and {at['shaft']} are drawn at {bore.nominal_mm:g} mm and "
                f"{shaft.nominal_mm:g} mm: the form {words!r} draws a bore over a shaft"
                + (" at one nominal" if one_nominal else "")
            )
        return {
            at["bore"]: replace(bore, limits=bore_limits, text=None),
            at["shaft"]: replace(shaft, limits=shaft_limits, text=None),
        }

    return Form(words, apply)


def _fit(at: At, places: Places) -> tuple[dict[str, PlaceName], ...]:
    return ({"bore": PlaceName(at["bore"]), "shaft": PlaceName(at["shaft"])},)


def _fit_call(bore: str, shaft: str) -> ToolCall:
    return ToolCall(
        "check_fit",
        {"bore_dimension_ref": PlaceName(bore), "shaft_dimension_ref": PlaceName(shaft)},
    )


FIT_ROLES = {
    "bore": "dimension",
    "shaft": "dimension",
    "sibling_bore": "dimension",
    "sibling_shaft": "dimension",
}
"""A planted fit's two dimensions on the assembly's sheet, and the sibling fit beside them."""

CLEAN_FIT = _fit_form("hole and shaft both toleranced for clearance", CLEARANCE, one_nominal=False)


def _core_fit(name: str, status: ExpectedStatus, plant: Form) -> SeedKind:
    """A fit core kind: model-produced, its limits on the assembly's ingested sheet only, keyed
    by its two dimensions; decoys the sibling fit and the bore against itself."""
    return SeedKind(
        name=name,
        check="fit.size_only",
        producer="model",
        expected_status=status,
        withheld=("tolerance_source", "drawing_only"),
        roles=FIT_ROLES,
        plant=plant,
        clean=CLEAN_FIT,
        references=_fit,
        correct_calls=lambda at, places: (_fit_call(at["bore"], at["shaft"]),),
        decoys=lambda at, places: (
            _fit_call(at["sibling_bore"], at["sibling_shaft"]),
            _fit_call(at["bore"], at["bore"]),
        ),
    )


FIT_TRANSITION = _core_fit(
    "fit_transition",
    "suspected",
    _fit_form(
        "hole and shaft limits that straddle zero clearance, where the part must slide",
        TRANSITION,
        one_nominal=True,
    ),
)
"""The fit check writes a transition fit suspected, never demonstrated (`checks/fit.py:75-77,
112`)."""

FIT_INTERFERENCE_UNINTENDED = _core_fit(
    "fit_interference_unintended",
    "suspected",
    _fit_form(
        "limits wholly interfering where a slip fit is meant", INTERFERENCE, one_nominal=True
    ),
)

FIT_LIMIT_MISSING = _core_fit(
    "fit_limit_missing",
    "unresolved",
    _fit_form(
        "the hole drawn with no tolerance, the shaft toleranced", BORE_UNDRAWN, one_nominal=False
    ),
)


# --- axial stacks ----------------------------------------------------------------------------

STACK_ROLES = {
    "enclosing": "dimension",
    "inside_1": "dimension",
    "inside_2": "dimension",
    "target": "dimension",
}
"""A stack's enclosing dimension, what lies inside it, and its drawn target gap, all on the
assembly's sheet: the gap is the enclosing dimension less every inside one."""


def _contributors(at: At) -> list[str]:
    """The stack's contributors in stack order: three, or four with `inside_3`."""
    return [
        at["enclosing"],
        at["inside_1"],
        at["inside_2"],
        *[at[r] for r in ("inside_3",) if r in at],
    ]


def _signs(count: int) -> list[int]:
    """The enclosing dimension `+1`, everything inside it `-1` (`checks/stack.py:51-52`)."""
    return [1] + [-1] * (count - 1)


def _range_mm(record: DimensionPlace, name: str) -> tuple[float, float]:
    """A toleranced dimension's lowest and highest size."""
    if record.limits is None:
        raise ValueError(f"{name} is drawn with no tolerance, and a stack's target is toleranced")
    if record.limits[0] == "symmetric":
        half = record.limits[1]
        return record.nominal_mm - half, record.nominal_mm + half
    _, upper, lower = record.limits
    return record.nominal_mm + lower, record.nominal_mm + upper


def _stack_form(words: str, *, leaves_target: bool) -> Form:
    """A form tolerancing every contributor alike, symmetric: wide enough that the worst-case
    band spans the whole target (so it leaves it on both sides), or tight enough that the band
    stays inside half the nearer margin. The design draws the stack's nominal strictly inside
    its target."""

    def apply(at: At, places: Places) -> dict[str, Place]:
        names = _contributors(at)
        records = [_record(places, name, DimensionPlace) for name in names]
        gap = records[0].nominal_mm - sum(record.nominal_mm for record in records[1:])
        low, high = _range_mm(_record(places, at["target"], DimensionPlace), at["target"])
        if not low < gap < high:
            raise ValueError(
                f"the stack {', '.join(names)} sums to {gap:g} mm, not strictly inside its target "
                f"{at['target']}, {low:g} mm to {high:g} mm"
            )
        if leaves_target:
            half = math.ceil(round((high - low) / len(names) * 100, 6)) / 100
        else:
            half = math.floor(round(min(gap - low, high - gap) / (2 * len(names)) * 1000, 6)) / 1000
            if half <= 0:
                raise ValueError(
                    f"the stack {', '.join(names)} sums to {gap:g} mm, too near its target's "
                    f"limits for a 0.001 mm tolerance to stay inside"
                )
        return {
            name: replace(record, limits=("symmetric", half), text=None)
            for name, record in zip(names, records, strict=True)
        }

    return Form(words, apply)


def _stack_call(contributors: list[str], target: str) -> ToolCall:
    return ToolCall(
        "check_axial_stack",
        {
            "dimension_refs": [PlaceName(name) for name in contributors],
            "signs": _signs(len(contributors)),
            "target_gap": PlaceName(target),
        },
    )


STACK_OUT_OF_GAP = SeedKind(
    name="stack_out_of_gap",
    check="stack.worst_case",
    producer="model",
    expected_status="demonstrated",
    withheld=("tolerance_source", "drawing_only"),
    roles=STACK_ROLES,
    optional_roles={"inside_3": "dimension"},
    plant=_stack_form(
        "three or four drawn contributors whose worst-case band leaves the drawn target gap",
        leaves_target=True,
    ),
    clean=_stack_form(
        "the contributors' tolerances tightened inside the target gap", leaves_target=False
    ),
    references=lambda at, places: (
        {
            "contributors": [PlaceName(name) for name in _contributors(at)],
            "target": PlaceName(at["target"]),
        },
    ),
    correct_calls=lambda at, places: (_stack_call(_contributors(at), at["target"]),),
    decoys=lambda at, places: (_stack_call(_contributors(at)[:-1], at["target"]),),
)
"""A stack outside its target is demonstrated (`checks/stack.py:151-166`); its decoy leaves the
last contributor out."""


# --- drawings --------------------------------------------------------------------------------

CALLOUT_ROLES = {"callout": "dimension", "hole": "hole"}
"""The tapped-hole callout on the part's own drawing, and the model hole it calls out."""


def _called_out(at: At, places: Places) -> tuple[DimensionPlace, HolePlace]:
    """The callout and the tapped hole it calls out. Only a callout that states a thread depth
    needs the hole's (`_thread_depth`): a drill-only callout sits on `cover-blind-tap`'s hole
    row, which carries none (`cases.md` 6.4)."""
    callout = _record(places, at["callout"], DimensionPlace)
    hole = _record(places, at["hole"], HolePlace)
    if hole.thread is None:
        raise ValueError(f"{at['hole']} is no tapped hole to call out")
    return callout, hole


def _callout_text(count: int, thread: str, word: str, depth: float) -> str:
    """A tapped-hole callout as the sheet reads: "4X M6x1.0 - 6H THREAD ↧ 10"."""
    return f"{count}X {thread} - 6H {word} ↧ {depth:g}"


CalloutText = Callable[[HolePlace, str], tuple[str, float]]
"""`(the model hole, its place name)` to a callout's text and the depth it states."""


def _callout_form(words: str, text_of: CalloutText) -> Form:
    """A form writing the seed's callout from the model hole it calls out."""

    def apply(at: At, places: Places) -> dict[str, Place]:
        callout, hole = _called_out(at, places)
        text, depth = text_of(hole, at["hole"])
        return {
            at["callout"]: replace(
                callout, nominal_mm=depth, limits=None, text=text, nominal_text=None
            )
        }

    return Form(words, apply)


def _thread_depth(hole: HolePlace, name: str) -> float:
    if hole.thread_depth_mm is None:
        raise ValueError(f"{name} carries no usable thread depth for its callout to state")
    return hole.thread_depth_mm


def _full_callout(hole: HolePlace, name: str) -> tuple[str, float]:
    depth = _thread_depth(hole, name)
    return _callout_text(hole.count, str(hole.thread), "THREAD", depth), depth


def _drill_only(hole: HolePlace, name: str) -> tuple[str, float]:
    if hole.hole_depth_mm is None:
        raise ValueError(f"{name} states no drill depth for its callout to state alone")
    return _callout_text(
        hole.count, str(hole.thread), "DRILL", hole.hole_depth_mm
    ), hole.hole_depth_mm


def _other_thread(hole: HolePlace, name: str) -> tuple[str, float]:
    diameter, pitch = _one_size_below(hole.thread, name)
    depth = _thread_depth(hole, name)
    return _callout_text(hole.count, f"M{diameter}x{pitch}", "THREAD", depth), depth


def _other_count(hole: HolePlace, name: str) -> tuple[str, float]:
    depth = _thread_depth(hole, name)
    return _callout_text(hole.count + 1, str(hole.thread), "THREAD", depth), depth


FULL_CALLOUT = _callout_form(
    "the callout states the model hole's count, thread and thread depth", _full_callout
)

Observed = Callable[[DimensionPlace, HolePlace], str]
"""`(the callout, the model hole)` to what a correct reviewer records the drawing does."""


def _drawing_kind(
    name: str,
    status: ExpectedStatus,
    plant: Form,
    observed: Observed,
    requirement: str,
    action: str,
) -> SeedKind:
    """A drawing core kind: keyed to the part's own drawing document, which carries no other
    seed (`cases.md` 6.2); its correct call `record_drawing_finding` on the callout, quoting
    only what the drawing shows (`tools/session.py:673`), which cannot confirm the clean form
    (`confirms_clean`); no decoys, the entry being document-level."""

    def calls(at: At, places: Places) -> tuple[ToolCall, ...]:
        callout, hole = _called_out(at, places)
        return (
            ToolCall(
                "record_drawing_finding",
                {
                    "document_id": PlaceName(callout.drawing),
                    "sheet": callout.sheet,
                    "observed": observed(callout, hole),
                    "requirement": requirement,
                    "source_refs": [PlaceName(at["callout"])],
                    "status": status,
                    "recommended_action": action,
                },
            ),
        )

    return SeedKind(
        name=name,
        check="drawing.manufacturing_inputs",
        producer="model",
        expected_status=status,
        withheld=("drawing_only",),
        roles=CALLOUT_ROLES,
        plant=plant,
        clean=FULL_CALLOUT,
        documents=lambda at, places: (_record(places, at["callout"], DimensionPlace).drawing,),
        correct_calls=calls,
        confirms_clean=False,
    )


CALLOUT_DRILL_ONLY = _drawing_kind(
    "callout_drill_only",
    "unresolved",
    _callout_form(
        "the part drawing's tapped-hole callout states the drill depth only", _drill_only
    ),
    lambda callout, hole: (
        f"The tapped-hole callout {callout.as_read()!r} states a drill depth and no thread depth."
    ),
    "A blind tapped hole's callout states its usable thread depth; a drill depth is not one.",
    "State the thread depth in the callout.",
)
"""A value missing from a drawing is unresolved (`answer-key.md` 7.1)."""

CALLOUT_THREAD_DIFFERS = _drawing_kind(
    "callout_thread_differs",
    "suspected",
    _callout_form(
        "the callout's thread differs from the model hole's Hole Wizard thread", _other_thread
    ),
    lambda callout, hole: (
        f"The tapped-hole callout {callout.as_read()!r} names a thread other than the model "
        f"hole's {hole.thread}."
    ),
    "A tapped hole's callout names the thread the model's Hole Wizard hole cuts.",
    "Make the callout's thread and the model hole's agree.",
)

CALLOUT_COUNT_DIFFERS = _drawing_kind(
    "callout_count_differs",
    "suspected",
    _callout_form("the callout's instance count differs from the model hole's", _other_count),
    lambda callout, hole: (
        f"The tapped-hole callout {callout.as_read()!r} counts other than the model hole's "
        "instances."
    ),
    "A tapped hole's callout counts the instances the model's Hole Wizard hole has.",
    "Make the callout's count and the model hole's instances agree.",
)
"""The model's drawing finding writes suspected or unresolved only (`tools/session.py:57-58`)."""


# --- the anchor kinds (cases.md 6.3 and 6.4) --------------------------------------------------


def _anchor_fit(
    name: str, status: ExpectedStatus | None, plant: Form | None, clean: Form | None
) -> SeedKind:
    """R-3's fits: a pin and the bore it sits in, both drawn on one ingested sheet (a bought pin
    has no drawing of its own), keyed by their two dimensions; the decoy is the bore against
    itself, a fit on another pin being the case's own."""
    return SeedKind(
        name=name,
        check="fit.size_only",
        producer="model",
        expected_status=status,
        withheld=("tolerance_source", "drawing_only"),
        roles={"bore": "dimension", "shaft": "dimension"},
        plant=plant,
        clean=clean,
        references=_fit,
        correct_calls=lambda at, places: (_fit_call(at["bore"], at["shaft"]),),
        decoys=lambda at, places: (_fit_call(at["bore"], at["bore"]),),
    )


PRESS_FIT_DRAWN = _anchor_fit(
    "press_fit_drawn",
    "suspected",
    _fit_form(
        "a pin drawn wholly above its hole's limits while the model sits it line to line: a "
        "press fit (R-3, variant A)",
        INTERFERENCE,
        one_nominal=True,
    ),
    None,
)
"""`kalo-fit-1`: "2X Ø3.0 +0.010/0" over "Ø3.0 +0.020/+0.014"; no model dimension, position
tolerance or ISO 286 class on the joint's parts (`tolerance_source`)."""

PRESS_FIT_UNDRAWN = _anchor_fit(
    "press_fit_undrawn",
    "unresolved",
    _fit_form(
        "hole and pin drawn with no tolerance, the pin's oversize only as free text (R-3, "
        "variant B)",
        UNDRAWN,
        one_nominal=True,
    ),
    None,
)
"""`kalo-fit-2`: the fit check writes unresolved naming the bore; the free text is the design's
variant, a configuration property no check reads."""

SLIP_FIT = _anchor_fit(
    "slip_fit",
    None,
    None,
    _fit_form(
        "a pin in a larger hole with slip-fit limits (R-3's clean case)",
        CLEARANCE,
        one_nominal=False,
    ),
)
"""Clean only: `kalo-fit-clean`'s correct condition, a 3.0 mm pin in a 3.1 mm hole."""


def _contact_between(at: At, places: Places) -> tuple[str, ContactPlace]:
    """The one contact place the design lays between the seed's two components."""
    pair = {at["a"], at["b"]}
    found = [
        (name, record)
        for name, record in places.items()
        if isinstance(record, ContactPlace) and {record.a, record.b} == pair
    ]
    if len(found) != 1:
        raise ValueError(
            f"the design lays {len(found)} contact places between {at['a']} and {at['b']}, not one"
        )
    return found[0]


def _overlap(at: At, places: Places) -> dict[str, Place]:
    name, contact = _contact_between(at, places)
    if contact.overlap_mm3 is None or contact.overlap_mm3 <= 0:
        raise ValueError(f"{name} states no positive overlap for interference_positive to plant")
    return {name: replace(contact, volume_mm3=contact.overlap_mm3)}


INTERFERENCE_POSITIVE = SeedKind(
    name="interference_positive",
    check="interference.static",
    producer="code",
    expected_status="demonstrated",
    withheld=(),
    roles={"a": "component", "b": "component"},
    plant=Form("a positive-volume interference row between the two parts", _overlap),
    clean=None,
    parts=lambda at, places: (at["a"], at["b"]),
)
"""R-4's positive twin and AF-3's groups: the volume is the overlap the design's geometry gives the
pair; the group check judges every group (16A)."""


def _offset_hole(at: At, places: Places) -> dict[str, Place]:
    hole = _record(places, at["hole"], HolePlace)
    return {at["hole"]: replace(hole, offset_mm=AF2_OFFSET_MM)}


ALIGNMENT_OFFSET_PLACED = SeedKind(
    name="alignment_offset_placed",
    check="hole.nominal_alignment",
    producer="code",
    expected_status="demonstrated",
    withheld=(),
    roles={"pin": "component", "seat": "hole", "hole": "hole"},
    plant=Form(
        "a pin seated in one part 0.750 mm off the axis of the other part's clearance hole",
        _offset_hole,
    ),
    clean=None,
    references=lambda at, places: (
        {"hole_instances": [PlaceName(at["seat"], instance=1), PlaceName(at["hole"], instance=1)]},
    ),
    parts=lambda at, places: (at["pin"],),
)
"""AF-2's code-produced form, on `kalo-contact-positive`: the joint map's alignment on the placed
pin's joint, keyed by its hole instances (the seat and the hole each one instance, `#1`).
`cases.md` 6.3 and `generator.md` 3 leave the check and status to the package's evidence;
decided here from the code: for a 3.0 mm pin 0.750 mm off the axis of a 3.1 mm clearance hole,
`check_nominal_alignment` takes its `offset > allowed` branch and writes demonstrated, the
allowed offset being the sum of the joint's clearance terms `(H - F)/2`, 0.05 mm for each 3.1 mm
hole (`checks/joint_alignment.py:287-376`), while `hole.position_stack` never runs, since the
package holds no tolerance source (`checks/joint_alignment.py:698-712`). Leg (a) confirms it on
`kalo-contact-positive` (T134)."""


def _seated_below(at: At, places: Places) -> dict[str, Place]:
    name = at["fastener"]
    screw = _record(places, name, ScrewPlace)
    return {name: replace(screw, seated=True, **_thread_below(name, screw, places))}


THREAD_MISMATCH_PLACED = SeedKind(
    name="thread_mismatch_placed",
    check="fastener.thread_match",
    producer="code",
    expected_status="demonstrated",
    withheld=(),
    roles={"fastener": "fastener"},
    plant=Form(
        "a screw one thread size below its tapped hole's, seated on the hole's axis", _seated_below
    ),
    clean=None,
    references=lambda at, places: (_joint(at, places),),
)
"""AF-1's code-produced form, on `kalo-empty-positive`: the joint map places the screw and its
thread check demonstrates the mismatch."""


def _component(at: At, places: Places) -> tuple[str]:
    return (at["component"],)


def _component_document(at: At, places: Places) -> tuple[str]:
    return (_record(places, at["component"], ComponentPlace).document,)


DocumentChange = Callable[[DocumentPlace, str], DocumentPlace]
"""`(the document's record, its place name)` to its changed record."""


def _document_form(words: str, change: DocumentChange) -> Form:
    """A form changing the record of the document the seed's component is an instance of."""

    def apply(at: At, places: Places) -> dict[str, Place]:
        name = _record(places, at["component"], ComponentPlace).document
        return {name: change(_record(places, name, DocumentPlace), name)}

    return Form(words, apply)


def _document_kind(name: str, check: str, plant: Form, clean: Form | None = None) -> SeedKind:
    """A code-produced kind on one component and its document, keyed on both: the finding names
    the document's instances, or the document where it has none (`scoring.md` 2.2)."""
    return SeedKind(
        name=name,
        check=check,
        producer="code",
        expected_status="demonstrated",
        withheld=(),
        roles={"component": "component"},
        plant=plant,
        clean=clean,
        parts=_component,
        documents=_component_document,
    )


REVISION_MISSING = _document_kind(
    "revision_missing",
    "hygiene.revision_present",
    _document_form(
        "a document carrying no revision under the profile's revision property",
        lambda document, name: replace(document, revision=False),
    ),
)
"""R-8's positive twin, on `mir-sitting-positive`: hygiene writes one finding per document
missing the profile's `revision.property` (`checks/hygiene.py`)."""

COMPONENT_LIGHTWEIGHT = _document_kind(
    "component_lightweight",
    "hygiene.component_not_resolved",
    _document_form(
        "the part's instances lightweight and its document not opened",
        lambda document, name: replace(document, opened=False),
    ),
)
"""R-5, on `kalo-lightweight`: true of the package (`checks/hygiene.py:259-301`), so it is keyed;
every instance of the document is laid lightweight, with no interference row."""


def _tree_form(words: str, **flags: bool) -> Form:
    """A form setting `flags` on the feature tree of the seed's custom part."""

    def change(document: DocumentPlace, name: str) -> DocumentPlace:
        if document.tree is None:
            raise ValueError(f"{name} carries no feature tree for the form {words!r}")
        return replace(document, tree=replace(document.tree, **flags))

    return _document_form(words, change)


def _r7_kind(check: str, flag: str, planted: str, clean: str) -> SeedKind:
    """One of R-7's four kinds, named after its check: code-produced, demonstrated, the status
    its rule's registered severity maps to (`checks/rms/registry.py:72`;
    `checks/rules/results.py:67-68`; `answer-key.md` 7.2), on the custom part's tree."""
    return _document_kind(
        check, check, _tree_form(planted, **{flag: False}), _tree_form(clean, **{flag: True})
    )


SKETCH_UNDER_DEFINED = "the custom part's Core sketch under-defined"
SKETCHES_DEFINED = "every sketch of the custom part fully defined"

RMS_SKETCHES_FULLY_DEFINED = _r7_kind(
    "rms.sketches.fully_defined", "sketches_defined", SKETCH_UNDER_DEFINED, SKETCHES_DEFINED
)
STANDARDS_SKETCHES_FULLY_DEFINED = _r7_kind(
    "standards.part.sketches_fully_defined",
    "sketches_defined",
    SKETCH_UNDER_DEFINED,
    SKETCHES_DEFINED,
)
"""One under-defined sketch, listed by both families: each its own entry (`cases.md` 6.3)."""

RMS_GROUPING = _r7_kind(
    "rms.grouping.all_features_in_a_group",
    "grouped",
    "twenty content features of the custom part outside every group folder",
    "every content feature of the custom part inside a group folder",
)
RMS_GLOBAL_VARIABLES = _r7_kind(
    "rms.params.global_variables_present",
    "global_variable",
    "the custom part's equations holding no global variable",
    "a global variable driving the custom part's dimension",
)


def _screws_into(hole: str, places: Places) -> list[str]:
    """Every screw place whose record goes into `hole`, in the design's order."""
    screws = [
        name
        for name, record in places.items()
        if isinstance(record, ScrewPlace) and record.hole == hole
    ]
    if not screws:
        raise ValueError(f"no screw place of the design goes into {hole}")
    return screws


def _depth_unknown(at: At, places: Places) -> dict[str, Place]:
    hole = _record(places, at["hole"], HolePlace)
    changed: dict[str, Place] = {at["hole"]: replace(hole, thread_depth_mm=None)}
    for name in _screws_into(at["hole"], places):
        changed[name] = replace(_record(places, name, ScrewPlace), seated=False)
    return changed


BOTTOMING_THREAD_DEPTH_UNKNOWN = SeedKind(
    name="bottoming_thread_depth_unknown",
    check="fastener.bottoming",
    producer="model",
    expected_status="unresolved",
    withheld=("joint_placement",),
    roles={"hole": "hole"},
    plant=Form(
        "a tapped hole whose usable thread depth the package does not carry, its screws on no "
        "extracted hole axis",
        _depth_unknown,
    ),
    clean=None,
    references=lambda at, places: tuple(
        {"fastener": PlaceName(name), "hole": PlaceName(at["hole"])}
        for name in _screws_into(at["hole"], places)
    ),
    correct_calls=lambda at, places: tuple(
        _joint_call(name, places) for name in _screws_into(at["hole"], places)
    ),
)
"""`cover-blind-tap`'s D-1 (`answer-key.md` 7.1): one joint element per screw into the hole row,
each reachable once FR-061 puts references on the unresolved path; exact, never `fastener.*`."""


KINDS: dict[str, SeedKind] = {
    kind.name: kind
    for kind in (
        THREAD_MISMATCH_UNPLACED,
        BOTTOMING_UNPLACED,
        ENGAGEMENT_UNPLACED,
        COAXIALITY_DRAWN,
        COAXIALITY_UNDRAWN,
        FIT_TRANSITION,
        FIT_INTERFERENCE_UNINTENDED,
        FIT_LIMIT_MISSING,
        STACK_OUT_OF_GAP,
        CALLOUT_DRILL_ONLY,
        CALLOUT_THREAD_DIFFERS,
        CALLOUT_COUNT_DIFFERS,
        PRESS_FIT_DRAWN,
        PRESS_FIT_UNDRAWN,
        SLIP_FIT,
        INTERFERENCE_POSITIVE,
        ALIGNMENT_OFFSET_PLACED,
        THREAD_MISMATCH_PLACED,
        REVISION_MISSING,
        COMPONENT_LIGHTWEIGHT,
        RMS_SKETCHES_FULLY_DEFINED,
        STANDARDS_SKETCHES_FULLY_DEFINED,
        RMS_GROUPING,
        RMS_GLOBAL_VARIABLES,
        BOTTOMING_THREAD_DEPTH_UNKNOWN,
    )
}
"""Every seed kind by its name: the core kinds of `generator.md` 3's table, then the anchor
kinds."""
