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
from collections.abc import Mapping
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

SCHEMA_VERSION = "1.3.0"
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
    data = handler(model)
    for name in names:
        if data.get(name) is None:
            data.pop(name, None)
    return data


Transform = Annotated[list[Annotated[list[float], Len(4, 4)]], Len(4, 4)]
"""Row-major 4x4, translation in meters (SOLIDWORKS internal units)."""

BBox2D = Annotated[list[float], Len(4, 4)]
"""[x0, y0, x1, y1] in PDF points."""

LengthUnit = Literal["mm", "in", "m"]
AngleUnit = Literal["deg", "rad"]
VolumeUnit = Literal["mm3", "in3", "m3"]


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


class Gap(IRModel):
    kind: Literal["not_extracted", "unsupported", "tool_error", "no_text"]
    entity_kind: str
    entity_id: str | None
    reason: str
    error: str | None


class ExtractorInfo(IRModel):
    name: str
    version: str
    sw_version: str | None = Field(
        description="e.g. '2024 SP3'; null for exported-file-only packages"
    )
    machine: str
    profile: Literal["full", "model_check"] = Field(
        default="full",
        description=(
            "Which dump profile wrote this package (schema 1.2.0). 'model_check' skips "
            "the hole, fastener, face and body phases, so those arrays are empty by "
            "design rather than by failure. Absent in 1.0.0 and 1.1.0 packages, which "
            "were all 'full'."
        ),
    )


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
    features: list[Feature] = Field(default_factory=list)
    equations: list[Equation] = Field(default_factory=list)
    rms_suppress_test: SuppressTestRun | None = None
    gaps: list[Gap]

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
