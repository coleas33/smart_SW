"""Can a tool reach every screw head, and does every recess take its head (feature 010 US5).

`contracts/tool-access.md` is normative. Two questions, asked of every placed screw with no
argument a model chooses:

- **Tool access** (`fastener.head_clearance`, FR-014). The joint says which end of the screw
  is in the thread, so the head is the other end and the tool comes from outside it. The head
  plane is the far end of the screw's mesh, else of its shank face plus the head height from
  `head_dimensions.yaml`, labelled derived; the tool is the one the head code's drive names,
  else the one the head type names (`tool_envelopes.yaml`), else unresolved; its radius and
  reach are pilot defaults that say so (owner answer 2026-09-23). The envelope is swept
  outward against every other body with `geometry.envelope_raycast`, and the existing
  `_head_clearance` rule decides - a body in the way is demonstrated and named.
- **Head fit** (`fastener.head_fit`, FR-015). A counterbore's diameter and depth, or a
  countersink's diameter and angle, against the largest head the screw's standard allows.

Pure but for the mesh load: the checks take meshes as values; the tool loads them. Nothing
is guessed - a missing mesh, face, drive, head row or recess size is unresolved, naming it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Literal

import numpy as np
import trimesh
import yaml

from swreview import units
from swreview.checks.fastener import CHECK_HEAD_CLEARANCE, HeadSweep, parse_thread
from swreview.checks.fastener_identity import (
    MESH_PLACES,
    RecognisedFastener,
    ScrewExtent,
    screw_extent,
    tapped_span_mm,
    thread_entry,
)
from swreview.checks.joint_alignment import JointResult
from swreview.checks.joints import HoleInstance, Joint, JointMap
from swreview.checks.result import ROUNDING_ASSUMPTION, CheckResult, round_length, unresolved
from swreview.checks.tool_envelopes import ToolEnvelopes, load_envelopes
from swreview.findings import Calculation
from swreview.geometry.envelope import envelope_raycast
from swreview.ir.models import Angle, Axis, EvidencePackage, Quantity, Vec3

__all__ = [
    "CHECK_HEAD_CLEARANCE",
    "CHECK_HEAD_FIT",
    "DEFAULT_HEADS_PATH",
    "HeadDimensions",
    "HeadGeometry",
    "HeadRow",
    "ToolChoice",
    "check_head_fit",
    "choose_tool",
    "head_geometry",
    "load_head_dimensions",
    "recess_group",
    "run_head_fit",
    "sweep_head",
]

CHECK_HEAD_FIT = "fastener.head_fit"
FUNCTION = "swreview.checks.tool_access.check_head_fit"
FUNCTION_VERSION = "1"

DEFAULT_HEADS_PATH = Path(__file__).with_name("head_dimensions.yaml")


# --- the head table ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HeadRow:
    """The largest head one standard allows at one size, and where the numbers came from."""

    standard: str
    head_type: str
    size: str
    dk_max_mm: float
    k_max_mm: float
    countersink_angle_deg: float | None
    source: str


@dataclass(frozen=True)
class HeadDimensions:
    """`head_dimensions.yaml`: rows by `(head type, size)`."""

    version: int
    rows: Mapping[tuple[str, str], HeadRow]

    def row(self, head_type: str | None, designation: str | None) -> HeadRow | None:
        """The row for a head type and a thread designation (`M8x1.25` reads as `M8`), or
        `None` when either is missing or the table does not carry it."""
        if head_type is None or designation is None:
            return None
        thread = parse_thread(designation)
        if thread.series != "metric" or thread.nominal_diameter is None:
            return None
        return self.rows.get((head_type.lower(), f"M{thread.nominal_diameter.value:g}"))


def _positive(value: object, name: str, path: Path) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ValueError(f"{path}: {name} must be a positive number, got {value!r}")
    return float(value)


def _parse_heads(document: object, path: Path) -> HeadDimensions:
    if not isinstance(document, Mapping) or "standards" not in document:
        raise ValueError(f"{path}: the head table must be a mapping with standards")
    rows: dict[tuple[str, str], HeadRow] = {}
    for standard, entry in document["standards"].items():
        for key in ("head_type", "source", "rows"):
            if key not in entry:
                raise ValueError(f"{path}: {standard} carries no {key}")
        angle = entry.get("countersink_angle_deg")
        angle = None if angle is None else _positive(angle, f"{standard} angle", path)
        head_type = str(entry["head_type"]).lower()
        for size, row in entry["rows"].items():
            name = f"{standard} {size}"
            rows[(head_type, str(size))] = HeadRow(
                standard=str(standard),
                head_type=head_type,
                size=str(size),
                dk_max_mm=_positive(row.get("dk_max_mm"), f"{name} dk_max_mm", path),
                k_max_mm=_positive(row.get("k_max_mm"), f"{name} k_max_mm", path),
                countersink_angle_deg=angle,
                source=" ".join(str(entry["source"]).split()),
            )
    return HeadDimensions(version=int(document["version"]), rows=rows)


@lru_cache(maxsize=4)
def _load_cached(path: Path) -> HeadDimensions:
    return _parse_heads(yaml.safe_load(path.read_text(encoding="utf-8")), path)


def load_head_dimensions(path: Path | str | None = None) -> HeadDimensions:
    """Read the head table; `path` defaults to the one beside this module. Cached per path."""
    return _load_cached(Path(path or DEFAULT_HEADS_PATH).resolve())


# --- the head and the tool --------------------------------------------------------------------


@dataclass(frozen=True)
class HeadGeometry:
    """Where a placed screw's head is and which way the tool comes from (research R2.15)."""

    joint_id: str
    plane_mm: float
    """The head plane's position along the joint's reference axis, from its origin."""
    head_plane_origin: np.ndarray
    outward: np.ndarray
    """Unit vector from the thread toward the head: the way the tool approaches from."""
    source: Literal["mesh", "face_plus_k"]
    description: str


def _outward_sign(joint: Joint, low_mm: float, high_mm: float) -> int | None:
    """+1 when the head is toward the reference axis's positive end, -1 toward its negative
    end, from which end of the tapped face the screw enters; `None` when that is not read."""
    low, high = tapped_span_mm(joint)
    extent = ScrewExtent(low_mm=low_mm, high_mm=high_mm, source="mesh")
    entry = thread_entry(extent, low, high)
    if entry == "high":
        return 1
    if entry == "low":
        return -1
    screw_mid, tapped_mid = (low_mm + high_mm) / 2.0, (low + high) / 2.0
    if screw_mid == tapped_mid:
        return None
    return 1 if screw_mid > tapped_mid else -1


def head_geometry(
    joint: Joint,
    package: EvidencePackage,
    screw_mesh: trimesh.Trimesh | None,
    heads: HeadDimensions | None = None,
) -> HeadGeometry | str:
    """The head plane and the outward direction of `joint`'s placed screw, or why not.

    The far end of the screw's mesh first (exact on any axis); else the far end of its shank
    face plus the head height `k_max`, labelled derived, which needs an aligned axis and a
    head row; else unresolved.
    """
    placed = joint.fastener
    assert placed is not None and joint.tapped_instance is not None
    reference = joint.reference_instance
    geometry = reference.geometry
    mesh_extent = screw_extent(_without_face(joint), package, screw_mesh)
    if mesh_extent is not None:
        sign = _outward_sign(joint, mesh_extent.low_mm, mesh_extent.high_mm)
        if sign is None:
            return "which end of the screw is its head is not measured"
        plane = mesh_extent.high_mm if sign > 0 else mesh_extent.low_mm
        source: Literal["mesh", "face_plus_k"] = "mesh"
        description = "the far end of the screw's exported mesh (supplementary geometry)"
    else:
        face_extent = screw_extent(joint, package, None)
        if face_extent is None or face_extent.source != "face":
            return "the screw has no exported mesh and no extracted face"
        if not reference.axis_aligned:
            return "the axis is oblique; the shank face's bounding box is not used"
        row = (heads or load_head_dimensions()).row(
            placed.fastener.head_type, placed.fastener.thread_designation
        )
        if row is None:
            return (
                f"the head of a {placed.fastener.head_type or 'unnamed'} "
                f"{placed.designation} screw is not in head_dimensions.yaml"
            )
        sign = _outward_sign(joint, face_extent.low_mm, face_extent.high_mm)
        if sign is None:
            return "which end of the screw is its head is not measured"
        far = face_extent.high_mm if sign > 0 else face_extent.low_mm
        plane = round(far + sign * row.k_max_mm, MESH_PLACES)
        source = "face_plus_k"
        description = (
            f"derived: the far end of shank face {placed.shank_face_id} plus k max "
            f"{row.k_max_mm!r} mm ({row.standard})"
        )
    outward = geometry.direction * float(sign)
    return HeadGeometry(
        joint_id=joint.id,
        plane_mm=round(plane, MESH_PLACES),
        head_plane_origin=geometry.origin + geometry.direction * (plane / 1000.0),
        outward=outward,
        source=source,
        description=description,
    )


def _without_face(joint: Joint) -> Joint:
    """The joint as `screw_extent` should read it for the head: from the mesh, whether or
    not the screw also has a shank face (the head is in the mesh, not in the shank)."""
    assert joint.fastener is not None
    return replace(joint, fastener=replace(joint.fastener, shank_face_id=None))


@dataclass(frozen=True)
class ToolChoice:
    """The tool that turns a head, how wide and how far it sweeps, and why that tool."""

    tool: str
    reason: Literal["drive", "head_type"]
    radius_mm: float
    reach_mm: float
    sources: tuple[str, ...]


def choose_tool(
    placed: RecognisedFastener, envelopes: ToolEnvelopes | None = None
) -> ToolChoice | str:
    """`contracts/tool-access.md` section 2: the drive, else the head type, else why not."""
    envelopes = envelopes or load_envelopes()
    fastener = placed.fastener
    designation = fastener.thread_designation
    nominal = None if designation is None else parse_thread(designation).nominal_diameter
    if nominal is None or not placed.size_trusted:
        return f"the size of {placed.designation} is not known well enough to size a tool"
    reason: Literal["drive", "head_type"]
    if fastener.drive is not None and fastener.drive.lower() in envelopes.drive_tools:
        tool, reason = envelopes.drive_tools[fastener.drive.lower()], "drive"
    elif fastener.head_type is not None and fastener.head_type.lower() in envelopes.head_tools:
        tool, reason = envelopes.head_tools[fastener.head_type.lower()], "head_type"
    else:
        code = placed.name.head_code if placed.name is not None else None
        return (
            f"the drive of head code {code or fastener.head_type or 'unnamed'} is not stated "
            "in fastener_names.yaml, and no tool is named for its head type"
        )
    d = units.as_mm(nominal)
    return ToolChoice(
        tool=tool,
        reason=reason,
        radius_mm=round_length(envelopes.radius_mm(tool, d)),
        reach_mm=round_length(envelopes.reach_mm(tool, d)),
        sources=(" ".join(envelopes.tools[tool].source.split()),),
    )


# --- the sweep --------------------------------------------------------------------------------


def _envelope_box(head: HeadGeometry, radius_m: float, reach_m: float) -> np.ndarray:
    start = head.head_plane_origin
    end = start + head.outward * reach_m
    return np.array([np.minimum(start, end) - radius_m, np.maximum(start, end) + radius_m])


def _near(mesh: trimesh.Trimesh, box: np.ndarray) -> bool:
    bounds = np.asarray(mesh.bounds, dtype=float)
    return bool(np.all(bounds[1] >= box[0]) and np.all(bounds[0] <= box[1]))


def sweep_head(
    joint: Joint,
    package: EvidencePackage,
    *,
    screw_mesh: trimesh.Trimesh | None,
    others: Sequence[tuple[str, trimesh.Trimesh | None]],
    unfetched: Sequence[str] = (),
    heads: HeadDimensions | None = None,
    envelopes: ToolEnvelopes | None = None,
) -> HeadSweep:
    """Sweep `joint`'s screw head: the head, the tool, then the raycast outward over every
    other body in `others` (the screw's own excluded by the caller; a `None` mesh is one that
    could not be loaded and is named). A body whose bounds the envelope cannot reach is not
    cast against - it cannot be hit. `unfetched` names components whose bodies lever 10a
    never fetched; each makes the sweep unresolved rather than clear."""
    placed = joint.fastener
    assert placed is not None
    head = head_geometry(joint, package, screw_mesh, heads)
    if isinstance(head, str):
        return HeadSweep(envelope=None, missing=head)
    tool = choose_tool(placed, envelopes)
    if isinstance(tool, str):
        return HeadSweep(envelope=None, missing=tool)

    radius_m, reach_m = tool.radius_mm / 1000.0, tool.reach_mm / 1000.0
    box = _envelope_box(head, radius_m, reach_m)
    swept = [(cid, mesh) for cid, mesh in others if mesh is None or _near(mesh, box)]
    origin = head.head_plane_origin
    direction = -head.outward
    result = envelope_raycast(
        Axis(
            origin=Vec3(x=float(origin[0]), y=float(origin[1]), z=float(origin[2])),
            direction=Vec3(x=float(direction[0]), y=float(direction[1]), z=float(direction[2])),
        ),
        radius_m=radius_m,
        length_m=reach_m,
        meshes=swept,
    )
    result.unresolved.extend(
        f"{cid}: its body was never fetched (lazy meshes, lever 10a), so it was not swept"
        for cid in unfetched
    )
    return HeadSweep(
        envelope=result,
        inputs={
            "tool": tool.tool,
            "tool_chosen_by": tool.reason,
            "tool_radius": Quantity(value=tool.radius_mm, unit="mm"),
            "tool_reach": Quantity(value=tool.reach_mm, unit="mm"),
            "tool_source": tool.sources[0],
            "head_plane_mm": Quantity(value=head.plane_mm, unit="mm"),
            "head_plane_source": head.description,
        },
    )


# --- head fit -----------------------------------------------------------------------------------

HEAD_FIT_REQUIREMENT = (
    "a counterbore or countersink receives the largest head the screw's standard allows: "
    "its diameter at least the head's dk max and a counterbore at least k max deep"
)


def _recess(joint: Joint) -> HoleInstance | None:
    return next(
        (item for item in joint.instances if item.hole_type in ("counterbore", "countersink")),
        None,
    )


def recess_group(joint: Joint) -> str:
    """The fold group of a head-fit result: the screw's document and the recessed part."""
    recess = _recess(joint)
    assert joint.fastener is not None and recess is not None
    return f"{joint.fastener.document_id}|{recess.component_id}"


def _wizard_mm(value: Quantity | None) -> float | None:
    return None if value is None else round_length(units.as_mm(value))


def _degrees(value: Angle | None) -> float | None:
    if value is None:
        return None
    return round_length(math.degrees(value.value) if value.unit == "rad" else value.value)


def _number(value: float) -> str:
    return repr(round_length(value))


def check_head_fit(
    joint: Joint, package: EvidencePackage, heads: HeadDimensions | None = None
) -> CheckResult | None:
    """`fastener.head_fit` for `joint`'s placed screw and its counterbore or countersink,
    or `None` when the joint has no placed screw or no recess (`contracts/tool-access.md`
    section 4)."""
    del package  # everything read is on the joint
    placed, recess = joint.fastener, _recess(joint)
    if placed is None or recess is None:
        return None
    fastener = placed.fastener
    inputs: list[Quantity | str] = [recess.id, placed.component_id]

    def missing(what: str) -> CheckResult:
        return unresolved(
            CHECK_HEAD_FIT,
            what,
            inputs,
            requirement=HEAD_FIT_REQUIREMENT,
            recommended_action=(
                "Supply the missing size (Hole Wizard data, a head standard for this screw), "
                "then re-run the review."
            ),
        )

    if not placed.size_trusted:
        return missing(f"the head of {placed.designation} ({placed.untrusted_reason()})")
    row = (heads or load_head_dimensions()).row(fastener.head_type, fastener.thread_designation)
    if row is None:
        return missing(
            f"the head of a {fastener.head_type or 'unnamed'} {placed.designation} screw "
            "(head_dimensions.yaml carries no row for it)"
        )
    wizard = recess.hole.wizard
    calc_inputs: dict[str, Quantity | str] = {
        "recess_instance": recess.id,
        "dk_max": Quantity(value=row.dk_max_mm, unit="mm"),
        "k_max": Quantity(value=row.k_max_mm, unit="mm"),
        "head_standard": f"{row.standard} {row.size}: {row.source}",
    }
    result: dict[str, Quantity | bool | str | float] = {
        "recess": recess.hole_type,
        "dk_max_mm": row.dk_max_mm,
        "k_max_mm": row.k_max_mm,
        "standard": f"{row.standard} {row.size}",
    }
    head = f"{placed.designation} {row.head_type} ({row.standard})"
    problems: list[tuple[str, str]] = []

    if recess.hole_type == "counterbore":
        diameter = _wizard_mm(None if wizard is None else wizard.counterbore_diameter)
        diameter_source = "the Hole Wizard counterbore diameter"
        if diameter is None and len(recess.diameters_mm) >= 2:
            diameter, diameter_source = recess.diameters_mm[-1], "derived from the counterbore face"
        if diameter is None:
            return missing(
                f"the counterbore diameter of {recess.id} (one face diameter and no Hole Wizard "
                "counterbore size)"
            )
        depth = _wizard_mm(None if wizard is None else wizard.counterbore_depth)
        depth_source = "the Hole Wizard counterbore depth"
        if depth is None:
            if recess.counterbore_geometry is None:
                return missing(f"the counterbore depth of {recess.id} (no counterbore face)")
            if not recess.axis_aligned:
                return missing(
                    f"the counterbore depth of {recess.id} (the axis is oblique; bounding-box "
                    "extents are not used)"
                )
            cb = recess.counterbore_geometry
            low, high = cb.span(recess.geometry.origin, recess.geometry.direction)
            depth = round_length((high - low) * 1000.0)
            depth_source = "derived: the counterbore face's axial extent"
        calc_inputs.update(
            {
                "recess_diameter": Quantity(value=diameter, unit="mm"),
                "recess_diameter_source": diameter_source,
                "recess_depth": Quantity(value=depth, unit="mm"),
                "recess_depth_source": depth_source,
            }
        )
        result.update({"recess_diameter_mm": diameter, "recess_depth_mm": depth})
        if diameter < row.dk_max_mm:
            problems.append(
                (
                    "high",
                    f"The {_number(diameter)} mm counterbore of {recess.id} is smaller than the "
                    f"{_number(row.dk_max_mm)} mm head of an {head}: the head cannot seat",
                )
            )
        if depth < row.k_max_mm:
            problems.append(
                (
                    "medium",
                    f"The {_number(depth)} mm deep counterbore of {recess.id} is shallower than "
                    f"the {_number(row.k_max_mm)} mm head of an {head}: the head stands "
                    f"{_number(row.k_max_mm - depth)} mm proud",
                )
            )
        passed = (
            f"The {_number(diameter)} x {_number(depth)} mm counterbore of {recess.id} receives "
            f"the {_number(row.dk_max_mm)} x {_number(row.k_max_mm)} mm head of an {head}"
        )
    else:
        diameter = _wizard_mm(None if wizard is None else wizard.countersink_diameter)
        if diameter is None:
            return missing(
                f"the countersink diameter of {recess.id} (read from the Hole Wizard from IR "
                "1.5.0; this package does not carry it)"
            )
        angle = _degrees(None if wizard is None else wizard.countersink_angle)
        calc_inputs.update(
            {
                "recess_diameter": Quantity(value=diameter, unit="mm"),
                "recess_diameter_source": "the Hole Wizard countersink diameter",
            }
        )
        result["recess_diameter_mm"] = diameter
        if diameter < row.dk_max_mm:
            problems.append(
                (
                    "high",
                    f"The {_number(diameter)} mm countersink of {recess.id} is smaller than the "
                    f"{_number(row.dk_max_mm)} mm head of an {head}: the head stands proud",
                )
            )
        if angle is not None and row.countersink_angle_deg is not None:
            calc_inputs["countersink_angle"] = f"{_number(angle)} deg"
            result["countersink_angle_deg"] = angle
            if abs(angle - row.countersink_angle_deg) > 1e-6:
                problems.append(
                    (
                        "high",
                        f"The {_number(angle)} degree countersink of {recess.id} does not "
                        f"match the {_number(row.countersink_angle_deg)} degree head of an "
                        f"{head}",
                    )
                )
        passed = (
            f"The {_number(diameter)} mm countersink of {recess.id} receives the "
            f"{_number(row.dk_max_mm)} mm head of an {head}"
        )

    result["fits"] = not problems
    calculation = Calculation(
        model=CHECK_HEAD_FIT,
        inputs=calc_inputs,  # type: ignore[arg-type]
        assumptions=[
            "the head is at the largest size its standard allows (dk max, k max)",
            "a counterbore's diameter is its larger face and its depth that face's length "
            "along the axis, unless the Hole Wizard states them",
            ROUNDING_ASSUMPTION,
        ],
        excluded_effects=[
            "the socket or key that turns the head (fastener.head_clearance covers the tool)",
            "washers under the head, and the head's chamfer and fillet",
        ],
        result=result,
        units_out="mm",
        function=FUNCTION,
        function_version=FUNCTION_VERSION,
    )
    if problems:
        severity = "high" if any(level == "high" for level, _ in problems) else "medium"
        return CheckResult(
            check=CHECK_HEAD_FIT,
            status="demonstrated",
            severity=severity,  # type: ignore[arg-type]
            observed="; ".join(text for _, text in problems),
            requirement=HEAD_FIT_REQUIREMENT,
            inputs=inputs,
            calculation=calculation,
            coverage_limits=[],
            recommended_action=(
                f"Open up the {recess.hole_type} of {recess.id} to take the head, or choose a "
                "screw whose head it receives."
            ),
        )
    return CheckResult(
        check=CHECK_HEAD_FIT,
        status="checked_within_scope",
        severity="info",
        observed=passed,
        requirement=HEAD_FIT_REQUIREMENT,
        inputs=inputs,
        calculation=calculation,
        coverage_limits=[
            f"{CHECK_HEAD_FIT} compared the recess with the head only; the tool is "
            "fastener.head_clearance's"
        ],
        recommended_action="",
    )


def run_head_fit(
    package: EvidencePackage, joint_map: JointMap, heads: HeadDimensions | None = None
) -> list[JointResult]:
    """`fastener.head_fit` over every joint with a placed screw and a recess, tapped or not:
    a head that cannot seat is a defect whether or not the thread it drives into was read."""
    return [
        JointResult(joint, result)
        for joint in joint_map.joints
        if (result := check_head_fit(joint, package, heads)) is not None
    ]
