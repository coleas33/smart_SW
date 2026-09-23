"""Typed intermediate representation of one reviewed SOLIDWORKS design.

Every type here mirrors `specs/001-agentic-design-review/contracts/ir.schema.json`;
`swreview.ir.schema.export_schema()` regenerates that contract from these models and
`tests/unit/test_schema_sync.py` keeps the two in step.

Two rules drive the shapes (data-model.md, constitution Principle I):

- a value that could not be obtained is ``None`` and the reason is listed in
  ``EvidencePackage.gaps``; nothing is ever defaulted to a favourable number;
- every entity carries ``persist_ref`` plus ``persist_ref_scope``, the ``document_id``
  whose ``IModelDocExtension`` produced the reference.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from annotated_types import Len
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StringConstraints,
    model_serializer,
    model_validator,
)

SCHEMA_VERSION = "1.5.0"
SUPPORTED_SCHEMA_MAJOR = 1
SCHEMA_VERSION_PATTERN = r"^1\.[0-9]+\.[0-9]+$"

_SEMVER = re.compile(r"^([0-9]+)\.([0-9]+)\.([0-9]+)$")


class UnsupportedSchemaVersionError(ValueError):
    """An evidence package declares a schema major version this build cannot read.

    Distinct from `pydantic.ValidationError` so a caller can tell "written by a newer
    extractor" apart from "malformed package" (FR-016, research R5).
    """


def require_supported_schema_version(value: object) -> None:
    """Raise `UnsupportedSchemaVersionError` when `value` names an unsupported major.

    Called before pydantic validation, not from a field validator: pydantic wraps every
    `ValueError` raised inside a validator into a `ValidationError`, which would erase
    the distinction this error exists to make. A value that is not a semver string is
    left to pydantic's pattern constraint to report.
    """
    if not isinstance(value, str):
        return
    match = _SEMVER.match(value)
    if match is None:
        return
    major = int(match.group(1))
    if major != SUPPORTED_SCHEMA_MAJOR:
        raise UnsupportedSchemaVersionError(
            f"evidence package schema_version {value!r} has major {major}; "
            f"this build reads major {SUPPORTED_SCHEMA_MAJOR}"
        )


def _check_base64(value: str) -> str:
    try:
        base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("persist_ref must be base64-encoded bytes") from exc
    return value


PersistRef = Annotated[
    str,
    StringConstraints(min_length=1),
    AfterValidator(_check_base64),
    Field(
        json_schema_extra={"contentEncoding": "base64"},
        description="IModelDocExtension.GetPersistReference3 bytes, base64",
    ),
]

def omit_additive(
    handler: SerializerFunctionWrapHandler,
    model: BaseModel,
    *,
    nulls: Sequence[str] = (),
    empties: Sequence[str] = (),
) -> dict[str, Any]:
    """Serialize `model`, dropping the named additive fields when they say nothing.

    The IR's additivity rule (feature 006 `contracts/ir-additions.md`): a field added
    after the model shipped is optional, absent from `required`, and **omitted when it is
    null** - or, for a list, when it carries no rows - because an absent key and a null are
    then the same fact, and the absent key is the one that keeps a package written by the
    older build byte-identical to what that build wrote.

    `nulls` names scalars, `empties` names lists: "no rows" is a list's absence, so a list
    is never written as `null` beside its own empty spelling.
    """
    data = handler(model)
    for name in nulls:
        if data.get(name) is None:
            data.pop(name, None)
    for name in empties:
        if not data.get(name):
            data.pop(name, None)
    return data


def omit_when_null(
    handler: SerializerFunctionWrapHandler, model: BaseModel, *names: str
) -> dict[str, Any]:
    """Serialize `model` and drop the named fields when they are null (feature 005).

    A field added by feature 005 is optional and absent from `required` in both contracts,
    so a null is the same fact as an absent key - and the absent key is the one that keeps
    a lever-off run *byte-identical* to a run of the tree before the lever existed
    (SC-007). Two readers make that measurable rather than cosmetic: the model-facing tool
    payload (`tools/registry.py` encodes the same objects), where five extra null members
    per finding and per manifest entry are tokens paid on the off arm of an efficiency
    feature, and `events.jsonl`, whose flag-off stream must be comparable line for line.

    Only fields named here are dropped, and only when null: every field a package or a
    session already carried keeps its null, because dropping those would change the shape
    feature 001's readers were written against.
    """
    return omit_additive(handler, model, nulls=names)


Transform = Annotated[list[Annotated[list[float], Len(4, 4)]], Len(4, 4)]
"""Row-major 4x4, translation in meters (SOLIDWORKS internal units)."""

BBox2D = Annotated[list[float], Len(4, 4)]
"""[x0, y0, x1, y1] in PDF points."""

LengthUnit = Literal["mm", "in", "m"]
AngleUnit = Literal["deg", "rad"]
VolumeUnit = Literal["mm3", "in3", "m3"]

MateEntityResolution = Literal["resolved", "unresolved", "unknown"]
"""What `IMateEntity2.Reference` said about one mate entity (schema 1.4.0)."""

DrawingEvidenceSource = Literal["native", "pdf_ingest"]
"""Which path produced a drawing sheet: the native dump phase or the PDF ingest (1.4.0)."""


class IRModel(BaseModel):
    """Strict base: no coercion, no unknown fields (research R5)."""

    model_config = ConfigDict(strict=True, extra="forbid")


# --- 1. Shared value types -------------------------------------------------------


class Quantity(IRModel):
    value: float
    unit: LengthUnit


class Volume(IRModel):
    value: float
    unit: VolumeUnit


class Angle(IRModel):
    value: float
    unit: AngleUnit


class Vec3(IRModel):
    x: float
    y: float
    z: float


class Axis(IRModel):
    origin: Vec3
    direction: Vec3


class SourceRef(IRModel):
    """Where a value came from. At least one locator must be set."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        json_schema_extra={
            "anyOf": [
                {"required": ["sheet"]},
                {"required": ["annotation"]},
                {"required": ["persist_ref"]},
                {"required": ["page"]},
            ]
        },
    )

    document_id: str
    sheet: str | None = None
    view: str | None = None
    annotation: str | None = None
    persist_ref: PersistRef | None = None
    page: int | None = None
    bbox: BBox2D | None = None

    @model_validator(mode="after")
    def _require_a_locator(self) -> SourceRef:
        if self.sheet is None and self.annotation is None:
            if self.persist_ref is None and self.page is None:
                raise ValueError(
                    "SourceRef needs at least one locator: sheet, annotation, persist_ref or page"
                )
        return self


class Tolerance(IRModel):
    kind: Literal["symmetric", "bilateral", "limits", "basic", "none"]
    upper: Quantity | Angle | None
    lower: Quantity | Angle | None
    source: SourceRef


class Dimension(IRModel):
    nominal: Quantity | Angle
    tolerance: Tolerance
    source: SourceRef
    text_as_read: str


# --- 2. Intermediate representation ----------------------------------------------


class ManifestEntry(IRModel):
    document_id: str
    vault_path: str
    vault_version: int | None
    revision: str | None
    configuration: str
    local_modified: bool | None
    export_method: Literal["native", "pdf", "step", "manual"]
    file_modified_utc: datetime | None = Field(
        default=None,
        strict=False,
        description=(
            "`FileInfo.LastWriteTimeUtc` of `vault_path` when the dump ran (schema 1.3.0). "
            "Null plus a gap when the path could not be stat'ed, and null in every package "
            "written before 1.3.0. Never 0 and never 'now': the package-reuse key (feature "
            "005 lever 9) treats unknown as a refusal, not as a match."
        ),
    )
    file_size_bytes: int | None = Field(
        default=None,
        ge=0,
        description=(
            "`FileInfo.Length` of `vault_path`, same source and same null-with-a-gap rule "
            "as `file_modified_utc` (schema 1.3.0)."
        ),
    )

    @model_serializer(mode="wrap")
    def _omit_null_1_3_0_fields(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Leave the 1.3.0 additions out when they are null, so a 1.2.0 entry round-trips
        to the bytes a 1.2.0 build wrote (`omit_when_null`)."""
        return omit_when_null(handler, self, "file_modified_utc", "file_size_bytes")


class Discrepancy(IRModel):
    document_id: str
    kind: Literal["version_mismatch", "local_modification", "missing_document", "config_mismatch"]
    expected: str | int | None
    actual: str | int | None
    note: str


class Manifest(IRModel):
    entries: list[ManifestEntry]
    discrepancies: list[Discrepancy]


class Design(IRModel):
    design_id: str
    name: str
    root_assembly_document_id: str
    active_configuration: str
    drawing_document_ids: list[str]


class MassProperties(IRModel):
    mass_kg: float
    volume_m3: float
    center_of_mass: Vec3
    configuration: str


class Document(IRModel):
    document_id: str
    kind: Literal["part", "assembly", "drawing"]
    file_name: str
    path: str
    configurations: list[str]
    active_configuration: str
    custom_properties: dict[str, str]
    config_properties: dict[str, dict[str, str]]
    material: str | None
    mass: MassProperties | None
    is_exploded: bool | None = Field(
        default=None,
        description=(
            "IModelDoc2.IsExploded() for an assembly document (schema 1.4.0); null plus an "
            "assembly_exploded gap when unreadable. Always null for a part or a drawing, "
            "where the question does not apply and the absence is not a gap."
        ),
    )
    rebuild_error_count: int | None = Field(
        default=None,
        ge=0,
        description=(
            "IModelDocExtension.GetWhatsWrongCount read as the document stands - nothing is "
            "rebuilt (schema 1.4.0); null plus a rebuild_error_count gap when unreadable."
        ),
    )
    mass_overridden: bool | None = Field(
        default=None,
        description=(
            "Whether the mass is overridden, read before the volume gates so a surface-only "
            "part still answers (schema 1.4.0). From feature 010 through the interface that "
            "has it: IModelDocExtension.CreateMassProperty()'s IMassProperty.OverrideMass, "
            "else IMassProperty2.GetOverrideOptions()'s OverrideMass; null plus one "
            "mass_override gap naming both paths when neither answers."
        ),
    )
    material_configuration: str | None = Field(
        default=None,
        description=(
            "The configuration `material` was read in (schema 1.4.0). Null for an assembly or "
            "a drawing, and present whenever the read was attempted - including when "
            "`material` came back null, because 'no material in configuration X' and 'no "
            "material, configuration unknown' are different facts."
        ),
    )

    @model_serializer(mode="wrap")
    def _omit_null_1_4_0_fields(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Leave the 1.4.0 additions out when they are null, so a 1.3.0 document round-trips
        to the bytes a 1.3.0 build wrote (`omit_additive`)."""
        return omit_additive(
            handler,
            self,
            nulls=(
                "is_exploded",
                "rebuild_error_count",
                "mass_overridden",
                "material_configuration",
            ),
        )


class ComponentInstance(IRModel):
    id: Annotated[str, StringConstraints(pattern=r"^cmp:[0-9]{4,}$")]
    persist_ref: PersistRef
    persist_ref_scope: str = Field(
        description="document_id whose IModelDocExtension produced persist_ref; "
        "resolve against that document"
    )
    name: str
    document_id: str
    parent_id: str | None
    referenced_configuration: str
    transform: Transform = Field(
        description="Row-major 4x4 relative to the root assembly, translation in meters"
    )
    suppression: Literal["resolved", "lightweight", "suppressed", "unloaded"]
    is_fixed: bool
    pattern_id: str | None
    is_toolbox: bool
    full_path: str = Field(
        description="IComponent2.Name2 full instance path, unique in the assembly"
    )
    constrained_status_raw: int | None = Field(
        default=None,
        description="IComponent2.GetConstrainedStatus verbatim; null (plus a "
        "component_constrained_status gap) when unreadable. Named in Python, not here.",
    )
    transparency_raw: float | None = Field(
        default=None,
        description=(
            "Slot 7 of IComponent2.GetMaterialPropertyValues2(1, null) verbatim (schema "
            "1.4.0); null plus a component_transparency gap when unreadable, and null "
            "without a gap when has_appearance_override is false - there is nothing to read."
        ),
    )
    has_appearance_override: bool | None = Field(
        default=None,
        description=(
            "IComponent2.HasMaterialPropertyValues() (schema 1.4.0); null plus a "
            "component_transparency gap when unreadable. Replaces the -1 sentinel that "
            "conflated 'no override' with a real value."
        ),
    )
    visibility_raw: int | None = Field(
        default=None,
        description=(
            "IComponent2.Visible verbatim, in swComponentVisibilityState_e - hidden 0, "
            "visible 1, unknown -1 (schema 1.4.0); null plus a component_visibility gap when "
            "unreadable. The extractor records the number; Python names it."
        ),
    )
    is_pattern_instance: bool | None = Field(
        default=None,
        description=(
            "IComponent2.IsPatternInstance() (schema 1.4.0); null plus a component_pattern "
            "gap when unreadable. `pattern_id` keeps the pattern's name and cannot replace "
            "this: a null pattern_id conflates 'not in a pattern' with 'the pattern map was "
            "never built'."
        ),
    )

    @model_serializer(mode="wrap")
    def _omit_null_1_4_0_fields(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Leave the 1.4.0 additions out when they are null; `constrained_status_raw` and
        every earlier member keep their null (`omit_additive`)."""
        return omit_additive(
            handler,
            self,
            nulls=(
                "transparency_raw",
                "has_appearance_override",
                "visibility_raw",
                "is_pattern_instance",
            ),
        )


class SketchInfo(IRModel):
    """What the extractor reads off a feature's sketch (schema 1.1.0).

    `raw_status` is `ISketch.GetConstrainedStatus` verbatim: the extractor classifies
    nothing, so the name behind the number is Python's job (`RmsTypeTable`).
    """

    raw_status: int | None = Field(
        description="ISketch.GetConstrainedStatus verbatim; null plus a sketch_status gap"
    )
    consumer_ids: list[str] | None = Field(
        description="Feature ids that consume this sketch (GetChildren); "
        "null plus a feature_children gap when unavailable, [] when there are none"
    )
    text_segment_count: int | None = Field(
        default=None,
        ge=0,
        description=(
            "len(ISketch.GetSketchTextSegments()), 0 for an empty or null array (schema "
            "1.4.0); null plus a sketch_text gap when unreadable, which leaves the sketch "
            "unresolved because the text exemption can then neither be applied nor ruled out."
        ),
    )

    @model_serializer(mode="wrap")
    def _omit_null_1_4_0_fields(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return omit_additive(handler, self, nulls=("text_segment_count",))


class FilletInfo(IRModel):
    """The default radius of a simple fillet feature (schema 1.1.0)."""

    default_radius: Quantity | None = Field(
        description="ISimpleFilletFeatureData2.DefaultRadius in meters; null plus a "
        "fillet_radius gap when unreadable or when the fillet is variable"
    )


class Feature(IRModel):
    """One node of a part document's feature tree, in traversal order (schema 1.1.0).

    The extractor decides nothing about folders, end tags, groups or classes: those are
    derived in Python from `type_name` and `name` against `checks/rms_types.yaml`.
    """

    id: Annotated[str, StringConstraints(pattern=r"^feat:[0-9]{4,}$")]
    persist_ref: PersistRef
    persist_ref_scope: str = Field(
        description="document_id whose IModelDocExtension produced persist_ref; "
        "resolve against that document"
    )
    document_id: str
    configuration: str = Field(
        description="The configuration the tree was read in (the document's active one)"
    )
    name: str
    type_name: str = Field(description="GetTypeName2 verbatim; may be a name no table knows")
    description: str | None = Field(
        description="IFeature.Description; null when unreadable (gap), '' when blank"
    )
    index: int = Field(
        ge=0, description="Flat order within the document's tree, folders inline"
    )
    depth: int = Field(
        ge=0, description="0 top level, 1 inside a folder, from sub-features only"
    )
    folder_id: str | None = Field(description="id of the nearest enclosing feature")
    suppressed: bool | None = Field(description="In `configuration`; null when unreadable")
    error_code: int | None = Field(description="GetErrorCode2; null when unreadable")
    child_ids: list[str] | None = Field(
        description="Dependents from GetChildren; null plus a feature_children gap"
    )
    parent_ids: list[str] | None = Field(
        description="Dependencies from GetParents; null plus a feature_parents gap"
    )
    sketch: SketchInfo | None = Field(
        description="Present only for features GetSpecificFeature2 returns an ISketch for"
    )
    fillet: FilletInfo | None = Field(
        description="Present only for features whose definition is a simple fillet"
    )


class Equation(IRModel):
    """One row of a document's equation manager (schema 1.1.0)."""

    document_id: str
    index: int = Field(ge=0, description="Position in the equation manager")
    text: str = Field(description="Full equation text as read")
    lhs: str = Field(description="Left of the first '=', quotes stripped; evidence only")
    is_global: bool | None = Field(
        description="IEquationMgr.GlobalVariable(i); null plus an equations gap"
    )
    value: float | None = Field(description="Value(i); null when unreadable")


class MateEntity(IRModel):
    component_id: str
    persist_ref: PersistRef | None
    entity_kind: str
    resolution_status: MateEntityResolution | None = Field(
        default=None,
        description=(
            "What IMateEntity2.Reference gave, with no new interop call (schema 1.4.0): "
            "'resolved' when the reference was non-null, 'unresolved' when it was null, "
            "'unknown' plus a mate_entity_reference gap when the read threw. Null only in a "
            "package written before 1.4.0. Without it both outcomes are a null persist_ref "
            "and indistinguishable."
        ),
    )

    @model_serializer(mode="wrap")
    def _omit_null_1_4_0_fields(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return omit_additive(handler, self, nulls=("resolution_status",))


class Mate(IRModel):
    id: str
    persist_ref: PersistRef
    persist_ref_scope: str = Field(
        description="document_id whose IModelDocExtension produced persist_ref; "
        "resolve against that document"
    )
    type: str
    entities: Annotated[list[MateEntity], Len(1)]
    alignment: Literal["aligned", "anti_aligned", "closest"]
    suppressed: bool
    distance: Quantity | None
    angle: Angle | None


class HoleWizardData(IRModel):
    """What a Hole Wizard feature says beyond its size, depths and axis (schema 1.5.0,
    feature 010 US8): the fit and thread classes and the drill, counterbore and countersink
    sizes (FR-021).

    Every field is read verbatim from `IWizardHoleFeatureData2` in the units SOLIDWORKS
    reports - metres and radians - and nothing is derived. A read that failed is null plus a
    `hole_wizard` gap naming the field; a read that answered zero or a blank (the field does
    not apply to this hole type) is null with no gap. Absent keys and nulls are the same
    fact, so the record carries only what was read, and an empty record says the wizard data
    was read and nothing applied.
    """

    fit_class_raw: str | None = Field(
        default=None,
        description=(
            "IWizardHoleFeatureData2.HoleFit as the name of its swWzdHoleScrewClearanceTypes_e "
            "member (swScrewClearanceClose, ...Normal, ...Loose), or the integer's text for a "
            "value the enumeration does not name. A screw clearance fit, never an ISO 286 "
            "tolerance class: a hole's ISO class arrives on its dimension "
            "(ModelDimension.fit_hole_class). Read for counterbore and countersink holes only, "
            "the two types the API documents it for."
        ),
    )
    thread_class_raw: str | None = Field(
        default=None,
        description=(
            "IWizardHoleFeatureData2.ThreadClass verbatim (1B, 2B, 3B for ANSI inch); read for "
            "a tapped hole only, because only a tapped hole has a thread."
        ),
    )
    thru_hole_diameter: Quantity | None = Field(
        default=None, description="IWizardHoleFeatureData2.ThruHoleDiameter, metres"
    )
    tap_drill_diameter: Quantity | None = Field(
        default=None, description="IWizardHoleFeatureData2.TapDrillDiameter, metres"
    )
    counterbore_diameter: Quantity | None = Field(
        default=None, description="IWizardHoleFeatureData2.CounterBoreDiameter, metres"
    )
    counterbore_depth: Quantity | None = Field(
        default=None, description="IWizardHoleFeatureData2.CounterBoreDepth, metres"
    )
    countersink_diameter: Quantity | None = Field(
        default=None, description="IWizardHoleFeatureData2.CounterSinkDiameter, metres"
    )
    countersink_angle: Angle | None = Field(
        default=None,
        description="IWizardHoleFeatureData2.CounterSinkAngle, radians (the API's system unit)",
    )
    head_clearance: Quantity | None = Field(
        default=None, description="IWizardHoleFeatureData2.HeadClearance, metres"
    )

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return omit_additive(
            handler,
            self,
            nulls=(
                "fit_class_raw",
                "thread_class_raw",
                "thru_hole_diameter",
                "tap_drill_diameter",
                "counterbore_diameter",
                "counterbore_depth",
                "countersink_diameter",
                "countersink_angle",
                "head_clearance",
            ),
        )


class Hole(IRModel):
    id: str
    persist_ref: PersistRef
    persist_ref_scope: str = Field(
        description="document_id whose IModelDocExtension produced persist_ref; "
        "resolve against that document"
    )
    component_id: str
    feature_name: str
    hole_type: Literal["tapped", "clearance", "counterbore", "countersink", "simple", "unknown"]
    standard: str | None
    size: str | None
    thread_designation: str | None
    thread_depth: Quantity | None = Field(
        description="Usable thread depth. null = unknown; never derived from hole_depth."
    )
    hole_depth: Quantity | None
    end_condition: Literal["blind", "through", "unknown"]
    diameter: Quantity | None
    axis: Axis
    face_ids: list[str]
    wizard: HoleWizardData | None = Field(
        default=None,
        description=(
            "The Hole Wizard data beyond size, depths and axis (schema 1.5.0, feature 010). "
            "Omitted when null: a package written before 1.5.0, or a hole whose definition "
            "was not read."
        ),
    )

    @model_serializer(mode="wrap")
    def _omit_null_1_5_0_fields(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Leave `wizard` out when it is null, so a 1.4.0 hole round-trips to the bytes a
        1.4.0 build wrote (`omit_additive`)."""
        return omit_additive(handler, self, nulls=("wizard",))


class CosmeticThread(IRModel):
    id: str
    persist_ref: PersistRef
    persist_ref_scope: str = Field(
        description="document_id whose IModelDocExtension produced persist_ref; "
        "resolve against that document"
    )
    component_id: str
    face_id: str
    designation: str
    depth: Quantity | None
    is_external: bool


class Fastener(IRModel):
    id: str
    persist_ref: PersistRef
    persist_ref_scope: str = Field(
        description="document_id whose IModelDocExtension produced persist_ref; "
        "resolve against that document"
    )
    component_id: str
    kind: Literal["screw", "bolt", "nut", "washer", "pin", "other"]
    identity_source: Literal["toolbox", "custom_property", "name_parse", "manual"]
    thread_designation: str | None
    length: Quantity | None
    head_type: str | None
    head_diameter: Quantity | None
    head_height: Quantity | None
    drive: str | None
    axis: Axis
    material: str | None


class CylinderFace(IRModel):
    axis_origin: Vec3
    axis_dir: Vec3
    radius_m: float = Field(gt=0)


class PlaneFace(IRModel):
    origin: Vec3
    normal: Vec3


class BBox3D(IRModel):
    min: Vec3
    max: Vec3


class FaceGeometry(IRModel):
    id: str
    persist_ref: PersistRef
    persist_ref_scope: str = Field(
        description="document_id whose IModelDocExtension produced persist_ref; "
        "resolve against that document"
    )
    component_id: str
    body_id: str
    kind: Literal["cylinder", "plane", "cone", "torus", "other"]
    cylinder: CylinderFace | None
    plane: PlaneFace | None
    bbox: BBox3D
    area_m2: float | None


class BodyRef(IRModel):
    id: str
    persist_ref: PersistRef
    persist_ref_scope: str = Field(
        description="document_id whose IModelDocExtension produced persist_ref; "
        "resolve against that document"
    )
    component_id: str
    mesh_file: Annotated[str, StringConstraints(pattern=r"\.(glb|stl)$")]
    triangle_count: int = Field(ge=0)
    is_solid: bool


class InterferenceSettings(IRModel):
    treat_coincident_as_interference: bool
    treat_subassemblies_as_components: bool
    include_multibody: bool
    ignore_hidden: bool
    fastener_folder_treatment: Literal["include", "exclude", "only"]


class Interference(IRModel):
    id: str
    configuration: str
    component_ids: Annotated[list[str], Len(2, 2)]
    volume: Volume | None = Field(
        description="Unit as verified by the extractor on the workstation; "
        "IInterference.Volume units are undocumented"
    )
    settings: InterferenceSettings
    status: Literal["computed", "truncated", "failed"]
    error: str | None
    group_key: str
    is_fastener: bool = Field(description="IInterference.IsFastener")
    is_possible: bool = Field(
        description="IInterference.IsPossibleInterference (coincident/touching)"
    )


class SuppressTestRow(IRModel):
    """What one planned feature's suppression attempt produced (schema 1.1.0)."""

    feature_id: str
    persist_ref: PersistRef
    persist_ref_scope: str = Field(
        description="document_id whose IModelDocExtension produced persist_ref; "
        "resolve against that document"
    )
    name: str
    outcome: Literal[
        "ok", "rebuild_errors", "already_suppressed", "not_applied", "truncated", "aborted"
    ]
    whats_wrong_count: int | None = Field(ge=0)
    messages: Annotated[list[str], Len(0, 20)]
    messages_truncated: int = Field(ge=0, description="Messages dropped beyond the 20 kept")
    error: str | None
    elapsed_ms: int | None = Field(ge=0)


class SuppressTestRun(IRModel):
    """One `suppress-test` run appended to the package (schema 1.1.0).

    Written only by the console command through `PackageAppender`; a later `dump`
    overwrites the package and drops it, exactly as interference results are dropped.
    """

    document_id: str
    configuration: str
    group: str = Field(description="The Detail group name from the plan")
    plan_file: str = Field(description="Path of the plan consumed")
    # Relaxed like EvidencePackage.created_at: the package's custom __init__ validates
    # nested models in python mode even when the input came from JSON, which a strict
    # datetime would reject for the ISO string in the file.
    run_at: datetime = Field(strict=False)
    acknowledged: bool = Field(description="Always true; the command refuses otherwise")
    baseline_whats_wrong_count: int = Field(
        ge=0,
        description="Read before the first suppression; the command refuses when non-zero, "
        "so this is 0 in every written run and is recorded for audit",
    )
    limit: int = Field(ge=1, description="--limit in effect")
    timeout_seconds: int = Field(ge=1, description="--timeout-seconds in effect")
    features_present: int = Field(ge=0, description="Planned features; equals len(rows)")
    restore_verified: bool = Field(
        description="The post-run tree matched the pre-run snapshot"
    )
    unrestored_feature_ids: list[str] = Field(description="Empty when restore_verified")
    rows: list[SuppressTestRow] = Field(
        description="One per planned feature, in plan order; untested ones are truncated"
    )

    @model_validator(mode="after")
    def _rows_account_for_every_planned_feature(self) -> SuppressTestRun:
        """The two invariants a reader of a run relies on (data-model.md section 1).

        A feature the run never reached is a `truncated` row, not a missing one, so a
        short table can never be read as a complete one; and a restore that left features
        suppressed was not verified, whatever the flag says.
        """
        if len(self.rows) != self.features_present:
            raise ValueError(
                f"features_present is {self.features_present} but there are "
                f"{len(self.rows)} rows; every planned feature carries a row"
            )
        if self.restore_verified and self.unrestored_feature_ids:
            raise ValueError(
                "restore_verified is true but "
                f"{len(self.unrestored_feature_ids)} feature(s) are listed as unrestored"
            )
        return self


class Capture(IRModel):
    id: str
    persist_ref: PersistRef | None
    component_ids: list[str]
    file: Annotated[str, StringConstraints(pattern=r"\.png$")]
    view: str
    note: str


class Note(IRModel):
    text: str
    source: SourceRef
    kind: Literal["general_tolerance", "material", "finish", "other"]


class SheetView(IRModel):
    name: str
    bbox: BBox2D


class DrawingSheet(IRModel):
    document_id: str
    sheet_name: str
    page: int = Field(ge=1)
    scale: str | None
    units: Literal["mm", "in", "unknown"]
    general_notes: list[Note]
    dimensions: list[Dimension]
    views: list[SheetView]
    parse_status: Literal["text", "no_text", "failed"]
    parser: str
    source: DrawingEvidenceSource | None = Field(
        default=None,
        description=(
            "Which path wrote this sheet (schema 1.4.0); the PDF ingest stamps 'pdf_ingest'. "
            "Null in a sheet written before the stamp existed, which a consumer reads as "
            "'source not recorded' and the drawing checks treat exactly as 'pdf_ingest'."
        ),
    )

    @model_serializer(mode="wrap")
    def _omit_null_1_4_0_fields(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return omit_additive(handler, self, nulls=("source",))


# --- 2b. Native drawing evidence (schema 1.4.0, feature 006) ----------------------
#
# These are new models, not an extension of `DrawingSheet`: the PDF ingest's sheet requires
# `page`, `parse_status` and `parser`, none of which a natively dumped sheet has, and
# filling them in would be a fiction (006 research R9). They live in their own
# `EvidencePackage.drawing_records[]` beside the untouched `drawings[]` for the same
# reason. Every record carries a package id allocated in traversal order, plus
# `persist_ref`/`persist_ref_scope` when SOLIDWORKS gave one - a **null** persist_ref is
# the statement FR-026 requires: the id is a within-dump identity, so a consumer never
# presents it as a persistent one.


class RevisionTableRow(IRModel):
    """One row of a revision table, keyed by its index inside that table (schema 1.4.0).

    Which row is the revision row, and whether a row is the header, are profile questions
    answered in Python; the extractor records cells and classifies nothing.
    """

    index: int = Field(ge=0, description="Position in the table, from 0")
    cells: list[str | None] = Field(
        default_factory=list,
        description=(
            "One per column, from ITableAnnotation.Text[row, col]. An empty cell is the "
            "empty string - a null cell is one that could not be read, and the two must not "
            "be confused: an empty revision cell is a real mismatch."
        ),
    )
    is_header: bool | None = Field(
        default=None,
        description=(
            "The extractor's reading of the table's own title-row structure (TotalRowCount "
            "versus RowCount); may be null, and no check relies on it alone."
        ),
    )

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return omit_additive(handler, self, nulls=("is_header",), empties=("cells",))


class RevisionTable(IRModel):
    """One revision table on one sheet (schema 1.4.0). Every table is read, not just the
    one `ISheet.RevisionTable` returns, so a second table is visible rather than silently
    missing from the one check whose purpose is coverage."""

    id: Annotated[str, StringConstraints(pattern=r"^drv:[0-9]{4,}$")]
    sheet_id: str
    current_revision_raw: str | None = Field(
        default=None,
        description=(
            "IRevisionTableAnnotation.CurrentRevision verbatim, including the empty string. "
            "Recorded alongside the rows because it comes back empty under some vaults; the "
            "check names both readings with their source rather than letting the dumper "
            "choose."
        ),
    )
    row_count: int | None = Field(
        default=None,
        ge=0,
        description="ITableAnnotation.RowCount; null plus a revision_table_read gap",
    )
    column_count: int | None = Field(
        default=None,
        ge=0,
        description="ITableAnnotation.ColumnCount; null plus a revision_table_read gap",
    )
    rows: list[RevisionTableRow] = Field(
        default_factory=list, description="Empty when the COM cast failed; the gap says so"
    )
    persist_ref: PersistRef | None = None
    persist_ref_scope: str | None = Field(
        default=None,
        description="document_id whose IModelDocExtension produced persist_ref; null when "
        "SOLIDWORKS gave none, and `id` is then the identity",
    )

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return omit_additive(
            handler,
            self,
            nulls=("current_revision_raw", "row_count", "column_count", "persist_ref",
                   "persist_ref_scope"),
            empties=("rows",),
        )


class DrawingNote(IRModel):
    """One note read off a drawing view (schema 1.4.0). Notes are reachable only through a
    view, and the export-control statement lives on the sheet-format pseudo-view."""

    id: Annotated[str, StringConstraints(pattern=r"^dnt:[0-9]{4,}$")]
    owner_id: str = Field(description="The DrawingView.id it was read from")
    text: str | None = Field(
        default=None,
        description=(
            "INote.GetText(); null plus a note_text gap, which leaves the export-control "
            "check unresolved because an unread note cannot be shown not to carry the phrase."
        ),
    )
    persist_ref: PersistRef | None = None
    persist_ref_scope: str | None = None

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return omit_additive(
            handler, self, nulls=("text", "persist_ref", "persist_ref_scope")
        )


class DrawingAnnotation(IRModel):
    """One annotation of any type on a drawing view (schema 1.4.0)."""

    id: Annotated[str, StringConstraints(pattern=r"^dan:[0-9]{4,}$")]
    owner_id: str = Field(
        description="The DrawingView.id it was read from; a sheet-format annotation's owner "
        "is the type-1 pseudo-view"
    )
    name: str | None = Field(
        default=None,
        description="IAnnotation.GetName(); null plus an annotation_identity gap. The "
        "annotation is still a subject, identified by `id`, its sheet and its view",
    )
    type_raw: int | None = Field(
        default=None,
        description="IAnnotation.GetType() verbatim, in swAnnotationType_e; Python names it",
    )
    is_dangling: bool | None = Field(
        default=None,
        description="IAnnotation.IsDangling(); null plus an annotation_dangling gap, and "
        "that annotation is then unresolved",
    )
    persist_ref: PersistRef | None = None
    persist_ref_scope: str | None = None

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return omit_additive(
            handler,
            self,
            nulls=("name", "type_raw", "is_dangling", "persist_ref", "persist_ref_scope"),
        )


class DisplayDimensionRecord(IRModel):
    """One display dimension on a drawing view (schema 1.4.0).

    Both value members are a `Quantity | Angle` union, following the existing IR precedent
    `Tolerance.upper` / `.lower`: `Quantity` carries a `LengthUnit` only, so an angular
    dimension cannot be represented by one and `dimension_type_raw` is what decides which
    of the two a record carries.
    """

    id: Annotated[str, StringConstraints(pattern=r"^ddm:[0-9]{4,}$")]
    view_id: str
    name: str | None = Field(
        default=None,
        description="IDimension.FullName, falling back to Name; null plus a "
        "dimension_override gap",
    )
    dimension_type_raw: int | None = Field(
        default=None,
        description="IDisplayDimension.Type2 verbatim; what decides whether the value is a "
        "length or an angle, and therefore its unit. Python names it",
    )
    is_overridden: bool | None = Field(
        default=None,
        description="IDisplayDimension.GetOverride(); null plus a dimension_override gap, "
        "and the dimension is then unresolved",
    )
    override_value: Quantity | Angle | None = Field(
        default=None,
        description=(
            "IDisplayDimension.GetOverrideValue() in the unit dimension_type_raw implies; "
            "null plus a dimension_unit gap when the unit could not be determined even "
            "though a number was read, because a number with a guessed unit is worse than "
            "no number."
        ),
    )
    value: Quantity | Angle | None = Field(
        default=None,
        description="IDimension.GetSystemValue3(1, null), the computed value, for the "
        "finding's observed text; same union and same null rule",
    )
    persist_ref: PersistRef | None = None
    persist_ref_scope: str | None = None

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return omit_additive(
            handler,
            self,
            nulls=("name", "dimension_type_raw", "is_overridden", "override_value", "value",
                   "persist_ref", "persist_ref_scope"),
        )


class DrawingView(IRModel):
    """One view on one sheet, including the sheet-format pseudo-view (schema 1.4.0)."""

    id: Annotated[str, StringConstraints(pattern=r"^dvw:[0-9]{4,}$")]
    sheet_id: str
    name: str | None = Field(
        default=None, description="IView.GetName2(); null plus a drawing_view gap"
    )
    view_type_raw: int | None = Field(
        default=None,
        description="IView.Type verbatim, in swDrawingViewTypes_e; 1 is the sheet-format "
        "pseudo-view. Python names the number",
    )
    referenced_document_id: str | None = Field(
        default=None,
        description="IView.ReferencedDocument resolved to a Document in this package; null "
        "when the view references nothing, or when the referenced model is not loaded - a "
        "drawing_referenced_document gap names the second case",
    )
    referenced_model_path: str | None = Field(
        default=None,
        description="IView.GetReferencedModelName(), recorded even when "
        "referenced_document_id is null, because it is what lets the gap name the model "
        "that was not loaded",
    )
    display_dimensions: list[DisplayDimensionRecord] = Field(default_factory=list)
    annotations: list[DrawingAnnotation] = Field(default_factory=list)
    notes: list[DrawingNote] = Field(default_factory=list)
    persist_ref: PersistRef | None = None
    persist_ref_scope: str | None = None

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return omit_additive(
            handler,
            self,
            nulls=("name", "view_type_raw", "referenced_document_id", "referenced_model_path",
                   "persist_ref", "persist_ref_scope"),
            empties=("display_dimensions", "annotations", "notes"),
        )


class DrawingSheetRecord(IRModel):
    """One natively dumped sheet of a drawing document (schema 1.4.0).

    `was_active` is load-bearing: nothing activates a sheet, so if only the active sheet's
    contents come back this is how a consumer knows which rows to trust.
    """

    id: Annotated[str, StringConstraints(pattern=r"^dsh:[0-9]{4,}$")]
    source: Literal["native"] = Field(
        default="native",
        description="Constant for this model: the per-sheet half of FR-024, so a sheet from "
        "either path says which produced it",
    )
    name: str = Field(description="ISheet.GetName()")
    index: int = Field(ge=0, description="Position in GetSheetNames(), from 0")
    sheet_format_name: str | None = Field(
        default=None,
        description="ISheet.GetSheetFormatName(); null plus a drawing_sheet gap",
    )
    was_active: bool = Field(
        description="Whether this sheet was the active one when it was read; nothing "
        "activates a sheet"
    )
    views: list[DrawingView] = Field(
        default_factory=list,
        description="ISheet.GetViews() order. Empty plus a drawing_sheet_views gap when the "
        "enumeration failed or came back empty on a non-active sheet",
    )
    revision_tables: list[RevisionTable] = Field(
        default_factory=list, description="Every revision table on the sheet, not just one"
    )
    persist_ref: PersistRef | None = None
    persist_ref_scope: str | None = None

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return omit_additive(
            handler,
            self,
            nulls=("sheet_format_name", "persist_ref", "persist_ref_scope"),
            empties=("views", "revision_tables"),
        )


class DrawingRecord(IRModel):
    """One natively dumped drawing document, keyed by its `document_id` (schema 1.4.0).

    Keyed rather than identified: there is one record per drawing document, so it carries
    neither a package id nor a persistent reference of its own.
    """

    document_id: str
    source: Literal["native"] = Field(
        default="native", description="Constant for this model (FR-024)"
    )
    active_sheet_name: str | None = Field(
        default=None,
        description="IDrawingDoc.GetCurrentSheet().GetName(), recorded read-only so the "
        "coverage reason can say which sheet was active while the others were read",
    )
    sheets: list[DrawingSheetRecord] = Field(
        default_factory=list,
        description="GetSheetNames() order; empty plus a drawing_sheet gap when the "
        "enumeration failed",
    )

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return omit_additive(
            handler, self, nulls=("active_sheet_name",), empties=("sheets",)
        )


class CutListItem(IRModel):
    """One cut-list item of one part document (schema 1.4.0).

    Identified structurally from the body-folder tree, never by matching a feature name:
    a renamed item is not a waiver.
    """

    id: Annotated[str, StringConstraints(pattern=r"^cut:[0-9]{4,}$")]
    document_id: str
    configuration: str = Field(description="The configuration the tree was read in")
    folder_name: str = Field(description="IFeature.Name of the enclosing cut-list folder")
    folder_type_name: str = Field(
        description="IFeature.GetTypeName2 of the enclosing folder, verbatim, so an unknown "
        "folder type is visible rather than silently dropped"
    )
    name: str = Field(description="IFeature.Name of the item")
    body_count: int | None = Field(
        default=None,
        ge=0,
        description=(
            "IBodyFolder.GetBodyCount(); null plus a cut_list_body_count gap. A folder whose "
            "count is 0 is not displayed by SOLIDWORKS and is not a subject of any check; it "
            "is still recorded so a coverage reason can say how many folders were seen and "
            "how many were displayable."
        ),
    )
    excluded_from_cut_list: bool | None = Field(
        default=None,
        description="IFeature.ExcludeFromCutList(); null plus a cut_list_exclusion gap, and "
        "that item is then unresolved",
    )
    persist_ref: PersistRef | None = None
    persist_ref_scope: str | None = Field(
        default=None,
        description="document_id whose IModelDocExtension produced persist_ref; null when "
        "SOLIDWORKS gave none, and `id` is then the identity",
    )

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return omit_additive(
            handler,
            self,
            nulls=("body_count", "excluded_from_cut_list", "persist_ref", "persist_ref_scope"),
        )


class ModelDimension(IRModel):
    """One dimension of a part document's features and its tolerance (schema 1.5.0,
    feature 010 US8, FR-022).

    Read from `IFeature.GetFirstDisplayDimension`/`GetNextDisplayDimension`,
    `IDisplayDimension.GetDimension2(0)` and `IDimension.Tolerance` (`IDimensionTolerance`),
    once per part document. Every dimension is recorded, toleranced or not, because a
    tolerance binds to a hole only through a dimension that is the unique one of its value in
    the document (research R2.18). Values are in SOLIDWORKS' system units, metres and radians.
    """

    id: Annotated[str, StringConstraints(pattern=r"^mdm:[0-9]{4,}$")]
    document_id: str
    feature_name: str = Field(description="IFeature.Name of the feature that owns the dimension")
    name: str = Field(description="IDimension.FullName, e.g. D1@Sketch1@part.SLDPRT")
    dimension_type: Literal["linear", "diameter", "radius", "angular", "other"] = Field(
        description=(
            "Named from IDisplayDimension.Type2 (swDimensionType_e): diameter 6, radial 5, "
            "angular 3 and 16, linear and ordinate 1, 2, 7, 8, 9, 11, 12; anything else is "
            "'other' and dimension_type_raw keeps the number"
        )
    )
    dimension_type_raw: int | None = Field(
        default=None, description="IDisplayDimension.Type2 verbatim"
    )
    nominal: Quantity | Angle = Field(
        description="IDimension.GetSystemValue3 in this configuration: metres or radians"
    )
    tolerance: Tolerance | None = Field(
        default=None,
        description=(
            "IDimensionTolerance read into the IR's Tolerance, the limits as the signed "
            "deviations GetMinValue2/GetMaxValue2 report: swTolNONE is kind 'none', BASIC "
            "'basic', SYMMETRIC 'symmetric', BILAT, LIMIT, FITWITHTOL and FITTOLONLY "
            "'bilateral'. Null when the type has no IR kind (MIN, MAX, FIT, BLOCK, GENERAL - "
            "tolerance_type_raw says which, and a fit's classes are below) or when the read "
            "failed (a model_dimension gap). Null is never 'none'."
        ),
    )
    tolerance_type_raw: int | None = Field(
        default=None, description="IDimensionTolerance.Type verbatim (swTolType_e)"
    )
    fit_hole_class: str | None = Field(
        default=None,
        description="IDimensionTolerance.GetHoleFitValue verbatim (e.g. H7), for a fit type",
    )
    fit_shaft_class: str | None = Field(
        default=None,
        description="IDimensionTolerance.GetShaftFitValue verbatim (e.g. g6), for a fit type",
    )
    persist_ref: PersistRef | None = None
    persist_ref_scope: str | None = Field(
        default=None,
        description="document_id whose IModelDocExtension produced persist_ref; null when "
        "SOLIDWORKS gave none, and `id` and `name` are then the identity",
    )

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return omit_additive(
            handler,
            self,
            nulls=(
                "dimension_type_raw",
                "tolerance",
                "tolerance_type_raw",
                "fit_hole_class",
                "fit_shaft_class",
                "persist_ref",
                "persist_ref_scope",
            ),
        )


class GtolFrame(IRModel):
    """One frame of a geometric tolerance, as SOLIDWORKS answered it (schema 1.5.0).

    A GTol created before SOLIDWORKS 2022 answers the frame calls `GetFrameSymbols3` and
    `GetFrameValues`; one in the 2022 format answers `IGtol.GetFrame(n).GetSymbolXml()`
    instead. Both are asked and each answer is recorded verbatim; parsing is Python's.
    """

    number: int = Field(ge=1, description="The one-based frame number the calls were asked for")
    symbols_raw: list[str] = Field(
        default_factory=list,
        description=(
            "IGtol.GetFrameSymbols3 verbatim: the geometric characteristic symbol, then the "
            "material condition symbols of tolerance 1, tolerance 2 and datums 1 to 3"
        ),
    )
    values_raw: list[str] = Field(
        default_factory=list,
        description="IGtol.GetFrameValues verbatim: tolerance 1, tolerance 2, datums 1 to 3",
    )
    symbol_xml_raw: str | None = Field(
        default=None, description="IGtolFrame.GetSymbolXml verbatim, for the 2022 format"
    )

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return omit_additive(
            handler, self, nulls=("symbol_xml_raw",), empties=("symbols_raw", "values_raw")
        )


class ModelAnnotation(IRModel):
    """One geometric tolerance or datum tag of a part document, DimXpert or MBD (schema
    1.5.0, feature 010 US8, FR-022).

    Read from `IModelDocExtension.GetAnnotations`, kept when `IAnnotation.GetType` is a GTol
    or a datum tag. It binds to a hole only through `attached_persist_refs`, the faces the
    annotation is attached to (research R2.18).
    """

    id: Annotated[str, StringConstraints(pattern=r"^man:[0-9]{4,}$")]
    document_id: str
    kind: Literal["gtol", "datum"]
    frames: list[GtolFrame] = Field(
        default_factory=list,
        description="A GTol's frames, 1 to IGtol.GetFrameCount(); empty for a datum tag",
    )
    datum_identifier_raw: str | None = Field(
        default=None, description="IGtol.GetDatumIdentifier verbatim, when not blank"
    )
    label: str | None = Field(default=None, description="IDatumTag.GetLabel, for a datum tag")
    is_dimxpert: bool | None = Field(
        default=None,
        description="IAnnotation.IsDimXpert(); null plus a model_annotation gap when unreadable",
    )
    attached_persist_refs: list[PersistRef] = Field(
        default_factory=list,
        description=(
            "The persistent references of the faces IAnnotation.GetAttachedEntities3 returns; "
            "edges, vertices and dangling attachments carry no face reference and are left out"
        ),
    )
    persist_ref: PersistRef | None = None
    persist_ref_scope: str | None = Field(
        default=None,
        description="document_id whose IModelDocExtension produced persist_ref; null when "
        "SOLIDWORKS gave none, and `id` is then the identity",
    )

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return omit_additive(
            handler,
            self,
            nulls=(
                "datum_identifier_raw",
                "label",
                "is_dimxpert",
                "persist_ref",
                "persist_ref_scope",
            ),
            empties=("frames", "attached_persist_refs"),
        )


class Gap(IRModel):
    kind: Literal["not_extracted", "unsupported", "tool_error", "no_text"]
    entity_kind: str
    entity_id: str | None
    reason: str
    error: str | None


class DumpPhase(IRModel):
    """What one phase of the dump cost and what became of it (schema 1.3.0, feature 005 T033).

    The same shape `SuppressTestRow.elapsed_ms` set as the package's only elapsed
    precedent. `status` is recorded rather than inferred from which arrays came back
    empty: an empty `holes[]` beside an `ok` row is a part with no holes, beside a
    `failed` one it is evidence the dump lost, and beside a `skipped` one it is a phase
    nobody ran.
    """

    name: str = Field(
        description=(
            "The phase as `PackageWriter` names it in its gaps: document, manifest, mate, "
            "feature, equation, cutlist, drawing, hole, tolerance, fastener, face, body"
        )
    )
    elapsed_ms: int | None = Field(
        ge=0,
        description=(
            "Wall clock across the phase, whole milliseconds. Null when the phase never "
            "ran - never 0, which is a phase that ran and came back inside the clock's "
            "resolution."
        ),
    )
    status: Literal["ok", "failed", "aborted", "skipped"] = Field(
        description=(
            "'ok' ran and returned; 'failed' threw, was recorded as a gap and the dump "
            "carried on; 'aborted' met an open circuit and the phases behind it were "
            "skipped; 'skipped' never ran - switched off by the profile or the options, "
            "or behind a phase that aborted."
        )
    )


class ExtractorInfo(IRModel):
    name: str
    version: str
    sw_version: str | None = Field(
        description="e.g. '2024 SP3'; null for exported-file-only packages"
    )
    machine: str
    profile: Literal["full", "model_check", "standards"] = Field(
        default="full",
        description=(
            "Which dump profile wrote this package (schema 1.2.0). 'model_check' skips "
            "the hole, tolerance, fastener, face and body phases, so those arrays are empty by "
            "design rather than by failure. 'standards' (schema 1.4.0) extends it with the "
            "cutlist phase, and the drawing phase for a drawing root. A closed enumeration "
            "in both serializers, so a pre-1.4.0 reader refuses a 'standards' package "
            "outright rather than reading it. Absent in 1.0.0 and 1.1.0 packages, which "
            "were all 'full'."
        ),
    )
    phases: list[DumpPhase] = Field(
        default_factory=list,
        description=(
            "One row per phase of the dump, in the order it ran them (schema 1.3.0, "
            "feature 005 T033 - the same minor the reuse fields arrived in). Empty in a "
            "package written by a build that timed nothing and in one assembled from "
            "exported files rather than dumped. In a package with `reused_from` set every "
            "row is 'skipped' with no elapsed time: no phase ran in that run, and the "
            "original dump's wall clock is not this run's. This is the only dump metric a "
            "package carries."
        ),
    )

    @model_serializer(mode="wrap")
    def _omit_empty_phases(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Leave `phases` out when nothing was timed, so a package written before the
        member existed round-trips to the bytes that build wrote and the feature 001/002/003
        goldens stay byte-identical (SC-007).

        Empty rather than null is what is dropped here, which is why this is not
        `omit_when_null`: the member is a list of rows and "no rows" is the absence, so a
        `None` would be a second way to say the same thing.
        """
        data = handler(self)
        if not data.get("phases"):
            data.pop("phases", None)
        return data


class EvidencePackage(IRModel):
    """Intermediate representation of one SOLIDWORKS design.

    Use `model_validate_json` (or `swreview.ir.loader.load_package`) to read a package:
    `package_id` and `created_at` are strict UUID/datetime fields, so JSON strings are
    only accepted in JSON mode.
    """

    schema_version: str = Field(
        pattern=SCHEMA_VERSION_PATTERN,
        description="Major 1. Consumers reject any other major.",
    )
    # Relaxed on purpose: the schema-version gate below needs a custom __init__, which
    # makes pydantic validate this model in python mode even when the input came from
    # JSON. Strict UUID/datetime fields would then reject the ISO strings in a package
    # file. Both are still parsed and rejected when malformed.
    package_id: UUID = Field(strict=False)
    created_at: datetime = Field(strict=False)
    reuse_key: str | None = Field(
        default=None,
        description=(
            "SHA-256 over what this package claims to be - the extractor, the schema, the "
            "profile, the four dump options, the root document and configuration, every "
            "manifest entry's file stat and every component's suppression state (schema "
            "1.3.0, feature 005 lever 9, `benchmark/reuse.py`). Null in a package written "
            "by a build that computes none. Declared here, ahead of the bulk of the "
            "package, so a bounded head read can find it without parsing tens of megabytes."
        ),
    )
    reused_from: str | None = Field(
        default=None,
        description=(
            "The run folder this package was copied from instead of dumped (schema 1.3.0, "
            "feature 005 lever 9); null when it was freshly dumped. Reuse is stated, never "
            "silent: this member, the pane's status line, the report header and "
            "`session.json` all say it."
        ),
    )
    reused_at: datetime | None = Field(
        default=None,
        strict=False,
        description=(
            "When the reuse decision was made - not when the original was dumped "
            "(schema 1.3.0)."
        ),
    )
    extractor: ExtractorInfo
    manifest: Manifest
    design: Design
    documents: list[Document]
    components: list[ComponentInstance]
    mates: list[Mate] = Field(default_factory=list)
    holes: list[Hole] = Field(default_factory=list)
    threads: list[CosmeticThread] = Field(default_factory=list)
    fasteners: list[Fastener] = Field(default_factory=list)
    faces: list[FaceGeometry] = Field(default_factory=list)
    bodies: list[BodyRef] = Field(default_factory=list)
    interferences: list[Interference] = Field(default_factory=list)
    captures: list[Capture] = Field(default_factory=list)
    drawings: list[DrawingSheet] = Field(default_factory=list)
    drawing_records: list[DrawingRecord] = Field(
        default_factory=list,
        description=(
            "Natively dumped drawing documents (schema 1.4.0), one per drawing, written by "
            "the `drawing` phase. Beside `drawings` rather than inside it: that member is "
            "the PDF ingest's `DrawingSheet`, whose `page`, `parse_status` and `parser` a "
            "native sheet has no honest value for (006 research R9). Omitted when empty, so "
            "a package that ran no drawing phase serializes as it did before 1.4.0."
        ),
    )
    features: list[Feature] = Field(default_factory=list)
    equations: list[Equation] = Field(default_factory=list)
    cut_list_items: list[CutListItem] = Field(
        default_factory=list,
        description=(
            "Cut-list items of the package's part documents (schema 1.4.0), written by the "
            "`cutlist` phase. Omitted when empty."
        ),
    )
    model_dimensions: list[ModelDimension] = Field(
        default_factory=list,
        description=(
            "The part documents' feature dimensions and their tolerances (schema 1.5.0, "
            "feature 010), written by the `tolerance` phase. Omitted when empty."
        ),
    )
    model_annotations: list[ModelAnnotation] = Field(
        default_factory=list,
        description=(
            "The part documents' geometric tolerances and datum tags, DimXpert or MBD "
            "(schema 1.5.0, feature 010), written by the `tolerance` phase. Omitted when empty."
        ),
    )
    rms_suppress_test: SuppressTestRun | None = None
    gaps: list[Gap]

    @model_serializer(mode="wrap")
    def _omit_empty_additive_arrays(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        """Leave the 1.4.0 and 1.5.0 arrays out when they carry no rows, so a package that
        ran none of their phases round-trips to the bytes the 1.3.0 build wrote and the
        feature 001, 002 and 003 goldens stay byte-identical (SC-004, feature 010 FR-028).

        Only these four are dropped: every array feature 001 shipped keeps its `[]`, because
        dropping those would change the shape its readers were written against.
        """
        return omit_additive(
            handler,
            self,
            empties=("drawing_records", "cut_list_items", "model_dimensions", "model_annotations"),
        )

    # The three entry points below gate the schema major before pydantic runs, so an
    # unreadable major surfaces as UnsupportedSchemaVersionError instead of being
    # wrapped into a ValidationError by pydantic-core.

    def __init__(self, **data: Any) -> None:
        require_supported_schema_version(data.get("schema_version"))
        super().__init__(**data)

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> EvidencePackage:
        if isinstance(obj, Mapping):
            require_supported_schema_version(obj.get("schema_version"))
        return super().model_validate(obj, **kwargs)

    @classmethod
    def model_validate_json(
        cls, json_data: str | bytes | bytearray, **kwargs: Any
    ) -> EvidencePackage:
        try:
            peeked = json.loads(json_data)
        except ValueError:
            peeked = None
        if isinstance(peeked, Mapping):
            require_supported_schema_version(peeked.get("schema_version"))
        return super().model_validate_json(json_data, **kwargs)
