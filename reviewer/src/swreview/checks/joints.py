"""The joint map: which holes, screws and pins of an assembly go together (feature 010).

`contracts/joint-map.md` is normative. A package lists holes and faces; it never says which
of them form a joint, and every check that needs a joint - alignment, the stack-up,
fastener identity, thread match, engagement, tool access - used to wait for a model to pick
a pair. This module finds the joints from the geometry alone, with no argument a model
chooses, and records the values each one was judged on so a wrong pairing is visible
rather than authoritative (plan RK-1).

Five rules, in the order the map is built:

1. **Instances, not rows.** A `Hole` row is a Hole Wizard *feature*: `HoleDumper` puts every
   cylinder face of every instance in its `face_ids` and takes the row's `axis` from the
   first face only (research R2.1). The map explodes each row into instances - one per group
   of faces sharing an axis - and never reads `Hole.axis` as the axis of a hole.
2. **Three gates, one partner per component.** Two instances on different components pair
   when they are parallel, their projections overlap and they are axially adjacent (the
   thresholds are `joint_rules.yaml`). Each instance keeps at most one partner per other
   component, the nearest; a pair that passed and lost that assignment, and a pair that
   missed exactly one gate by no more than the margin, are *candidates* for the engineer and
   never findings (R2.2).
3. **Screws and pins join as cylinder members** when a free cylinder face on a component
   with no hole of its own sits coaxially in an instance (R2.3). A free face on a component
   that has holes is never a member - the package does not say whether it is a bore or a
   boss - and is counted in one gap per component instead.
4. **Joints are connected clusters** of kept pairs and member links, classified by their
   members (R2.4), measured along their tapped instance when they have one.
5. **Nothing is guessed.** An instance with no usable face, a hole on an unread component
   and a package whose hole phase did not run are gaps; the map never raises on a valid
   package and is identical under any order of the package's arrays.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import numpy as np
import yaml

from swreview import units
from swreview.checks.fastener import parse_thread
from swreview.checks.result import CheckResult, round_length
from swreview.geometry.axis import is_axis_aligned, unit_vector
from swreview.ir.models import Axis, BBox3D, EvidencePackage, FaceGeometry, Hole

__all__ = [
    "CLEARANCE_TYPES",
    "DEFAULT_JOINT_RULES_PATH",
    "INSTANCE_COAXIAL_MM",
    "INSTANCE_PARALLEL_DEG",
    "Candidate",
    "CandidateReason",
    "CylinderMember",
    "HoleInstance",
    "Joint",
    "JointKind",
    "JointMap",
    "JointMapGap",
    "JointRules",
    "PairValues",
    "build_joint_map",
    "fold_by_pattern",
    "load_joint_rules",
    "plain_diameter_mm",
]

DEFAULT_JOINT_RULES_PATH = Path(__file__).with_name("joint_rules.yaml")

INSTANCE_PARALLEL_DEG = 0.01
INSTANCE_COAXIAL_MM = 0.001
"""Two faces of one hole feature are one instance when their axes agree this closely
(research R2.1). Not tunable data: it says what "the same axis" means for faces SOLIDWORKS
cut in one operation, where the residual is float noise, not modelling slop."""

CLEARANCE_TYPES: tuple[str, ...] = ("clearance", "counterbore", "countersink", "simple")
"""Hole types a fastener or pin passes through rather than threads into. `unknown` is in
neither set: a hole whose type the extractor could not read is judged by nothing."""

JointKind = Literal["screw", "pin", "through_bolt", "unclassified"]
CandidateReason = Literal["angle_near", "overlap_near", "gap_near", "assigned_elsewhere"]
MemberRole = Literal["in_bore", "in_counterbore"]


# --- the thresholds -----------------------------------------------------------------------

_SCALARS: tuple[str, ...] = (
    "parallel_deg",
    "adjacency_gap_mm",
    "member_coaxial_mm",
    "member_diameter_allowance_mm",
    "origin_on_axis_mm",
    "axis_aligned_deg",
)
_MARGINS: tuple[str, ...] = ("angle_deg", "overlap_mm", "gap_mm")


@dataclass(frozen=True)
class JointRules:
    """`joint_rules.yaml`: every threshold the map is judged on, each with its source."""

    version: int
    parallel_deg: float
    adjacency_gap_mm: float
    member_coaxial_mm: float
    member_diameter_allowance_mm: float
    origin_on_axis_mm: float
    axis_aligned_deg: float
    candidate_angle_deg: float
    candidate_overlap_mm: float
    candidate_gap_mm: float
    sources: Mapping[str, str]


def _entry(document: Mapping[str, Any], key: str, name: str, path: Path) -> tuple[float, str]:
    """One `{value, source}` entry, refused naming `name` unless it is exactly that."""
    if key not in document:
        raise ValueError(f"{path}: {name} is missing")
    entry = document[key]
    if not isinstance(entry, Mapping) or set(entry) != {"value", "source"}:
        raise ValueError(f"{path}: {name} must be a mapping of exactly value and source")
    value, source = entry["value"], entry["source"]
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{path}: {name} value must be a number, got {value!r}")
    if not isinstance(source, str) or not source.strip():
        raise ValueError(f"{path}: {name} needs a source")
    if value < 0:
        raise ValueError(f"{path}: {name} must not be negative, got {value}")
    return float(value), source.strip()


def _parse_rules(document: object, path: Path) -> JointRules:
    if not isinstance(document, Mapping):
        raise ValueError(f"{path}: joint rules must be a mapping")
    unknown = sorted(set(document) - {"version", "candidate_margin", *_SCALARS})
    if unknown:
        raise ValueError(f"{path}: unknown key(s) {unknown}")
    if "version" not in document:
        raise ValueError(f"{path}: version is missing")

    values: dict[str, float] = {}
    sources: dict[str, str] = {}
    for key in _SCALARS:
        values[key], sources[key] = _entry(document, key, key, path)
    if "candidate_margin" not in document or not isinstance(document["candidate_margin"], Mapping):
        raise ValueError(f"{path}: candidate_margin is missing")
    margins = document["candidate_margin"]
    unknown_margins = sorted(set(margins) - set(_MARGINS))
    if unknown_margins:
        raise ValueError(f"{path}: unknown candidate_margin key(s) {unknown_margins}")
    for key in _MARGINS:
        name = f"candidate_margin.{key}"
        values[name], sources[name] = _entry(margins, key, name, path)

    for name, value in (
        ("parallel_deg", values["parallel_deg"]),
        ("axis_aligned_deg", values["axis_aligned_deg"]),
        (
            "candidate_margin.angle_deg",
            values["parallel_deg"] + values["candidate_margin.angle_deg"],
        ),
    ):
        if value >= 90.0:
            raise ValueError(f"{path}: {name} reaches {value} degrees; an angle stays below 90")

    return JointRules(
        version=int(document["version"]),
        parallel_deg=values["parallel_deg"],
        adjacency_gap_mm=values["adjacency_gap_mm"],
        member_coaxial_mm=values["member_coaxial_mm"],
        member_diameter_allowance_mm=values["member_diameter_allowance_mm"],
        origin_on_axis_mm=values["origin_on_axis_mm"],
        axis_aligned_deg=values["axis_aligned_deg"],
        candidate_angle_deg=values["candidate_margin.angle_deg"],
        candidate_overlap_mm=values["candidate_margin.overlap_mm"],
        candidate_gap_mm=values["candidate_margin.gap_mm"],
        sources=sources,
    )


@lru_cache(maxsize=4)
def _load_rules_cached(path: Path) -> JointRules:
    return _parse_rules(yaml.safe_load(path.read_text(encoding="utf-8")), path)


def load_joint_rules(path: Path | str | None = None) -> JointRules:
    """Read the joint thresholds; `path` defaults to the file shipped beside this module.

    Cached per resolved path, like `engagement_rules.load_rules`: the table is read once.
    """
    return _load_rules_cached(Path(path or DEFAULT_JOINT_RULES_PATH).resolve())


# --- the entities ----------------------------------------------------------------------------

_ID_NUMBER = re.compile(r"^(.*?)(\d+)$")


def _id_key(identifier: str) -> tuple[Any, ...]:
    """Natural order for `hol:0014#2` and `fac:10000`: text and numbers compared as such."""
    parts: list[Any] = []
    for piece in identifier.split("#"):
        match = _ID_NUMBER.match(piece)
        parts.extend((match.group(1), int(match.group(2))) if match else (piece, -1))
    return tuple(parts)


def _mm(metres: float) -> float:
    return round_length(metres * 1000.0)


@dataclass(frozen=True)
class _Geometry:
    """An axis and the axial boxes of the faces on it, ready for projection."""

    origin: np.ndarray
    direction: np.ndarray
    corners: np.ndarray

    def span(self, origin: np.ndarray, direction: np.ndarray) -> tuple[float, float]:
        projections = (self.corners - origin) @ direction
        return float(projections.min()), float(projections.max())

    def midpoint(self) -> np.ndarray:
        low, high = self.span(self.origin, self.direction)
        return self.origin + self.direction * (low + high) / 2.0


def _corners(boxes: Sequence[BBox3D]) -> np.ndarray:
    return np.array(
        [
            [x, y, z]
            for box in boxes
            for x in (box.min.x, box.max.x)
            for y in (box.min.y, box.max.y)
            for z in (box.min.z, box.max.z)
        ],
        dtype=float,
    )


def _point(vector: Any) -> np.ndarray:
    return np.array([vector.x, vector.y, vector.z], dtype=float)


@dataclass(frozen=True)
class HoleInstance:
    """One instance of a Hole Wizard feature: faces of the row that share one axis (R2.1)."""

    id: str
    hole: Hole
    face_ids: tuple[str, ...]
    axis: Axis
    diameters_mm: tuple[float, ...]
    bore_mm: float
    size_mm: float
    size_source: Literal["hole_wizard", "face"]
    axis_aligned: bool
    extent_bound_mm: float
    """How far a face box's projection can overrun the true extent on this axis:
    `r sin(angle to the nearest coordinate axis)` for the largest face, 0 when aligned."""
    geometry: _Geometry = field(repr=False, compare=False)
    counterbore_geometry: _Geometry | None = field(repr=False, compare=False, default=None)

    @property
    def hole_id(self) -> str:
        return self.hole.id

    @property
    def component_id(self) -> str:
        return self.hole.component_id

    @property
    def hole_type(self) -> str:
        return self.hole.hole_type

    @property
    def is_tapped(self) -> bool:
        return self.hole.hole_type == "tapped"

    @property
    def is_clearance(self) -> bool:
        return self.hole.hole_type in CLEARANCE_TYPES

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "component_id": self.component_id,
            "hole_type": self.hole_type,
            "face_ids": list(self.face_ids),
            "diameters_mm": list(self.diameters_mm),
            "size_mm": self.size_mm,
            "size_source": self.size_source,
            "axis_aligned": self.axis_aligned,
        }


@dataclass(frozen=True)
class CylinderMember:
    """A free cylinder face sitting in an instance: a screw's shank or head, a pin (R2.3)."""

    face_id: str
    component_id: str
    diameter_mm: float
    role: MemberRole
    instance_id: str
    offset_mm: float
    overlap_mm: float

    def as_json(self) -> dict[str, Any]:
        return {
            "face_id": self.face_id,
            "component_id": self.component_id,
            "diameter_mm": self.diameter_mm,
            "role": self.role,
            "instance_id": self.instance_id,
            "offset_mm": self.offset_mm,
            "overlap_mm": self.overlap_mm,
        }


@dataclass(frozen=True)
class PairValues:
    """What one pair of instances was judged on, measured along `a`'s axis."""

    a: str
    b: str
    angle_deg: float
    offset_mm: float
    radius_sum_mm: float
    gap_mm: float

    def as_dict(self) -> dict[str, float]:
        return {
            "angle_deg": self.angle_deg,
            "offset_mm": self.offset_mm,
            "radius_sum_mm": self.radius_sum_mm,
            "gap_mm": self.gap_mm,
        }


@dataclass(frozen=True)
class Joint:
    """Two or more members that go together, classified by what they are (R2.4)."""

    id: str
    kind: JointKind
    instances: tuple[HoleInstance, ...]
    cylinders: tuple[CylinderMember, ...]
    reference: str
    """The instance the joint is measured along: its tapped instance, else its first."""
    offset_mm: float
    """The largest lateral offset of any member axis from the reference axis."""
    component_ids: tuple[str, ...]
    pattern_key: str
    """The kind and the `(hole, component)` of every instance. Joints sharing it are one
    pattern group (R2.21); cylinder members are left out, so a screw modelled with a face
    in one joint of a pattern does not split the pattern from its siblings."""
    axis_aligned: bool
    pairs: tuple[PairValues, ...]
    fastener: Any | None = None
    """The recognised fastener placed in the joint, from US4; `None` until then."""

    def instance(self, instance_id: str) -> HoleInstance:
        return next(item for item in self.instances if item.id == instance_id)

    @property
    def reference_instance(self) -> HoleInstance:
        return self.instance(self.reference)

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "instances": [item.id for item in self.instances],
            "cylinders": [item.as_json() for item in self.cylinders],
            "reference": self.reference,
            "offset_mm": self.offset_mm,
            "component_ids": list(self.component_ids),
            "pattern_key": self.pattern_key,
            "axis_aligned": self.axis_aligned,
            "pairs": [{"a": pair.a, "b": pair.b, **pair.as_dict()} for pair in self.pairs],
        }


@dataclass(frozen=True)
class Candidate:
    """A pair listed for the engineer: never a joint, never a finding (R2.2)."""

    members: tuple[str, str]
    reason: CandidateReason
    values: Mapping[str, float]
    component_ids: tuple[str, str]

    def as_json(self) -> dict[str, Any]:
        return {"members": list(self.members), "reason": self.reason, "values": dict(self.values)}


@dataclass(frozen=True)
class JointMapGap:
    """Something the map could not use, and why: a hole, an instance, a component."""

    subject: str
    reason: str
    component_id: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {"subject": self.subject, "reason": self.reason}


@dataclass(frozen=True)
class JointMap:
    """Every joint of a package, the pairs listed for the engineer, and what went unused."""

    instances: tuple[HoleInstance, ...]
    joints: tuple[Joint, ...]
    candidates: tuple[Candidate, ...]
    gaps: tuple[JointMapGap, ...]
    unplaced: tuple[Any, ...]
    rules: JointRules

    def pattern_groups(self) -> dict[str, tuple[str, ...]]:
        """`{pattern key: joint ids}`, in joint order."""
        groups: dict[str, list[str]] = {}
        for joint in self.joints:
            groups.setdefault(joint.pattern_key, []).append(joint.id)
        return {key: tuple(ids) for key, ids in groups.items()}

    def as_json(self) -> dict[str, Any]:
        return {
            "rules_version": self.rules.version,
            "instance_count": len(self.instances),
            "joints": [joint.as_json() for joint in self.joints],
            "pattern_groups": {key: list(ids) for key, ids in self.pattern_groups().items()},
            "candidates": [candidate.as_json() for candidate in self.candidates],
            "gaps": [gap.as_json() for gap in self.gaps],
        }


# --- building the map ------------------------------------------------------------------------


def plain_diameter_mm(size: str | None) -> float | None:
    """A Hole Wizard size written as a bare diameter (`Ø3.0`), or `None` when it is not one.

    A thread designation (`M8`) is not a plain diameter even though it names a size: it is
    the fastener the hole was made for, which `parse_thread` reads.
    """
    if size is None or parse_thread(size).recognized:
        return None
    text = size.strip().lstrip("Øø⌀").strip()
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value > 0 else None


def _angle_deg(a: np.ndarray, b: np.ndarray) -> float:
    return math.degrees(math.acos(min(1.0, abs(float(a @ b)))))


def _lateral(point: np.ndarray, origin: np.ndarray, direction: np.ndarray) -> float:
    between = point - origin
    return float(np.linalg.norm(between - float(between @ direction) * direction))


def _deviation_deg(direction: np.ndarray) -> float:
    return math.degrees(math.acos(min(1.0, float(np.max(np.abs(direction))))))


def _explode(
    package: EvidencePackage, rules: JointRules
) -> tuple[list[HoleInstance], list[JointMapGap]]:
    """Every hole row as instances, and a gap for every row or face that yields none."""
    components = {item.id: item for item in package.components}
    faces = {item.id: item for item in package.faces}
    instances: list[HoleInstance] = []
    gaps: list[JointMapGap] = []

    for hole in sorted(package.holes, key=lambda item: _id_key(item.id)):
        component = components.get(hole.component_id)
        if component is None or component.suppression != "resolved":
            state = "not in the package" if component is None else component.suppression
            gaps.append(
                JointMapGap(
                    hole.id,
                    f"{hole.id} is on {hole.component_id}, which is {state}; its faces were "
                    "not read, so it is in no joint",
                    hole.component_id,
                )
            )
            continue

        groups: list[list[FaceGeometry]] = []
        problems: list[str] = []
        for face_id in sorted(hole.face_ids, key=_id_key):
            face = faces.get(face_id)
            if face is None:
                problems.append(f"face {face_id} is not in the package")
                continue
            if face.kind != "cylinder" or face.cylinder is None:
                continue
            try:
                direction = unit_vector(face.cylinder.axis_dir, f"face {face_id}")
            except ValueError:
                problems.append(f"face {face_id} has a zero-length axis")
                continue
            for group in groups:
                first = group[0].cylinder
                assert first is not None
                first_direction = unit_vector(first.axis_dir, "the instance axis")
                if _angle_deg(first_direction, direction) <= INSTANCE_PARALLEL_DEG and (
                    _lateral(
                        _point(face.cylinder.axis_origin),
                        _point(first.axis_origin),
                        first_direction,
                    )
                    * 1000.0
                    <= INSTANCE_COAXIAL_MM
                ):
                    group.append(face)
                    break
            else:
                groups.append([face])

        if problems:
            gaps.append(
                JointMapGap(hole.id, f"{hole.id}: {'; '.join(problems)}", hole.component_id)
            )
        if not groups and not problems:
            gaps.append(
                JointMapGap(
                    hole.id,
                    f"{hole.id} has no cylinder face, so no instance of it can be measured",
                    hole.component_id,
                )
            )
        for number, group in enumerate(groups, start=1):
            instances.append(_instance(hole, number, group, rules))
    return instances, gaps


def _instance(
    hole: Hole, number: int, group: list[FaceGeometry], rules: JointRules
) -> HoleInstance:
    first = group[0].cylinder
    assert first is not None
    direction = unit_vector(first.axis_dir, f"{hole.id}#{number}")
    diameters = tuple(
        sorted({_mm(face.cylinder.radius_m * 2.0) for face in group if face.cylinder})
    )
    geometry = _Geometry(_point(first.axis_origin), direction, _corners([f.bbox for f in group]))
    counterbore_geometry = None
    if len(diameters) > 1:
        largest = [
            face.bbox
            for face in group
            if face.cylinder is not None and _mm(face.cylinder.radius_m * 2.0) == diameters[-1]
        ]
        counterbore_geometry = _Geometry(geometry.origin, direction, _corners(largest))
    if hole.diameter is not None:
        size_mm, source = round_length(units.as_mm(hole.diameter)), "hole_wizard"
    else:
        size_mm, source = diameters[0], "face"
    aligned = is_axis_aligned(first.axis_dir, rules.axis_aligned_deg)
    bound = (
        0.0
        if aligned
        else round_length(diameters[-1] / 2.0 * math.sin(math.radians(_deviation_deg(direction))))
    )
    return HoleInstance(
        id=f"{hole.id}#{number}",
        hole=hole,
        face_ids=tuple(face.id for face in group),
        axis=Axis(origin=first.axis_origin, direction=first.axis_dir),
        diameters_mm=diameters,
        bore_mm=diameters[0],
        size_mm=size_mm,
        size_source=source,  # type: ignore[arg-type]
        axis_aligned=aligned,
        extent_bound_mm=bound,
        geometry=geometry,
        counterbore_geometry=counterbore_geometry,
    )


def _pair_values(a: HoleInstance, b: HoleInstance) -> PairValues:
    ga, gb = a.geometry, b.geometry
    low_a, high_a = ga.span(ga.origin, ga.direction)
    low_b, high_b = gb.span(ga.origin, ga.direction)
    return PairValues(
        a=a.id,
        b=b.id,
        angle_deg=round_length(_angle_deg(ga.direction, gb.direction)),
        offset_mm=_mm(_lateral(gb.midpoint(), ga.origin, ga.direction)),
        radius_sum_mm=round_length(a.bore_mm / 2.0 + b.bore_mm / 2.0),
        gap_mm=_mm(max(low_a, low_b) - min(high_a, high_b)),
    )


def _judge_pairs(
    instances: Sequence[HoleInstance], rules: JointRules
) -> tuple[list[PairValues], list[Candidate]]:
    """Every pair of instances on different components through the three gates."""
    passed: list[PairValues] = []
    candidates: list[Candidate] = []
    for index, a in enumerate(instances):
        for b in instances[index + 1 :]:
            if a.component_id == b.component_id:
                continue
            angle = round_length(_angle_deg(a.geometry.direction, b.geometry.direction))
            if angle - rules.parallel_deg > rules.candidate_angle_deg:
                continue
            values = _pair_values(a, b)
            misses: list[tuple[CandidateReason, float, float]] = []
            if values.angle_deg > rules.parallel_deg:
                misses.append(
                    ("angle_near", values.angle_deg - rules.parallel_deg, rules.candidate_angle_deg)
                )
            if values.offset_mm >= values.radius_sum_mm:
                misses.append(
                    (
                        "overlap_near",
                        values.offset_mm - values.radius_sum_mm,
                        rules.candidate_overlap_mm,
                    )
                )
            if values.gap_mm >= rules.adjacency_gap_mm:
                misses.append(
                    ("gap_near", values.gap_mm - rules.adjacency_gap_mm, rules.candidate_gap_mm)
                )
            if not misses:
                passed.append(values)
            elif len(misses) == 1 and round_length(misses[0][1]) <= misses[0][2]:
                candidates.append(
                    Candidate(
                        (a.id, b.id),
                        misses[0][0],
                        values.as_dict(),
                        (a.component_id, b.component_id),
                    )
                )
    return passed, candidates


def _assign(
    passed: list[PairValues], by_id: Mapping[str, HoleInstance]
) -> tuple[list[PairValues], list[Candidate]]:
    """One partner per instance per other component: the nearest wins, ties by id (R2.2)."""
    kept: list[PairValues] = []
    losers: list[Candidate] = []
    partner: dict[tuple[str, str], str] = {}
    for values in sorted(
        passed, key=lambda item: (item.offset_mm, _id_key(item.a), _id_key(item.b))
    ):
        a, b = by_id[values.a], by_id[values.b]
        if (a.id, b.component_id) in partner or (b.id, a.component_id) in partner:
            losers.append(
                Candidate(
                    (a.id, b.id),
                    "assigned_elsewhere",
                    values.as_dict(),
                    (a.component_id, b.component_id),
                )
            )
            continue
        partner[(a.id, b.component_id)] = b.id
        partner[(b.id, a.component_id)] = a.id
        kept.append(values)
    return kept, losers


@dataclass(frozen=True)
class _FreeFace:
    face: FaceGeometry
    geometry: _Geometry
    diameter_mm: float


def _free_faces(
    package: EvidencePackage, instances: Sequence[HoleInstance]
) -> tuple[list[_FreeFace], list[JointMapGap]]:
    """Cylinder faces in no hole row: members-to-be, and a gap per part that has holes."""
    in_holes = {face_id for hole in package.holes for face_id in hole.face_ids}
    with_holes = {hole.component_id for hole in package.holes}
    free: list[_FreeFace] = []
    on_parts_with_holes: dict[str, int] = {}
    for face in sorted(package.faces, key=lambda item: _id_key(item.id)):
        if face.id in in_holes or face.kind != "cylinder" or face.cylinder is None:
            continue
        if face.component_id in with_holes:
            on_parts_with_holes[face.component_id] = (
                on_parts_with_holes.get(face.component_id, 0) + 1
            )
            continue
        try:
            direction = unit_vector(face.cylinder.axis_dir, f"face {face.id}")
        except ValueError:
            continue
        geometry = _Geometry(_point(face.cylinder.axis_origin), direction, _corners([face.bbox]))
        free.append(_FreeFace(face, geometry, _mm(face.cylinder.radius_m * 2.0)))
    gaps = [
        JointMapGap(
            component_id,
            f"{count} cylinder face{'s' if count != 1 else ''} on {component_id} "
            f"{'are' if count != 1 else 'is'} in no hole feature; the component has holes of "
            "its own, and the package does not say whether such a face is a bore or a boss, "
            "so none is used as a joint member",
            component_id,
        )
        for component_id, count in sorted(
            on_parts_with_holes.items(), key=lambda item: _id_key(item[0])
        )
    ]
    return free, gaps


def _member(free: _FreeFace, instance: HoleInstance, rules: JointRules) -> CylinderMember | None:
    """`free` as a member of `instance`, or `None` when it fails any test of section 4."""
    if free.face.component_id == instance.component_id:
        return None
    ga = instance.geometry
    if _angle_deg(ga.direction, free.geometry.direction) > rules.parallel_deg:
        return None
    offset = _mm(_lateral(free.geometry.midpoint(), ga.origin, ga.direction))
    if offset > rules.member_coaxial_mm:
        return None
    low, high = free.geometry.span(ga.origin, ga.direction)
    inst_low, inst_high = ga.span(ga.origin, ga.direction)
    overlap = _mm(min(high, inst_high) - max(low, inst_low))
    if overlap <= 0.0:
        return None

    limit = instance.bore_mm
    if instance.is_tapped and instance.hole.thread_designation:
        major = parse_thread(instance.hole.thread_designation).nominal_diameter
        if major is not None:
            limit = max(limit, units.as_mm(major))
    if free.diameter_mm <= round_length(limit + rules.member_diameter_allowance_mm):
        return CylinderMember(
            free.face.id,
            free.face.component_id,
            free.diameter_mm,
            "in_bore",
            instance.id,
            offset,
            overlap,
        )
    counterbore = instance.counterbore_geometry
    if counterbore is not None and free.diameter_mm <= instance.diameters_mm[-1]:
        cb_low, cb_high = counterbore.span(ga.origin, ga.direction)
        if _mm(min(high, cb_high) - max(low, cb_low)) > 0.0:
            return CylinderMember(
                free.face.id,
                free.face.component_id,
                free.diameter_mm,
                "in_counterbore",
                instance.id,
                offset,
                overlap,
            )
    return None


class _Clusters:
    """Union by id: instances and free faces joined by kept pairs and member links."""

    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        self.parent.setdefault(item, item)
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def join(self, a: str, b: str) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            low, high = sorted((root_a, root_b), key=_id_key)
            self.parent[high] = low


def _kind(instances: Sequence[HoleInstance], cylinders: Sequence[CylinderMember]) -> JointKind:
    """Section 6: the first rule that matches (rule 2 arrives with US4's fasteners)."""
    if any(item.is_tapped for item in instances):
        return "screw"
    clearances = [item for item in instances if item.is_clearance]
    if (
        not clearances
        or (len(clearances) < 2 and not cylinders)
        or len(clearances) != len(instances)
    ):
        return "unclassified"
    plain = [plain_diameter_mm(item.hole.size) is not None for item in clearances]
    threads = [
        item.hole.size is not None and parse_thread(item.hole.size).recognized
        for item in clearances
    ]
    if all(plain):
        return "pin"
    if all(threads) and len(clearances) >= 2:
        return "through_bolt"
    return "unclassified"


def _joint(
    number: int,
    instances: list[HoleInstance],
    cylinders: list[CylinderMember],
    pairs: list[PairValues],
    free_by_face: Mapping[str, _FreeFace],
) -> Joint:
    instances = sorted(instances, key=lambda item: _id_key(item.id))
    tapped = [item for item in instances if item.is_tapped]
    reference = (tapped or instances)[0]
    ref = reference.geometry
    offsets = [
        _lateral(item.geometry.midpoint(), ref.origin, ref.direction) for item in instances
    ] + [
        _lateral(free_by_face[item.face_id].geometry.midpoint(), ref.origin, ref.direction)
        for item in cylinders
    ]
    kind = _kind(instances, cylinders)
    members = sorted(f"{item.hole_id}@{item.component_id}" for item in instances)
    return Joint(
        id=f"jnt:{number:04d}",
        kind=kind,
        instances=tuple(instances),
        cylinders=tuple(sorted(cylinders, key=lambda item: _id_key(item.face_id))),
        reference=reference.id,
        offset_mm=_mm(max(offsets)),
        component_ids=tuple(
            sorted(
                {item.component_id for item in instances}
                | {item.component_id for item in cylinders},
                key=_id_key,
            )
        ),
        pattern_key=f"{kind}|{','.join(members)}",
        axis_aligned=all(item.axis_aligned for item in instances),
        pairs=tuple(sorted(pairs, key=lambda item: (_id_key(item.a), _id_key(item.b)))),
    )


def build_joint_map(
    package: EvidencePackage, rules: JointRules | None = None, fasteners: Any = None
) -> JointMap:
    """Every joint of `package`, per `contracts/joint-map.md` sections 1 to 6.

    `fasteners` is where US4's recognised fasteners arrive to be placed (section 5); it is
    accepted and unused until then, so the foundational map is what this returns. Never
    raises on a valid package: whatever cannot be used is a `JointMapGap`.
    """
    del fasteners  # placed from US4 (T041)
    rules = rules or load_joint_rules()
    if package.extractor.profile == "model_check":
        return JointMap(
            (),
            (),
            (),
            (JointMapGap("package", "the hole phase did not run (profile model_check)"),),
            (),
            rules,
        )
    if not package.holes:
        return JointMap((), (), (), (JointMapGap("package", "no hole was extracted"),), (), rules)

    instances, gaps = _explode(package, rules)
    by_id = {item.id: item for item in instances}
    passed, near = _judge_pairs(instances, rules)
    kept, losers = _assign(passed, by_id)
    free, free_gaps = _free_faces(package, instances)

    clusters = _Clusters()
    for values in kept:
        clusters.join(values.a, values.b)
    links: dict[str, list[CylinderMember]] = {}
    for item in free:
        for instance in instances:
            member = _member(item, instance, rules)
            if member is not None:
                links.setdefault(item.face.id, []).append(member)
                clusters.join(instance.id, item.face.id)

    grouped_instances: dict[str, list[HoleInstance]] = {}
    for instance in instances:
        if instance.id in clusters.parent:
            grouped_instances.setdefault(clusters.find(instance.id), []).append(instance)
    grouped_cylinders: dict[str, list[CylinderMember]] = {}
    for face_id, members in links.items():
        first = min(members, key=lambda member: _id_key(member.instance_id))
        grouped_cylinders.setdefault(clusters.find(face_id), []).append(first)
    grouped_pairs: dict[str, list[PairValues]] = {}
    for values in kept:
        grouped_pairs.setdefault(clusters.find(values.a), []).append(values)

    roots = sorted(
        grouped_instances,
        key=lambda root: _id_key(min((item.id for item in grouped_instances[root]), key=_id_key)),
    )
    free_by_face = {item.face.id: item for item in free}
    joints = tuple(
        _joint(
            number,
            grouped_instances[root],
            grouped_cylinders.get(root, []),
            grouped_pairs.get(root, []),
            free_by_face,
        )
        for number, root in enumerate(roots, start=1)
    )
    candidates = tuple(
        sorted(
            [*near, *losers], key=lambda item: (_id_key(item.members[0]), _id_key(item.members[1]))
        )
    )
    return JointMap(
        instances=tuple(instances),
        joints=joints,
        candidates=candidates,
        gaps=tuple(sorted([*gaps, *free_gaps], key=lambda item: _id_key(item.subject))),
        unplaced=(),
        rules=rules,
    )


# --- folding patterned results --------------------------------------------------------------


def _fold_key(joint: Joint, result: CheckResult) -> tuple[Any, ...]:
    """What makes two joints' results one finding: same pattern, check, verdict and numbers."""
    calculation = result.calculation
    numbers = (
        tuple(sorted((key, repr(value)) for key, value in calculation.result.items()))
        if calculation is not None
        else (result.observed, tuple(result.coverage_limits))
    )
    return (joint.pattern_key, result.check, result.status, result.severity, numbers)


def fold_by_pattern(
    results: Sequence[tuple[Joint, CheckResult]],
) -> list[tuple[tuple[Joint, ...], CheckResult]]:
    """Results with the same check, status, severity and calculation result within one
    pattern group, as one entry naming every joint (research R2.21), in first-seen order.

    A result whose numbers differ from its siblings' stays its own entry, so folding never
    hides a joint that differs (plan RK-4). The first joint's result stands for the group;
    the caller writes the joint list into the finding.
    """
    groups: dict[tuple[Any, ...], tuple[list[Joint], CheckResult]] = {}
    for joint, result in results:
        key = _fold_key(joint, result)
        if key in groups:
            groups[key][0].append(joint)
        else:
            groups[key] = ([joint], result)
    return [(tuple(joints), result) for joints, result in groups.values()]
