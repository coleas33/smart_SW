"""Builders for the mechanical-check fixtures of feature 010 (T002, `contracts/fixtures.md`).

`tests/fixtures/mechanical/generate_fixtures.py` builds two packages shaped like the recorded
830-02342 and 810-11249 runs out of these builders, and the unit tests of feature 010 build
their small hand-made packages out of the same ones, so there is one definition of what a
hole feature, a screw or an interference row looks like in a package.

**The shapes are the recorded packages' shapes** (research R2.1, R2.3, R3):

- a Hole Wizard feature is **one** `Hole` row whose `face_ids` hold every cylinder face of
  every instance, with the row's `axis` taken from the first face - which is exactly what
  `HoleDumper.AddAxisAndFaces` writes - and `diameter` null, as on every recorded row;
- a counterbore instance is two coaxial faces, the bore and the counterbore;
- a screw is a component whose document is named in the vendor shape
  (`SHC_M4-0.7X12_FICT-0001.SLDPRT`, description `SCREW, SOC M4-0.7 X 12 MM, FICTIONAL`),
  with a body mesh and optionally a shank face; `is_toolbox` is false and no `Fastener` row
  is written, as on all 89 recorded components;
- every document that was opened carries a `mass_override` tool-error gap, because the
  recorded override read failed on every document (analyst fact 26).

**Every string is fictional.** Paths start with `FICTIONAL_ROOT`; names are built from
`VOCABULARY`, sizes, ids and two SOLIDWORKS library material names committed goldens already
use; `test_mechanical_fixtures_are_fictional.py` holds the fixtures to that, and to the
owner's denylist when it is on the machine.

**Meshes are GLB in world metres**, written by `trimesh`: the format the extractor writes
and the one `geometry.mesh.load_mesh` reads without a unit argument. A component with faces
and no explicit mesh gets a *frame* mesh - four boxes around each cylinder face, the material
a hole is cut in - so a plate is present to a tool-envelope sweep without enclosing the heads
seated in its holes.

The schema version is pinned to `FIXTURE_SCHEMA_VERSION`, never `SCHEMA_VERSION`: these
packages are 1.4.0 packages, and a later IR minor must load them unchanged (FR-028) rather than
rewrite them under the regeneration test.
"""

from __future__ import annotations

import importlib.util
import math
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Literal
from uuid import UUID

import numpy as np
import trimesh

from swreview.ir.models import (
    Axis,
    BBox3D,
    BodyRef,
    ComponentInstance,
    CylinderFace,
    Design,
    Document,
    DumpPhase,
    EvidencePackage,
    ExtractorInfo,
    FaceGeometry,
    Gap,
    Hole,
    Interference,
    InterferenceSettings,
    Manifest,
    ManifestEntry,
    MassProperties,
    Quantity,
    Vec3,
    Volume,
)
from tests.support.packages import persist_ref

__all__ = [
    "FICTIONAL_ROOT",
    "FIXTURE_SCHEMA_VERSION",
    "HYGIENE_PROPERTIES",
    "LIBRARY_MATERIALS",
    "VOCABULARY",
    "Built",
    "Face",
    "Instance",
    "PackageBuilder",
    "box_mesh",
    "cylinder_mesh",
    "fictional_offences",
    "load_generator",
    "screw_description",
    "screw_file_name",
]

FIXTURE_SCHEMA_VERSION = "1.4.0"
FICTIONAL_ROOT = "C:\\Fictional\\"
LIBRARY_MATERIALS: tuple[str, ...] = ("6061-T6", "Alloy Steel")
"""The two SOLIDWORKS library material names the committed goldens already carry."""

HYGIENE_PROPERTIES: tuple[str, str, str] = ("Meridian Part Ref", "Meridian Summary", "MeridianRev")
"""The part-number, description and revision property names of the fictional profile A
(`tests/fixtures/standards/profile-a.yaml`, version 2): the fixture documents carry the
property names the hygiene checks will be pointed at, and nothing else is a property name."""

VOCABULARY: frozenset[str] = frozenset(
    {
        # invented syllables, the only material a name here is made of
        "kalo",
        "mir",
        "ven",
        "tessa",
        "brun",
        "okta",
        "pelin",
        "davo",
        "rusk",
        "lori",
        "venta",
        "quill",
        "sorn",
        "hask",
        "fenn",
        "arvo",
        "tulm",
        "zeph",
        "ombra",
        "nixa",
        # the grammar the vendor shapes and SOLIDWORKS itself impose
        "fict",
        "fictional",
        "screw",
        "pin",
        "soc",
        "flt",
        "btn",
        "mm",
        "x",
        "shc",
        "fht",
        "bht",
        "hole",
        "sldprt",
        "sldasm",
        "default",
        "seat",
    }
)
"""Every word a fixture name may contain; `fictional_offences` checks it."""

_TOKEN = re.compile(r"[A-Za-z0-9]+")
_SIZE_OR_ID = re.compile(r"^(?:m?\d+(?:x\d+)?|x\d+|\d+x\d+|\d+)$", re.IGNORECASE)


def _built_from_vocabulary(token: str) -> bool:
    """Whether `token` is one or more `VOCABULARY` words run together (`KALOMIR`)."""
    word = token.lower()
    reachable = [True] + [False] * len(word)
    for end in range(1, len(word) + 1):
        reachable[end] = any(
            reachable[start] and word[start:end] in VOCABULARY for start in range(end)
        )
    return reachable[-1]


def fictional_offences(text: str) -> list[str]:
    """The tokens of `text` that are neither vocabulary nor a size, a number or an id.

    A token may be several vocabulary syllables run together; a single character (a
    revision letter) identifies nothing and passes. A library material name counts as
    fictional as a whole, because it is SOLIDWORKS' own and already committed. An empty list
    means the text is built only from the vocabulary.
    """
    if text in LIBRARY_MATERIALS:
        return []
    return [
        token
        for token in _TOKEN.findall(text)
        if len(token) > 1 and not _SIZE_OR_ID.match(token) and not _built_from_vocabulary(token)
    ]


Vec = tuple[float, float, float]

PACKAGE_ID = UUID("01000000-0000-4000-8000-000000000010")
CREATED_AT = datetime(2026, 9, 23, 9, 0, 0, tzinfo=UTC)
PHASES: tuple[str, ...] = (
    "document",
    "manifest",
    "mate",
    "feature",
    "equation",
    "cutlist",
    "hole",
    "fastener",
    "face",
    "body",
)
SETTINGS = InterferenceSettings(
    treat_coincident_as_interference=True,
    treat_subassemblies_as_components=True,
    include_multibody=False,
    ignore_hidden=True,
    fastener_folder_treatment="include",
)
"""Coincident faces treated as interference, which is how zero-volume rows arise (R2.9)."""

FRAME_WIDTH_MM = 3.0
FRAME_CLEARANCE_MM = 0.5
"""A frame mesh is a square ring `FRAME_WIDTH_MM` wide whose inner edge stands
`FRAME_CLEARANCE_MM` off the cylinder face it surrounds."""

STEEL_DENSITY_KG_M3 = 7850.0

HeadCode = Literal["SHC", "FHT", "BHT"]

HEADS: dict[str, dict[str, Any]] = {
    "SHC": {"kind": "SCREW", "abbr": "SOC", "countersunk": False},
    "FHT": {"kind": "SCREW", "abbr": "FLT", "countersunk": True},
    "BHT": {"kind": "SCREW", "abbr": "BTN", "countersunk": False},
}
"""What a head code means in the fixture's vendor strings. Data about the fixture's own
names, not the product's head-code table (`checks/fastener_names.yaml`, T039)."""

HEAD_SIZES_MM: dict[str, dict[float, tuple[float, float]]] = {
    "SHC": {
        2: (3.8, 2.0),
        3: (5.5, 3.0),
        4: (7.0, 4.0),
        5: (8.5, 5.0),
        8: (13.0, 8.0),
        10: (16.0, 10.0),
    },
    "FHT": {2: (3.8, 1.2), 3: (5.5, 1.7), 4: (7.5, 2.3), 5: (9.4, 2.8)},
    "BHT": {3: (5.7, 1.65), 4: (7.6, 2.2), 5: (9.5, 2.75)},
}
"""`(head diameter, head height)` the fixture meshes are drawn with. Shape only: no check
reads a head size from a mesh."""


# --- names ----------------------------------------------------------------------------


def _number(value: float) -> str:
    return f"{value:g}"


def _thread_parts(thread: str) -> tuple[float, float]:
    """`M4-0.7` as `(4.0, 0.7)`."""
    match = re.fullmatch(r"M(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)", thread)
    if match is None:
        raise ValueError(f"a fixture screw thread is written M<d>-<p>, got {thread!r}")
    return float(match.group(1)), float(match.group(2))


def screw_file_name(head: str, thread: str, length_mm: float, serial: int) -> str:
    """The vendor file-name shape: `SHC_M4-0.7X12_FICT-0001.SLDPRT` (contracts/fixtures.md)."""
    return f"{head}_{thread}X{_number(length_mm)}_FICT-{serial:04d}.SLDPRT"


def screw_description(head: str, thread: str, length_mm: float) -> str:
    """The vendor description shape: `SCREW, SOC M4-0.7 X 12 MM, FICTIONAL`."""
    style = HEADS[head]
    return f"{style['kind']}, {style['abbr']} {thread} X {_number(length_mm)} MM, FICTIONAL"


# --- geometry ------------------------------------------------------------------------


def _unit(direction: Vec) -> np.ndarray:
    array = np.array(direction, dtype=float)
    norm = float(np.linalg.norm(array))
    if norm == 0.0:
        raise ValueError("a fixture axis needs a direction")
    return array / norm


def _vec3(point_m: np.ndarray) -> Vec3:
    return Vec3(x=float(point_m[0]), y=float(point_m[1]), z=float(point_m[2]))


def _m(point_mm: Sequence[float]) -> np.ndarray:
    return np.array(point_mm, dtype=float) / 1000.0


def rotation_to(direction: Vec) -> np.ndarray:
    """A rotation whose third column is `direction`: the part's z axis becomes that axis."""
    z = _unit(direction)
    helper = np.array([1.0, 0.0, 0.0]) if abs(z[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    x = np.cross(helper, z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    return np.column_stack([x, y, z])


def transform(origin_mm: Sequence[float], direction: Vec = (0.0, 0.0, 1.0)) -> list[list[float]]:
    """Row-major 4x4, translation in metres in the last column (`ComponentInstance`)."""
    matrix = np.eye(4)
    matrix[:3, :3] = rotation_to(direction)
    matrix[:3, 3] = _m(origin_mm)
    return [[float(value) for value in row] for row in matrix]


IDENTITY = transform((0.0, 0.0, 0.0))


def _cylinder_bbox(
    origin_m: np.ndarray, axis: np.ndarray, radius_m: float, lo_m: float, hi_m: float
) -> BBox3D:
    """The exact bounding box of a cylinder's lateral surface."""
    ends = np.stack([origin_m + lo_m * axis, origin_m + hi_m * axis])
    reach = radius_m * np.sqrt(np.clip(1.0 - axis**2, 0.0, 1.0))
    return BBox3D(min=_vec3(ends.min(axis=0) - reach), max=_vec3(ends.max(axis=0) + reach))


def cylinder_mesh(
    origin_mm: Sequence[float],
    direction: Vec,
    diameter_mm: float,
    lo_mm: float,
    hi_mm: float,
    sections: int = 12,
) -> trimesh.Trimesh:
    """A closed cylinder from `lo_mm` to `hi_mm` along the axis, in metres."""
    height = (hi_mm - lo_mm) / 1000.0
    mesh = trimesh.creation.cylinder(radius=diameter_mm / 2000.0, height=height, sections=sections)
    mesh.apply_translation([0.0, 0.0, (lo_mm + hi_mm) / 2000.0])
    matrix = np.eye(4)
    matrix[:3, :3] = rotation_to(direction)
    matrix[:3, 3] = _m(origin_mm)
    mesh.apply_transform(matrix)
    return mesh


def box_mesh(minimum_mm: Sequence[float], maximum_mm: Sequence[float]) -> trimesh.Trimesh:
    """An axis-aligned closed box, in metres."""
    low, high = _m(minimum_mm), _m(maximum_mm)
    mesh = trimesh.creation.box(extents=high - low)
    mesh.apply_translation((low + high) / 2.0)
    return mesh


def _frame(
    origin_m: np.ndarray, axis: np.ndarray, radius_m: float, lo_m: float, hi_m: float
) -> list[trimesh.Trimesh]:
    """Four boxes around a cylinder face: the material the hole is cut in."""
    inner = radius_m + FRAME_CLEARANCE_MM / 1000.0
    outer = inner + FRAME_WIDTH_MM / 1000.0
    height = hi_m - lo_m
    matrix = np.eye(4)
    matrix[:3, :3] = rotation_to(tuple(axis))  # type: ignore[arg-type]
    matrix[:3, 3] = origin_m + axis * (lo_m + hi_m) / 2.0
    boxes = []
    for extents, centre in (
        ((outer - inner, 2 * outer, height), ((inner + outer) / 2, 0.0, 0.0)),
        ((outer - inner, 2 * outer, height), (-(inner + outer) / 2, 0.0, 0.0)),
        ((2 * inner, outer - inner, height), (0.0, (inner + outer) / 2, 0.0)),
        ((2 * inner, outer - inner, height), (0.0, -(inner + outer) / 2, 0.0)),
    ):
        box = trimesh.creation.box(extents=extents)
        box.apply_translation(centre)
        box.apply_transform(matrix)
        boxes.append(box)
    return boxes


# --- specs ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Face:
    """One cylinder face of a hole instance: its diameter and axial extent, in mm."""

    diameter_mm: float
    lo_mm: float
    hi_mm: float


@dataclass(frozen=True)
class Instance:
    """One instance of a hole feature: an axis and the faces on it, extents along it."""

    origin_mm: Vec
    direction: Vec
    faces: tuple[Face, ...]

    def moved(self, delta_mm: Vec) -> Instance:
        return replace(
            self,
            origin_mm=tuple(a + b for a, b in zip(self.origin_mm, delta_mm, strict=True)),  # type: ignore[arg-type]
        )


@dataclass
class _Face:
    face: FaceGeometry
    origin_m: np.ndarray
    axis: np.ndarray
    radius_m: float
    lo_m: float
    hi_m: float


@dataclass
class Built:
    """A built package and its meshes, ready to be rendered to bytes or written."""

    package: EvidencePackage
    meshes: dict[str, bytes]

    def render(self) -> dict[str, bytes]:
        """`{relative path: bytes}` exactly as `write` puts them on disk."""
        files = {"package.json": (self.package.model_dump_json(indent=2) + "\n").encode("utf-8")}
        files.update(self.meshes)
        return files

    def write(self, directory: Path | str) -> dict[str, bytes]:
        target = Path(directory)
        files = self.render()
        for relative, content in files.items():
            path = target / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return files


@dataclass
class PackageBuilder:
    """Accumulates a package entity by entity, allocating ids in insertion order.

    The root assembly document is created with the builder, as `doc:0001`. Every other id -
    `doc:`, `cmp:`, `hol:`, `fac:`, `bod:`, `int:` - is the next free number unless the
    caller names one, so a fixture can pin the component ids research R2.2 and R2.3 talk
    about while the rest fall where they fall.
    """

    design_stem: str
    root_properties: Mapping[str, str] | None = None
    package_id: UUID = PACKAGE_ID
    created_at: datetime = CREATED_AT
    _documents: list[Document] = field(default_factory=list)
    _components: dict[str, ComponentInstance] = field(default_factory=dict)
    _holes: list[Hole] = field(default_factory=list)
    _faces: list[_Face] = field(default_factory=list)
    _meshes: dict[str, list[trimesh.Trimesh]] = field(default_factory=dict)
    _solid: dict[str, bool] = field(default_factory=dict)
    _interferences: list[Interference] = field(default_factory=list)
    _gaps: list[Gap] = field(default_factory=list)
    _screw_heads: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.root_id = self.document(self.design_stem, "assembly", properties=self.root_properties)

    # --- documents and components -------------------------------------------------------

    def document(
        self,
        stem: str,
        kind: Literal["part", "assembly"],
        *,
        material: str | None = None,
        mass_kg: float | None = None,
        volume_mm3: float | None = None,
        properties: Mapping[str, str] | None = None,
        configurations: Sequence[str] = ("Default",),
        opened: bool = True,
    ) -> str:
        """A document; an unopened one reads as nothing and carries the gap that says so."""
        document_id = f"doc:{len(self._documents) + 1:04d}"
        extension = "SLDPRT" if kind == "part" else "SLDASM"
        mass = None
        if opened and mass_kg is not None:
            volume = 0.0 if volume_mm3 is None else volume_mm3 * 1e-9
            mass = MassProperties(
                mass_kg=mass_kg,
                volume_m3=volume,
                center_of_mass=Vec3(x=0.0, y=0.0, z=0.0),
                configuration=configurations[0],
            )
        self._documents.append(
            Document(
                document_id=document_id,
                kind=kind,
                file_name=f"{stem}.{extension}",
                path=f"{FICTIONAL_ROOT}Vault\\{stem}.{extension}",
                configurations=list(configurations),
                active_configuration=configurations[0],
                custom_properties=dict(properties or {}) if opened else {},
                config_properties={},
                material=material if opened else None,
                mass=mass,
                material_configuration=(configurations[0] if opened and kind == "part" else None),
            )
        )
        if opened:
            self._gaps.append(
                Gap(
                    kind="tool_error",
                    entity_kind="mass_override",
                    entity_id=document_id,
                    reason="IMassProperty.OverrideMass could not be read",
                    error="InvalidCastException: the mass property object is not IMassProperty",
                )
            )
        else:
            self._gaps.append(
                Gap(
                    kind="not_extracted",
                    entity_kind="document",
                    entity_id=document_id,
                    reason=(
                        "the document was not opened: every instance is lightweight or "
                        "suppressed, so its properties, material and mass were not read"
                    ),
                    error=None,
                )
            )
        return document_id

    def component(
        self,
        document_id: str,
        *,
        name: str | None = None,
        parent_id: str | None = None,
        placement: list[list[float]] | None = None,
        suppression: Literal["resolved", "lightweight", "suppressed"] = "resolved",
        configuration: str = "Default",
        component_id: str | None = None,
    ) -> str:
        """One instance of `document_id` in the assembly frame."""
        if component_id is None:
            component_id = f"cmp:{self._next_component():04d}"
        if component_id in self._components:
            raise ValueError(f"component {component_id} already exists")
        document = self._document(document_id)
        stem = document.file_name.rsplit(".", 1)[0]
        count = sum(1 for item in self._components.values() if item.document_id == document_id)
        label = name or f"{stem}-{count + 1}"
        parent = None if parent_id is None else self._components[parent_id]
        self._components[component_id] = ComponentInstance(
            id=component_id,
            persist_ref=persist_ref(component_id),
            persist_ref_scope=self.root_id,
            name=label,
            document_id=document_id,
            parent_id=parent_id,
            referenced_configuration=configuration,
            transform=placement or IDENTITY,
            suppression=suppression,
            is_fixed=False,
            pattern_id=None,
            is_toolbox=False,
            full_path=label if parent is None else f"{parent.full_path}/{label}",
        )
        if suppression != "resolved":
            self._gaps.append(
                Gap(
                    kind="not_extracted",
                    entity_kind="body",
                    entity_id=component_id,
                    reason=f"the component is {suppression}; its bodies were not read",
                    error=None,
                )
            )
        return component_id

    def set_mass(self, document_id: str, mass_kg: float, volume_mm3: float) -> None:
        """Give an opened document its mass once its children are known (an assembly)."""
        index = next(
            position
            for position, item in enumerate(self._documents)
            if item.document_id == document_id
        )
        document = self._documents[index]
        self._documents[index] = document.model_copy(
            update={
                "mass": MassProperties(
                    mass_kg=mass_kg,
                    volume_m3=volume_mm3 * 1e-9,
                    center_of_mass=Vec3(x=0.0, y=0.0, z=0.0),
                    configuration=document.active_configuration,
                )
            }
        )

    def mass_of(self, component_id: str) -> float | None:
        """The mass of a component's document, `None` when it was never read."""
        document = self._document(self._components[component_id].document_id)
        return None if document.mass is None else document.mass.mass_kg

    def children_of(self, parent_id: str | None) -> list[str]:
        return [item.id for item in self._components.values() if item.parent_id == parent_id]

    def _next_component(self) -> int:
        taken = {int(item.split(":")[1]) for item in self._components}
        number = 1
        while number in taken:
            number += 1
        return number

    def _document(self, document_id: str) -> Document:
        return next(item for item in self._documents if item.document_id == document_id)

    # --- holes and faces ------------------------------------------------------------------

    def cylinder_face(
        self,
        component_id: str,
        *,
        origin_mm: Sequence[float],
        direction: Vec,
        diameter_mm: float,
        lo_mm: float,
        hi_mm: float,
    ) -> str:
        """A cylinder face spanning `lo_mm..hi_mm` along `direction` from `origin_mm`."""
        if hi_mm <= lo_mm:
            raise ValueError(f"a face spans lo < hi, got {lo_mm}..{hi_mm}")
        face_id = f"fac:{len(self._faces) + 1:04d}"
        origin_m, axis = _m(origin_mm), _unit(direction)
        radius_m = diameter_mm / 2000.0
        lo_m, hi_m = lo_mm / 1000.0, hi_mm / 1000.0
        face = FaceGeometry(
            id=face_id,
            persist_ref=persist_ref(face_id),
            persist_ref_scope=self.root_id,
            component_id=component_id,
            body_id=self._body_id(component_id),
            kind="cylinder",
            cylinder=CylinderFace(
                axis_origin=_vec3(origin_m), axis_dir=_vec3(axis), radius_m=radius_m
            ),
            plane=None,
            bbox=_cylinder_bbox(origin_m, axis, radius_m, lo_m, hi_m),
            area_m2=2.0 * math.pi * radius_m * (hi_m - lo_m),
        )
        self._faces.append(_Face(face, origin_m, axis, radius_m, lo_m, hi_m))
        return face_id

    def hole(
        self,
        component_id: str,
        *,
        hole_type: Literal["tapped", "clearance", "counterbore", "countersink", "simple"],
        size: str,
        end_condition: Literal["blind", "through"],
        instances: Iterable[Instance],
        thread: str | None = None,
        thread_depth_mm: float | None = None,
        hole_depth_mm: float | None = None,
        faceless_axis: Instance | None = None,
        feature_name: str | None = None,
    ) -> str:
        """One Hole Wizard feature: one row, one face per instance and diameter (R2.1).

        `faceless_axis` gives the row its axis when the feature has no cylinder face, the
        case of two recorded rows; such a row carries a `face` gap as the extractor writes.
        """
        hole_id = f"hol:{len(self._holes) + 1:04d}"
        face_ids = [
            self.cylinder_face(
                component_id,
                origin_mm=instance.origin_mm,
                direction=instance.direction,
                diameter_mm=face.diameter_mm,
                lo_mm=face.lo_mm,
                hi_mm=face.hi_mm,
            )
            for instance in instances
            for face in instance.faces
        ]
        if face_ids:
            first = next(item.face for item in self._faces if item.face.id == face_ids[0])
            assert first.cylinder is not None
            axis = Axis(origin=first.cylinder.axis_origin, direction=first.cylinder.axis_dir)
        else:
            if faceless_axis is None:
                raise ValueError(f"{hole_id} has no face, so it needs faceless_axis")
            axis = Axis(
                origin=_vec3(_m(faceless_axis.origin_mm)),
                direction=_vec3(_unit(faceless_axis.direction)),
            )
            self._gaps.append(
                Gap(
                    kind="not_extracted",
                    entity_kind="hole",
                    entity_id=hole_id,
                    reason="no cylinder face of the hole feature could be read",
                    error=None,
                )
            )
        self._holes.append(
            Hole(
                id=hole_id,
                persist_ref=persist_ref(hole_id),
                persist_ref_scope=self._components[component_id].document_id,
                component_id=component_id,
                feature_name=feature_name or f"FICT-HOLE-{len(self._holes) + 1:04d}",
                hole_type=hole_type,
                standard="ISO",
                size=size,
                thread_designation=thread,
                thread_depth=(
                    None if thread_depth_mm is None else Quantity(value=thread_depth_mm, unit="mm")
                ),
                hole_depth=(
                    None if hole_depth_mm is None else Quantity(value=hole_depth_mm, unit="mm")
                ),
                end_condition=end_condition,
                diameter=None,
                axis=axis,
                face_ids=face_ids,
            )
        )
        return hole_id

    def gap(self, **fields: Any) -> None:
        self._gaps.append(Gap(**fields))

    # --- meshes ----------------------------------------------------------------------------

    def _body_id(self, component_id: str) -> str:
        """The component's one body id, allocated the first time anything needs it."""
        self._meshes.setdefault(component_id, [])
        return f"bod:{list(self._meshes).index(component_id) + 1:04d}"

    def mesh(self, component_id: str, *parts: trimesh.Trimesh, is_solid: bool = True) -> str:
        """Add `parts` (world metres) to the component's body mesh."""
        body_id = self._body_id(component_id)
        self._meshes[component_id].extend(parts)
        self._solid[component_id] = is_solid
        return body_id

    # --- screws ----------------------------------------------------------------------------

    def screw_document(
        self,
        head: HeadCode,
        thread: str,
        length_mm: float,
        *,
        serial: int,
        description: str | None = None,
        configurations: Sequence[str] = ("Default",),
        properties: Mapping[str, str] | None = None,
    ) -> str:
        """A screw document in the vendor naming shape, steel, with a believable mass."""
        d, _ = _thread_parts(thread)
        head_d, head_k = HEAD_SIZES_MM[head][d]
        shank = length_mm - head_k if HEADS[head]["countersunk"] else length_mm
        volume = math.pi / 4.0 * (d**2 * shank + head_d**2 * head_k)
        file_name = screw_file_name(head, thread, length_mm, serial)
        document_id = self.document(
            file_name.rsplit(".", 1)[0],
            "part",
            material="Alloy Steel",
            mass_kg=round(volume * 1e-9 * STEEL_DENSITY_KG_M3, 9),
            volume_mm3=round(volume, 6),
            properties={
                "Description": description or screw_description(head, thread, length_mm),
                **(properties or {}),
            },
            configurations=configurations,
        )
        self._screw_heads[document_id] = head
        return document_id

    def screw(
        self,
        document_id: str,
        *,
        bearing_mm: Sequence[float],
        direction: Vec,
        component_id: str | None = None,
        configuration: str | None = None,
        shank_face_mm: float | None = None,
        shank_face_span: tuple[float, float] | None = None,
        head_face_mm: float | None = None,
    ) -> str:
        """One screw instance, its origin at the bearing point and its z axis `direction`.

        `bearing_mm` is where the head bears - the under-head face of a socket or button
        head, the flush top of a countersunk one - and `direction` points from the tip toward
        the head. The mesh is the shank and the head; a shank face (optionally over
        `shank_face_span`, in mm along the axis from the bearing point) and a head face are
        extracted faces, present only when asked for.
        """
        document = self._document(document_id)
        head = self._screw_heads[document_id]
        match = re.match(r"^[A-Z]+_M(\d+(?:\.\d+)?)-[\d.]+X([\d.]+)_", document.file_name)
        assert match is not None
        d, length = float(match.group(1)), float(match.group(2))
        head_d, head_k = HEAD_SIZES_MM[head][d]
        if HEADS[head]["countersunk"]:
            shank_span, head_span = (-length, -head_k), (-head_k, 0.0)
        else:
            shank_span, head_span = (-length, 0.0), (0.0, head_k)
        configurations = document.configurations
        component_id = self.component(
            document_id,
            placement=transform(bearing_mm, direction),
            configuration=configuration or configurations[-1],
            component_id=component_id,
        )
        self.mesh(
            component_id,
            cylinder_mesh(bearing_mm, direction, d, *shank_span),
            cylinder_mesh(bearing_mm, direction, head_d, *head_span),
        )
        if shank_face_mm is not None:
            self.cylinder_face(
                component_id,
                origin_mm=bearing_mm,
                direction=direction,
                diameter_mm=shank_face_mm,
                lo_mm=(shank_face_span or shank_span)[0],
                hi_mm=(shank_face_span or shank_span)[1],
            )
        if head_face_mm is not None:
            self.cylinder_face(
                component_id,
                origin_mm=bearing_mm,
                direction=direction,
                diameter_mm=head_face_mm,
                lo_mm=head_span[0],
                hi_mm=head_span[1],
            )
        return component_id

    # --- interference ------------------------------------------------------------------------

    def interference(
        self,
        component_a: str,
        component_b: str,
        *,
        volume_mm3: float | None = 0.0,
        unit: Literal["mm3", "in3", "m3"] = "mm3",
        is_possible: bool = False,
        group_key: str | None = None,
        is_fastener: bool = False,
    ) -> str:
        """One interference row; `volume_mm3` is written in `unit` (`None` is no volume)."""
        interference_id = f"int:{len(self._interferences) + 1:04d}"
        pair = sorted([component_a, component_b])
        volume = None
        if volume_mm3 is not None:
            factor = {"mm3": 1.0, "in3": 1.0 / 16387.064, "m3": 1e-9}[unit]
            volume = Volume(value=volume_mm3 * factor, unit=unit)
        self._interferences.append(
            Interference(
                id=interference_id,
                configuration="Default",
                component_ids=pair,
                volume=volume,
                settings=SETTINGS,
                status="computed",
                error=None,
                group_key=group_key or "|".join(pair),
                is_fastener=is_fastener,
                is_possible=is_possible,
            )
        )
        return interference_id

    # --- the package --------------------------------------------------------------------------

    def build(self) -> Built:
        """The package, with a frame mesh for every faced component given no mesh."""
        meshes: dict[str, bytes] = {}
        bodies: list[BodyRef] = []
        for component_id, parts in self._meshes.items():
            body_id = self._body_id(component_id)
            if not parts:
                parts = [
                    box
                    for item in self._faces
                    if item.face.component_id == component_id
                    for box in _frame(item.origin_m, item.axis, item.radius_m, item.lo_m, item.hi_m)
                ]
            mesh = trimesh.util.concatenate(parts)
            name = f"meshes/{body_id.replace(':', '-')}.glb"
            meshes[name] = trimesh.exchange.gltf.export_glb(mesh)
            bodies.append(
                BodyRef(
                    id=body_id,
                    persist_ref=persist_ref(body_id),
                    persist_ref_scope=self.root_id,
                    component_id=component_id,
                    mesh_file=name,
                    triangle_count=len(mesh.faces),
                    is_solid=self._solid.get(component_id, True),
                )
            )
        root = self._document(self.root_id)
        package = EvidencePackage(
            schema_version=FIXTURE_SCHEMA_VERSION,
            package_id=self.package_id,
            created_at=self.created_at,
            extractor=ExtractorInfo(
                name="SwReview.Extractor",
                version="0.0.0-fictional",
                sw_version="2024 SP5",
                machine="FICT-SEAT",
                profile="full",
                phases=[DumpPhase(name=name, elapsed_ms=1, status="ok") for name in PHASES],
            ),
            manifest=Manifest(
                entries=[
                    ManifestEntry(
                        document_id=document.document_id,
                        vault_path=document.path,
                        vault_version=1,
                        revision=None,
                        configuration=document.active_configuration,
                        local_modified=False,
                        export_method="native",
                    )
                    for document in self._documents
                ],
                discrepancies=[],
            ),
            design=Design(
                design_id="dsn:fict",
                name=root.file_name.rsplit(".", 1)[0],
                root_assembly_document_id=self.root_id,
                active_configuration="Default",
                drawing_document_ids=[],
            ),
            documents=self._documents,
            components=[self._components[key] for key in sorted(self._components)],
            holes=self._holes,
            faces=[item.face for item in self._faces],
            bodies=bodies,
            interferences=self._interferences,
            gaps=self._gaps,
        )
        return Built(package=package, meshes=meshes)


def load_generator(path: Path) -> ModuleType:
    """Import a fixture generator from its file; the fixture tree is not a package."""
    spec = importlib.util.spec_from_file_location(f"_generator_{path.parent.name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
