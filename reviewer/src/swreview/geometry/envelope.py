"""Tool-envelope raycasting along a fastener axis (research R7).

The question is whether a driver can reach the screw head: sweep the cylinder the tool
occupies - a ring of rays on the envelope circle plus one down the centre - backwards from
the head plane and report every body the sweep runs into.

`embreex` accelerates the cast when its wheel is installed for the running CPython and is
optional by design; the pure-Python intersector produces the same hits. A body whose mesh
the caller could not load is listed in `unresolved`, never silently skipped
(constitution Principle I).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
import trimesh

from swreview.geometry.axis import unit_vector
from swreview.ir.models import Axis

__all__ = [
    "RING_RAY_COUNT",
    "EnvelopeHit",
    "EnvelopeResult",
    "embree_available",
    "envelope_raycast",
]

RING_RAY_COUNT = 16
"""Rays around the envelope circle, plus one down the axis. Enough to catch a boss or a
neighbouring screw head beside the axis without the cost of a full swept-volume boolean;
the sampling limit is reported as a coverage limit by the caller."""

_PARALLEL_EPS = 1e-12
"""A ray whose direction lies in a triangle's plane to within this does not hit it."""


@dataclass(frozen=True)
class EnvelopeHit:
    """One body the tool envelope runs into, and how far away it is from the head plane."""

    component_id: str
    first_hit_distance_m: float


@dataclass(frozen=True)
class EnvelopeResult:
    """Bodies in the way, and bodies that could not be tested."""

    hits: list[EnvelopeHit] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)


@lru_cache(maxsize=1)
def embree_available() -> bool:
    """True when the optional `embreex` wheel imports on this interpreter."""
    try:
        import embreex  # noqa: F401
    except ImportError:
        return False
    return True


def _perpendicular_basis(direction: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Two unit vectors spanning the plane perpendicular to `direction`."""
    seed = np.array([1.0, 0.0, 0.0]) if abs(direction[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(direction, seed)
    u /= np.linalg.norm(u)
    return u, np.cross(direction, u)


def _ray_origins(axis: Axis, radius_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Origins on the head-plane envelope circle (plus its centre) and the travel direction."""
    direction = unit_vector(axis.direction, "fastener_axis")
    centre = np.array([axis.origin.x, axis.origin.y, axis.origin.z], dtype=float)
    u, v = _perpendicular_basis(direction)
    angles = np.linspace(0.0, 2.0 * np.pi, RING_RAY_COUNT, endpoint=False)
    ring = centre + radius_m * (np.outer(np.cos(angles), u) + np.outer(np.sin(angles), v))
    # The tool approaches from behind the head, so it travels against the axis direction,
    # which points from the head towards the tip.
    return np.vstack([centre[None, :], ring]), -direction


def _embree_hit_distance(
    mesh: trimesh.Trimesh,
    origins: np.ndarray,
    direction: np.ndarray,
    length_m: float,
) -> float | None:
    from trimesh.ray.ray_pyembree import RayMeshIntersector

    directions = np.tile(direction, (len(origins), 1))
    locations, index_ray, _ = RayMeshIntersector(mesh).intersects_location(origins, directions)
    if len(locations) == 0:
        return None
    distances = np.linalg.norm(locations - origins[index_ray], axis=1)
    within = distances[distances <= length_m]
    return None if len(within) == 0 else float(within.min())


def _fallback_hit_distance(
    mesh: trimesh.Trimesh,
    origins: np.ndarray,
    direction: np.ndarray,
    length_m: float,
) -> float | None:
    """Moller-Trumbore over every triangle, vectorised across rays and triangles.

    trimesh's own pure-Python intersector needs an r-tree broad phase (`rtree`), a
    dependency this project does not carry; the bodies here are single exported solids and
    the ray count is fixed at `RING_RAY_COUNT + 1`, so the brute-force form is fast enough
    and keeps `embreex` genuinely optional (research R7).
    """
    triangles = np.asarray(mesh.triangles, dtype=float)  # (n, 3, 3)
    corner = triangles[:, 0, :]
    edge_1 = triangles[:, 1, :] - corner
    edge_2 = triangles[:, 2, :] - corner

    p = np.cross(direction, edge_2)  # (n, 3)
    determinant = np.einsum("nk,nk->n", edge_1, p)  # (n,)
    parallel = np.abs(determinant) < _PARALLEL_EPS
    inverse = np.where(parallel, 1.0, determinant)

    offset = origins[:, None, :] - corner[None, :, :]  # (m, n, 3)
    u = np.einsum("mnk,nk->mn", offset, p) / inverse
    q = np.cross(offset, edge_1[None, :, :])  # (m, n, 3)
    v = np.einsum("mnk,k->mn", q, direction) / inverse
    distance = np.einsum("nk,mnk->mn", edge_2, q) / inverse

    inside = (u >= 0.0) & (v >= 0.0) & (u + v <= 1.0)
    hit = inside & ~parallel[None, :] & (distance >= 0.0) & (distance <= length_m)
    if not hit.any():
        return None
    return float(distance[hit].min())


def _first_hit_distance(
    mesh: trimesh.Trimesh,
    origins: np.ndarray,
    direction: np.ndarray,
    length_m: float,
    use_embree: bool,
) -> float | None:
    if len(mesh.faces) == 0:
        return None
    if use_embree:
        return _embree_hit_distance(mesh, origins, direction, length_m)
    return _fallback_hit_distance(mesh, origins, direction, length_m)


def envelope_raycast(
    fastener_axis: Axis,
    radius_m: float,
    length_m: float,
    meshes: Sequence[tuple[str, trimesh.Trimesh | None]],
    use_embree: bool | None = None,
) -> EnvelopeResult:
    """Cast the tool envelope back from the head plane and report what it runs into.

    `fastener_axis.origin` is the head plane and `fastener_axis.direction` points from the
    head towards the tip, so the rays travel along `-direction` for `length_m`. `meshes`
    pairs a component id with its mesh in the world frame, in metres; a `None` mesh means
    the caller could not load that body and is reported in `unresolved`.

    `use_embree` defaults to using `embreex` when it is installed. Both intersectors
    return the same hits; embree is only faster.

    Raises `ValueError` for a non-positive envelope or a zero-length axis direction.
    """
    if radius_m <= 0.0:
        raise ValueError(f"radius_m must be positive, got {radius_m}")
    if length_m <= 0.0:
        raise ValueError(f"length_m must be positive, got {length_m}")
    if use_embree is None:
        use_embree = embree_available()

    origins, direction = _ray_origins(fastener_axis, radius_m)
    hits: list[EnvelopeHit] = []
    unresolved: list[str] = []
    for component_id, mesh in meshes:
        if mesh is None:
            unresolved.append(f"missing mesh for component {component_id}")
            continue
        distance = _first_hit_distance(mesh, origins, direction, length_m, use_embree)
        if distance is not None:
            hits.append(EnvelopeHit(component_id=component_id, first_hit_distance_m=distance))
    return EnvelopeResult(hits=hits, unresolved=unresolved)
