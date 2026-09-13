"""Distances between axes and between faces, in the world frame.

`axis_distance` backs `measure_axis_distance` and the `hole.coaxiality` check;
`face_gap` backs `measure_face_gap`. Both take IR entities and return either a number or
an explicit "unsupported" - never an approximation of a case they cannot model
(contracts/agent-tools.md, constitution Principle II).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

from swreview.ir.models import Axis, FaceGeometry, Quantity, Vec3

__all__ = [
    "ANGLE_TOL_RAD",
    "DISTANCE_TOL_M",
    "AxisRelation",
    "axis_distance",
    "face_gap",
    "unit_vector",
]

AxisRelationKind = Literal["parallel", "skew", "intersecting", "coincident"]

ANGLE_TOL_RAD = 1e-9
"""Below this the axes are treated as parallel. Extracted directions are unit vectors
computed by SOLIDWORKS, so the residual is float noise, not modelling slop."""

DISTANCE_TOL_M = 1e-12
"""Below this the axes are treated as meeting (1 pm; float noise on metre-scale data)."""


@dataclass(frozen=True)
class AxisRelation:
    """How two axes sit relative to one another, in metres and radians."""

    distance_m: float
    angle_rad: float
    relation: AxisRelationKind


def unit_vector(vector: Vec3, what: str) -> np.ndarray:
    """`vector` normalised, or `ValueError` naming `what` when it has no direction.

    The one normalisation in the reviewer: an axis, a face normal and a fastener axis are
    all directions the extractor emitted, and a zero-length one is a missing input, not a
    direction to approximate (constitution Principle I).
    """
    array = np.array([vector.x, vector.y, vector.z], dtype=float)
    norm = float(np.linalg.norm(array))
    if norm == 0.0:
        raise ValueError(f"{what} has a zero-length direction vector")
    return array / norm


def _point(vector: Vec3) -> np.ndarray:
    return np.array([vector.x, vector.y, vector.z], dtype=float)


def _line_relation(
    origin_a: np.ndarray,
    direction_a: np.ndarray,
    origin_b: np.ndarray,
    direction_b: np.ndarray,
) -> AxisRelation:
    """Closest distance and angle between two infinite lines given as unit directions."""
    # Direction sign is arbitrary on an axis, so the angle is measured between lines:
    # |cos| folds it into [0, pi/2].
    cosine = min(1.0, abs(float(np.dot(direction_a, direction_b))))
    angle_rad = math.acos(cosine)
    between = origin_b - origin_a

    if angle_rad <= ANGLE_TOL_RAD:
        perpendicular = between - float(np.dot(between, direction_a)) * direction_a
        distance_m = float(np.linalg.norm(perpendicular))
        relation: AxisRelationKind = "coincident" if distance_m <= DISTANCE_TOL_M else "parallel"
        return AxisRelation(distance_m=distance_m, angle_rad=angle_rad, relation=relation)

    normal = np.cross(direction_a, direction_b)
    distance_m = abs(float(np.dot(between, normal))) / float(np.linalg.norm(normal))
    relation = "intersecting" if distance_m <= DISTANCE_TOL_M else "skew"
    return AxisRelation(distance_m=distance_m, angle_rad=angle_rad, relation=relation)


def axis_distance(a: Axis, b: Axis) -> AxisRelation:
    """Closest distance and angle between two axes treated as infinite lines.

    For parallel axes the distance is the perpendicular distance between the lines; for
    skew axes it is the common-perpendicular distance. Raises `ValueError` when either
    direction vector is zero-length.
    """
    return _line_relation(
        _point(a.origin),
        unit_vector(a.direction, "axis a"),
        _point(b.origin),
        unit_vector(b.direction, "axis b"),
    )


def _as_mm(metres: float) -> Quantity:
    return Quantity(value=metres * 1000.0, unit="mm")


def _plane_gap(a: FaceGeometry, b: FaceGeometry) -> Quantity | Literal["unsupported"]:
    if a.plane is None or b.plane is None:
        return "unsupported"
    normal_a = unit_vector(a.plane.normal, f"face {a.id}")
    normal_b = unit_vector(b.plane.normal, f"face {b.id}")
    if math.acos(min(1.0, abs(float(np.dot(normal_a, normal_b))))) > ANGLE_TOL_RAD:
        return "unsupported"
    between = _point(b.plane.origin) - _point(a.plane.origin)
    return _as_mm(float(np.dot(between, normal_a)))


def _cylinder_gap(a: FaceGeometry, b: FaceGeometry) -> Quantity | Literal["unsupported"]:
    if a.cylinder is None or b.cylinder is None:
        return "unsupported"
    relation = _line_relation(
        _point(a.cylinder.axis_origin),
        unit_vector(a.cylinder.axis_dir, f"face {a.id}"),
        _point(b.cylinder.axis_origin),
        unit_vector(b.cylinder.axis_dir, f"face {b.id}"),
    )
    if relation.relation != "coincident":
        return "unsupported"
    return _as_mm(b.cylinder.radius_m - a.cylinder.radius_m)


def face_gap(a: FaceGeometry, b: FaceGeometry) -> Quantity | Literal["unsupported"]:
    """Signed gap between two faces, or `"unsupported"` for a pair this cannot model.

    Two cases are supported. For parallel planes the gap is measured along `a`'s normal,
    so it is positive when `b` lies on the side `a` faces and negative when `b` is behind
    it. For coaxial cylinders the gap is the radius difference `b - a`, negative when `b`
    is the smaller of the two - the shaft-in-bore sign convention.

    Every other pair (non-parallel planes, offset cylinders, cones, tori, a face whose
    geometry the extractor did not record) returns `"unsupported"`: the caller reports it
    as unresolved coverage rather than as a measurement.
    """
    if a.kind == "plane" and b.kind == "plane":
        return _plane_gap(a, b)
    if a.kind == "cylinder" and b.kind == "cylinder":
        return _cylinder_gap(a, b)
    return "unsupported"
