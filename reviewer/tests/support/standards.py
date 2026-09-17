"""Builders for standards-check evidence packages (T008).

`packages.py` keeps the schema version, the package id, the creation time and the extractor
block in one place, and this module builds on it, exactly as `features.py` does for feature
003. The feature tree is not laid out a second time either: `build_features` from
`features.py` allocates the `feat:NNNN` ids, resolves names to ids and emits the rows, and
this module adds the evidence feature 003 has no reason to carry - vault-shaped document
paths, data-card properties, the appearance, visibility and pattern readings on an instance,
mate-entity resolution, cut-list items and the native drawing record.

Two layers, the same split `features.py` uses:

1. **Specs** - frozen dataclasses naming everything by *name*: a component says which document
   it instantiates and which component it hangs under, a drawing view says which document it
   references. A name that is not in the package is an error, never a silently dropped
   reference.
2. **Layout** - `standards_package`, which allocates every id in traversal order
   (`doc:`, `cmp:`, `mate:`, `feat:`, `cut:`, `dsh:`, `dvw:`, `ddm:`, `dan:`, `dnt:`, `drv:`)
   and emits validated IR models.

Two conventions worth stating, because a fixture that disagrees with them is a wrong fixture:

- **Paths are written for a profile.** `folder` is vault-relative and `vault_root` (or
  `profile`) supplies the root, so a fixture package and the profile it is graded against
  agree about which library prefix a document is under without either of them repeating the
  other's strings.
- **No gap is invented here.** `gaps` is passed through verbatim: which gap a dumper records
  beside a null is the contract's business and a fixture must be free to say "this reading is
  missing and *no* gap was recorded", which is the case the checks must not clear.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from swreview.checks.standards.profile import StandardsProfile
from swreview.ir.models import (
    Angle,
    ComponentInstance,
    CutListItem,
    Design,
    DisplayDimensionRecord,
    Document,
    DrawingAnnotation,
    DrawingNote,
    DrawingRecord,
    DrawingSheetRecord,
    DrawingView,
    DumpPhase,
    EvidencePackage,
    ExtractorInfo,
    Feature,
    Gap,
    Manifest,
    ManifestEntry,
    Mate,
    MateEntity,
    Quantity,
    RevisionTable,
    RevisionTableRow,
)
from tests.support.features import FeatureSpec, Shape, build_features
from tests.support.packages import IDENTITY_TRANSFORM, build_package, persist_ref

Suppression = Literal["resolved", "lightweight", "suppressed", "unloaded"]
MateResolution = Literal["resolved", "unresolved", "unknown"]

PHASE_ORDER: tuple[str, ...] = (
    "document",
    "manifest",
    "mate",
    "feature",
    "equation",
    "cutlist",
    "drawing",
    "hole",
    "fastener",
    "face",
    "body",
)
"""Every phase `PackageWriter` names, in the order it runs them (`ir-additions.md` §6)."""

STANDARDS_PHASES: frozenset[str] = frozenset(
    {"document", "manifest", "mate", "feature", "equation", "cutlist"}
)
"""What the `standards` profile runs on every root; `drawing` runs for a drawing root only,
and the hole, fastener, face and body phases are switched off by the profile."""

EXTENSIONS: dict[str, str] = {"part": "SLDPRT", "assembly": "SLDASM", "drawing": "SLDDRW"}

PHASE_ELAPSED_MS = 1
"""A whole millisecond for every phase that ran: fixtures are not measurements, and `0`
means something else (a phase that ran inside the clock's resolution)."""


# --- 1. Specs -----------------------------------------------------------------------------


@dataclass(frozen=True)
class ComponentSpec:
    """One `ComponentInstance`, naming the document it instantiates by spec name."""

    name: str
    document: str
    parent: str | None = None
    """Another component's name; `None` hangs it under the root assembly instance."""

    suppression: Suppression = "resolved"
    is_fixed: bool = False
    constrained_status_raw: int | None = None
    transparency_raw: float | None = None
    has_appearance_override: bool | None = False
    visibility_raw: int | None = 1
    is_pattern_instance: bool | None = False
    pattern_id: str | None = None
    is_toolbox: bool = False
    referenced_configuration: str | None = None
    """Defaults to the referenced document's configuration."""


@dataclass(frozen=True)
class MateEntitySpec:
    """One end of a mate. `resolution_status` `None` is a package written before 1.4.0."""

    component: str
    entity_kind: str = "FACE"
    resolution_status: MateResolution | None = "resolved"


@dataclass(frozen=True)
class MateSpec:
    entities: Sequence[MateEntitySpec]
    type: str = "COINCIDENT"
    alignment: Literal["aligned", "anti_aligned", "closest"] = "aligned"
    suppressed: bool = False


@dataclass(frozen=True)
class CutListSpec:
    """One cut-list item. A folder whose `body_count` is 0 is not displayed by SOLIDWORKS."""

    name: str
    folder_name: str = "Cut-List-Item1"
    folder_type_name: str = "CutListFolder"
    body_count: int | None = 1
    excluded_from_cut_list: bool | None = True


@dataclass(frozen=True)
class DimensionSpec:
    """One display dimension. `override_mm`/`override_degrees` is what was typed over it."""

    name: str
    is_overridden: bool | None = False
    dimension_type_raw: int | None = 2
    value_mm: float | None = 10.0
    override_mm: float | None = None
    value_degrees: float | None = None
    override_degrees: float | None = None


@dataclass(frozen=True)
class AnnotationSpec:
    name: str | None = None
    type_raw: int | None = 1
    is_dangling: bool | None = False


@dataclass(frozen=True)
class NoteSpec:
    """One note. `text=None` is a note that could not be read, which is not "no text"."""

    text: str | None


@dataclass(frozen=True)
class ViewSpec:
    """One view. `view_type_raw` 1 is the sheet-format pseudo-view, where notes live."""

    name: str | None
    view_type_raw: int | None = 2
    references: str | None = None
    """A document spec's name; the view's referenced model."""

    referenced_model_path: str | None = None
    """Set it to record a referenced model that is *not* in the package (a gap's case)."""

    dimensions: Sequence[DimensionSpec] = ()
    annotations: Sequence[AnnotationSpec] = ()
    notes: Sequence[NoteSpec] = ()


@dataclass(frozen=True)
class RevisionTableSpec:
    """One revision table. `header_index` names the header row; `None` records no reading."""

    rows: Sequence[Sequence[str | None]] = ()
    current_revision_raw: str | None = None
    header_index: int | None = 0
    row_count: int | None = None
    """Defaults to the number of rows; set it to record a count the rows disagree with."""

    column_count: int | None = None


@dataclass(frozen=True)
class SheetSpec:
    name: str
    sheet_format_name: str | None = "Sheet Format"
    was_active: bool = False
    views: Sequence[ViewSpec] = ()
    revision_tables: Sequence[RevisionTableSpec] = ()


@dataclass(frozen=True)
class _DocumentSpec:
    """What every document spec carries: where it lives and what its data card says."""

    name: str
    folder: str = ""
    configuration: str = "Default"
    configurations: Sequence[str] | None = None
    properties: Mapping[str, str] = field(default_factory=dict)
    config_properties: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    rebuild_error_count: int | None = 0


@dataclass(frozen=True)
class PartSpec(_DocumentSpec):
    material: str | None = None
    material_configuration: str | None = None
    """Defaults to the part's own configuration whenever `material` was read."""

    mass_overridden: bool | None = False
    features: Sequence[FeatureSpec] = ()
    cut_list: Sequence[CutListSpec] = ()
    shape: Shape = "nested"


@dataclass(frozen=True)
class AssemblySpec(_DocumentSpec):
    is_exploded: bool | None = False
    components: Sequence[ComponentSpec] = ()
    mates: Sequence[MateSpec] = ()


@dataclass(frozen=True)
class DrawingSpec(_DocumentSpec):
    rebuild_error_count: int | None = None
    """Null by default: the drawing checks do not read it, and absence is not a gap."""

    active_sheet: str | None = None
    sheets: Sequence[SheetSpec] = ()


DocumentSpec = PartSpec | AssemblySpec | DrawingSpec


# --- 2. Layout ----------------------------------------------------------------------------


def standards_package(
    *,
    documents: Sequence[DocumentSpec],
    profile: StandardsProfile | None = None,
    vault_root: str | None = None,
    gaps: Sequence[Gap] = (),
) -> EvidencePackage:
    """An `EvidencePackage` as the `standards` dump profile writes one.

    The first spec is the root document. `vault_root` prefixes every path; it defaults to
    `profile.vault_root` when a profile is given, so a fixture is written for the profile it
    will be graded against, and to nothing when neither is given.
    """
    if not documents:
        raise ValueError("standards_package needs at least one document")

    root = _vault_root(profile, vault_root)
    ids = _document_ids(documents)
    rows = [_document(spec, ids[spec.name], root) for spec in documents]
    paths = {spec.name: row.path for spec, row in zip(documents, rows, strict=True)}

    components = _components(documents, ids)
    return build_package(
        extractor=_extractor(documents),
        manifest=Manifest(entries=[_entry(row) for row in rows], discrepancies=[]),
        design=Design(
            design_id="dsn:1",
            name=documents[0].name,
            root_assembly_document_id=ids[documents[0].name],
            active_configuration=documents[0].configuration,
            drawing_document_ids=[
                ids[spec.name] for spec in documents if isinstance(spec, DrawingSpec)
            ],
        ),
        documents=rows,
        components=components,
        mates=_mates(documents, {row.name: row.id for row in components}),
        holes=[],
        fasteners=[],
        features=_features(documents, ids),
        cut_list_items=_cut_list_items(documents, ids),
        drawing_records=_drawing_records(documents, ids, paths),
        gaps=list(gaps),
    )


def _vault_root(profile: StandardsProfile | None, vault_root: str | None) -> str:
    if vault_root is not None:
        return vault_root.rstrip("/")
    return profile.vault_root.rstrip("/") if profile is not None else ""


def _document_ids(documents: Sequence[DocumentSpec]) -> dict[str, str]:
    ids: dict[str, str] = {}
    for number, spec in enumerate(documents, start=1):
        if spec.name in ids:
            raise ValueError(f"duplicate document name {spec.name!r}")
        ids[spec.name] = f"doc:{number}"
    return ids


def _kind(spec: DocumentSpec) -> Literal["part", "assembly", "drawing"]:
    if isinstance(spec, PartSpec):
        return "part"
    return "assembly" if isinstance(spec, AssemblySpec) else "drawing"


def _document(spec: DocumentSpec, document_id: str, root: str) -> Document:
    kind = _kind(spec)
    file_name = f"{spec.name}.{EXTENSIONS[kind]}"
    parts = [part for part in (root, spec.folder.strip("/"), file_name) if part]
    material = spec.material if isinstance(spec, PartSpec) else None
    return Document(
        document_id=document_id,
        kind=kind,
        file_name=file_name,
        path="/".join(parts),
        configurations=(
            list(spec.configurations) if spec.configurations is not None else [spec.configuration]
        ),
        active_configuration=spec.configuration,
        custom_properties=dict(spec.properties),
        config_properties={
            name: dict(values) for name, values in spec.config_properties.items()
        },
        material=material,
        mass=None,
        is_exploded=spec.is_exploded if isinstance(spec, AssemblySpec) else None,
        rebuild_error_count=spec.rebuild_error_count,
        mass_overridden=spec.mass_overridden if isinstance(spec, PartSpec) else None,
        material_configuration=_material_configuration(spec),
    )


def _material_configuration(spec: DocumentSpec) -> str | None:
    """Present whenever the material read was attempted, including when it came back null."""
    if not isinstance(spec, PartSpec):
        return None
    return spec.material_configuration if spec.material_configuration is not None else (
        spec.configuration
    )


def _entry(document: Document) -> ManifestEntry:
    return ManifestEntry(
        document_id=document.document_id,
        vault_path=document.path,
        vault_version=1,
        revision="A",
        configuration=document.active_configuration,
        local_modified=False,
        export_method="native",
    )


@dataclass(frozen=True)
class _Synthesized:
    """One instance the dump synthesizes rather than reading it off a component spec."""

    document: str
    """The document spec's name it instantiates."""

    parent: str | None = None
    """Another synthesized instance's document name; `None` is the forest's own top."""


def _synthesized(documents: Sequence[DocumentSpec]) -> tuple[_Synthesized, ...]:
    """The instances no component spec names, in traversal order.

    An **assembly** root contributes its own instance. A **drawing** root contributes the
    synthesized forest root the dump hangs one subtree per referenced model under, plus one
    instance of each referenced **assembly** - the dump walks a referenced model's component
    tree exactly as it walks an assembly root (`contracts/ir-additions.md` section 7,
    `research.md` R9). A referenced part has no component tree and so has no subtree to hang.
    A part opened alone contributes none.
    """
    root = documents[0]
    if isinstance(root, AssemblySpec):
        return (_Synthesized(root.name),)
    if isinstance(root, DrawingSpec):
        return (
            _Synthesized(root.name),
            *(
                _Synthesized(name, parent=root.name)
                for name in _referenced_assemblies(root, documents)
            ),
        )
    return ()


def _referenced_assemblies(
    root: DrawingSpec, documents: Sequence[DocumentSpec]
) -> tuple[str, ...]:
    """Every assembly a view on any sheet references, once each, in sheet and view order."""
    assemblies = {spec.name for spec in documents if isinstance(spec, AssemblySpec)}
    seen: dict[str, None] = {}
    for sheet in root.sheets:
        for view in sheet.views:
            if view.references is not None and view.references in assemblies:
                seen.setdefault(view.references, None)
    return tuple(seen)


def _components(
    documents: Sequence[DocumentSpec], ids: Mapping[str, str]
) -> list[ComponentInstance]:
    """The synthesized instances first, then every component spec in document order."""
    root_spec = documents[0]
    synthesized = _synthesized(documents)
    specs = [(spec, owner) for owner in documents for spec in _component_specs(owner)]

    synthesized_ids = {
        item.document: f"cmp:{number:04d}" for number, item in enumerate(synthesized, start=1)
    }
    numbers: dict[str, str] = dict(synthesized_ids)
    for number, (spec, _) in enumerate(specs, start=len(numbers) + 1):
        if spec.name in numbers:
            raise ValueError(f"duplicate component instance name {spec.name!r}")
        numbers[spec.name] = f"cmp:{number:04d}"

    configurations = {spec.name: spec.configuration for spec in documents}
    rows = [
        _synthesized_row(item, synthesized_ids, ids, configurations, root_spec)
        for item in synthesized
    ]

    forest_root_id = synthesized_ids.get(root_spec.name)
    for spec, owner in specs:
        if spec.document not in ids:
            raise ValueError(
                f"component {spec.name!r} names document {spec.document!r}, "
                "which is not a document of this package"
            )
        if spec.parent is not None and spec.parent not in numbers:
            raise ValueError(
                f"component {spec.name!r} names parent {spec.parent!r}, "
                "which is not a component instance of this package"
            )
        parent_id = (
            numbers[spec.parent]
            if spec.parent is not None
            else synthesized_ids.get(owner.name, forest_root_id)
        )
        full_path = spec.name if spec.parent is None else f"{spec.parent}/{spec.name}"
        rows.append(
            ComponentInstance(
                id=numbers[spec.name],
                persist_ref=persist_ref(numbers[spec.name]),
                persist_ref_scope=ids[owner.name],
                name=spec.name,
                full_path=full_path,
                document_id=ids[spec.document],
                parent_id=parent_id,
                referenced_configuration=(
                    spec.referenced_configuration or configurations[spec.document]
                ),
                transform=IDENTITY_TRANSFORM,
                suppression=spec.suppression,
                is_fixed=spec.is_fixed,
                pattern_id=spec.pattern_id,
                is_toolbox=spec.is_toolbox,
                constrained_status_raw=spec.constrained_status_raw,
                transparency_raw=spec.transparency_raw,
                has_appearance_override=spec.has_appearance_override,
                visibility_raw=spec.visibility_raw,
                is_pattern_instance=spec.is_pattern_instance,
            )
        )
    return rows


def _synthesized_row(
    item: _Synthesized,
    synthesized_ids: Mapping[str, str],
    ids: Mapping[str, str],
    configurations: Mapping[str, str],
    root: DocumentSpec,
) -> ComponentInstance:
    """One synthesized instance: a top-level, resolved, fixed instance of its document."""
    instance_id = synthesized_ids[item.document]
    return ComponentInstance(
        id=instance_id,
        persist_ref=persist_ref(instance_id),
        persist_ref_scope=ids[root.name],
        name=item.document,
        full_path=item.document if item.parent is None else f"{item.parent}/{item.document}",
        document_id=ids[item.document],
        parent_id=None if item.parent is None else synthesized_ids[item.parent],
        referenced_configuration=configurations[item.document],
        transform=IDENTITY_TRANSFORM,
        suppression="resolved",
        is_fixed=True,
        pattern_id=None,
        is_toolbox=False,
        has_appearance_override=False,
        visibility_raw=1,
        is_pattern_instance=False,
    )


def _component_specs(spec: DocumentSpec) -> Sequence[ComponentSpec]:
    return spec.components if isinstance(spec, AssemblySpec) else ()


def _mates(documents: Sequence[DocumentSpec], component_ids: Mapping[str, str]) -> list[Mate]:
    rows: list[Mate] = []
    for owner in documents:
        if not isinstance(owner, AssemblySpec):
            continue
        for spec in owner.mates:
            mate_id = f"mate:{len(rows) + 1:04d}"
            rows.append(
                Mate(
                    id=mate_id,
                    persist_ref=persist_ref(mate_id),
                    persist_ref_scope=_document_id_of(documents, owner),
                    type=spec.type,
                    entities=[
                        MateEntity(
                            component_id=_component_id(component_ids, entity.component, mate_id),
                            persist_ref=persist_ref(f"{mate_id}/{entity.component}"),
                            entity_kind=entity.entity_kind,
                            resolution_status=entity.resolution_status,
                        )
                        for entity in spec.entities
                    ],
                    alignment=spec.alignment,
                    suppressed=spec.suppressed,
                    distance=None,
                    angle=None,
                )
            )
    return rows


def _document_id_of(documents: Sequence[DocumentSpec], spec: DocumentSpec) -> str:
    return f"doc:{list(documents).index(spec) + 1}"


def _component_id(component_ids: Mapping[str, str], name: str, mate_id: str) -> str:
    if name not in component_ids:
        raise ValueError(f"{mate_id} names {name!r}, which is not a component instance")
    return component_ids[name]


def _features(documents: Sequence[DocumentSpec], ids: Mapping[str, str]) -> list[Feature]:
    rows: list[Feature] = []
    for spec in documents:
        if not isinstance(spec, PartSpec) or not spec.features:
            continue
        rows.extend(
            build_features(
                spec.features,
                document_id=ids[spec.name],
                shape=spec.shape,
                configuration=spec.configuration,
                start=len(rows) + 1,
            )
        )
    return rows


def _cut_list_items(
    documents: Sequence[DocumentSpec], ids: Mapping[str, str]
) -> list[CutListItem]:
    rows: list[CutListItem] = []
    for spec in documents:
        if not isinstance(spec, PartSpec):
            continue
        for item in spec.cut_list:
            item_id = f"cut:{len(rows) + 1:04d}"
            rows.append(
                CutListItem(
                    id=item_id,
                    document_id=ids[spec.name],
                    configuration=spec.configuration,
                    folder_name=item.folder_name,
                    folder_type_name=item.folder_type_name,
                    name=item.name,
                    body_count=item.body_count,
                    excluded_from_cut_list=item.excluded_from_cut_list,
                    persist_ref=persist_ref(item_id),
                    persist_ref_scope=ids[spec.name],
                )
            )
    return rows


@dataclass
class _Counters:
    """One counter per identified drawing model, so ids are allocated in traversal order."""

    sheet: int = 0
    view: int = 0
    dimension: int = 0
    annotation: int = 0
    note: int = 0
    table: int = 0

    def next(self, which: str, prefix: str) -> str:
        number = getattr(self, which) + 1
        setattr(self, which, number)
        return f"{prefix}:{number:04d}"


def _drawing_records(
    documents: Sequence[DocumentSpec], ids: Mapping[str, str], paths: Mapping[str, str]
) -> list[DrawingRecord]:
    counters = _Counters()
    return [
        DrawingRecord(
            document_id=ids[spec.name],
            active_sheet_name=spec.active_sheet,
            sheets=[
                _sheet(sheet, index, counters, ids, paths)
                for index, sheet in enumerate(spec.sheets)
            ],
        )
        for spec in documents
        if isinstance(spec, DrawingSpec)
    ]


def _sheet(
    spec: SheetSpec,
    index: int,
    counters: _Counters,
    ids: Mapping[str, str],
    paths: Mapping[str, str],
) -> DrawingSheetRecord:
    sheet_id = counters.next("sheet", "dsh")
    return DrawingSheetRecord(
        id=sheet_id,
        name=spec.name,
        index=index,
        sheet_format_name=spec.sheet_format_name,
        was_active=spec.was_active,
        views=[_view(view, sheet_id, counters, ids, paths) for view in spec.views],
        revision_tables=[
            _revision_table(table, sheet_id, counters) for table in spec.revision_tables
        ],
        persist_ref=persist_ref(sheet_id),
        persist_ref_scope=None,
    )


def _view(
    spec: ViewSpec,
    sheet_id: str,
    counters: _Counters,
    ids: Mapping[str, str],
    paths: Mapping[str, str],
) -> DrawingView:
    view_id = counters.next("view", "dvw")
    referenced_id = None
    referenced_path = spec.referenced_model_path
    if spec.references is not None:
        if spec.references not in ids:
            raise ValueError(
                f"view {spec.name!r} references {spec.references!r}, "
                "which is not a document of this package"
            )
        referenced_id = ids[spec.references]
        referenced_path = referenced_path or paths[spec.references]
    return DrawingView(
        id=view_id,
        sheet_id=sheet_id,
        name=spec.name,
        view_type_raw=spec.view_type_raw,
        referenced_document_id=referenced_id,
        referenced_model_path=referenced_path,
        display_dimensions=[
            _dimension(dimension, view_id, counters) for dimension in spec.dimensions
        ],
        annotations=[
            _annotation(annotation, view_id, counters) for annotation in spec.annotations
        ],
        notes=[_note(note, view_id, counters) for note in spec.notes],
        persist_ref=persist_ref(view_id),
        persist_ref_scope=None,
    )


def _dimension(
    spec: DimensionSpec, view_id: str, counters: _Counters
) -> DisplayDimensionRecord:
    dimension_id = counters.next("dimension", "ddm")
    return DisplayDimensionRecord(
        id=dimension_id,
        view_id=view_id,
        name=spec.name,
        dimension_type_raw=spec.dimension_type_raw,
        is_overridden=spec.is_overridden,
        override_value=_measure(spec.override_mm, spec.override_degrees),
        value=_measure(spec.value_mm, spec.value_degrees),
        persist_ref=persist_ref(dimension_id),
        persist_ref_scope=None,
    )


def _measure(millimetres: float | None, degrees: float | None) -> Quantity | Angle | None:
    """A length or an angle, never both: `dimension_type_raw` is what decides which."""
    if millimetres is not None and degrees is not None:
        raise ValueError("a dimension is a length or an angle, not both")
    if degrees is not None:
        return Angle(value=degrees, unit="deg")
    return Quantity(value=millimetres, unit="mm") if millimetres is not None else None


def _annotation(spec: AnnotationSpec, view_id: str, counters: _Counters) -> DrawingAnnotation:
    annotation_id = counters.next("annotation", "dan")
    return DrawingAnnotation(
        id=annotation_id,
        owner_id=view_id,
        name=spec.name,
        type_raw=spec.type_raw,
        is_dangling=spec.is_dangling,
        persist_ref=persist_ref(annotation_id),
        persist_ref_scope=None,
    )


def _note(spec: NoteSpec, view_id: str, counters: _Counters) -> DrawingNote:
    note_id = counters.next("note", "dnt")
    return DrawingNote(
        id=note_id,
        owner_id=view_id,
        text=spec.text,
        persist_ref=persist_ref(note_id),
        persist_ref_scope=None,
    )


def _revision_table(spec: RevisionTableSpec, sheet_id: str, counters: _Counters) -> RevisionTable:
    table_id = counters.next("table", "drv")
    rows = [
        RevisionTableRow(
            index=index,
            cells=list(cells),
            is_header=None if spec.header_index is None else index == spec.header_index,
        )
        for index, cells in enumerate(spec.rows)
    ]
    widest = max((len(row.cells) for row in rows), default=0)
    return RevisionTable(
        id=table_id,
        sheet_id=sheet_id,
        current_revision_raw=spec.current_revision_raw,
        row_count=len(rows) if spec.row_count is None else spec.row_count,
        column_count=widest if spec.column_count is None else spec.column_count,
        rows=rows,
        persist_ref=persist_ref(table_id),
        persist_ref_scope=None,
    )


def _extractor(documents: Sequence[DocumentSpec]) -> ExtractorInfo:
    """The base package's extractor block, with this feature's profile and phase rows.

    Taken from `build_package` rather than retyped, so the name, version and machine of a
    standards package are the ones every other fixture carries.
    """
    drew = any(isinstance(spec, DrawingSpec) for spec in documents)
    phases = [
        DumpPhase(
            name=name,
            status="ok" if name in STANDARDS_PHASES or (name == "drawing" and drew) else "skipped",
            elapsed_ms=(
                PHASE_ELAPSED_MS
                if name in STANDARDS_PHASES or (name == "drawing" and drew)
                else None
            ),
        )
        for name in PHASE_ORDER
    ]
    return build_package().extractor.model_copy(update={"profile": "standards", "phases": phases})
