"""Which components are fasteners, and whether their names can be believed (feature 010 US4).

`contracts/fasteners.md` section 3 is normative. `recognise_fasteners` finds them:

1. every `Fastener` row, as the extractor wrote it; its component's names, when they parse,
   only cross-check it;
2. every other *resolved* component whose file name, Description or configuration name
   parses to a screw, bolt or pin (`checks/fastener_names.py`), one per instance, with an
   in-memory `Fastener` built from the name - `identity_source = "name_parse"`;
3. its **shank**, the component's free cylinder face of largest area, compared with the
   thread's ISO 68-1 band `[d3 - 0.05, d + 0.05]` mm, `d3 = d - 1.226869 P`: from the basic
   minor diameter to the major one, because a recorded package models screws both ways - an
   M10x1.5 at 8.5 mm and an M3 at 3.0 mm (research R2.12). The 0.05 mm is a stated
   modelling allowance, not a tolerance.

`build_joint_map(package, fasteners=...)` places them (`contracts/joint-map.md` section 5).

`fastener.identity` is **suspected**, one finding per document, when the shank lies outside
the band or two of the fastener's names disagree on its size: a correct name is not a
suspicion, but a name the geometry contradicts is, and every check that would lean on that
size - engagement above all - stays unresolved for it (the spec's parser-disagreement edge
case). No size is ever reconciled or guessed (constitution Principle I).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
import trimesh

from swreview import units
from swreview.checks.engagement_rules import EngagementRules
from swreview.checks.fastener import (
    CHECK_ENGAGEMENT,
    CHECK_HEAD_CLEARANCE,
    THROUGH_TAPPED_SOURCE,
    Placement,
    ThreadSpec,
    UsableThread,
    check_placed_screw,
    parse_thread,
)
from swreview.checks.fastener_names import (
    SOURCE_LABELS,
    FastenerNames,
    ParsedName,
    load_fastener_names,
    read_fastener_names,
    same_thread,
)
from swreview.checks.joint_alignment import JointResult
from swreview.checks.joints import Joint, JointMap, build_joint_map, component_frame
from swreview.checks.result import CheckResult, round_length
from swreview.findings import Calculation
from swreview.geometry.axis import axial_extent
from swreview.geometry.envelope import EnvelopeResult
from swreview.ir.models import (
    Axis,
    ComponentInstance,
    Document,
    EvidencePackage,
    FaceGeometry,
    Fastener,
    Quantity,
    Vec3,
)
from swreview.report.session import CoverageItem, CoverageScope

__all__ = [
    "CHECK_IDENTITY",
    "MINOR_DIAMETER_FACTOR",
    "RECOGNISED_KINDS",
    "SHANK_ALLOWANCE_MM",
    "Agreement",
    "EnvelopeOf",
    "FastenerChecks",
    "MeshOf",
    "RecognisedFastener",
    "ScrewExtent",
    "check_identity",
    "fastener_group",
    "joint_map_with_fasteners",
    "measure_placement",
    "recognise_fasteners",
    "run_fastener_checks",
    "screw_extent",
    "shank_band_mm",
]

CHECK_IDENTITY = "fastener.identity"
FUNCTION = "swreview.checks.fastener_identity.check_identity"
FUNCTION_VERSION = "1"

RECOGNISED_KINDS: tuple[str, ...] = ("screw", "bolt", "pin")
"""A name that parses to one of these makes a component a fastener; a nut or a washer
named by size is recorded nowhere yet (it is not in a joint the checks model)."""

MINOR_DIAMETER_FACTOR = 1.226869
"""ISO 68-1: the basic minor diameter of an external thread is `d - 1.226869 P`."""

SHANK_ALLOWANCE_MM = 0.05
"""The modelling allowance either side of the band, stated, never a tolerance (R2.12)."""

DESCRIPTION_PROPERTY = "Description"
"""The property the vendor shape writes its description into (`contracts/fasteners.md`
section 1). Read from the referenced configuration's properties first, then the document's."""

Agreement = Literal["agrees", "disagrees", "unmeasured"]
IdentitySource = Literal["toolbox", "custom_property", "name_parse", "manual"]

REQUIREMENT = (
    "a fastener's name and its modelled shank agree: the shank lies between the thread's "
    f"basic minor diameter less {SHANK_ALLOWANCE_MM} mm and its major diameter plus "
    f"{SHANK_ALLOWANCE_MM} mm (ISO 68-1), and every name the part carries states the same size"
)


@dataclass(frozen=True)
class RecognisedFastener:
    """One fastener instance: what it is, how it is known, and how far its name holds."""

    component_id: str
    document_id: str
    identity_source: IdentitySource
    name: ParsedName | None
    """The first of the component's names that parsed; the others cross-check it."""
    name_conflicts: tuple[str, ...]
    fastener: Fastener
    shank_face_id: str | None
    shank_mm: float | None
    shank_source: Literal["face"] | None
    band_mm: tuple[float, float] | None
    agreement: Agreement
    placement: Literal["face", "origin"] | None = None
    """Set by `build_joint_map`; `None` until placed, and for an unplaced fastener."""
    placed_on: str | None = None
    """The hole instance the fastener was placed on."""
    unplaced_reason: str | None = None

    @property
    def designation(self) -> str:
        return self.fastener.thread_designation or "an unsized fastener"

    @property
    def size_trusted(self) -> bool:
        """Whether a check may lean on the named size: the shank does not contradict it and
        no two names disagree about it."""
        return self.agreement != "disagrees" and not self.name_conflicts

    def untrusted_reason(self) -> str:
        """Why the size cannot be leaned on, in words a missing-input phrase can carry."""
        reasons = []
        if self.agreement == "disagrees":
            reasons.append("the parsed size disagrees with the measured shank")
        reasons.extend(self.name_conflicts)
        return "; ".join(reasons)


# --- geometry helpers -----------------------------------------------------------------------


def shank_band_mm(thread: ThreadSpec) -> tuple[float, float] | None:
    """`[d3 - 0.05, d + 0.05]` in mm, or `None` when the thread states no pitch or no size."""
    if not thread.recognized or thread.nominal_diameter is None or thread.pitch_mm is None:
        return None
    major = units.as_mm(thread.nominal_diameter)
    minor = major - MINOR_DIAMETER_FACTOR * thread.pitch_mm
    return round_length(minor - SHANK_ALLOWANCE_MM), round_length(major + SHANK_ALLOWANCE_MM)


def _shank_face(package: EvidencePackage, component_id: str) -> FaceGeometry | None:
    """The component's free cylinder face of largest area; ties go to the lower face id."""
    in_holes = {face_id for hole in package.holes for face_id in hole.face_ids}
    faces = [
        face
        for face in package.faces
        if face.component_id == component_id
        and face.kind == "cylinder"
        and face.cylinder is not None
        and face.id not in in_holes
    ]
    if not faces:
        return None
    return min(
        faces,
        key=lambda face: (-(face.area_m2 if face.area_m2 is not None else -1.0), face.id),
    )


def _description(document: Document, configuration: str) -> str | None:
    by_configuration = document.config_properties.get(configuration, {})
    return by_configuration.get(DESCRIPTION_PROPERTY) or document.custom_properties.get(
        DESCRIPTION_PROPERTY
    )


def _row_conflicts(row: Fastener, others: Sequence[ParsedName]) -> tuple[str, ...]:
    """Each parsed name that states a different size or length from the extractor's row."""
    if row.thread_designation is None:
        return ()
    row_thread = parse_thread(row.thread_designation)
    conflicts = []
    for parsed in others:
        if not same_thread(row_thread, parsed.thread):
            conflicts.append(
                f"{SOURCE_LABELS[parsed.source]} reads {parsed.designation} where the fastener "
                f"row reads {row.thread_designation}"
            )
    return tuple(conflicts)


def _named_row(
    component: ComponentInstance, document: Document, name: ParsedName
) -> Fastener:
    """The in-memory `Fastener` of a name-parsed screw (`data-model.md` section 2). Its axis
    is the component's z axis through its origin until a joint places it."""
    origin, basis = component_frame(component)
    return Fastener(
        id=f"fst:name:{component.id}",
        persist_ref=component.persist_ref,
        persist_ref_scope=component.persist_ref_scope,
        component_id=component.id,
        kind=name.kind,  # type: ignore[arg-type]
        identity_source="name_parse",
        thread_designation=name.designation,
        length=None if name.length_mm is None else Quantity(value=name.length_mm, unit="mm"),
        head_type=name.head_type,
        head_diameter=None,
        head_height=None,
        drive=name.drive,
        axis=Axis(
            origin=Vec3(x=float(origin[0]), y=float(origin[1]), z=float(origin[2])),
            direction=Vec3(x=float(basis[2][0]), y=float(basis[2][1]), z=float(basis[2][2])),
        ),
        material=document.material,
    )


def _recognised(
    package: EvidencePackage,
    component: ComponentInstance,
    document: Document,
    fastener: Fastener,
    identity_source: IdentitySource,
    name: ParsedName | None,
    conflicts: tuple[str, ...],
) -> RecognisedFastener:
    face = _shank_face(package, component.id)
    shank = None
    if face is not None:
        assert face.cylinder is not None
        shank = round_length(face.cylinder.radius_m * 2000.0)
    thread = parse_thread(fastener.thread_designation) if fastener.thread_designation else None
    band = None if thread is None else shank_band_mm(thread)
    if shank is None or band is None:
        agreement: Agreement = "unmeasured"
    else:
        agreement = "agrees" if band[0] <= shank <= band[1] else "disagrees"
    return RecognisedFastener(
        component_id=component.id,
        document_id=document.document_id,
        identity_source=identity_source,
        name=name,
        name_conflicts=conflicts,
        fastener=fastener,
        shank_face_id=None if face is None else face.id,
        shank_mm=shank,
        shank_source=None if face is None else "face",
        band_mm=band,
        agreement=agreement,
    )


def recognise_fasteners(
    package: EvidencePackage, names: FastenerNames | None = None
) -> list[RecognisedFastener]:
    """Every fastener instance of `package`, in component id order (section 3, steps 1-3)."""
    names = names or load_fastener_names()
    documents = {item.document_id: item for item in package.documents}
    rows = {row.component_id: row for row in package.fasteners}
    found: list[RecognisedFastener] = []
    for component in sorted(package.components, key=lambda item: item.id):
        document = documents.get(component.document_id)
        if document is None:
            continue
        reading = read_fastener_names(
            document.file_name,
            _description(document, component.referenced_configuration),
            component.referenced_configuration,
            names,
        )
        row = rows.get(component.id)
        if row is not None:
            parsed = [item for item in (reading.name, *reading.others) if item is not None]
            found.append(
                _recognised(
                    package,
                    component,
                    document,
                    row,
                    row.identity_source,
                    reading.name,
                    _row_conflicts(row, parsed),
                )
            )
            continue
        if component.suppression != "resolved" or reading.name is None:
            continue
        if reading.name.kind not in RECOGNISED_KINDS:
            continue
        found.append(
            _recognised(
                package,
                component,
                document,
                _named_row(component, document, reading.name),
                "name_parse",
                reading.name,
                reading.conflicts,
            )
        )
    return found


def joint_map_with_fasteners(
    package: EvidencePackage,
) -> tuple[tuple[RecognisedFastener, ...], JointMap]:
    """The recognised fasteners and the joint map they are placed in: what `check_joints`
    checks and what the pre-run's digest counts, built one way for both."""
    recognised = tuple(recognise_fasteners(package))
    return recognised, build_joint_map(package, fasteners=recognised)


# --- fastener.identity ------------------------------------------------------------------------


def _number(value: float) -> str:
    return repr(round_length(value))


def check_identity(
    recognised: Sequence[RecognisedFastener], package: EvidencePackage
) -> list[CheckResult]:
    """One **suspected** `fastener.identity` per document whose size cannot be believed,
    every instance of it named; nothing for a document whose names and shank agree."""
    documents = {item.document_id: item for item in package.documents}
    by_document: dict[str, list[RecognisedFastener]] = {}
    for item in recognised:
        if not item.size_trusted:
            by_document.setdefault(item.document_id, []).append(item)

    results = []
    for document_id in sorted(by_document):
        instances = by_document[document_id]
        first = instances[0]
        file_name = documents[document_id].file_name
        sentences = []
        if first.agreement == "disagrees":
            assert first.shank_mm is not None and first.band_mm is not None
            sentences.append(
                f"{file_name} is named {first.designation} but its shank measures "
                f"{_number(first.shank_mm)} mm, outside the {_number(first.band_mm[0])} to "
                f"{_number(first.band_mm[1])} mm band of that thread"
            )
        if first.name_conflicts:
            sentences.append(
                f"{file_name} names its size in more than one place and they disagree: "
                + "; ".join(first.name_conflicts)
            )
        components = ", ".join(item.component_id for item in instances)
        count = len(instances)
        observed = (
            f"{'. '.join(sentences)} ({count} instance{'s' if count != 1 else ''}: {components})"
        )
        inputs: dict[str, Quantity | str] = {
            "document": file_name,
            "designation": first.designation,
            "identity_source": first.identity_source,
        }
        result: dict[str, Quantity | bool | str | float] = {
            "agrees": first.agreement == "agrees",
            "agreement": first.agreement,
            "name_conflicts": len(first.name_conflicts),
        }
        if first.shank_mm is not None:
            inputs["shank"] = Quantity(value=first.shank_mm, unit="mm")
            inputs["shank_face"] = first.shank_face_id or ""
        if first.band_mm is not None:
            result["band_low_mm"] = first.band_mm[0]
            result["band_high_mm"] = first.band_mm[1]
        results.append(
            CheckResult(
                check=CHECK_IDENTITY,
                status="suspected",
                severity="medium",
                observed=observed,
                requirement=REQUIREMENT,
                inputs=[item.component_id for item in instances],
                calculation=Calculation(
                    model=CHECK_IDENTITY,
                    inputs=inputs,  # type: ignore[arg-type]
                    assumptions=[
                        f"basic minor diameter d3 = d - {MINOR_DIAMETER_FACTOR} P (ISO 68-1)",
                        "the shank is the component's free cylinder face of largest area",
                        f"a {SHANK_ALLOWANCE_MM} mm modelling allowance either side of the "
                        "band, not a tolerance",
                    ],
                    excluded_effects=[
                        "thread class and the tolerance on the major diameter",
                        "a thread modelled cosmetically with no cylinder at either diameter",
                    ],
                    result=result,
                    units_out="mm",
                    function=FUNCTION,
                    function_version=FUNCTION_VERSION,
                ),
                coverage_limits=[
                    f"{CHECK_IDENTITY}: the size named for {file_name} is not used by the "
                    "joint checks, so its engagement and bottoming are unresolved"
                ],
                recommended_action=(
                    f"Correct the name of {file_name} or its modelled size so they agree, then "
                    "re-run the review."
                ),
            )
        )
    return results


# --- the screw's axial extent ----------------------------------------------------------------


MESH_PLACES = 3
"""A GLB stores vertices in single precision: about 2e-4 mm at four metres from the origin.
A mesh extent is rounded to 1e-3 mm, so float noise cannot split a pattern of identical
screws into several findings, and no digit the mesh cannot resolve is reported."""


@dataclass(frozen=True)
class ScrewExtent:
    """Where a placed screw lies along its joint's reference axis, in mm from the axis origin."""

    low_mm: float
    high_mm: float
    source: Literal["face", "mesh"]


def screw_extent(
    joint: Joint, package: EvidencePackage, mesh: trimesh.Trimesh | None
) -> ScrewExtent | None:
    """The placed screw's extent along `joint`'s reference axis (`contracts/fasteners.md`
    section 4): its shank face's box corners projected (`face`), else its exported mesh's
    vertices (`mesh`, supplementary geometry used only where no face exists, Principle IV),
    else `None`. `mesh` is in world metres; the caller loads it."""
    recognised = joint.fastener
    if recognised is None:
        return None
    reference = joint.reference_instance
    if recognised.shank_face_id is not None:
        face = next(item for item in package.faces if item.id == recognised.shank_face_id)
        low, high = axial_extent([face.bbox], reference.axis, f"the axis of {reference.id}")
        return ScrewExtent(
            low_mm=round_length(low * 1000.0), high_mm=round_length(high * 1000.0), source="face"
        )
    if mesh is not None and len(mesh.vertices):
        geometry = reference.geometry
        vertices = np.asarray(mesh.vertices, dtype=float)
        projections = (vertices - geometry.origin) @ geometry.direction
        return ScrewExtent(
            low_mm=round(float(projections.min()) * 1000.0, MESH_PLACES),
            high_mm=round(float(projections.max()) * 1000.0, MESH_PLACES),
            source="mesh",
        )
    return None


# --- the placed screw's protrusion and usable thread ------------------------------------------


def _protrusion(
    extent: ScrewExtent, low: float, high: float
) -> tuple[float, str] | str:
    """`(protrusion, how)` from the screw's extent and the tapped face's `[low, high]`, or the
    reason it cannot be read. The entry is the end of the tapped face that lies inside the
    screw's extent; the tip is the screw's end beyond it (`contracts/fasteners.md` s. 4)."""
    high_inside = extent.low_mm < high < extent.high_mm
    low_inside = extent.low_mm < low < extent.high_mm
    if high_inside and low_inside:
        return (
            round_length(min(high - extent.low_mm, extent.high_mm - low)),
            "the screw spans the whole tapped face, so the smaller of the two protrusions is used",
        )
    if high_inside:
        return round_length(high - extent.low_mm), "entering at the face's upper end"
    if low_inside:
        return round_length(extent.high_mm - low), "entering at the face's lower end"
    if extent.high_mm <= low or extent.low_mm >= high:
        short = round_length(min(abs(low - extent.high_mm), abs(extent.low_mm - high)))
        return (
            f"the screw's extent ends {short!r} mm short of the tapped face, so it does not "
            "reach the thread where it was placed"
        )
    return "the screw lies wholly inside the tapped face, so where it enters is not measured"


def measure_placement(
    joint: Joint, package: EvidencePackage, screw_mesh: trimesh.Trimesh | None
) -> Placement | None:
    """The protrusion and usable thread of `joint`'s placed screw, or `None` when the joint
    has no placed fastener or no tapped hole to measure against.

    Nothing is inferred: an oblique axis read from face boxes, a screw whose size its
    shank contradicts, a blind hole with no thread depth and an unknown end condition each
    leave the value missing and say why. `hole_depth` is never read.
    """
    recognised = joint.fastener
    tapped = joint.tapped_instance
    if recognised is None or tapped is None:
        return None
    hole = tapped.hole
    what = f"the protrusion of {recognised.fastener.id} into {tapped.id}"
    geometry = tapped.geometry
    span = geometry.span(geometry.origin, geometry.direction)
    low, high = round_length(span[0] * 1000.0), round_length(span[1] * 1000.0)

    missing: list[str] = []
    protrusion: float | None = None
    how = ""
    extent = screw_extent(joint, package, screw_mesh)
    if not recognised.size_trusted:
        missing.append(f"{what} ({recognised.untrusted_reason()})")
    elif extent is None:
        missing.append(f"{what} (no face and no exported mesh gives the screw's extent)")
    elif not tapped.axis_aligned:
        # The entry is the tapped face's box on the axis, which overruns an oblique face; a
        # mesh extent of the screw is exact, but the entry it is measured from is not
        # (`contracts/joint-map.md` section 2: engagement requires an aligned axis).
        detail = (
            "bounding-box extents are not used"
            if extent.source == "face"
            else "the screw's mesh extent is exact, but the thread entry would be read from "
            "the tapped face's bounding box"
        )
        missing.append(f"{what} (the axis is oblique; {detail})")
    else:
        measured = _protrusion(extent, low, high)
        if isinstance(measured, str):
            missing.append(f"{what} ({measured})")
        else:
            protrusion, entering = measured
            screw_source = (
                f"the screw's shank face {recognised.shank_face_id}"
                if extent.source == "face"
                else "the screw's exported mesh, supplementary geometry used because it has no face"
            )
            how = f"{screw_source} and the tapped face of {tapped.id}, {entering}"

    usable: UsableThread | None = None
    depth_of = f"the usable thread depth of hole {hole.id}"
    if hole.end_condition == "blind":
        if hole.thread_depth is None:
            missing.append(
                f"{depth_of} (no thread depth is recorded for this blind tapped hole; its hole "
                "depth is never used)"
            )
        else:
            usable = UsableThread(
                length_mm=round_length(units.as_mm(hole.thread_depth)),
                source=f"Hole.thread_depth of {hole.id}, measured inward from the thread entry",
            )
    elif hole.end_condition == "through":
        if not tapped.axis_aligned:
            missing.append(
                f"{depth_of} (the axis is oblique; the through-tapped length would be a "
                "bounding-box extent)"
            )
        else:
            usable = UsableThread(length_mm=round_length(high - low), source=THROUGH_TAPPED_SOURCE)
    else:
        missing.append(f"{depth_of} (its end condition is {hole.end_condition})")

    return Placement(
        protrusion_mm=protrusion,
        protrusion_source=how or "not measured",
        usable_thread=usable,
        missing=tuple(missing),
    )


# --- every placed screw -------------------------------------------------------------------------

MeshOf = Callable[[str], trimesh.Trimesh | None]
"""A component's body mesh in world metres, or `None` when it has none or it could not be
loaded. The tool supplies it from the package folder; the checks stay pure of files."""

EnvelopeOf = Callable[[Joint], EnvelopeResult | None]
"""The tool envelope swept from a joint's screw head (`checks/tool_access.py`, US5), or
`None` when it could not be swept; head clearance is then unresolved."""


def fastener_group(joint: Joint) -> str:
    """The fold group of a placed-screw result: the screw's document and the part it
    threads into, so one screw part mis-threaded into one part at two unrelated holes is
    one finding (SC-002), and a pattern of one screw in one part stays one."""
    assert joint.fastener is not None and joint.tapped_instance is not None
    return f"{joint.fastener.document_id}|{joint.tapped_instance.component_id}"


@dataclass(frozen=True)
class FastenerChecks:
    """What the fastener checks found, per joint, per document, and as coverage."""

    results: tuple[JointResult, ...]
    identity: tuple[CheckResult, ...]
    skipped: tuple[CoverageItem, ...]


def run_fastener_checks(
    package: EvidencePackage,
    joint_map: JointMap,
    recognised: Sequence[RecognisedFastener],
    *,
    mesh_of: MeshOf | None = None,
    rules: EngagementRules | None = None,
    envelope_of: EnvelopeOf | None = None,
) -> FastenerChecks:
    """Every placed screw through `check_placed_screw`, every fastener through
    `fastener.identity`, as plain values (`contracts/code-first.md` section 6).

    A screw placed in a joint with no tapped hole - its tapped part was not extracted - is
    one skipped coverage item for all such joints, never four unresolved findings each; so is
    head clearance when no `envelope_of` sweeps the heads. The tapped part's own document
    material selects the engagement rule.
    """
    documents = {item.document_id: item for item in package.documents}
    components = {item.id: item for item in package.components}
    results: list[JointResult] = []
    untapped: list[Joint] = []
    unswept: list[Joint] = []
    for joint in joint_map.joints:
        placed = joint.fastener
        if placed is None:
            continue
        tapped = joint.tapped_instance
        if tapped is None:
            untapped.append(joint)
            continue
        mesh = None
        if placed.shank_face_id is None and mesh_of is not None:
            mesh = mesh_of(placed.component_id)
        placement = measure_placement(joint, package, mesh)
        assert placement is not None
        component = components.get(tapped.component_id)
        document = None if component is None else documents.get(component.document_id)
        for result in check_placed_screw(
            placed.fastener,
            tapped.hole,
            placement,
            hole_material=None if document is None else document.material,
            rules=rules,
            envelope=None if envelope_of is None else envelope_of(joint),
        ):
            if envelope_of is None and result.check == CHECK_HEAD_CLEARANCE:
                unswept.append(joint)
                continue
            results.append(JointResult(joint, result))

    skipped: list[CoverageItem] = []
    if unswept:
        skipped.append(
            CoverageItem(
                check=CHECK_HEAD_CLEARANCE,
                scope=CoverageScope(
                    component_ids=sorted({cid for joint in unswept for cid in joint.component_ids})
                ),
                reason=(
                    f"no tool envelope was swept for the {len(unswept)} placed screws in "
                    "tapped holes, so head clearance was not evaluated for any of them"
                ),
                error=None,
            )
        )
    if untapped:
        names = ", ".join(
            f"{joint.fastener.component_id} in {joint.reference}"
            for joint in untapped
            if joint.fastener is not None
        )
        skipped.append(
            CoverageItem(
                check=CHECK_ENGAGEMENT,
                scope=CoverageScope(
                    component_ids=sorted({cid for joint in untapped for cid in joint.component_ids})
                ),
                reason=(
                    f"{len(untapped)} placed screw{'s' if len(untapped) != 1 else ''} ({names}) "
                    "enter a part whose tapped hole was not extracted, so thread match, "
                    "engagement, bottoming and head clearance were not evaluated for them"
                ),
                error=None,
            )
        )
    return FastenerChecks(
        results=tuple(results),
        identity=tuple(check_identity(recognised, package)),
        skipped=tuple(skipped),
    )
